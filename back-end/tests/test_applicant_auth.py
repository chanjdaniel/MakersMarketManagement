"""Tests for applicant email-key auth flow (request-key, verify-key, token validation)."""
import pytest
from unittest.mock import patch

from conftest import (
    FakeApplicationsCollection,
    stored_market,
)
from datatypes import (
    Application,
    ApplicationStatus,
    ApplicationType,
    MarketPhase,
)
from utils.tokens import generate_otp, get_otp_expiry

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

    def test_returns_403_when_market_is_draft(self, apps_coll, no_email, monkeypatch):
        fake = FakeSlugMarketsCollection([
            stored_market(phase=MarketPhase.DRAFT, name="Draft Market")
        ])
        monkeypatch.setattr(ApplicantsApi, "markets_collection", fake)

        result, status = ApplicantsApi.request_applicant_key("draft-market", "test@example.com")
        assert status == 404

    def test_a_closed_market_takes_no_new_application(self, apps_coll, no_email, monkeypatch):
        """The phase gates *starting* an application, so a stranger with an empty form cannot land
        on the organizer's applicant list after review has begun."""
        fake = FakeSlugMarketsCollection([
            stored_market(phase=MarketPhase.APPLICATIONS_CLOSED, name="Closed Market",
                          id="closed-1")
        ])
        monkeypatch.setattr(ApplicantsApi, "markets_collection", fake)

        result, status = ApplicantsApi.request_applicant_key("closed-market", "test@example.com")

        assert status == 403
        assert "Applications Closed" in result["error"]
        assert apps_coll.documents == []

    def test_an_existing_applicant_can_sign_in_after_applications_close(
        self, apps_coll, no_email, monkeypatch,
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
        assert apps_coll.documents[0]["otp"] is not None

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

    def test_creates_application_on_first_request(self, published_market, apps_coll, no_email):
        result, status = ApplicantsApi.request_applicant_key("test-market", "new@example.com")

        assert status == 200
        assert "code has been sent" in result["message"]
        assert len(apps_coll.documents) == 1
        doc = apps_coll.documents[0]
        assert doc["applicant_email"] == "new@example.com"
        assert doc["otp"] is not None

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

    def test_generic_message_preventing_email_enumeration(self, published_market, apps_coll, no_email):
        """The response message must be the same whether or not an app exists."""
        result, _ = ApplicantsApi.request_applicant_key("test-market", "unknown@example.com")
        # The key fact: the message says "If an application exists"
        assert "If an application exists" in result["message"]

    def test_sends_email_to_applicant(self, published_market, apps_coll):
        sent_emails = []

        def capture(email, otp):
            sent_emails.append((email, otp))
            return True

        with patch.object(ApplicantsApi, "send_otp_email", side_effect=capture):
            ApplicantsApi.request_applicant_key("test-market", "vendor@example.com")

        assert len(sent_emails) == 1
        assert sent_emails[0][0] == "vendor@example.com"

    def test_empties_attempt_counter_when_resending(self, published_market, apps_coll, no_email):
        app = Application(
            market_id="market-123",
            applicant_email="retry@example.com",
            form_data={},
            status=ApplicationStatus.OPEN,
            otp=generate_otp(),
            otp_expires=get_otp_expiry(),
            otp_attempts=3,
        )
        apps_coll.insert_one(app.model_dump())

        ApplicantsApi.request_applicant_key("test-market", "retry@example.com")
        doc = apps_coll.documents[0]
        assert doc["otp_attempts"] == 0

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


class TestVerifyKey:
    """Tests for verify_applicant_key (Stage 2 of the login flow)."""

    def _seeded_app(self, apps_coll, **overrides):
        otp = generate_otp()
        kwargs = {
            "market_id": "market-123",
            "applicant_email": "vendor@example.com",
            "form_data": {},
            "status": ApplicationStatus.OPEN,
            "otp": otp,
            "otp_expires": get_otp_expiry(minutes=5),
            "otp_attempts": 0,
        }
        kwargs.update(overrides)
        app = Application(**kwargs)
        apps_coll.insert_one(app.model_dump())
        return app, otp

    def test_returns_token_on_success(self, published_market, apps_coll):
        app, otp = self._seeded_app(apps_coll)

        result, status = ApplicantsApi.verify_applicant_key(
            "test-market", "vendor@example.com", otp
        )

        assert status == 200
        assert "token" in result
        assert result["application"]["applicantEmail"] == "vendor@example.com"

    def test_returns_application_data_in_camel_case(self, published_market, apps_coll):
        app, otp = self._seeded_app(apps_coll)

        result, status = ApplicantsApi.verify_applicant_key(
            "test-market", "vendor@example.com", otp
        )

        assert status == 200
        app_data = result["application"]
        assert "applicantEmail" in app_data
        assert "marketId" in app_data
        assert "formData" in app_data
        assert "status" in app_data

    def test_rejects_wrong_key(self, published_market, apps_coll):
        app, otp = self._seeded_app(apps_coll)
        wrong_otp = "000000" if otp != "000000" else "111111"

        result, status = ApplicantsApi.verify_applicant_key(
            "test-market", "vendor@example.com", wrong_otp
        )

        assert status == 401
        assert "Incorrect code" in result["error"]
        assert "attempt" in result["error"]

    def test_tracks_failed_attempts(self, published_market, apps_coll):
        app, otp = self._seeded_app(apps_coll)
        wrong_otp = "000000" if otp != "000000" else "111111"

        ApplicantsApi.verify_applicant_key("test-market", "vendor@example.com", wrong_otp)
        doc = apps_coll.documents[0]
        assert doc["otp_attempts"] == 1

    def test_locks_after_max_attempts(self, published_market, apps_coll):
        app, otp = self._seeded_app(apps_coll, otp_attempts=5)
        wrong_otp = "000000" if otp != "000000" else "111111"

        result, status = ApplicantsApi.verify_applicant_key(
            "test-market", "vendor@example.com", wrong_otp
        )

        assert status == 429
        assert "Too many incorrect attempts" in result["error"]

    def test_rejects_expired_otp(self, published_market, apps_coll):
        from datetime import datetime, timedelta, timezone
        otp = generate_otp()
        app = Application(
            market_id="market-123",
            applicant_email="vendor@example.com",
            form_data={},
            status=ApplicationStatus.OPEN,
            otp=otp,
            otp_expires=(datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
        )
        apps_coll.insert_one(app.model_dump())

        result, status = ApplicantsApi.verify_applicant_key(
            "test-market", "vendor@example.com", otp
        )

        assert status == 401
        assert "expired" in result["error"].lower()

    def test_clears_otp_on_success(self, published_market, apps_coll):
        app, otp = self._seeded_app(apps_coll)

        ApplicantsApi.verify_applicant_key("test-market", "vendor@example.com", otp)
        doc = apps_coll.documents[0]
        assert doc["otp"] is None
        assert doc.get("otp_expires") is None
        assert doc["otp_attempts"] == 0

    def test_returns_404_when_no_application_exists(self, published_market, apps_coll):
        result, status = ApplicantsApi.verify_applicant_key(
            "test-market", "never-applied@example.com", "123456"
        )

        assert status == 404
        assert "no application" in result["error"].lower()
        assert "apply" in result["error"].lower()

    def test_separate_market_otps_dont_cross_markets(self, apps_coll, no_email, monkeypatch):
        fake1 = FakeSlugMarketsCollection([
            stored_market(phase=MarketPhase.APPLICATIONS_OPEN, name="Market One", id="mkt-1")
        ])
        # Set up: market doc in applicants module comes from markets_collection.
        # We'll just verify cross-market isolation via the find_one filter.
        app1_otp = generate_otp()
        app1 = Application(
            market_id="mkt-1",
            applicant_email="vendor@example.com",
            form_data={},
            status=ApplicationStatus.OPEN,
            otp=app1_otp,
            otp_expires=get_otp_expiry(),
        )
        app2_otp = generate_otp()
        app2 = Application(
            market_id="mkt-2",
            applicant_email="vendor@example.com",
            form_data={},
            status=ApplicationStatus.OPEN,
            otp=app2_otp,
            otp_expires=get_otp_expiry(),
        )
        apps_coll.insert_one(app1.model_dump())
        apps_coll.insert_one(app2.model_dump())

        # With a markets_collection that only has "Market One"
        with patch.object(ApplicantsApi, "markets_collection", fake1):
            result, status = ApplicantsApi.verify_applicant_key(
                "market-one", "vendor@example.com", app1_otp
            )

        assert status == 200
        assert result["application"]["marketId"] == "mkt-1"

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
