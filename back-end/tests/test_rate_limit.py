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

    def test_a_refused_request_does_not_spend_the_budget_that_refused_it(self, rate_limits):
        """The stored count is what was *admitted*, and nothing else.

        Every budget on the applicant endpoints is one somebody else is also spending -- the global
        ceiling by every market's applicants, a per-IP one by everybody behind a convention hall's
        wifi. If refusals counted, a caller could hold a shared window down for its full length by
        hammering it after it was already spent, which turns a rate limit into the outage it exists
        to prevent.
        """
        _spend(5, now=AT)

        doc = rate_limits.documents[0]
        assert doc["count"] == 3

    def test_a_spent_window_stays_spent_for_the_rest_of_its_length(self, rate_limits):
        """Refunding the refusal must not let the caller back in: the count sits at the limit, and
        everything that follows is still over it."""
        _spend(5, now=AT)

        assert RateLimit.rate_limit_exceeded(
            "scope", "1.2.3.4", limit=3, window_seconds=60, now=AT + timedelta(seconds=30),
        ) is True

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


IP = RateLimit.Budget(scope="ip", key="1.2.3.4", limit=3, window_seconds=60)
CEILING = RateLimit.Budget(scope="global", key="", limit=2, window_seconds=60)


def _charged(rate_limits, budget, at=AT):
    """What the stored count of a budget's window is, from outside the limiter."""
    window_start = int(at.timestamp()) // budget.window_seconds * budget.window_seconds
    doc = rate_limits.find_one({"_id": f"{budget.scope}:{budget.key}:{window_start}"})
    return (doc or {}).get("count", 0)


class TestSeveralBudgetsAtOnce:
    """A request is admitted by all of its budgets or by none of them.

    The applicant endpoints charge a per-IP budget and a global ceiling for the same request, and
    both are budgets somebody else is also spending: the per-IP one belongs to everybody behind a
    convention hall's wifi, the ceiling to every market's applicants at once. So a request one of
    them refuses must not have spent the other, in either direction.
    """

    def _spend(self, times, budgets, **kwargs):
        return [RateLimit.any_budget_exceeded(budgets, now=AT, **kwargs) for _ in range(times)]

    def test_an_admitted_request_is_charged_to_every_budget(self, rate_limits):
        assert self._spend(2, [IP, CEILING]) == [False, False]

        assert _charged(rate_limits, IP) == 2
        assert _charged(rate_limits, CEILING) == 2

    def test_the_request_the_ceiling_refuses_is_refused(self, rate_limits):
        assert self._spend(3, [IP, CEILING]) == [False, False, True]

    def test_a_ceiling_refusal_does_not_spend_the_per_ip_budget(self, rate_limits):
        """The bug this exists for: an hour in which the product hits its global ceiling used to be
        an hour that burned down the hourly budget of every shared NAT signing in at the time."""
        self._spend(3, [IP, CEILING])

        assert _charged(rate_limits, IP) == 2

    def test_the_per_ip_budget_still_admits_its_full_limit_after_a_ceiling_refusal(
        self, rate_limits,
    ):
        """The refund is not bookkeeping: the applicants behind that address get their budget back."""
        self._spend(3, [IP, CEILING])

        assert RateLimit.any_budget_exceeded(
            [IP, RateLimit.Budget(scope="global", key="", limit=99, window_seconds=60)], now=AT,
        ) is False

    def test_a_budget_that_refuses_does_not_spend_itself(self, rate_limits):
        self._spend(4, [IP, CEILING])

        assert _charged(rate_limits, CEILING) == 2

    def test_a_budget_behind_the_one_that_refused_is_not_charged_at_all(self, rate_limits):
        self._spend(5, [CEILING, IP])

        assert _charged(rate_limits, CEILING) == 2
        assert _charged(rate_limits, IP) == 2

    def test_a_refused_request_stays_refused(self, rate_limits):
        """Refunding a refusal is not a way back in: the window sits at its limit for its length."""
        self._spend(3, [IP, CEILING])

        assert RateLimit.any_budget_exceeded([IP, CEILING], now=AT) is True

    def test_a_budget_the_database_cannot_count_does_not_refuse_the_request(
        self, rate_limits, monkeypatch,
    ):
        def boom(*_args, **_kwargs):
            raise PyMongoError("no route to host")

        monkeypatch.setattr(rate_limits, "find_one_and_update", boom)

        assert RateLimit.any_budget_exceeded([IP, CEILING], now=AT) is False
