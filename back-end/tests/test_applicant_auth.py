"""Tests for applicant email-key auth flow (request-key, verify-key, token validation).

The login endpoints are public, unauthenticated, and they send mail to whatever address they are
handed, so most of what is pinned here is what they *refuse* and what they refuse to *say*.
"""
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from pymongo.errors import DuplicateKeyError
from unittest.mock import patch

from conftest import (
    FakeApplicationsCollection,
    FakeKeyedCollection,
    FakeSlugMarketsCollection,
    stored_market,
)
from datatypes import (
    Application,
    ApplicationStatus,
    ApplicationType,
    MarketPhase,
)
from utils.tokens import generate_otp

import api.applicants as ApplicantsApi
import api.applications as ApplicationsApi

VALID_FORM = {
    "fields": [
        {"key": "business_name", "label": "Business Name", "type": "text", "required": True, "order": 0},
    ]
}

PUBLISHED_MARKET_DOC = stored_market(
    phase=MarketPhase.APPLICATIONS_OPEN,
    name="Test Market",
    applicationForm=VALID_FORM,
)

MAX_ATTEMPTS = ApplicantsApi.MAX_OTP_ATTEMPTS
COOLDOWN = ApplicantsApi.KEY_RESEND_COOLDOWN_SECONDS
# Longer ago than a code lives, so the seeded challenge is dead rather than merely old.
EXPIRED = ApplicantsApi.OTP_EXPIRY_MINUTES * 60 + 1


def _seed_challenge(
    login_codes, email, *, code="123456", attempts=0, issued_seconds_ago=0,
    market_id="market-123",
):
    """A login challenge as ``request_applicant_key`` would have written it.

    ``code=None`` is the challenge written for an address with no application: it holds nothing a
    caller can match, and it exists so that nothing about the answers ``verify_applicant_key`` gives
    depends on whether the address is on the organizer's applicant list.
    """
    issued = datetime.now(timezone.utc) - timedelta(seconds=issued_seconds_ago)
    expires = issued + timedelta(minutes=ApplicantsApi.OTP_EXPIRY_MINUTES)
    login_codes.insert_one({
        "market_id": market_id,
        "email": email,
        "code": code,
        "attempts": attempts,
        "issued_at": issued,
        "expires_at": expires,
        "purge_at": expires,
    })


def _stored_challenge(login_codes, email, market_id="market-123"):
    return login_codes.find_one({"market_id": market_id, "email": email})


@pytest.fixture
def published_market(monkeypatch):
    """A market in APPLICATIONS_OPEN phase with a valid application form."""
    fake = FakeSlugMarketsCollection([PUBLISHED_MARKET_DOC])
    monkeypatch.setattr(ApplicantsApi, "markets_collection", fake)
    return fake


@pytest.fixture
def apps_coll(monkeypatch):
    fake = FakeApplicationsCollection()
    monkeypatch.setattr(ApplicationsApi, "applications_collection", fake)
    return fake


@pytest.fixture
def no_email(monkeypatch):
    monkeypatch.setattr(ApplicantsApi, "send_otp_email", lambda *_a, **_kw: True)


@pytest.fixture(autouse=True)
def fast_key_request_floor(monkeypatch):
    """Every request-key call in this module waits out the floor, and only two of them are about it.

    The floor is a real ``time.sleep`` on the way out of the endpoint, so at its production length
    the ~40 calls here spend about a minute of the test job asleep, buying no coverage. It is shrunk
    for the module and restored, explicitly, by the tests in ``TestTheClockSaysNothingTheBodyDoesNot``
    that assert against a value of their own - so the behavior stays under test and the wait does
    not.
    """
    monkeypatch.setattr(ApplicantsApi, "KEY_REQUEST_FLOOR_SECONDS", 0.01)


class TestRequestKey:
    """Tests for request_applicant_key (Stage 1 of the login flow)."""

    def test_returns_404_when_market_not_found(self, apps_coll, no_email, monkeypatch):
        fake = FakeSlugMarketsCollection([])
        monkeypatch.setattr(ApplicantsApi, "markets_collection", fake)

        result, status = ApplicantsApi.request_applicant_key("nonexistent", "test@example.com")
        assert status == 404
        assert "not found" in result["error"].lower()

    def test_returns_404_when_market_is_draft(self, apps_coll, no_email, monkeypatch):
        """A draft market is invisible to the public slug lookup, so it is not found at all."""
        fake = FakeSlugMarketsCollection([
            stored_market(phase=MarketPhase.DRAFT, name="Draft Market")
        ])
        monkeypatch.setattr(ApplicantsApi, "markets_collection", fake)

        result, status = ApplicantsApi.request_applicant_key("draft-market", "test@example.com")
        assert status == 404

    def test_a_closed_market_takes_no_new_application(self, apps_coll, no_email, monkeypatch):
        """The phase gates *starting* an application, so a stranger with an empty form cannot land
        on the organizer's applicant list after review has begun -- but the refusal is silent, so
        that it does not become an oracle for who applied (see the enumeration tests below)."""
        fake = FakeSlugMarketsCollection([
            stored_market(phase=MarketPhase.APPLICATIONS_CLOSED, name="Closed Market",
                          id="closed-1")
        ])
        monkeypatch.setattr(ApplicantsApi, "markets_collection", fake)

        result, status = ApplicantsApi.request_applicant_key("closed-market", "test@example.com")

        assert status == 200
        assert result["message"] == ApplicantsApi.KEY_REQUEST_ACCEPTED_MESSAGE
        assert apps_coll.documents == []

    def test_an_existing_applicant_can_sign_in_after_applications_close(
        self, apps_coll, login_codes, no_email, monkeypatch,
    ):
        """Signing in is not applying. The dashboard exists to show the applicant the states their
        application reaches *after* the window closes, so the login cannot close with it."""
        fake = FakeSlugMarketsCollection([
            stored_market(phase=MarketPhase.APPLICATIONS_CLOSED, name="Closed Market",
                          id="closed-1")
        ])
        monkeypatch.setattr(ApplicantsApi, "markets_collection", fake)
        apps_coll.insert_one(Application(
            market_id="closed-1",
            applicant_email="applied@example.com",
            form_data={"business_name": "Acme"},
            status=ApplicationStatus.OPEN,
        ).model_dump())

        result, status = ApplicantsApi.request_applicant_key(
            "closed-market", "applied@example.com",
        )

        assert status == 200, result
        assert len(apps_coll.documents) == 1
        challenge = _stored_challenge(login_codes, "applied@example.com", market_id="closed-1")
        assert challenge["code"] is not None

    def test_an_existing_applicant_can_sign_in_after_the_market_is_archived(
        self, apps_coll, no_email, monkeypatch,
    ):
        fake = FakeSlugMarketsCollection([
            stored_market(phase=MarketPhase.ARCHIVED, name="Archived Market", id="arch-1")
        ])
        monkeypatch.setattr(ApplicantsApi, "markets_collection", fake)
        apps_coll.insert_one(Application(
            market_id="arch-1",
            applicant_email="applied@example.com",
            form_data={"business_name": "Acme"},
            status=ApplicationStatus.OPEN,
        ).model_dump())

        _result, status = ApplicantsApi.request_applicant_key(
            "archived-market", "applied@example.com",
        )

        assert status == 200

    def test_refuses_a_malformed_email(self, published_market, apps_coll, no_email):
        """A typo told "a code has been sent" is an applicant waiting forever, and a junk document
        on the organizer's applicant list."""
        result, status = ApplicantsApi.request_applicant_key("test-market", "vendor@gmail")

        assert status == 400
        assert "valid email" in result["error"].lower()
        assert apps_coll.documents == []

    def test_creates_application_on_first_request(
        self, published_market, apps_coll, login_codes, no_email,
    ):
        result, status = ApplicantsApi.request_applicant_key("test-market", "new@example.com")

        assert status == 200
        assert "code has been sent" in result["message"]
        assert len(apps_coll.documents) == 1
        assert apps_coll.documents[0]["applicant_email"] == "new@example.com"
        assert _stored_challenge(login_codes, "new@example.com")["code"] is not None

    def test_reuses_existing_application(self, published_market, apps_coll, no_email):
        app = Application(
            market_id="market-123",
            applicant_email="existing@example.com",
            form_data={"business_name": "Existing Co"},
            status=ApplicationStatus.OPEN,
        )
        apps_coll.insert_one(app.model_dump())

        result, status = ApplicantsApi.request_applicant_key("test-market", "existing@example.com")

        assert status == 200
        assert len(apps_coll.documents) == 1  # no duplicate created
        assert apps_coll.documents[0]["form_data"]["business_name"] == "Existing Co"

    def test_the_login_challenge_is_not_stored_on_the_application(
        self, published_market, apps_coll, login_codes, no_email,
    ):
        """The code and its attempt counter live in their own collection, keyed by (market, email).

        That is the whole enumeration fix: a challenge that lived on the application could only
        exist where an application does, and every refusal that reads it would then answer "this
        address has applied" to an unauthenticated caller.
        """
        ApplicantsApi.request_applicant_key("test-market", "new@example.com")

        doc = apps_coll.documents[0]
        assert "otp" not in doc and "otp_attempts" not in doc and "otp_expires" not in doc
        assert _stored_challenge(login_codes, "new@example.com") is not None

    def test_generic_message_preventing_email_enumeration(self, published_market, apps_coll, no_email):
        """The response message must be the same whether or not an app exists."""
        result, _ = ApplicantsApi.request_applicant_key("test-market", "unknown@example.com")
        assert "If an application exists" in result["message"]

    def test_a_closed_market_answers_an_applicant_and_a_stranger_identically(
        self, apps_coll, no_email, monkeypatch,
    ):
        """Who applied to a market is the organizer's private data, and this is the endpoint that
        knows it. Naming the phase gate only when no application exists makes the refusal an oracle:
        200 for an address on the applicant list, 403 for one that is not."""
        fake = FakeSlugMarketsCollection([
            stored_market(phase=MarketPhase.APPLICATIONS_CLOSED, name="Closed Market",
                          id="closed-1")
        ])
        monkeypatch.setattr(ApplicantsApi, "markets_collection", fake)
        apps_coll.insert_one(Application(
            market_id="closed-1",
            applicant_email="applied@example.com",
            form_data={"business_name": "Acme"},
            status=ApplicationStatus.OPEN,
        ).model_dump())

        applied = ApplicantsApi.request_applicant_key("closed-market", "applied@example.com")
        stranger = ApplicantsApi.request_applicant_key("closed-market", "stranger@example.com")

        assert applied == stranger

    def test_a_stranger_gets_a_challenge_that_holds_no_code(
        self, apps_coll, login_codes, no_email, monkeypatch,
    ):
        """The challenge is written for an address with no application too -- carrying no code, so
        no mail is sent for it and no guess can ever match it. Without it, verify-key would answer
        "there is no pending code" for a stranger and "incorrect code" for an applicant."""
        fake = FakeSlugMarketsCollection([
            stored_market(phase=MarketPhase.APPLICATIONS_CLOSED, name="Closed Market",
                          id="closed-1")
        ])
        monkeypatch.setattr(ApplicantsApi, "markets_collection", fake)

        ApplicantsApi.request_applicant_key("closed-market", "stranger@example.com")

        challenge = _stored_challenge(login_codes, "stranger@example.com", market_id="closed-1")
        assert challenge is not None
        assert challenge["code"] is None
        assert challenge["attempts"] == 0

    def test_sends_email_to_applicant(self, published_market, apps_coll):
        sent_emails = []

        def capture(email, otp):
            sent_emails.append((email, otp))
            return True

        with patch.object(ApplicantsApi, "send_otp_email", side_effect=capture):
            ApplicantsApi.request_applicant_key("test-market", "vendor@example.com")

        assert len(sent_emails) == 1
        assert sent_emails[0][0] == "vendor@example.com"

    def test_no_mail_is_sent_for_an_address_that_never_applied(
        self, apps_coll, no_email, monkeypatch,
    ):
        """The silent challenge must stay silent: a market that takes no new applications must not
        become a way to send mail from the product's domain to any address a caller names."""
        fake = FakeSlugMarketsCollection([
            stored_market(phase=MarketPhase.APPLICATIONS_CLOSED, name="Closed Market",
                          id="closed-1")
        ])
        monkeypatch.setattr(ApplicantsApi, "markets_collection", fake)
        sent = []

        with patch.object(
            ApplicantsApi, "send_otp_email",
            side_effect=lambda addr, otp: sent.append(addr) or True,
        ):
            ApplicantsApi.request_applicant_key("closed-market", "stranger@example.com")

        assert sent == []

    def test_validates_missing_fields(self, apps_coll, no_email):
        result, status = ApplicantsApi.request_applicant_key("", "test@example.com")
        assert status == 400
        assert "required" in result["error"].lower()

        result, status = ApplicantsApi.request_applicant_key("test-market", "")
        assert status == 400
        assert "required" in result["error"].lower()

    def test_a_non_string_email_is_refused_not_crashed_on(self, published_market, apps_coll, no_email):
        """The route hands the body value through verbatim, so the address is not a string until
        this says it is."""
        result, status = ApplicantsApi.request_applicant_key("test-market", {"not": "an email"})

        assert status == 400
        assert apps_coll.documents == []


class TestKeyRequestThrottle:
    """The bounds on a public, unauthenticated endpoint that mails whatever address it is handed.

    The captcha is the control: it is what keeps a script from being a caller at all. Behind it sit
    a per-address resend cooldown, which bounds the mail one applicant can be sent, and safety
    ceilings sized so that reaching one is evidence of abuse rather than of a busy afternoon --
    because applicants share addresses, and a market that opens at an announced hour takes hundreds
    of legitimate sign-ins in the first minutes of it.
    """

    def _sent(self, market_slug, email, **kwargs):
        sent = []
        with patch.object(
            ApplicantsApi, "send_otp_email",
            side_effect=lambda addr, otp: sent.append((addr, otp)) or True,
        ):
            result, status = ApplicantsApi.request_applicant_key(market_slug, email, **kwargs)
        return sent, result, status

    def test_a_second_code_inside_the_cooldown_is_not_sent(
        self, published_market, apps_coll, login_codes,
    ):
        apps_coll.insert_one(Application(
            market_id="market-123", applicant_email="vendor@example.com",
            form_data={}, status=ApplicationStatus.OPEN,
        ).model_dump())
        _seed_challenge(login_codes, "vendor@example.com", issued_seconds_ago=5)

        sent, _result, status = self._sent("test-market", "vendor@example.com")

        assert status == 200
        assert sent == []
        # The live code stands; it is still the one that works.
        assert _stored_challenge(login_codes, "vendor@example.com")["code"] == "123456"

    def test_the_throttled_answer_is_the_answer_a_send_gives(
        self, published_market, apps_coll, login_codes,
    ):
        """A 429 here would say out loud what the generic message exists to hide: only an address
        with a live code can be cooled down at all."""
        _seed_challenge(login_codes, "vendor@example.com", issued_seconds_ago=5)

        throttled = ApplicantsApi.request_applicant_key("test-market", "vendor@example.com")
        fresh = ApplicantsApi.request_applicant_key("test-market", "stranger@example.com")

        assert throttled == fresh == ({"message": ApplicantsApi.KEY_REQUEST_ACCEPTED_MESSAGE}, 200)

    def test_a_code_is_resent_once_the_cooldown_has_passed(
        self, published_market, apps_coll, login_codes,
    ):
        apps_coll.insert_one(Application(
            market_id="market-123", applicant_email="vendor@example.com",
            form_data={}, status=ApplicationStatus.OPEN,
        ).model_dump())
        _seed_challenge(login_codes, "vendor@example.com", issued_seconds_ago=COOLDOWN + 5)

        sent, _result, status = self._sent("test-market", "vendor@example.com")

        assert status == 200
        assert len(sent) == 1
        assert _stored_challenge(login_codes, "vendor@example.com")["code"] == sent[0][1] != "123456"

    def test_a_fresh_code_carries_a_fresh_attempt_budget(
        self, published_market, apps_coll, login_codes,
    ):
        """The attempt budget belongs to a single issued code, not to the address.

        Carrying a spent budget forward onto the next code hands anyone who knows an applicant's
        address a lockout: burn the five attempts the moment the code is mailed, and every code the
        applicant asks for afterwards is born dead. Resetting is safe -- the new code goes to the
        applicant's inbox, not to the attacker's.
        """
        apps_coll.insert_one(Application(
            market_id="market-123", applicant_email="vendor@example.com",
            form_data={}, status=ApplicationStatus.OPEN,
        ).model_dump())
        _seed_challenge(
            login_codes, "vendor@example.com",
            attempts=MAX_ATTEMPTS, issued_seconds_ago=COOLDOWN + 5,
        )

        sent, _result, status = self._sent("test-market", "vendor@example.com")

        assert status == 200
        assert len(sent) == 1, "a code whose budget an attacker spent must still be replaceable"
        challenge = _stored_challenge(login_codes, "vendor@example.com")
        assert challenge["attempts"] == 0
        assert challenge["code"] == sent[0][1]

    def test_an_attacker_cannot_lock_an_applicant_out_of_their_own_application(
        self, published_market, apps_coll, login_codes,
    ):
        """The full sequence: the attacker requests a code for the victim and burns every attempt,
        and then the victim -- past the cooldown -- asks for one and can use it."""
        apps_coll.insert_one(Application(
            market_id="market-123", applicant_email="victim@example.com",
            form_data={}, status=ApplicationStatus.OPEN,
        ).model_dump())

        attacker_sent, _r, _s = self._sent("test-market", "victim@example.com")
        for _ in range(MAX_ATTEMPTS):
            ApplicantsApi.verify_applicant_key("test-market", "victim@example.com", "000000")
        _exhausted, status = ApplicantsApi.verify_applicant_key(
            "test-market", "victim@example.com", attacker_sent[0][1],
        )
        assert status == 429

        # The victim waits out the cooldown and asks for a code of their own.
        challenge = _stored_challenge(login_codes, "victim@example.com")
        login_codes.update_one(
            {"market_id": "market-123", "email": "victim@example.com"},
            {"$set": {"issued_at": challenge["issued_at"] - timedelta(seconds=COOLDOWN + 5)}},
        )
        victim_sent, _r, _s = self._sent("test-market", "victim@example.com")

        assert len(victim_sent) == 1, "the applicant must never silently receive no mail"
        result, status = ApplicantsApi.verify_applicant_key(
            "test-market", "victim@example.com", victim_sent[0][1],
        )
        assert status == 200, result

    def test_a_first_code_is_never_throttled(self, published_market, apps_coll, login_codes):
        sent, _result, status = self._sent("test-market", "new@example.com")

        assert status == 200
        assert len(sent) == 1
        assert _stored_challenge(login_codes, "new@example.com")["code"] == sent[0][1]

    def test_one_caller_cannot_mail_an_unbounded_number_of_addresses(
        self, published_market, apps_coll, no_email, monkeypatch,
    ):
        """The cooldown is keyed on the address, so it bounds nothing about a caller that names a
        thousand of them: a thousand pieces of mail from the product's domain, and a thousand empty
        applications on the organizer's list -- which also trips the D9 form lock."""
        monkeypatch.setattr(ApplicantsApi, "REQUEST_KEY_IP_LIMIT", 3)

        for i in range(3):
            _result, status = ApplicantsApi.request_applicant_key(
                "test-market", f"target{i}@example.com", client_ip="203.0.113.9",
            )
            assert status == 200, f"request {i} should be within the budget"

        result, status = ApplicantsApi.request_applicant_key(
            "test-market", "target3@example.com", client_ip="203.0.113.9",
        )

        assert status == 429
        assert result["error"] == ApplicantsApi.RATE_LIMITED_ERROR
        assert len(apps_coll.documents) == 3

    def test_the_per_ip_budget_is_per_ip(self, published_market, apps_coll, no_email, monkeypatch):
        monkeypatch.setattr(ApplicantsApi, "REQUEST_KEY_IP_LIMIT", 3)
        for i in range(3):
            ApplicantsApi.request_applicant_key(
                "test-market", f"target{i}@example.com", client_ip="203.0.113.9",
            )

        _result, status = ApplicantsApi.request_applicant_key(
            "test-market", "someone@example.com", client_ip="198.51.100.4",
        )

        assert status == 200

    def test_a_convention_opening_does_not_rate_limit_its_own_applicants(
        self, published_market, apps_coll, no_email,
    ):
        """The bound that is not kept, and why.

        A market's applications open at an announced hour and hundreds of vendors sign in within
        minutes of it -- from a hall's shared wifi, or from phones behind one carrier NAT, so the
        crowd is a handful of addresses rather than hundreds. A per-market cap, or a per-IP cap set
        anywhere near a plausible peak, throttles exactly that crowd at exactly that moment while an
        attacker with a proxy list walks around it. Both budgets are therefore sized so a real
        opening cannot reach them, and the captcha is what actually keeps scripts off the endpoint.
        """
        for i in range(250):
            _r, status = ApplicantsApi.request_applicant_key(
                "test-market", f"vendor{i}@example.com", client_ip="203.0.113.9",
            )
            assert status == 200, f"applicant {i} of a normal opening must not be refused"

        assert len(apps_coll.documents) == 250

    def test_a_global_ceiling_bounds_how_much_mail_the_product_will_send(
        self, published_market, apps_coll, no_email, monkeypatch,
    ):
        """Domain reputation is one shared resource, so it needs a bound that no number of source
        IPs can walk around."""
        monkeypatch.setattr(ApplicantsApi, "REQUEST_KEY_GLOBAL_LIMIT", 3)

        for i in range(3):
            _r, status = ApplicantsApi.request_applicant_key(
                "test-market", f"target{i}@example.com", client_ip=f"203.0.113.{i}",
            )
            assert status == 200

        result, status = ApplicantsApi.request_applicant_key(
            "test-market", "one-too-many@example.com", client_ip="198.51.100.4",
        )

        assert status == 429
        assert result["error"] == ApplicantsApi.RATE_LIMITED_ERROR

    def test_a_failed_captcha_sends_no_mail_and_creates_no_application(
        self, published_market, apps_coll, monkeypatch,
    ):
        """The same reCAPTCHA gate ``register_user_with_captcha`` puts on the organizer-side signup,
        because this is the same kind of surface: public, unauthenticated, and it writes."""
        monkeypatch.setattr(ApplicantsApi, "verify_recaptcha", lambda *_a, **_kw: (False, 0.0))
        sent = []

        with patch.object(
            ApplicantsApi, "send_otp_email",
            side_effect=lambda addr, otp: sent.append(addr) or True,
        ):
            result, status = ApplicantsApi.request_applicant_key(
                "test-market", "bot@example.com", "bad-token", "203.0.113.9",
            )

        assert status == 400
        assert result["error"] == ApplicantsApi.CAPTCHA_REQUIRED_ERROR
        assert sent == []
        assert apps_coll.documents == []

    def test_the_captcha_is_scored_against_the_caller_ip(self, published_market, apps_coll, no_email):
        seen = []

        with patch.object(
            ApplicantsApi, "verify_recaptcha",
            side_effect=lambda token, ip: seen.append((token, ip)) or (True, 1.0),
        ):
            ApplicantsApi.request_applicant_key(
                "test-market", "vendor@example.com", "tok-123", "203.0.113.9",
            )

        assert seen == [("tok-123", "203.0.113.9")]

    def test_a_caller_that_fails_the_captcha_cannot_spend_any_budget(
        self, published_market, apps_coll, no_email, monkeypatch,
    ):
        """No budget may be spent by a caller that has not passed the captcha -- the per-IP one too.

        Every budget here is one somebody else is also spending: the global ceiling is shared by
        every market's applicants, and a per-IP budget is shared by everyone behind a convention
        hall's wifi or a carrier's NAT. Counted before the captcha, each of them is an outage anyone
        can buy with a garbage token: the request is refused, but only *after* being counted, so a
        script that never solves a captcha holds the window down and the real applicants behind that
        address get a 429.
        """
        monkeypatch.setattr(ApplicantsApi, "REQUEST_KEY_GLOBAL_LIMIT", 3)
        monkeypatch.setattr(ApplicantsApi, "REQUEST_KEY_IP_LIMIT", 3)
        monkeypatch.setattr(ApplicantsApi, "verify_recaptcha", lambda *_a, **_kw: (False, 0.0))

        for i in range(10):
            _result, status = ApplicantsApi.request_applicant_key(
                "test-market", f"bot{i}@example.com", "bad-token", "203.0.113.9",
            )
            assert status == 400

        monkeypatch.setattr(ApplicantsApi, "verify_recaptcha", lambda *_a, **_kw: (True, 1.0))
        _result, from_the_same_address = ApplicantsApi.request_applicant_key(
            "test-market", "applicant@example.com", "good-token", "203.0.113.9",
        )
        _result, from_elsewhere = ApplicantsApi.request_applicant_key(
            "test-market", "other@example.com", "good-token", "198.51.100.4",
        )

        assert from_the_same_address == 200, "a refused request must not have spent the IP budget"
        assert from_elsewhere == 200, "a refused request must not have spent the shared ceiling"

    def test_a_refused_request_does_not_spend_the_budget_that_refused_it(
        self, published_market, apps_coll, no_email, monkeypatch,
    ):
        """A budget refusal must not itself deepen the hole: the window stays spent for its length,
        but a caller cannot drive a shared count further down by hammering a spent one."""
        monkeypatch.setattr(ApplicantsApi, "REQUEST_KEY_IP_LIMIT", 2)

        for i in range(2):
            ApplicantsApi.request_applicant_key(
                "test-market", f"vendor{i}@example.com", client_ip="203.0.113.9",
            )
        for i in range(10):
            _r, status = ApplicantsApi.request_applicant_key(
                "test-market", f"bot{i}@example.com", client_ip="203.0.113.9",
            )
            assert status == 429

        monkeypatch.setattr(ApplicantsApi, "REQUEST_KEY_IP_LIMIT", 3)
        _r, status = ApplicantsApi.request_applicant_key(
            "test-market", "late@example.com", client_ip="203.0.113.9",
        )

        assert status == 200, "the window held 2 admitted requests, not 12"


class TestTheClockSaysNothingTheBodyDoesNot:
    """The enumeration guard is closed in the body, and it also has to hold on the clock.

    ``send_otp_email`` is a network round-trip to Resend, and it happens only for an address an
    application exists for. Returned as soon as its work is done, the response for an address on the
    organizer's applicant list takes hundreds of milliseconds longer than the response for one that
    is not, which answers - to the same unauthenticated caller the identical wording exists to defeat
    - exactly the question the body refuses to.

    The send is *awaited*, inside a floor on the response time. Handing it to a background thread
    also hides it, but only where the process outlives the response, and this product documents a
    serverless target: there the context is frozen the moment the response is written and the mail
    may never be sent at all. An applicant who is promised a code and never gets one is the worse
    failure of the two, and the floor closes the side-channel without risking it.
    """

    FLOOR = 0.25

    def _elapsed(self, market_slug, email):
        started = time.monotonic()
        _result, status = ApplicantsApi.request_applicant_key(market_slug, email)
        return time.monotonic() - started, status

    def test_the_mail_is_sent_on_the_request_thread_not_handed_to_one_that_may_never_run(
        self, published_market, apps_coll,
    ):
        """The send has to have *happened* by the time the response is written.

        Handing it to a background thread is what a serverless host breaks: the execution context is
        frozen the moment the response goes out, so the thread may never be scheduled and the
        applicant is promised a code that was never sent. Asserting only that the mail eventually
        arrives would not catch that - an unjoined thread usually wins that race in a test - so what
        is pinned is the thing a freeze cannot survive: the send runs on the thread that is answering
        the request, before it answers.
        """
        sent = []

        with patch.object(
            ApplicantsApi, "send_otp_email",
            side_effect=lambda addr, otp: sent.append((addr, threading.get_ident())) or True,
        ):
            _result, status = ApplicantsApi.request_applicant_key(
                "test-market", "vendor@example.com",
            )

        assert status == 200
        assert sent == [("vendor@example.com", threading.get_ident())]

    def test_a_send_that_fails_is_logged_and_never_named_to_the_caller(
        self, published_market, apps_coll, caplog,
    ):
        """Resend being down is the operator's problem, and it must not become the caller's answer:
        a send can only fail for an address there was an application to mail a code to, so a
        response that reported it would name that address as an applicant to anyone who asked."""
        with patch.object(
            ApplicantsApi, "send_otp_email", side_effect=RuntimeError("resend is down"),
        ):
            result, status = ApplicantsApi.request_applicant_key(
                "test-market", "vendor@example.com",
            )

        assert status == 200
        assert result == {"message": ApplicantsApi.KEY_REQUEST_ACCEPTED_MESSAGE}
        assert "vendor@example.com" in caplog.text, "the operator has to be able to see it"

    def test_an_applicant_and_a_stranger_are_answered_at_the_same_speed(
        self, apps_coll, no_email, login_codes, monkeypatch,
    ):
        """The market takes no new applications, so only the applicant's request sends mail. That
        send is the signal, and the floor is what buries it."""
        monkeypatch.setattr(ApplicantsApi, "KEY_REQUEST_FLOOR_SECONDS", self.FLOOR)
        monkeypatch.setattr(ApplicantsApi, "markets_collection", FakeSlugMarketsCollection([
            stored_market(phase=MarketPhase.APPLICATIONS_CLOSED, name="Closed Market", id="closed-1")
        ]))
        apps_coll.insert_one(Application(
            market_id="closed-1", applicant_email="vendor@example.com",
            form_data={}, status=ApplicationStatus.OPEN,
        ).model_dump())
        # A send is a network round-trip; the floor exists to be longer than one.
        monkeypatch.setattr(
            ApplicantsApi, "send_otp_email",
            lambda _addr, _otp: time.sleep(self.FLOOR / 2) or True,
        )

        applicant, applicant_status = self._elapsed("closed-market", "vendor@example.com")
        stranger, stranger_status = self._elapsed("closed-market", "stranger@example.com")

        assert applicant_status == stranger_status == 200
        assert applicant >= self.FLOOR
        assert stranger >= self.FLOOR

    def test_a_slow_captcha_does_not_eat_the_floor_the_send_hides_behind(
        self, apps_coll, login_codes, monkeypatch,
    ):
        """The floor has to cover the work that *branches*, so its clock starts where the branch
        does - not at the top of the request.

        Timed from the top, the shared prelude spends the budget: the captcha is an outbound call to
        Google with a five-second timeout, and one slow-but-successful verify is enough to leave
        nothing of the floor by the time the send begins. The send then lands back on the response
        clock in full, and the applicant answers slower than the stranger again - the enumeration
        oracle, restored by the tail latency an attacker only has to be patient enough to wait for.
        """
        monkeypatch.setattr(ApplicantsApi, "KEY_REQUEST_FLOOR_SECONDS", self.FLOOR)
        monkeypatch.setattr(ApplicantsApi, "markets_collection", FakeSlugMarketsCollection([
            stored_market(phase=MarketPhase.APPLICATIONS_CLOSED, name="Closed Market", id="closed-1")
        ]))
        apps_coll.insert_one(Application(
            market_id="closed-1", applicant_email="vendor@example.com",
            form_data={}, status=ApplicationStatus.OPEN,
        ).model_dump())
        # Google having a slow day. It runs for every caller and tells nobody's address apart.
        monkeypatch.setattr(
            ApplicantsApi, "verify_recaptcha",
            lambda *_a, **_kw: time.sleep(self.FLOOR) or (True, 0.9),
        )
        monkeypatch.setattr(
            ApplicantsApi, "send_otp_email",
            lambda _addr, _otp: time.sleep(self.FLOOR / 2) or True,
        )

        applicant, applicant_status = self._elapsed("closed-market", "vendor@example.com")
        stranger, stranger_status = self._elapsed("closed-market", "stranger@example.com")

        assert applicant_status == stranger_status == 200
        # The send is half a floor long and must still be buried by it: what separates the two is
        # scheduling noise, not a round-trip to Resend.
        assert abs(applicant - stranger) < self.FLOOR / 2, (
            "the send is back on the response clock: the floor was spent before the branch ran"
        )

    def test_a_refusal_is_not_held_back(self, published_market, apps_coll, no_email, monkeypatch):
        """The floor is for the answers that could betray the applicant list. A refusal keyed on the
        caller -- a bad captcha -- knows nothing about the address, so it costs nobody the wait."""
        monkeypatch.setattr(ApplicantsApi, "KEY_REQUEST_FLOOR_SECONDS", 5)
        monkeypatch.setattr(ApplicantsApi, "verify_recaptcha", lambda *_a, **_kw: (False, 0.0))

        started = time.monotonic()
        _result, status = ApplicantsApi.request_applicant_key(
            "test-market", "bot@example.com", "bad-token", "203.0.113.9",
        )

        assert status == 400
        assert time.monotonic() - started < 1

    def test_an_open_market_pays_no_floor_at_all(
        self, published_market, apps_coll, no_email, monkeypatch,
    ):
        """The floor buries a difference, and in ``applications_open`` there is none to bury: an
        address with no application gets one, so every caller pays for a send.

        Charging it anyway would be a ``time.sleep`` held over the busiest hour this product has --
        a market whose applications open at an announced time takes hundreds of sign-ins in the first
        minutes of it, and each one holding a worker for the floor is the back end saturating itself,
        organizer endpoints included, at exactly the peak the rate limits are written to let through.
        """
        monkeypatch.setattr(ApplicantsApi, "KEY_REQUEST_FLOOR_SECONDS", 5)

        elapsed, status = self._elapsed("test-market", "vendor@example.com")

        assert status == 200
        assert elapsed < 1, "an open market's applicants must not queue behind the floor"

    def test_the_open_market_that_pays_no_floor_still_sends_to_every_caller(
        self, published_market, apps_coll,
    ):
        """The premise the line above rests on, pinned: it is only safe to drop the floor here
        because a stranger's request costs exactly what an applicant's does -- an application, and
        the send that follows it. If a phase ever stopped mailing a first-time address, the send
        would be a branch again, and the floor would have to come back with it."""
        sent = []

        with patch.object(
            ApplicantsApi, "send_otp_email",
            side_effect=lambda addr, _otp: sent.append(addr) or True,
        ):
            ApplicantsApi.request_applicant_key("test-market", "stranger@example.com")

        assert sent == ["stranger@example.com"]
        assert ApplicantsApi._key_request_floor(MarketPhase.APPLICATIONS_OPEN) == 0

    @pytest.mark.parametrize("phase", [
        MarketPhase.APPLICATIONS_CLOSED,
        MarketPhase.REVIEW,
        MarketPhase.OFFERS,
    ])
    def test_every_phase_that_takes_no_new_applications_keeps_the_floor(self, phase):
        """Those are the phases where the send happens for an applicant and not for a stranger, so
        they are the phases the floor is for. They are also the quiet ones: nobody signs in in bulk
        after applications close."""
        assert ApplicantsApi._key_request_floor(phase) == ApplicantsApi.KEY_REQUEST_FLOOR_SECONDS


class TestIssuingAChallengeConcurrently:
    """The unique index on (market, email) is what stops one address holding two live codes, and
    two attempt budgets with it. Its failure mode is a ``DuplicateKeyError`` on the insert branch --
    which two concurrent requests for the same address can both take -- and unhandled that is a 500
    on a public endpoint, reachable on purpose by anyone willing to race it."""

    class _RacedCollection(FakeKeyedCollection):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        def update_one(self, query, update, upsert=False):
            self.attempts += 1
            if self.attempts == 1:
                # The concurrent request won the insert; the index refuses this one.
                super().update_one(query, update, upsert=upsert)
                raise DuplicateKeyError("market_email_unique")
            return super().update_one(query, update, upsert=upsert)

    def test_a_lost_insert_race_is_retried_not_returned_as_a_500(
        self, published_market, apps_coll, no_email, monkeypatch,
    ):
        raced = self._RacedCollection()
        monkeypatch.setattr(ApplicantsApi, "login_codes_collection", raced)

        result, status = ApplicantsApi.request_applicant_key("test-market", "vendor@example.com")

        assert status == 200
        assert result == {"message": ApplicantsApi.KEY_REQUEST_ACCEPTED_MESSAGE}
        assert raced.attempts == 2, "the retry is what takes the update branch"
        assert _stored_challenge(raced, "vendor@example.com") is not None


class TestCreatingAnApplicationConcurrently:
    """One applicant is one application, and only the database can hold that.

    ``request_applicant_key`` reads the applicant list before it writes to it, so two requests for
    the same new address can sit between the read and the write at once -- raced on purpose, or by
    nothing worse than a double-tapped button or a retried request. Two inserts then leave two main
    applications for one person: every read of an applicant's application finds one of them and takes
    it, so the other is unreachable forever, and it sits on the organizer's list double-counting them
    through review, through assignment, and through the D9 form lock.
    """

    class _RacedCollection(FakeApplicationsCollection):
        def __init__(self):
            super().__init__()
            self.upserts = 0

        def find_one_and_update(self, query, update, upsert=False, return_document=None):
            self.upserts += 1
            if self.upserts == 1:
                # The concurrent request's insert landed first; the unique index refuses this one.
                super().find_one_and_update(
                    query, update, upsert=upsert, return_document=return_document,
                )
                raise DuplicateKeyError(ApplicationsApi.APPLICANT_IDENTITY_INDEX)
            return super().find_one_and_update(
                query, update, upsert=upsert, return_document=return_document,
            )

    def test_a_lost_insert_race_yields_the_winners_application_not_a_second_one(
        self, published_market, no_email, monkeypatch,
    ):
        raced = self._RacedCollection()
        monkeypatch.setattr(ApplicationsApi, "applications_collection", raced)

        result, status = ApplicantsApi.request_applicant_key("test-market", "vendor@example.com")

        assert status == 200, "the duplicate must not surface as a 500 on a public endpoint"
        assert result == {"message": ApplicantsApi.KEY_REQUEST_ACCEPTED_MESSAGE}
        assert len(raced.documents) == 1, "the loser must not leave a second application behind"

    def test_creating_an_application_twice_returns_the_one_that_exists(self, apps_coll):
        """The upsert itself, without a race: the second creation is a read of the first."""
        def _new():
            return Application(
                market_id="market-123", applicant_email="vendor@example.com",
                form_data={}, status=ApplicationStatus.OPEN,
                application_type=ApplicationType.MAIN,
            )

        first = ApplicationsApi.find_or_create_application(_new())
        second = ApplicationsApi.find_or_create_application(_new())

        assert second.id == first.id, "a fresh id would be a second application"
        assert len(apps_coll.documents) == 1

    def test_a_waitlist_application_is_not_the_main_one(self, apps_coll):
        """The identity is (market, email, *type*): an applicant may hold one of each, and the index
        that stops the duplicate must not stop the waitlist entry beside it."""
        main = ApplicationsApi.find_or_create_application(Application(
            market_id="market-123", applicant_email="vendor@example.com",
            form_data={}, status=ApplicationStatus.OPEN,
            application_type=ApplicationType.MAIN,
        ))
        waitlist = ApplicationsApi.find_or_create_application(Application(
            market_id="market-123", applicant_email="vendor@example.com",
            form_data={}, status=ApplicationStatus.OPEN,
            application_type=ApplicationType.WAITLIST,
        ))

        assert waitlist.id != main.id
        assert len(apps_coll.documents) == 2

    def test_the_stored_document_is_the_one_the_model_describes(self, apps_coll):
        """The upsert builds the document from the filter plus ``$setOnInsert``, so what it stores
        has to be checked, not assumed: every field of the model, under the snake_case keys the
        collection's contract names."""
        app = ApplicationsApi.find_or_create_application(Application(
            market_id="market-123", applicant_email="vendor@example.com",
            form_data={}, status=ApplicationStatus.OPEN,
            application_type=ApplicationType.MAIN,
        ))

        stored = apps_coll.find_one({"id": app.id})
        assert stored is not None
        assert stored[ApplicationsApi.MARKET_ID_FIELD] == "market-123"
        assert stored[ApplicationsApi.APPLICANT_EMAIL_FIELD] == "vendor@example.com"
        assert stored[ApplicationsApi.APPLICATION_TYPE_FIELD] == ApplicationType.MAIN.value
        assert set(stored) == set(Application(
            market_id="market-123", applicant_email="vendor@example.com",
            form_data={}, status=ApplicationStatus.OPEN,
        ).model_dump())


class TestVerifyKey:
    """Tests for verify_applicant_key (Stage 2 of the login flow)."""

    def _signed_up(self, apps_coll, login_codes, *, email="vendor@example.com", attempts=0):
        """An application with a live code, exactly as stage 1 would have left it."""
        otp = generate_otp()
        app = Application(
            market_id="market-123",
            applicant_email=email,
            form_data={},
            status=ApplicationStatus.OPEN,
        )
        apps_coll.insert_one(app.model_dump())
        _seed_challenge(login_codes, email, code=otp, attempts=attempts)
        return app, otp

    def test_returns_token_on_success(self, published_market, apps_coll, login_codes):
        _app, otp = self._signed_up(apps_coll, login_codes)

        result, status = ApplicantsApi.verify_applicant_key(
            "test-market", "vendor@example.com", otp
        )

        assert status == 200
        assert "token" in result
        assert result["application"]["applicantEmail"] == "vendor@example.com"

    def test_returns_application_data_in_camel_case(self, published_market, apps_coll, login_codes):
        _app, otp = self._signed_up(apps_coll, login_codes)

        result, status = ApplicantsApi.verify_applicant_key(
            "test-market", "vendor@example.com", otp
        )

        assert status == 200
        app_data = result["application"]
        assert "applicantEmail" in app_data
        assert "marketId" in app_data
        assert "formData" in app_data
        assert "status" in app_data

    def test_rejects_wrong_key(self, published_market, apps_coll, login_codes):
        _app, otp = self._signed_up(apps_coll, login_codes)
        wrong_otp = "000000" if otp != "000000" else "111111"

        result, status = ApplicantsApi.verify_applicant_key(
            "test-market", "vendor@example.com", wrong_otp
        )

        assert status == 401
        assert "Incorrect code" in result["error"]
        assert "attempt" in result["error"]

    def test_tracks_failed_attempts(self, published_market, apps_coll, login_codes):
        _app, otp = self._signed_up(apps_coll, login_codes)
        wrong_otp = "000000" if otp != "000000" else "111111"

        ApplicantsApi.verify_applicant_key("test-market", "vendor@example.com", wrong_otp)

        assert _stored_challenge(login_codes, "vendor@example.com")["attempts"] == 1

    def test_locks_after_max_attempts(self, published_market, apps_coll, login_codes):
        _app, _otp = self._signed_up(apps_coll, login_codes, attempts=MAX_ATTEMPTS)

        result, status = ApplicantsApi.verify_applicant_key(
            "test-market", "vendor@example.com", "000000"
        )

        assert status == 429
        assert "Too many incorrect attempts" in result["error"]

    def test_a_spent_budget_does_not_admit_the_right_code(
        self, published_market, apps_coll, login_codes,
    ):
        _app, otp = self._signed_up(apps_coll, login_codes, attempts=MAX_ATTEMPTS)

        _result, status = ApplicantsApi.verify_applicant_key(
            "test-market", "vendor@example.com", otp
        )

        assert status == 429

    def test_rejects_expired_otp(self, published_market, apps_coll, login_codes):
        otp = generate_otp()
        apps_coll.insert_one(Application(
            market_id="market-123", applicant_email="vendor@example.com",
            form_data={}, status=ApplicationStatus.OPEN,
        ).model_dump())
        _seed_challenge(login_codes, "vendor@example.com", code=otp, issued_seconds_ago=EXPIRED)

        result, status = ApplicantsApi.verify_applicant_key(
            "test-market", "vendor@example.com", otp
        )

        assert status == 401
        assert "expired" in result["error"].lower()

    def test_clears_the_challenge_on_success(self, published_market, apps_coll, login_codes):
        _app, otp = self._signed_up(apps_coll, login_codes)

        ApplicantsApi.verify_applicant_key("test-market", "vendor@example.com", otp)

        assert _stored_challenge(login_codes, "vendor@example.com") is None

    def test_a_spent_code_cannot_be_replayed(self, published_market, apps_coll, login_codes):
        _app, otp = self._signed_up(apps_coll, login_codes)

        _first, first_status = ApplicantsApi.verify_applicant_key(
            "test-market", "vendor@example.com", otp
        )
        second, second_status = ApplicantsApi.verify_applicant_key(
            "test-market", "vendor@example.com", otp
        )

        assert first_status == 200
        assert second_status == 401
        assert second["error"] == ApplicantsApi.NO_PENDING_CODE_ERROR

    def test_an_address_that_never_applied_is_answered_as_a_spent_code(
        self, published_market, apps_coll, login_codes,
    ):
        """The refusal cannot say "no application found for this email": that confirms, to an
        unauthenticated caller, which addresses are on the market's applicant list."""
        stranger = ApplicantsApi.verify_applicant_key(
            "test-market", "never-applied@example.com", "123456"
        )

        # An application whose code has been used or has expired -- the only other way to get here.
        apps_coll.insert_one(Application(
            market_id="market-123", applicant_email="vendor@example.com",
            form_data={}, status=ApplicationStatus.OPEN,
        ).model_dump())
        spent = ApplicantsApi.verify_applicant_key(
            "test-market", "vendor@example.com", "123456"
        )

        assert stranger == spent == ({"error": ApplicantsApi.NO_PENDING_CODE_ERROR}, 401)

    def test_a_wrong_code_answers_a_stranger_and_an_applicant_identically(
        self, apps_coll, login_codes, no_email, monkeypatch,
    ):
        """The whole public sequence, in a phase where request-key does *not* create applications --
        which is where the wrong-code refusal used to be an oracle: "incorrect code, 4 attempts
        remaining" for an address on the organizer's applicant list, "there is no pending code" for
        one that is not, straight off a pair of unauthenticated calls."""
        monkeypatch.setattr(ApplicantsApi, "markets_collection", FakeSlugMarketsCollection([
            stored_market(phase=MarketPhase.REVIEW, name="Closed Market", id="closed-1")
        ]))
        apps_coll.insert_one(Application(
            market_id="closed-1", applicant_email="applied@example.com",
            form_data={"business_name": "Acme"}, status=ApplicationStatus.OPEN,
        ).model_dump())

        def probe(email):
            ApplicantsApi.request_applicant_key("closed-market", email)
            return [
                ApplicantsApi.verify_applicant_key("closed-market", email, "000000")
                for _ in range(MAX_ATTEMPTS + 1)
            ]

        assert probe("applied@example.com") == probe("stranger@example.com")

    def test_every_phase_answers_a_stranger_and_an_applicant_identically(
        self, apps_coll, login_codes, no_email, monkeypatch,
    ):
        for phase in (
            MarketPhase.APPLICATIONS_OPEN,
            MarketPhase.APPLICATIONS_CLOSED,
            MarketPhase.REVIEW,
            MarketPhase.OFFERS,
            MarketPhase.ARCHIVED,
        ):
            apps_coll.documents.clear()
            login_codes.documents.clear()
            monkeypatch.setattr(ApplicantsApi, "markets_collection", FakeSlugMarketsCollection([
                stored_market(phase=phase, name="Some Market", id="m-1")
            ]))
            apps_coll.insert_one(Application(
                market_id="m-1", applicant_email="applied@example.com",
                form_data={}, status=ApplicationStatus.OPEN,
            ).model_dump())

            applied_request = ApplicantsApi.request_applicant_key("some-market", "applied@example.com")
            applied_verify = ApplicantsApi.verify_applicant_key(
                "some-market", "applied@example.com", "000000",
            )
            stranger_request = ApplicantsApi.request_applicant_key("some-market", "stranger@example.com")
            stranger_verify = ApplicantsApi.verify_applicant_key(
                "some-market", "stranger@example.com", "000000",
            )

            assert applied_request == stranger_request, phase
            assert applied_verify == stranger_verify, phase

    def test_the_attempt_cap_does_not_depend_on_a_read(
        self, published_market, apps_coll, login_codes, monkeypatch,
    ):
        """The cap has to be spent and checked in one operation, or it is not a cap.

        Read the count, find it under the cap, then increment it, and guesses issued at once all
        read the same pre-increment value, all pass the check, and all get compared against the live
        code: the budget becomes the number of workers the caller has rather than five, which is a
        brute-force budget against a 5-minute code. What that looks like from here is a read that
        does not see the increments - which is what this pins, by answering every read with the
        challenge as it stood before any attempt was spent.
        """
        _app, otp = self._signed_up(apps_coll, login_codes)
        wrong = "000000" if otp != "000000" else "111111"
        stale = _stored_challenge(login_codes, "vendor@example.com")
        assert stale["attempts"] == 0
        monkeypatch.setattr(login_codes, "find_one", lambda _query: dict(stale))

        statuses = [
            ApplicantsApi.verify_applicant_key("test-market", "vendor@example.com", wrong)[1]
            for _ in range(MAX_ATTEMPTS + 3)
        ]

        assert statuses.count(401) == MAX_ATTEMPTS - 1, "only the budget's worth may be compared"
        assert statuses[-1] == 429
        # Read past the stale-read patch: the document itself, as the conditional update left it.
        assert login_codes.documents[0]["attempts"] == MAX_ATTEMPTS

    def test_the_right_code_is_refused_once_a_concurrent_burst_has_spent_the_budget(
        self, published_market, apps_coll, login_codes, monkeypatch,
    ):
        _app, otp = self._signed_up(apps_coll, login_codes)
        stale = _stored_challenge(login_codes, "vendor@example.com")
        monkeypatch.setattr(login_codes, "find_one", lambda _query: dict(stale))
        for _ in range(MAX_ATTEMPTS):
            ApplicantsApi.verify_applicant_key("test-market", "vendor@example.com", "000000")

        _result, status = ApplicantsApi.verify_applicant_key(
            "test-market", "vendor@example.com", otp,
        )

        assert status == 429

    def test_guessing_is_bounded_per_caller(
        self, published_market, apps_coll, login_codes, monkeypatch,
    ):
        """The attempt cap is per code and the cooldown is per address, so neither of them bounds a
        caller that cycles request + guess against one address for as long as it likes."""
        monkeypatch.setattr(ApplicantsApi, "VERIFY_KEY_IP_LIMIT", 5)
        self._signed_up(apps_coll, login_codes)

        for _ in range(5):
            ApplicantsApi.verify_applicant_key(
                "test-market", "vendor@example.com", "000000", client_ip="203.0.113.9",
            )

        result, status = ApplicantsApi.verify_applicant_key(
            "test-market", "vendor@example.com", "000000", client_ip="203.0.113.9",
        )

        assert status == 429
        assert result["error"] == ApplicantsApi.RATE_LIMITED_ERROR

    def test_a_failed_captcha_spends_no_budget_and_compares_no_guess(
        self, published_market, apps_coll, login_codes, rate_limits, monkeypatch,
    ):
        """The rule the budgets are written under: nothing spends one before passing the captcha.

        The guess budget is per-IP, and a per-IP budget is not one caller's - everybody behind a
        convention hall's wifi or a carrier's CGNAT pool spends the same one. A script that could
        charge it without passing the captcha would not be guessing codes, it would be taking sign-in
        away from every real applicant behind that address, which is the outage the ceiling exists to
        prevent rather than to become.
        """
        _app, otp = self._signed_up(apps_coll, login_codes)
        monkeypatch.setattr(ApplicantsApi, "verify_recaptcha", lambda *_a, **_kw: (False, 0.0))

        result, status = ApplicantsApi.verify_applicant_key(
            "test-market", "vendor@example.com", otp, "bad-token", "203.0.113.9",
        )

        assert status == 400
        assert result["error"] == ApplicantsApi.CAPTCHA_REQUIRED_ERROR
        assert rate_limits.documents == [], "a caller that failed the captcha spent a shared budget"
        assert _stored_challenge(login_codes, "vendor@example.com")["attempts"] == 0, (
            "the code was compared against a guess that never passed the captcha"
        )

    def test_the_captcha_is_scored_against_the_caller_ip(
        self, published_market, apps_coll, login_codes,
    ):
        seen = []

        with patch.object(
            ApplicantsApi, "verify_recaptcha",
            side_effect=lambda token, ip: seen.append((token, ip)) or (True, 1.0),
        ):
            ApplicantsApi.verify_applicant_key(
                "test-market", "vendor@example.com", "000000", "tok-123", "203.0.113.9",
            )

        assert seen == [("tok-123", "203.0.113.9")]

    def test_separate_market_otps_dont_cross_markets(self, apps_coll, login_codes, no_email, monkeypatch):
        fake1 = FakeSlugMarketsCollection([
            stored_market(phase=MarketPhase.APPLICATIONS_OPEN, name="Market One", id="mkt-1")
        ])
        app1_otp = generate_otp()
        app2_otp = generate_otp()
        for market_id in ("mkt-1", "mkt-2"):
            apps_coll.insert_one(Application(
                market_id=market_id,
                applicant_email="vendor@example.com",
                form_data={},
                status=ApplicationStatus.OPEN,
            ).model_dump())
        _seed_challenge(login_codes, "vendor@example.com", code=app1_otp, market_id="mkt-1")
        _seed_challenge(login_codes, "vendor@example.com", code=app2_otp, market_id="mkt-2")

        with patch.object(ApplicantsApi, "markets_collection", fake1):
            result, status = ApplicantsApi.verify_applicant_key(
                "market-one", "vendor@example.com", app1_otp
            )
            crossed, crossed_status = ApplicantsApi.verify_applicant_key(
                "market-one", "vendor@example.com", app2_otp
            )

        assert status == 200
        assert result["application"]["marketId"] == "mkt-1"
        assert crossed_status == 401

    def test_validates_missing_fields(self, apps_coll):
        result, status = ApplicantsApi.verify_applicant_key("", "test@example.com", "123456")
        assert status == 400

        result, status = ApplicantsApi.verify_applicant_key("test-market", "", "123456")
        assert status == 400

        result, status = ApplicantsApi.verify_applicant_key("test-market", "test@example.com", "")
        assert status == 400

    def test_refuses_a_malformed_email(self, published_market, apps_coll):
        """The address is the application's key on both stages of the flow, so it is one rule."""
        result, status = ApplicantsApi.verify_applicant_key(
            "test-market", "vendor@gmail", "123456",
        )

        assert status == 400
        assert "valid email" in result["error"].lower()


class TestAuthenticateRequest:
    """Tests for the token authentication helper."""

    def test_returns_none_for_missing_header(self):
        assert ApplicantsApi.authenticate_request(None) is None

    def test_returns_none_for_malformed_header(self):
        assert ApplicantsApi.authenticate_request("invalid") is None
        assert ApplicantsApi.authenticate_request("Bearer") is None

    def test_returns_payload_for_valid_token(self):
        from utils.application_token import generate_application_token
        token = generate_application_token("app-1", "mkt-1", "test@example.com")
        payload = ApplicantsApi.authenticate_request(f"Bearer {token}")
        assert payload is not None
        assert payload["application_id"] == "app-1"

    def test_returns_none_for_expired_token(self):
        import time, jwt
        from utils.secret_key import signing_secret
        expired = jwt.encode(
            {"application_id": "a", "market_id": "m", "email": "e", "exp": int(time.time()) - 1},
            signing_secret(),
            algorithm="HS256",
        )
        assert ApplicantsApi.authenticate_request(f"Bearer {expired}") is None

    def test_a_token_signed_with_the_secret_this_repository_used_to_publish_is_refused(self):
        """The signing key was once a literal committed to this repo, which made every applicant
        token forgeable by anyone who could read it. There is no fallback secret now, so the string
        that used to be one authenticates nobody."""
        import time, jwt
        forged = jwt.encode(
            {
                "application_id": "someone-elses-app",
                "market_id": "m",
                "email": "victim@example.com",
                "exp": int(time.time()) + 600,
            },
            "TEMP_KEY_CHANGE_IN_PRODUCTION",
            algorithm="HS256",
        )
        assert ApplicantsApi.authenticate_request(f"Bearer {forged}") is None


class TestGetApplication:
    TOKEN = {
        "application_id": "app-xyz",
        "market_id": "market-123",
        "email": "vendor@example.com",
    }

    def test_returns_404_for_missing_application(self, published_market, apps_coll):
        result, status = ApplicantsApi.get_applicant_application(
            "test-market", {**self.TOKEN, "application_id": "no-such-app"},
        )

        assert status == 404

    def test_returns_application_in_camel_case(self, published_market, apps_coll):
        app = Application(
            id="app-xyz",
            market_id="market-123",
            applicant_email="vendor@example.com",
            form_data={"business_name": "Acme"},
            status=ApplicationStatus.OPEN,
        )
        apps_coll.insert_one(app.model_dump())

        result, status = ApplicantsApi.get_applicant_application("test-market", self.TOKEN)

        assert status == 200
        assert result["application"]["applicantEmail"] == "vendor@example.com"
        assert result["application"]["formData"]["business_name"] == "Acme"


class TestReviewerVerdictIsNotSentToTheApplicant:
    """The organizer delivers the decision; a reviewer recording one does not.

    The applicant's browser can read everything the server sends it, so the verdict has to be gone
    from the payload, not merely from the label rendered over it: a client-side mapping still ships
    ``reviewer_rejected`` in the response body and into the page markup.
    """

    TOKEN = {
        "application_id": "app-xyz",
        "market_id": "market-123",
        "email": "vendor@example.com",
    }

    def _application_with_status(self, apps_coll, status):
        apps_coll.insert_one(Application(
            id="app-xyz",
            market_id="market-123",
            applicant_email="vendor@example.com",
            form_data={"business_name": "Acme"},
            status=status,
        ).model_dump())

    @pytest.mark.parametrize("stored", sorted(ApplicantsApi.REVIEW_IN_PROGRESS_STATUSES))
    def test_a_review_in_progress_reads_as_under_review(
        self, published_market, apps_coll, stored,
    ):
        self._application_with_status(apps_coll, stored)

        result, _ = ApplicantsApi.get_applicant_application("test-market", self.TOKEN)

        assert result["application"]["status"] == ApplicationStatus.UNDER_REVIEW.value

    def test_an_approval_and_a_rejection_are_indistinguishable(self, published_market, apps_coll):
        approved = ApplicantsApi.applicant_visible_status(ApplicationStatus.REVIEWER_APPROVED)
        rejected = ApplicantsApi.applicant_visible_status(ApplicationStatus.REVIEWER_REJECTED)

        assert approved == rejected == ApplicationStatus.UNDER_REVIEW

    @pytest.mark.parametrize("stored", [
        ApplicationStatus.OPEN,
        ApplicationStatus.ASSIGNMENT_SENT,
        ApplicationStatus.VENDOR_ACCEPTED,
        ApplicationStatus.VENDOR_REFUSED,
        ApplicationStatus.CANCELLED,
    ])
    def test_a_state_the_organizer_has_acted_outward_on_is_sent_as_it_is(
        self, published_market, apps_coll, stored,
    ):
        self._application_with_status(apps_coll, stored)

        result, _ = ApplicantsApi.get_applicant_application("test-market", self.TOKEN)

        assert result["application"]["status"] == stored.value


class TestSlugLookup:
    """The applicant endpoints resolve a market by the same slug rule the front end links with.

    ``marketNameToKebabSlug`` (front-end/src/utils/marketSlug.ts) folds accents before it
    substitutes, so "Café Market" is linked as /cafe-market/apply. A lookup that skipped the fold
    would compute "caf-market" and answer every applicant endpoint behind that link with 404.
    """

    ACCENTED_MARKET = stored_market(
        phase=MarketPhase.APPLICATIONS_OPEN,
        name="Café Market",
        applicationForm=VALID_FORM,
    )

    @pytest.fixture
    def accented_market(self, monkeypatch):
        fake = FakeSlugMarketsCollection([self.ACCENTED_MARKET])
        monkeypatch.setattr(ApplicantsApi, "markets_collection", fake)
        return fake

    def test_shared_rule_matches_the_front_end_slug(self):
        from market_documents import market_name_slug
        assert market_name_slug("Café Market") == "cafe-market"

    def test_accented_market_is_found_by_its_folded_slug(self, accented_market, apps_coll, no_email):
        result, status = ApplicantsApi.request_applicant_key("cafe-market", "vendor@example.com")

        assert status == 200, result

    def test_public_form_is_served_for_an_accented_market(self, accented_market):
        result, status = ApplicantsApi.get_public_application_form("cafe-market")

        assert status == 200
        assert result["is_open"] is True

    def test_attendance_resolves_the_same_market_by_the_same_slug(self, monkeypatch):
        """The check-in lookup and the applicant lookup are the same lookup."""
        import api.attendance as AttendanceApi

        fake = FakeSlugMarketsCollection([self.ACCENTED_MARKET])
        monkeypatch.setattr(AttendanceApi, "markets_collection", fake)
        monkeypatch.setattr(ApplicantsApi, "markets_collection", fake)

        by_check_in = AttendanceApi.get_published_market_by_slug("cafe-market")
        by_applicant = ApplicantsApi._get_market_doc_by_slug("cafe-market")

        assert by_check_in is not None
        assert by_applicant is not None
        assert by_check_in["id"] == by_applicant["id"]

    def test_draft_market_is_not_reachable_by_slug(self, monkeypatch):
        draft = stored_market(phase=MarketPhase.DRAFT, name="Café Market")
        monkeypatch.setattr(
            ApplicantsApi, "markets_collection", FakeSlugMarketsCollection([draft]),
        )

        assert ApplicantsApi._get_market_doc_by_slug("cafe-market") is None
