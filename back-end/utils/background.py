"""Work that must not happen while a caller waits, because the fact that it happened is a secret.

Sending mail is a network round-trip to Resend, and on the applicant login endpoint it happens for
an address on the organizer's applicant list and does not happen for one that is not. Done inline,
that is the applicant list, readable by anyone with a stopwatch: the response body is identical
either way by design, but a request that waits on a hundreds-of-milliseconds send answers plainly
enough. Handing the send off here makes the two paths take the same work, so the clock says nothing
the body does not.

It is an in-process pool rather than a broker because the send is fire-and-forget: nothing waits on
its result and no caller retries it. A failure is logged, not raised -- there is no request left to
fail by the time it happens.
"""

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="deferred")


def run_later(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Optional[Future]:
    """Run ``fn`` off the request path, and return its future for tests that want to wait on it."""

    def _guarded() -> Any:
        try:
            return fn(*args, **kwargs)
        except Exception:  # pragma: no cover - the point is that nothing propagates
            logger.exception(
                "Deferred %s failed", getattr(fn, "__name__", repr(fn)),
            )
            return None

    try:
        return _executor.submit(_guarded)
    except RuntimeError as exc:  # pragma: no cover - the interpreter is shutting down
        logger.warning("Could not defer %s: %s", getattr(fn, "__name__", repr(fn)), exc)
        return None
