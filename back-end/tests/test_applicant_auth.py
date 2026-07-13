"""Tests for applicant email-key auth flow (request-key, verify-key, token validation).

The login endpoints are public, unauthenticated, and they send mail to whatever address they are
handed, so most of what is pinned here is what they *refuse* and what they refuse to *say*.
"""
from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import patch

from conftest import (
    FakeApplicationsCollection,
    FakeKeyedCollection,
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


class FakeSlugMarketsCollection:
    """Stand-in for the markets collection that supports both find_one and find
    (the latter is needed by _get_market_doc_by_slug which iterates with find())."""

    def __init__(self, docs):
        self.docs = docs if isinstance(docs, list) else [docs]
        self.last_update = None

    def find_one(self, query):
        for doc in self.docs:
            match = True
            for k, v in (query or {}).items():
                if doc.get(k) != v:
                    match = False
                    break
            if match:
                return dict(doc)
        return None

    def find(self, query):
        matched = [dict(d) for d in self.docs]
        return iter(matched)

    def update_one(self, _filter, update):
        self.last_update = update
        from types import SimpleNamespace
        return SimpleNamespace(matched_count=1, modified_count=1, upserted_id=None)

    def insert_one(self, document):
        from types import SimpleNamespace
        return SimpleNamespace(inserted_id="fake-id")


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

    Three layers, each answering what the others cannot: a captcha, so a script is not a caller at
    all; per-IP and global budgets, which bound a caller *across* addresses; and a per-address
    resend cooldown, which bounds the mail one applicant can be sent.
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
        self, published_market, apps_coll, no_email,
    ):
        """The cooldown is keyed on the address, so it bounds nothing about a caller that names a
        thousand of them: a thousand pieces of mail from the product's domain, and a thousand empty
        applications on the organizer's list -- which also trips the D9 form lock."""
        limit = ApplicantsApi.REQUEST_KEY_IP_LIMIT
        for i in range(limit):
            _result, status = ApplicantsApi.request_applicant_key(
                "test-market", f"target{i}@example.com", client_ip="203.0.113.9",
            )
            assert status == 200, f"request {i} should be within the budget"

        result, status = ApplicantsApi.request_applicant_key(
            "test-market", f"target{limit}@example.com", client_ip="203.0.113.9",
        )

        assert status == 429
        assert result["error"] == ApplicantsApi.RATE_LIMITED_ERROR
        assert len(apps_coll.documents) == limit

    def test_the_per_ip_budget_is_per_ip(self, published_market, apps_coll, no_email):
        for i in range(ApplicantsApi.REQUEST_KEY_IP_LIMIT):
            ApplicantsApi.request_applicant_key(
                "test-market", f"target{i}@example.com", client_ip="203.0.113.9",
            )

        _result, status = ApplicantsApi.request_applicant_key(
            "test-market", "someone@example.com", client_ip="198.51.100.4",
        )

        assert status == 200

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

    def test_guessing_is_bounded_per_caller(self, published_market, apps_coll, login_codes):
        """The attempt cap is per code and the cooldown is per address, so neither of them bounds a
        caller that cycles request + guess against one address for as long as it likes."""
        self._signed_up(apps_coll, login_codes)

        for _ in range(ApplicantsApi.VERIFY_KEY_IP_LIMIT):
            ApplicantsApi.verify_applicant_key(
                "test-market", "vendor@example.com", "000000", "203.0.113.9",
            )

        result, status = ApplicantsApi.verify_applicant_key(
            "test-market", "vendor@example.com", "000000", "203.0.113.9",
        )

        assert status == 429
        assert result["error"] == ApplicantsApi.RATE_LIMITED_ERROR

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
        import time, jwt, os
        expired = jwt.encode(
            {"application_id": "a", "market_id": "m", "email": "e", "exp": int(time.time()) - 1},
            os.getenv("SECRET_KEY", "TEMP_KEY_CHANGE_IN_PRODUCTION"),
            algorithm="HS256",
        )
        assert ApplicantsApi.authenticate_request(f"Bearer {expired}") is None


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
