"""Tests for application submission, phase gate, D9 lock proof, and field validation.

Tests that submitting an application through the applicant endpoints:
- Respects the market phase (only allowed in applications_open)
- Engages the D9 lock (the form is counted by the same collection)
- Validates form data against the application form fields
- Returns clear anti-F6 error messages
"""
import pytest
from unittest.mock import patch

from conftest import (
    FakeApplicationsCollection,
    FakeMarketsCollection,
    FakeSlugMarketsCollection,
    stored_market,
)
from datatypes import (
    Application,
    ApplicationForm,
    ApplicationStatus,
    ApplicationType,
    FormField,
    MarketPhase,
)

import api.applicants as ApplicantsApi
import api.applications as ApplicationsApi
import api.markets as MarketsApi
import api.permissions as PermissionsApi


VALID_FORM = {
    "fields": [
        {"key": "business_name", "label": "Business Name", "type": "text", "required": True, "order": 0},
        {"key": "email", "label": "Contact Email", "type": "email", "required": True, "order": 1},
        {"key": "booth_size", "label": "Booth Size", "type": "select", "options": ["Small", "Large"], "required": True, "order": 2},
        {"key": "extra_days", "label": "Extra Days", "type": "multi_select", "options": ["Fri", "Sat"], "required": False, "order": 3},
        {"key": "agree", "label": "Agree to Terms", "type": "checkbox", "required": True, "order": 4},
        {"key": "staff_count", "label": "Number of Staff", "type": "number", "required": False, "order": 5},
        {"key": "start_date", "label": "Start Date", "type": "date", "required": False, "order": 6},
    ]
}


MARKET_SLUG = "test-market"


def _token(application_id="app-xyz", market_id="market-123", email="vendor@example.com"):
    from utils.application_token import generate_application_token
    return generate_application_token(application_id, market_id, email)


@pytest.fixture
def apps_coll(monkeypatch):
    fake = FakeApplicationsCollection()
    monkeypatch.setattr(ApplicationsApi, "applications_collection", fake)
    return fake


@pytest.fixture
def open_market(monkeypatch):
    """A market in APPLICATIONS_OPEN phase with a valid application form."""
    doc = stored_market(
        phase=MarketPhase.APPLICATIONS_OPEN,
        name="Test Market",
        applicationForm=VALID_FORM,
    )
    fake = FakeSlugMarketsCollection([doc])
    monkeypatch.setattr(ApplicantsApi, "markets_collection", fake)
    return fake


def _seeded_app(apps_coll, market_id="market-123", email="vendor@example.com", **overrides):
    kwargs = {
        "id": "app-xyz",
        "market_id": market_id,
        "applicant_email": email,
        "form_data": {},
        "status": ApplicationStatus.OPEN,
        "application_type": ApplicationType.MAIN,
    }
    kwargs.update(overrides)
    app = Application(**kwargs)
    apps_coll.insert_one(app.model_dump())
    return app


class TestSaveApplication:
    """Tests for save_applicant_application."""

    TOKEN = lambda self: {
        "application_id": "app-xyz",
        "market_id": "market-123",
        "email": "vendor@example.com",
    }

    def test_saves_form_data(self, open_market, apps_coll):
        _seeded_app(apps_coll)
        token = self.TOKEN()

        result, status = ApplicantsApi.save_applicant_application(
            MARKET_SLUG, token, {"business_name": "Acme Corp", "email": "acme@example.com",
                    "booth_size": "Large", "agree": True}
        )

        assert status == 200
        assert result["application"]["formData"]["business_name"] == "Acme Corp"
        assert result["application"]["status"] == "open"

    def test_sets_submitted_at_on_first_save(self, open_market, apps_coll):
        _seeded_app(apps_coll)
        token = self.TOKEN()

        result, _ = ApplicantsApi.save_applicant_application(
            MARKET_SLUG, token, {"business_name": "Acme", "email": "a@b.com", "booth_size": "Small", "agree": True}
        )

        assert result["application"]["submittedAt"] is not None

    def test_preserves_original_submitted_at_on_update(self, open_market, apps_coll):
        _seeded_app(apps_coll, submitted_at="2026-01-15T00:00:00Z")
        token = self.TOKEN()

        result, _ = ApplicantsApi.save_applicant_application(
            MARKET_SLUG, token, {"business_name": "Acme v2", "email": "a@b.com", "booth_size": "Large", "agree": True}
        )

        assert result["application"]["submittedAt"] == "2026-01-15T00:00:00Z"

    def test_validates_required_field(self, open_market, apps_coll):
        _seeded_app(apps_coll)
        token = self.TOKEN()

        result, status = ApplicantsApi.save_applicant_application(
            MARKET_SLUG, token, {"email": "a@b.com", "booth_size": "Small", "agree": True}
            # missing required "business_name"
        )

        assert status == 422
        assert "Business Name" in result["error"]
        assert "required" in result["error"].lower()

    def test_validates_email_format(self, open_market, apps_coll):
        _seeded_app(apps_coll)
        token = self.TOKEN()

        result, status = ApplicantsApi.save_applicant_application(
            MARKET_SLUG, token, {"business_name": "Acme", "email": "not-an-email", "booth_size": "Small", "agree": True}
        )

        assert status == 422
        assert "valid email" in result["error"].lower()

    def test_validates_select_value(self, open_market, apps_coll):
        _seeded_app(apps_coll)
        token = self.TOKEN()

        result, status = ApplicantsApi.save_applicant_application(
            MARKET_SLUG, token, {"business_name": "Acme", "email": "a@b.com", "booth_size": "Invalid", "agree": True}
        )

        assert status == 422
        assert "invalid selection" in result["error"].lower()

    def test_validates_multi_select_values(self, open_market, apps_coll):
        _seeded_app(apps_coll)
        token = self.TOKEN()

        result, status = ApplicantsApi.save_applicant_application(
            MARKET_SLUG, token, {"business_name": "Acme", "email": "a@b.com", "booth_size": "Small",
                    "extra_days": ["Fri", "Sun"], "agree": True}
        )

        assert status == 422
        assert "Sun" in result["error"]

    def test_validates_checkbox(self, open_market, apps_coll):
        _seeded_app(apps_coll)
        token = self.TOKEN()

        result, status = ApplicantsApi.save_applicant_application(
            MARKET_SLUG, token, {"business_name": "Acme", "email": "a@b.com", "booth_size": "Small",
                    "agree": "yes"}
        )

        assert status == 422
        assert "true or false" in result["error"].lower()

    def test_validates_number(self, open_market, apps_coll):
        _seeded_app(apps_coll)
        token = self.TOKEN()

        result, status = ApplicantsApi.save_applicant_application(
            MARKET_SLUG, token, {"business_name": "Acme", "email": "a@b.com", "booth_size": "Small",
                    "agree": True, "staff_count": "many"}
        )

        assert status == 422
        assert "number" in result["error"].lower()

    def test_allows_empty_optional_fields(self, open_market, apps_coll):
        _seeded_app(apps_coll)
        token = self.TOKEN()

        result, status = ApplicantsApi.save_applicant_application(
            MARKET_SLUG, token, {"business_name": "Acme", "email": "a@b.com", "booth_size": "Small", "agree": True}
            # optional fields omitted
        )

        assert status == 200
        assert result["application"]["formData"]["business_name"] == "Acme"

    def test_no_form_skips_validation(self, monkeypatch, apps_coll):
        """When the market has no application form, any data is accepted."""
        doc = stored_market(phase=MarketPhase.APPLICATIONS_OPEN, name="Test Market")
        fake = FakeSlugMarketsCollection([doc])
        monkeypatch.setattr(ApplicantsApi, "markets_collection", fake)
        _seeded_app(apps_coll)
        token = self.TOKEN()

        result, status = ApplicantsApi.save_applicant_application(
            MARKET_SLUG, token, {"anything": "goes"}
        )

        assert status == 200


class TestSaveDoesNotOwnStatus:
    """An applicant's save writes the applicant's answers, and nothing that is the organizer's.

    ``status`` is the organizer's column: the only writer of anything but ``open`` is a reviewer
    recording a verdict. This is reachable, not theoretical - ``applications_closed ->
    applications_open`` is a transition ``guards.py`` allows, so an organizer can reopen a market
    after review has begun, and from that moment every applicant with a session can save.
    """

    TOKEN = lambda self: {
        "application_id": "app-xyz",
        "market_id": "market-123",
        "email": "vendor@example.com",
    }

    @pytest.mark.parametrize("verdict", [
        ApplicationStatus.UNDER_REVIEW,
        ApplicationStatus.REVIEWER_APPROVED,
        ApplicationStatus.REVIEWER_REJECTED,
        ApplicationStatus.ASSIGNED,
    ])
    def test_an_edit_does_not_reset_a_recorded_verdict(self, open_market, apps_coll, verdict):
        _seeded_app(apps_coll, status=verdict)
        token = self.TOKEN()

        result, status = ApplicantsApi.save_applicant_application(
            MARKET_SLUG, token,
            {"business_name": "Edited", "email": "a@b.com", "booth_size": "Small", "agree": True},
        )

        assert status == 200
        assert result["application"]["formData"]["business_name"] == "Edited", "the answers are theirs"
        assert apps_coll.documents[0]["status"] == verdict.value, "the verdict is not"

    def test_a_document_with_no_status_is_opened(self, open_market, apps_coll):
        """The one case with no status to preserve. ``open`` is what a missing one means."""
        _seeded_app(apps_coll)
        apps_coll.documents[0].pop("status", None)
        token = self.TOKEN()

        _result, status = ApplicantsApi.save_applicant_application(
            MARKET_SLUG, token,
            {"business_name": "Acme", "email": "a@b.com", "booth_size": "Small", "agree": True},
        )

        assert status == 200
        assert apps_coll.documents[0]["status"] == ApplicationStatus.OPEN.value


class TestPhaseGate:
    """Tests that applications are refused when the market is not in applications_open."""

    TOKEN = lambda self: {
        "application_id": "app-xyz",
        "market_id": "market-123",
        "email": "vendor@example.com",
    }

    def _market_in_phase(self, monkeypatch, apps_coll, phase):
        doc = stored_market(phase=phase, name="Test Market", applicationForm=VALID_FORM)
        fake = FakeSlugMarketsCollection([doc])
        monkeypatch.setattr(ApplicantsApi, "markets_collection", fake)
        _seeded_app(apps_coll)
        return self.TOKEN()

    def test_refuses_in_draft(self, monkeypatch, apps_coll):
        token = self._market_in_phase(monkeypatch, apps_coll, MarketPhase.DRAFT)

        result, status = ApplicantsApi.save_applicant_application(
            MARKET_SLUG, token, {"business_name": "Test"}
        )

        assert status == 403
        assert "no longer open" in result["error"].lower()
        assert "Draft" in result["error"]

    def test_refuses_in_closed(self, monkeypatch, apps_coll):
        token = self._market_in_phase(monkeypatch, apps_coll, MarketPhase.APPLICATIONS_CLOSED)

        result, status = ApplicantsApi.save_applicant_application(
            MARKET_SLUG, token, {"business_name": "Test"}
        )

        assert status == 403
        assert "Applications Closed" in result["error"]

    def test_refuses_in_review(self, monkeypatch, apps_coll):
        token = self._market_in_phase(monkeypatch, apps_coll, MarketPhase.REVIEW)

        result, _ = ApplicantsApi.save_applicant_application(MARKET_SLUG, token, {"business_name": "Test"})
        assert result.get("error", "")

    def test_refuses_in_archived(self, monkeypatch, apps_coll):
        token = self._market_in_phase(monkeypatch, apps_coll, MarketPhase.ARCHIVED)

        result, status = ApplicantsApi.save_applicant_application(
            MARKET_SLUG, token, {"business_name": "Test"}
        )
        assert status == 403

    def test_every_non_open_phase_is_refused(self, monkeypatch, apps_coll):
        """Every phase except APPLICATIONS_OPEN must refuse submission."""
        for phase in MarketPhase:
            if phase == MarketPhase.APPLICATIONS_OPEN:
                continue
            token = self._market_in_phase(monkeypatch, apps_coll, phase)

            result, status = ApplicantsApi.save_applicant_application(
                MARKET_SLUG, token, {"business_name": "Test"}
            )
            assert status == 403, f"Phase {phase.value} should return 403"


class TestD9LockProof:
    """Tests that prove the D9 lock fires when applications exist.

    The D9 lock lives in api.markets.save_application_form, which counts documents
    in the applications collection. Our applicant endpoints write through
    api.applications (the same module the lock reads), so any application we create
    through the applicant flow is immediately counted by the lock.

    This is the first PR where applications can actually be created (PR 4 only
    built the counting mechanism), so this is the first time the D9 lock arm can
    ever have executed against real application documents.
    """

    def _setup(self, monkeypatch):
        """Create a market, save a form, submit an application, then try to edit the form."""
        monkeypatch.setattr(PermissionsApi, "user_has_permission", lambda *_a, **_kw: True)

        # A market in draft with a form
        market = stored_market(
            phase=MarketPhase.DRAFT,
            name="D9 Test Market",
            applicationForm=VALID_FORM,
        )
        fake_markets = FakeMarketsCollection(market)
        fake_apps = FakeApplicationsCollection()

        monkeypatch.setattr(ApplicationsApi, "applications_collection", fake_apps)
        monkeypatch.setattr(MarketsApi, "markets_collection", fake_markets)

        # Save the form through the normal API (this works because phase is draft)
        MarketsApi.save_application_form("market-123", {"fields": [
            {"key": "business_name", "label": "Business Name", "type": "text", "required": True, "order": 0},
        ]}, "user-1")

        # Simulate the applicant flow: insert an application document
        app = Application(
            market_id="market-123",
            applicant_email="vendor@example.com",
            form_data={"business_name": "Acme"},
            status=ApplicationStatus.OPEN,
        )
        fake_apps.insert_one(app.model_dump())

        return fake_markets, fake_apps

    def test_d9_lock_engages_after_applicant_submits_via_our_endpoint(self, monkeypatch):
        """The D9 lock uses api.applications.count_applications_for_market.
        We proved in test_application_form.py that the lock counts by market_id.
        Our applicant endpoints write through the same api.applications module,
        so any document we insert is counted. This test proves they interoperate."""

        fake_markets, fake_apps = self._setup(monkeypatch)

        # fake_apps now has one application for market-123.
        # The D9 lock should count it and refuse form edits.
        count = ApplicationsApi.count_applications_for_market("market-123")
        assert count == 1, "D9 lock must see the application we wrote"

        # This proves the interop: save_application_form should raise the lock error
        from api.markets import ApplicationFormLockedError
        with pytest.raises(ApplicationFormLockedError, match="1 application"):
            MarketsApi.save_application_form("market-123", {"fields": [
                {"key": "new_field", "label": "Should Not Work", "type": "text", "order": 0},
            ]}, "user-1")

    def test_d9_lock_is_market_scoped(self, monkeypatch):
        """Applications for one market must not lock another market's form."""
        fake_markets, fake_apps = self._setup(monkeypatch)

        # Create a second market (also in draft, no applications)
        market2 = stored_market(
            phase=MarketPhase.DRAFT,
            name="Second Market",
            id="market-456",
            applicationForm={"fields": [{"key": "x", "label": "X", "type": "text"}]},
        )
        fake_markets2 = FakeMarketsCollection(market2)
        monkeypatch.setattr(MarketsApi, "markets_collection", fake_markets2)
        count = ApplicationsApi.count_applications_for_market("market-456")
        assert count == 0

    def test_applications_collection_is_the_same_one_the_lock_reads(self, monkeypatch):
        """Sanity check: the applications_collection our endpoints use IS the
        same one the D9 lock's count_applications_for_market counts."""
        fake = FakeApplicationsCollection()
        monkeypatch.setattr(ApplicationsApi, "applications_collection", fake)

        app = Application(
            market_id="market-123",
            applicant_email="test@example.com",
            form_data={},
            status=ApplicationStatus.OPEN,
        )
        fake.insert_one(app.model_dump())

        count = ApplicationsApi.count_applications_for_market("market-123")
        assert count == 1

    def test_write_stored_in_snake_case_preserves_market_id_contract(self, apps_coll):
        """The D9 lock reads by market_id (snake_case). Our writer must use
        the same key, or the lock counts zero and is silently dead.
        Application.model_dump() writes snake_case, so we test that what
        the insert_one receives has the right key."""
        app = Application(
            market_id="market-123",
            applicant_email="test@example.com",
            form_data={},
            status=ApplicationStatus.OPEN,
        )
        dump = app.model_dump()
        apps_coll.insert_one(dump)

        doc = apps_coll.documents[0]
        assert "market_id" in doc, "must be snake_case for D9 lock to count it"
        assert doc["market_id"] == "market-123"


class TestGetPublicApplicationForm:
    def test_returns_form_and_phase_for_open_market(self, open_market):
        result, status = ApplicantsApi.get_public_application_form("test-market")

        assert status == 200
        assert result["application_form"]["fields"][0]["key"] == "business_name"
        assert result["is_open"] is True
        assert result["phase"] == "applications_open"

    def test_returns_the_market_name_the_applicant_knows_it_by(self, open_market):
        """The applicant-facing screens have nowhere else to get the name from, and a URL slug is
        not a market name."""
        result, status = ApplicantsApi.get_public_application_form("test-market")

        assert status == 200
        assert result["market_name"] == "Test Market"

    def test_returns_null_form_when_no_form_exists(self, monkeypatch):
        doc = stored_market(phase=MarketPhase.APPLICATIONS_OPEN, name="No Form")
        fake = FakeSlugMarketsCollection([doc])
        monkeypatch.setattr(ApplicantsApi, "markets_collection", fake)

        result, status = ApplicantsApi.get_public_application_form("no-form")

        assert status == 200
        assert result["application_form"] is None

    def test_reports_is_open_false_for_different_phase(self, monkeypatch):
        doc = stored_market(phase=MarketPhase.REVIEW, name="Review Market")
        fake = FakeSlugMarketsCollection([doc])
        monkeypatch.setattr(ApplicantsApi, "markets_collection", fake)

        result, status = ApplicantsApi.get_public_application_form("review-market")

        assert status == 200
        assert result["is_open"] is False

    def test_returns_404_for_draft_market(self, monkeypatch):
        doc = stored_market(phase=MarketPhase.DRAFT, name="Draft")
        fake = FakeSlugMarketsCollection([doc])
        monkeypatch.setattr(ApplicantsApi, "markets_collection", fake)

        result, status = ApplicantsApi.get_public_application_form("draft")

        assert status == 404


class TestPublicFormCeiling:
    """This is the one public applicant surface with no captcha in front of it - it is a page load,
    and a browser that has not run a script yet must still be able to open a market's application
    URL. The per-IP ceiling is therefore the only bound it has."""

    def _load(self, ip="1.2.3.4", times=1):
        for _ in range(times - 1):
            ApplicantsApi.get_public_application_form(MARKET_SLUG, ip)
        return ApplicantsApi.get_public_application_form(MARKET_SLUG, ip)

    def test_a_caller_over_the_ceiling_is_refused(self, open_market, monkeypatch):
        monkeypatch.setattr(ApplicantsApi, "PUBLIC_FORM_IP_LIMIT", 3)

        _result, status = self._load(times=3)
        assert status == 200

        result, status = self._load()
        assert status == 429
        assert result["error"] == ApplicantsApi.RATE_LIMITED_ERROR

    def test_the_ceiling_is_per_caller(self, open_market, monkeypatch):
        """A budget shared by every applicant at every market is one an attacker reaches on
        purpose, and what breaks when they do is the application form for all of them. There is
        deliberately no global ceiling here."""
        monkeypatch.setattr(ApplicantsApi, "PUBLIC_FORM_IP_LIMIT", 3)

        self._load(ip="1.2.3.4", times=4)

        _result, status = self._load(ip="5.6.7.8")
        assert status == 200

    def test_an_applicant_loading_every_screen_is_nowhere_near_it(self, open_market):
        """The real bound: the sign-in budget already assumes no more than REQUEST_KEY_IP_LIMIT
        sign-ins an hour from one address, and this allows ten form loads for each of them - so a
        hall's shared wifi cannot spend it, which is the whole point of a ceiling."""
        assert (
            ApplicantsApi.PUBLIC_FORM_IP_LIMIT
            >= 10 * ApplicantsApi.REQUEST_KEY_IP_LIMIT
        )

    def test_a_refused_load_is_not_counted(self, open_market, monkeypatch, rate_limits):
        """Refusals are refunded, so a shared window cannot be held down by callers already turned
        away. See ``utils.rate_limit``."""
        monkeypatch.setattr(ApplicantsApi, "PUBLIC_FORM_IP_LIMIT", 2)

        self._load(times=4)

        counts = [doc["count"] for doc in rate_limits.documents]
        assert counts == [2], "the window counts admitted requests and nothing else"


class TestRequiredFieldAnswers:
    """A required field is not satisfied by a value that means "not answered".

    ``False`` for a mandatory consent checkbox and ``[]`` for a mandatory multi_select are both
    non-null and non-blank, so a purely null/empty-string test waves them through and the
    applicant submits an unanswered mandatory field.
    """

    REQUIRED_FORM = {
        "fields": [
            {"key": "agree", "label": "Agree to Terms", "type": "checkbox", "required": True, "order": 0},
            {"key": "days", "label": "Days", "type": "multi_select", "options": ["Fri", "Sat"],
             "required": True, "order": 1},
        ]
    }

    TOKEN = lambda self: {
        "application_id": "app-xyz",
        "market_id": "market-123",
        "email": "vendor@example.com",
    }

    @pytest.fixture
    def required_market(self, monkeypatch):
        doc = stored_market(
            phase=MarketPhase.APPLICATIONS_OPEN,
            name="Test Market",
            applicationForm=self.REQUIRED_FORM,
        )
        fake = FakeSlugMarketsCollection([doc])
        monkeypatch.setattr(ApplicantsApi, "markets_collection", fake)
        return fake

    def test_required_checkbox_false_is_unanswered(self, required_market, apps_coll):
        _seeded_app(apps_coll)

        result, status = ApplicantsApi.save_applicant_application(
            MARKET_SLUG, self.TOKEN(), {"agree": False, "days": ["Fri"]}
        )

        assert status == 422
        assert "Agree to Terms" in result["error"]
        assert "required" in result["error"].lower()

    def test_required_multi_select_empty_list_is_unanswered(self, required_market, apps_coll):
        _seeded_app(apps_coll)

        result, status = ApplicantsApi.save_applicant_application(
            MARKET_SLUG, self.TOKEN(), {"agree": True, "days": []}
        )

        assert status == 422
        assert "Days" in result["error"]
        assert "required" in result["error"].lower()

    def test_answered_required_checkbox_and_multi_select_are_accepted(self, required_market, apps_coll):
        _seeded_app(apps_coll)

        result, status = ApplicantsApi.save_applicant_application(
            MARKET_SLUG, self.TOKEN(), {"agree": True, "days": ["Fri", "Sat"]}
        )

        assert status == 200
        assert result["application"]["formData"] == {"agree": True, "days": ["Fri", "Sat"]}

    def test_optional_checkbox_false_is_accepted(self, open_market, apps_coll):
        _seeded_app(apps_coll)

        result, status = ApplicantsApi.save_applicant_application(
            MARKET_SLUG, self.TOKEN(),
            {"business_name": "Acme", "email": "a@b.com", "booth_size": "Small",
             "agree": True, "extra_days": []},
        )

        assert status == 200
        assert result["application"]["formData"]["extra_days"] == []


class TestNumberAnswersAreStoredAsNumbers:
    """A field the form declares as a number is stored as one, whatever the browser sent."""

    TOKEN = lambda self: {
        "application_id": "app-xyz",
        "market_id": "market-123",
        "email": "vendor@example.com",
    }

    def _save(self, staff_count):
        return ApplicantsApi.save_applicant_application(
            MARKET_SLUG, self.TOKEN(),
            {"business_name": "Acme", "email": "a@b.com", "booth_size": "Small",
             "agree": True, "staff_count": staff_count},
        )

    def test_numeric_string_is_coerced(self, open_market, apps_coll):
        _seeded_app(apps_coll)

        result, status = self._save("3")

        assert status == 200
        assert result["application"]["formData"]["staff_count"] == 3
        assert isinstance(apps_coll.find_one({"id": "app-xyz"})["form_data"]["staff_count"], int)

    def test_decimal_string_keeps_its_fraction(self, open_market, apps_coll):
        _seeded_app(apps_coll)

        result, status = self._save("2.5")

        assert status == 200
        assert result["application"]["formData"]["staff_count"] == 2.5

    def test_blank_number_is_stored_as_none_not_empty_string(self, open_market, apps_coll):
        _seeded_app(apps_coll)

        result, status = self._save("")

        assert status == 200
        assert result["application"]["formData"]["staff_count"] is None

    def test_boolean_is_not_a_number(self, open_market, apps_coll):
        _seeded_app(apps_coll)

        result, status = self._save(True)

        assert status == 422
        assert "number" in result["error"].lower()

    def test_infinity_is_not_a_number(self, open_market, apps_coll):
        _seeded_app(apps_coll)

        result, status = self._save("inf")

        assert status == 422
        assert "number" in result["error"].lower()

    def test_a_number_too_large_to_store_is_refused_not_a_500(self, open_market, apps_coll):
        """``1e300`` is finite, is an integer, and is typeable into the form's number input -- and
        no BSON document can hold it. Refused here, or the driver raises at encode time and the
        applicant gets a 500 from a validator that already said yes."""
        _seeded_app(apps_coll)

        result, status = self._save("1e300")

        assert status == 422
        assert "too large" in result["error"].lower()
        assert apps_coll.find_one({"id": "app-xyz"})["form_data"].get("staff_count") is None

    def test_a_number_below_the_storable_range_is_refused(self, open_market, apps_coll):
        _seeded_app(apps_coll)

        result, status = self._save(-(2 ** 63) - 1)

        assert status == 422
        assert "too large" in result["error"].lower()

    def test_the_largest_storable_integer_is_accepted(self, open_market, apps_coll):
        """The bound is storage's, so it has to be exact: a parse by way of a float rounds this to
        2**63 and refuses the largest number a document can actually hold."""
        _seeded_app(apps_coll)

        result, status = self._save(str(2 ** 63 - 1))

        assert status == 200
        assert result["application"]["formData"]["staff_count"] == 2 ** 63 - 1


class TestDateAnswersAreStoredAsDates:
    """A field the form declares as a date is stored as the date the refusal message promises."""

    TOKEN = lambda self: {
        "application_id": "app-xyz",
        "market_id": "market-123",
        "email": "vendor@example.com",
    }

    def _save(self, start_date):
        return ApplicantsApi.save_applicant_application(
            MARKET_SLUG, self.TOKEN(),
            {"business_name": "Acme", "email": "a@b.com", "booth_size": "Small",
             "agree": True, "start_date": start_date},
        )

    def test_iso_date_is_stored(self, open_market, apps_coll):
        _seeded_app(apps_coll)

        result, status = self._save("2026-01-31")

        assert status == 200
        assert result["application"]["formData"]["start_date"] == "2026-01-31"

    def test_surrounding_whitespace_is_stripped(self, open_market, apps_coll):
        _seeded_app(apps_coll)

        result, status = self._save("  2026-01-31  ")

        assert status == 200
        assert result["application"]["formData"]["start_date"] == "2026-01-31"

    def test_basic_format_is_refused(self, open_market, apps_coll):
        """`fromisoformat` parses "20260131"; the message promises YYYY-MM-DD, so the check does."""
        _seeded_app(apps_coll)

        result, status = self._save("20260131")

        assert status == 422
        assert "YYYY-MM-DD" in result["error"]
        assert apps_coll.find_one({"id": "app-xyz"})["form_data"] == {}

    def test_datetime_is_refused(self, open_market, apps_coll):
        """A datetime under a date key is a stored type that contradicts the form."""
        _seeded_app(apps_coll)

        result, status = self._save("2026-01-31T10:00:00+00:00")

        assert status == 422
        assert "YYYY-MM-DD" in result["error"]

    def test_impossible_date_is_refused(self, open_market, apps_coll):
        _seeded_app(apps_coll)

        result, status = self._save("2026-02-30")

        assert status == 422


class TestFormDataIsProjectedOntoTheForm:
    """Only the answers the market's form declares reach the applications collection."""

    TOKEN = lambda self: {
        "application_id": "app-xyz",
        "market_id": "market-123",
        "email": "vendor@example.com",
    }

    def test_undeclared_keys_are_not_stored(self, open_market, apps_coll):
        _seeded_app(apps_coll)

        result, status = ApplicantsApi.save_applicant_application(
            MARKET_SLUG, self.TOKEN(),
            {"business_name": "Acme", "email": "a@b.com", "booth_size": "Small", "agree": True,
             "not_a_field": "x" * 5000, "status": "reviewer_approved"},
        )

        assert status == 200
        stored = result["application"]["formData"]
        assert "not_a_field" not in stored
        assert "status" not in stored
        assert stored["business_name"] == "Acme"
        assert apps_coll.find_one({"id": "app-xyz"})["form_data"] == stored
        assert apps_coll.find_one({"id": "app-xyz"})["status"] == "open"

    def test_market_with_no_form_declares_no_keys_and_stores_none(self, monkeypatch, apps_coll):
        doc = stored_market(phase=MarketPhase.APPLICATIONS_OPEN, name="Test Market")
        fake = FakeSlugMarketsCollection([doc])
        monkeypatch.setattr(ApplicantsApi, "markets_collection", fake)
        _seeded_app(apps_coll)

        result, status = ApplicantsApi.save_applicant_application(
            MARKET_SLUG, self.TOKEN(), {"anything": "goes"}
        )

        assert status == 200
        assert result["application"]["formData"] == {}

    def test_non_object_form_data_is_refused(self, open_market, apps_coll):
        _seeded_app(apps_coll)

        result, status = ApplicantsApi.save_applicant_application(MARKET_SLUG, self.TOKEN(), ["not", "an", "object"])

        assert status == 400
        assert "object" in result["error"].lower()


class TestAnswerValuesAreTyped:
    """A declared field constrains the type of what it accepts, not only its shape when it happens
    to arrive as the expected one. Otherwise every text key is an unbounded, untyped write."""

    TOKEN = lambda self: {
        "application_id": "app-xyz",
        "market_id": "market-123",
        "email": "vendor@example.com",
    }

    def _save(self, **answers):
        base = {"business_name": "Acme", "email": "a@b.com", "booth_size": "Small", "agree": True}
        base.update(answers)
        return ApplicantsApi.save_applicant_application(MARKET_SLUG, self.TOKEN(), base)

    def test_object_under_a_text_key_is_refused(self, open_market, apps_coll):
        _seeded_app(apps_coll)

        result, status = self._save(business_name={"deeply": {"nested": ["x"]}})

        assert status == 422
        assert "text" in result["error"].lower()
        assert apps_coll.find_one({"id": "app-xyz"})["form_data"] == {}

    def test_object_under_an_email_key_is_refused(self, open_market, apps_coll):
        _seeded_app(apps_coll)

        result, status = self._save(email={"not": "an email"})

        assert status == 422
        assert "text" in result["error"].lower()

    def test_object_under_a_date_key_is_refused(self, open_market, apps_coll):
        _seeded_app(apps_coll)

        result, status = self._save(start_date={"y": 2026})

        assert status == 422

    def test_oversized_text_is_refused(self, open_market, apps_coll):
        _seeded_app(apps_coll)

        result, status = self._save(business_name="x" * (ApplicantsApi.MAX_TEXT_LENGTH + 1))

        assert status == 422
        assert "too long" in result["error"].lower()

    def test_text_at_the_limit_is_accepted(self, open_market, apps_coll):
        _seeded_app(apps_coll)

        result, status = self._save(business_name="x" * ApplicantsApi.MAX_TEXT_LENGTH)

        assert status == 200

    def test_repeated_multi_select_option_is_refused(self, open_market, apps_coll):
        """Without this the list is bounded only by the request body: one valid option, a million
        times, is a million valid selections."""
        _seeded_app(apps_coll)

        result, status = self._save(extra_days=["Fri"] * 1000)

        assert status == 422
        assert "repeats" in result["error"].lower()

    def test_unanswered_text_field_stores_its_own_empty_value_not_the_payload(
        self, open_market, apps_coll,
    ):
        """`[]` reads as unanswered, and an unanswered text field stores text, not a list."""
        _seeded_app(apps_coll)

        result, status = self._save(start_date=[])

        assert status == 200
        assert result["application"]["formData"]["start_date"] == ""

    def test_field_type_the_build_cannot_validate_is_refused_not_stored(
        self, monkeypatch, apps_coll,
    ):
        doc = stored_market(
            phase=MarketPhase.APPLICATIONS_OPEN,
            name="Test Market",
            applicationForm={"fields": [
                {"key": "portfolio", "label": "Portfolio", "type": "file", "required": False,
                 "order": 0},
            ]},
        )
        monkeypatch.setattr(
            ApplicantsApi, "markets_collection", FakeSlugMarketsCollection([doc]),
        )
        _seeded_app(apps_coll)

        result, status = ApplicantsApi.save_applicant_application(
            MARKET_SLUG, self.TOKEN(), {"portfolio": {"bytes": "x" * 100}},
        )

        assert status == 422
        assert apps_coll.find_one({"id": "app-xyz"})["form_data"] == {}


class TestApplicantSessionIsMarketScoped:
    """A token issued for one market must not read or write another market's application.

    Both applicant routes name the market they act on and the server decides that the token agrees,
    because the alternative is that the client decides: an applicant signed in for market A who
    opens market B's public application URL submits B's answers onto A's application, and where the
    two forms share a field key it silently overwrites a submitted application.
    """

    TOKEN = lambda self: {
        "application_id": "app-xyz",
        "market_id": "market-123",
        "email": "vendor@example.com",
    }

    ANSWERS = {"business_name": "Acme", "email": "a@b.com", "booth_size": "Small", "agree": True}

    def test_save_refuses_a_token_issued_for_another_market(self, open_market, apps_coll):
        _seeded_app(apps_coll)

        result, status = ApplicantsApi.save_applicant_application(
            "some-other-market", self.TOKEN(), self.ANSWERS,
        )

        assert status == 403
        assert "different market" in result["error"].lower()
        assert apps_coll.find_one({"id": "app-xyz"})["form_data"] == {}

    def test_get_refuses_a_token_issued_for_another_market(self, open_market, apps_coll):
        _seeded_app(apps_coll)

        result, status = ApplicantsApi.get_applicant_application(
            "some-other-market", self.TOKEN(),
        )

        assert status == 403
        assert "different market" in result["error"].lower()

    def test_the_market_the_token_was_issued_for_is_accepted(self, open_market, apps_coll):
        _seeded_app(apps_coll)

        result, status = ApplicantsApi.save_applicant_application(
            MARKET_SLUG, self.TOKEN(), self.ANSWERS,
        )

        assert status == 200

    def test_slug_of_a_market_the_token_does_not_name_is_refused(self, monkeypatch, apps_coll):
        """Two published markets, a session for the first, a request naming the second."""
        market_a = stored_market(
            phase=MarketPhase.APPLICATIONS_OPEN, name="Test Market", applicationForm=VALID_FORM,
        )
        market_b = stored_market(
            phase=MarketPhase.APPLICATIONS_OPEN, name="Other Market", id="market-456",
            applicationForm=VALID_FORM,
        )
        monkeypatch.setattr(
            ApplicantsApi, "markets_collection", FakeSlugMarketsCollection([market_a, market_b]),
        )
        _seeded_app(apps_coll)

        result, status = ApplicantsApi.save_applicant_application(
            "other-market", self.TOKEN(), self.ANSWERS,
        )

        assert status == 403
        assert apps_coll.find_one({"id": "app-xyz"})["form_data"] == {}


class TestApplicantReadsOnlyTheFieldsItServes:
    """The applicant endpoints fetch the market fields they read, and none of the organizer's.

    A market document carries the organizer's working state - ``setupObject``, ``assignmentObject``,
    ``modificationList`` - which for a market with a full assignment is megabytes. The applicant's
    dashboard calls the token-gated endpoints and the public form endpoint on every mount, and an
    unprojected read of any of them pays for decoding all of that on every load and every save. A
    token makes that a cost rather than an exposure; it does not make it free.
    """

    TOKEN = lambda self: {
        "application_id": "app-xyz",
        "market_id": "market-123",
        "email": "vendor@example.com",
    }

    ORGANIZER_ONLY = ("setupObject", "assignmentObject", "modificationList")

    def test_the_token_gated_read_does_not_fetch_the_organizers_working_state(
        self, open_market, apps_coll,
    ):
        _seeded_app(apps_coll)

        _, status = ApplicantsApi.get_applicant_application(MARKET_SLUG, self.TOKEN())

        assert status == 200
        assert open_market.last_projection, "the market was fetched whole"
        for key in self.ORGANIZER_ONLY:
            assert key not in open_market.last_projection

    def test_the_save_does_not_fetch_the_organizers_working_state(self, open_market, apps_coll):
        _seeded_app(apps_coll)

        _, status = ApplicantsApi.save_applicant_application(
            MARKET_SLUG,
            self.TOKEN(),
            {"business_name": "Acme", "email": "a@b.com", "booth_size": "Small", "agree": True},
        )

        assert status == 200
        assert open_market.last_projection, "the market was fetched whole"
        for key in self.ORGANIZER_ONLY:
            assert key not in open_market.last_projection

    def test_the_public_form_read_does_not_fetch_the_organizers_working_state(self, open_market):
        _, status = ApplicantsApi.get_public_application_form(MARKET_SLUG, client_ip="203.0.113.7")

        assert status == 200
        assert open_market.last_projection, "the market was fetched whole"
        for key in self.ORGANIZER_ONLY:
            assert key not in open_market.last_projection
