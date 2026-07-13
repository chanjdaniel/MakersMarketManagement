"""Tests for the Mongo-backed fixed-window rate limiter.

The counter is in the database, not in process memory, because the surfaces it bounds are public
and unauthenticated: an in-memory limiter on a two-worker deployment is a limit of 2N, and on a
serverless one it is no limit at all.
"""
from datetime import datetime, timedelta, timezone

import pytest
from pymongo.errors import PyMongoError

import utils.rate_limit as RateLimit

AT = datetime(2026, 7, 13, 12, 0, 0, tzinfo=timezone.utc)


def _spend(times, **kwargs):
    return [
        RateLimit.rate_limit_exceeded("scope", "1.2.3.4", limit=3, window_seconds=60, **kwargs)
        for _ in range(times)
    ]


class TestRateLimit:
    def test_a_budget_admits_exactly_its_limit(self, rate_limits):
        assert _spend(3, now=AT) == [False, False, False]

    def test_the_request_past_the_limit_is_refused(self, rate_limits):
        _spend(3, now=AT)

        assert RateLimit.rate_limit_exceeded(
            "scope", "1.2.3.4", limit=3, window_seconds=60, now=AT,
        ) is True

    def test_a_refused_request_still_counts(self, rate_limits):
        """A caller that keeps hammering a spent window stays spent for the rest of it, rather than
        being let back in by its own refusals not being counted."""
        _spend(5, now=AT)

        doc = rate_limits.documents[0]
        assert doc["count"] == 5

    def test_the_budget_is_per_key(self, rate_limits):
        _spend(4, now=AT)

        assert RateLimit.rate_limit_exceeded(
            "scope", "5.6.7.8", limit=3, window_seconds=60, now=AT,
        ) is False

    def test_the_budget_is_per_scope(self, rate_limits):
        _spend(4, now=AT)

        assert RateLimit.rate_limit_exceeded(
            "other-scope", "1.2.3.4", limit=3, window_seconds=60, now=AT,
        ) is False

    def test_the_next_window_is_a_fresh_budget(self, rate_limits):
        _spend(4, now=AT)

        assert _spend(1, now=AT + timedelta(seconds=60)) == [False]

    def test_a_window_is_shared_by_every_instant_inside_it(self, rate_limits):
        _spend(3, now=AT)

        assert RateLimit.rate_limit_exceeded(
            "scope", "1.2.3.4", limit=3, window_seconds=60, now=AT + timedelta(seconds=59),
        ) is True

    def test_a_spent_window_is_left_for_mongo_to_reap(self, rate_limits):
        _spend(1, now=AT)

        purge_at = rate_limits.documents[0]["purge_at"]
        assert purge_at > AT

    def test_an_unreachable_database_does_not_refuse_the_request(self, rate_limits, monkeypatch):
        """Mongo being down fails every other part of the request anyway, so a limiter that cannot
        count is not a reason to refuse a caller it cannot prove is abusive."""
        def boom(*_args, **_kwargs):
            raise PyMongoError("no route to host")

        monkeypatch.setattr(rate_limits, "find_one_and_update", boom)

        assert RateLimit.rate_limit_exceeded(
            "scope", "1.2.3.4", limit=3, window_seconds=60, now=AT,
        ) is False
