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
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from pymongo import ReturnDocument
from pymongo.errors import PyMongoError

from db_config import get_database

logger = logging.getLogger(__name__)

db = get_database()
rate_limits_collection = db["rate_limits"]

_ttl_index_ready = False


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


def rate_limit_exceeded(
    scope: str,
    key: str,
    *,
    limit: int,
    window_seconds: int,
    now: Optional[datetime] = None,
) -> bool:
    """Count one request against ``(scope, key)`` and report whether it is over the limit.

    A refused request does not spend the budget it was refused by: the increment that took the count
    past the limit is given back, so the stored count is the number of requests that were *admitted*
    and nothing else. The window still stays spent for the rest of its length - a count sitting at
    the limit refuses everything that follows - but a budget the caller shares with other people
    (the global ceiling, and a per-IP budget behind a NAT that a whole convention hall is on) cannot
    be driven further into the ground by requests that were already turned away.

    A database error is not a licence to skip the limit quietly, but it is also not a reason to
    refuse a request the limiter cannot prove is abusive -- Mongo being unreachable fails every
    other part of the request anyway. It is logged and the request is allowed through.

    Args:
        scope: The surface being limited, e.g. ``applicant_request_key_ip``.
        key: What the budget belongs to within that scope, e.g. a client IP. May be empty for a
            global budget.
        limit: How many requests the window allows.
        window_seconds: How long the window is.
        now: Overridable clock, for tests.

    Returns:
        True when this request is over the limit and should be refused.
    """
    moment = now or datetime.now(timezone.utc)
    window_start = int(moment.timestamp()) // window_seconds * window_seconds
    window_id = f"{scope}:{key}:{window_start}"
    _ensure_ttl_index()

    try:
        doc: Any = rate_limits_collection.find_one_and_update(
            {"_id": window_id},
            {
                "$inc": {"count": 1},
                "$setOnInsert": {
                    "purge_at": datetime.fromtimestamp(window_start, tz=timezone.utc)
                    + timedelta(seconds=window_seconds * 2),
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except PyMongoError as exc:
        logger.warning("Rate limit for %s could not be counted: %s", scope, exc)
        return False

    if (doc or {}).get("count", 0) <= limit:
        return False

    try:
        rate_limits_collection.update_one({"_id": window_id}, {"$inc": {"count": -1}})
    except PyMongoError as exc:  # pragma: no cover - the refusal stands either way
        logger.warning("Rate limit for %s could not be refunded: %s", scope, exc)
    return True
