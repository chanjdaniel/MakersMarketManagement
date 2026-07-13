"""Fixed-window rate limiting, counted in Mongo.

The counter lives in the database rather than in process memory because the bound has to hold for
the deployment, not for one worker: an in-memory limiter on a two-worker gunicorn is a limit of
2N, on a serverless deployment it is no limit at all, and the surfaces that need bounding here are
public and unauthenticated. One document per (scope, key, window) is incremented atomically, so
concurrent workers count against the same total.

The window is a fixed one -- the current instant floored to a multiple of the window length -- so a
caller can, at worst, spend a full budget at the end of one window and another at the start of the
next. That burst is a factor of two, and the limits below are set with room for it.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Sequence

from pymongo import ReturnDocument
from pymongo.errors import PyMongoError

from db_config import get_database

logger = logging.getLogger(__name__)

db = get_database()
rate_limits_collection = db["rate_limits"]

_ttl_index_ready = False


@dataclass(frozen=True)
class Budget:
    """One budget a request is counted against: how many of what, over how long."""

    scope: str
    key: str
    limit: int
    window_seconds: int


def _ensure_ttl_index() -> None:
    """Let Mongo expire spent windows, so the collection does not grow without bound.

    Created lazily rather than at import: this module is imported by the test suite and by any
    tooling that never touches the database, and an index build is a network call.
    """
    global _ttl_index_ready
    if _ttl_index_ready:
        return
    try:
        rate_limits_collection.create_index("purge_at", expireAfterSeconds=0)
        _ttl_index_ready = True
    except PyMongoError as exc:  # pragma: no cover - index creation is best effort
        logger.warning("Could not create the rate-limit TTL index: %s", exc)


def _charge(budget: Budget, moment: datetime) -> Optional[Any]:
    """Count one request against a budget's current window, and return that window's new count.

    ``None`` when the count could not be taken at all, which is not the same answer as a number: it
    means the limiter does not know, and the caller decides what to do about that.
    """
    window_start = int(moment.timestamp()) // budget.window_seconds * budget.window_seconds
    window_id = f"{budget.scope}:{budget.key}:{window_start}"

    try:
        doc: Any = rate_limits_collection.find_one_and_update(
            {"_id": window_id},
            {
                "$inc": {"count": 1},
                "$setOnInsert": {
                    "purge_at": datetime.fromtimestamp(window_start, tz=timezone.utc)
                    + timedelta(seconds=budget.window_seconds * 2),
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except PyMongoError as exc:
        logger.warning("Rate limit for %s could not be counted: %s", budget.scope, exc)
        return None

    return ((doc or {}).get("count", 0), window_id)


def _refund(window_id: str) -> None:
    """Give back an increment that admitted nothing."""
    try:
        rate_limits_collection.update_one({"_id": window_id}, {"$inc": {"count": -1}})
    except PyMongoError as exc:  # pragma: no cover - the refusal stands either way
        logger.warning("Rate limit window %s could not be refunded: %s", window_id, exc)


def rate_limit_exceeded(
    scope: str,
    key: str,
    *,
    limit: int,
    window_seconds: int,
    now: Optional[datetime] = None,
) -> bool:
    """Count one request against ``(scope, key)`` and report whether it is over the limit."""
    return any_budget_exceeded(
        [Budget(scope=scope, key=key, limit=limit, window_seconds=window_seconds)], now=now,
    )


def any_budget_exceeded(
    budgets: Sequence[Budget], *, now: Optional[datetime] = None,
) -> bool:
    """Count one request against every budget at once, and report whether any of them refuses it.

    Every budget a request is subject to is checked here, together, because a request is admitted by
    all of them or by none of them: what a caller must never be able to do is spend a budget on a
    request that some *other* budget then turns away. Charged one at a time, that is exactly what
    happens -- the per-IP budget is spent, the global ceiling refuses, and the increment stays behind
    -- and it is a live bug, not a bookkeeping one: every budget on the public applicant endpoints is
    one somebody else is also spending. A per-IP window belongs to everybody behind a convention
    hall's wifi, and burning it down on requests the *global* ceiling refused locks out precisely the
    applicants who were doing nothing wrong. Reordering the two checks only moves the leak: an
    abusive IP would then burn the shared global ceiling with requests its own budget refused, which
    is the same failure aimed at everybody instead of at one NAT.

    So the increments are charged in order, and the first refusal gives back every increment this
    request took -- its own included. The stored count of every window stays what the docstring
    above says it is: the number of requests that were *admitted*, and nothing else. A window that is
    already at its limit still stays spent for the rest of its length; refunding a refusal is not a
    way back in.

    A database error is not a licence to skip the limit quietly, but it is also not a reason to
    refuse a request the limiter cannot prove is abusive -- Mongo being unreachable fails every
    other part of the request anyway. It is logged, that budget is not counted, and the rest are.

    Args:
        budgets: The budgets this request is subject to, in the order they should be charged.
        now: Overridable clock, for tests.

    Returns:
        True when this request is over one of the limits and should be refused.
    """
    moment = now or datetime.now(timezone.utc)
    _ensure_ttl_index()

    charged: List[str] = []
    for budget in budgets:
        counted = _charge(budget, moment)
        if counted is None:
            continue

        count, window_id = counted
        charged.append(window_id)
        if count > budget.limit:
            for spent in charged:
                _refund(spent)
            return True

    return False
