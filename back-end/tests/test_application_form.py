"""Tests for ApplicationForm CRUD, phase-gating, and D9 locking.

The lock lives in ``api.markets.application_form_lock_reason`` and is reached from both
``save_application_form`` and ``update_market``, so both routes are exercised here.
"""
from types import SimpleNamespace

import pytest

import api.markets as MarketsApi
import api.permissions as PermissionsApi
from datatypes import (
    ApplicationForm, AssignmentObject, FormField, Market, MarketPhase, MarketRole,
)


class FakeMarketsCollection:
    def __init__(self, doc):
        self.doc = doc
        self.last_update = None

    def find_one(self, _query):
        return dict(self.doc) if self.doc is not None else None

    def update_one(self, _filter, update):
        self.last_update = update
        return SimpleNamespace(matched_count=1, modified_count=1, upserted_id=None)


class FakeApplicationsCollection:
    def __init__(self, count=0):
        self.count = count

    def count_documents(self, _query):
        return self.count


class FakeDb(dict):
    """Any collection other than the ones seeded here is a no-op stand-in."""

    def __missing__(self, name):
        return SimpleNamespace(update_one=lambda *_a, **_kw: None)


def _stored_market(**overrides):
    doc = {
        "id": "market-123",
        "name": "Test Market",
        "creationDate": "2026-01-01T00:00:00Z",
        "roles": {"user-1": "owner"},
        "modificationList": [],
        "assignmentObject": {"vendorAssignments": [], "assignmentStatistics": None},
        "isDraft": True,
        "phase": MarketPhase.DRAFT.value,
    }
    doc.update(overrides)
    return doc


def _client_market(**overrides):
    kwargs = {
        "id": "market-123",
        "name": "Test Market",
        "creation_date": "2026-01-01T00:00:00Z",
        "roles": {"user-1": MarketRole.OWNER},
        "modification_list": [],
        "assignment_object": AssignmentObject(),
        "is_draft": True,
    }
    kwargs.update(overrides)
    return Market(**kwargs)


VALID_FORM = {
    "fields": [
        {"key": "business_name", "label": "Business Name", "type": "text", "required": True,
         "help_text": "As it appears on your permit", "order": 0},
        {"key": "size", "label": "Booth Size", "type": "select", "options": ["S", "M"], "order": 1},
    ]
}


@pytest.fixture
def markets(monkeypatch):
    fake = FakeMarketsCollection(_stored_market())
    monkeypatch.setattr(MarketsApi, "markets_collection", fake)
    monkeypatch.setattr(PermissionsApi, "user_has_permission", lambda *_a, **_kw: True)
    return fake


@pytest.fixture
def applications(monkeypatch):
    fake = FakeApplicationsCollection()
    monkeypatch.setattr(MarketsApi, "db", FakeDb({MarketsApi.APPLICATIONS_COLLECTION: fake}))
    return fake


class TestSaveApplicationForm:
    def test_saves_form_to_market_in_camel_case(self, markets, applications):
        MarketsApi.save_application_form("market-123", VALID_FORM, "user-1")

        written = markets.last_update["$set"]["applicationForm"]
        assert written["fields"][0]["key"] == "business_name"
        assert written["fields"][0]["helpText"] == "As it appears on your permit"
        assert "help_text" not in written["fields"][0]
        assert written["publishedAt"] is None

    def test_returns_camel_case_matching_the_front_end_contract(self, markets, applications):
        result = MarketsApi.save_application_form("market-123", VALID_FORM, "user-1")

        assert result["fields"][0]["helpText"] == "As it appears on your permit"
        assert "publishedAt" in result
        assert "help_text" not in result["fields"][0]
        assert "published_at" not in result

    def test_missing_market_raises(self, monkeypatch, applications):
        monkeypatch.setattr(MarketsApi, "markets_collection", FakeMarketsCollection(None))

        with pytest.raises(ValueError, match="Market not found"):
            MarketsApi.save_application_form("nope", VALID_FORM, "user-1")

    def test_requires_editor_permission(self, markets, applications, monkeypatch):
        monkeypatch.setattr(PermissionsApi, "user_has_permission", lambda *_a, **_kw: False)

        with pytest.raises(PermissionError):
            MarketsApi.save_application_form("market-123", VALID_FORM, "user-1")


class TestPhaseGate:
    def test_non_draft_phase_is_refused(self, monkeypatch, applications):
        monkeypatch.setattr(
            MarketsApi, "markets_collection",
            FakeMarketsCollection(_stored_market(phase=MarketPhase.APPLICATIONS_OPEN.value)),
        )
        monkeypatch.setattr(PermissionsApi, "user_has_permission", lambda *_a, **_kw: True)

        with pytest.raises(RuntimeError, match="draft phase"):
            MarketsApi.save_application_form("market-123", VALID_FORM, "user-1")

    def test_every_non_draft_phase_is_refused(self, monkeypatch, applications):
        monkeypatch.setattr(PermissionsApi, "user_has_permission", lambda *_a, **_kw: True)
        for phase in MarketPhase:
            if phase == MarketPhase.DRAFT:
                continue
            monkeypatch.setattr(
                MarketsApi, "markets_collection",
                FakeMarketsCollection(_stored_market(phase=phase.value)),
            )
            with pytest.raises(RuntimeError):
                MarketsApi.save_application_form("market-123", VALID_FORM, "user-1")


class TestD9Lock:
    def test_form_is_frozen_once_an_application_exists(self, markets, applications):
        applications.count = 3

        with pytest.raises(RuntimeError, match="3 application"):
            MarketsApi.save_application_form("market-123", VALID_FORM, "user-1")

        assert markets.last_update is None

    def test_form_is_editable_while_no_application_exists(self, markets, applications):
        applications.count = 0

        MarketsApi.save_application_form("market-123", VALID_FORM, "user-1")

        assert markets.last_update is not None

    def test_market_put_cannot_rewrite_a_locked_form(self, monkeypatch, applications):
        """The lock is an invariant: PUT /markets/{id} enforces the same gate."""
        applications.count = 1
        stored = _stored_market(
            applicationForm={
                "fields": [{"key": "shop_name", "label": "Shop name", "type": "text"}]
            }
        )
        fake = FakeMarketsCollection(stored)
        monkeypatch.setattr(MarketsApi, "markets_collection", fake)
        monkeypatch.setattr(PermissionsApi, "user_has_permission", lambda *_a, **_kw: True)

        rewritten = ApplicationForm(fields=[FormField(key="gotcha", label="Gotcha", type="text")])

        with pytest.raises(RuntimeError, match="locked"):
            MarketsApi.update_market("market-123", _client_market(application_form=rewritten), "user-1")

        assert fake.last_update is None

    def test_market_put_cannot_null_a_locked_form(self, monkeypatch, applications):
        applications.count = 1
        fake = FakeMarketsCollection(
            _stored_market(
                applicationForm={
                    "fields": [{"key": "shop_name", "label": "Shop name", "type": "text"}]
                }
            )
        )
        monkeypatch.setattr(MarketsApi, "markets_collection", fake)
        monkeypatch.setattr(PermissionsApi, "user_has_permission", lambda *_a, **_kw: True)

        with pytest.raises(RuntimeError, match="locked"):
            MarketsApi.update_market("market-123", _client_market(application_form=None), "user-1")

        assert fake.last_update is None

    def test_market_put_of_an_unchanged_locked_form_still_succeeds(self, monkeypatch, applications):
        """A client round-tripping the market it fetched must not trip the lock."""
        applications.count = 1
        stored_form = {"fields": [{"key": "shop_name", "label": "Shop name", "type": "text"}]}
        fake = FakeMarketsCollection(_stored_market(applicationForm=stored_form))
        monkeypatch.setattr(MarketsApi, "markets_collection", fake)
        monkeypatch.setattr(PermissionsApi, "user_has_permission", lambda *_a, **_kw: True)

        unchanged = ApplicationForm(
            fields=[FormField(key="shop_name", label="Shop name", type="text")]
        )
        MarketsApi.update_market("market-123", _client_market(application_form=unchanged), "user-1")

        assert fake.last_update["$set"]["name"] == "Test Market"

    def test_market_put_omitting_the_form_does_not_trip_the_lock(self, monkeypatch, applications):
        applications.count = 1
        fake = FakeMarketsCollection(
            _stored_market(
                applicationForm={
                    "fields": [{"key": "shop_name", "label": "Shop name", "type": "text"}]
                }
            )
        )
        monkeypatch.setattr(MarketsApi, "markets_collection", fake)
        monkeypatch.setattr(PermissionsApi, "user_has_permission", lambda *_a, **_kw: True)

        MarketsApi.update_market("market-123", _client_market(), "user-1")

        assert fake.last_update["$set"]["applicationForm"]["fields"][0]["key"] == "shop_name"


class TestFieldValidation:
    def _save(self, fields):
        return MarketsApi.save_application_form("market-123", {"fields": fields}, "user-1")

    def test_empty_form_is_refused(self, markets, applications):
        with pytest.raises(ValueError, match="at least one field"):
            self._save([])

    def test_unrecognized_type_is_refused(self, markets, applications):
        with pytest.raises(ValueError, match="Unrecognized field type"):
            self._save([{"key": "bad", "label": "Bad", "type": "invalid_type"}])

    @pytest.mark.parametrize("field_type", ["select", "multi_select"])
    def test_select_without_options_is_refused(self, markets, applications, field_type):
        with pytest.raises(ValueError, match="no options defined"):
            self._save([{"key": "size", "label": "Size", "type": field_type}])

    def test_every_supported_type_is_accepted(self, markets, applications):
        fields = [
            {"key": "a", "label": "A", "type": "text"},
            {"key": "b", "label": "B", "type": "number"},
            {"key": "c", "label": "C", "type": "select", "options": ["x"]},
            {"key": "d", "label": "D", "type": "multi_select", "options": ["x"]},
            {"key": "e", "label": "E", "type": "checkbox"},
            {"key": "f", "label": "F", "type": "date"},
            {"key": "g", "label": "G", "type": "email"},
        ]
        self._save(fields)

        assert len(markets.last_update["$set"]["applicationForm"]["fields"]) == 7

    def test_duplicate_keys_are_refused(self, markets, applications):
        """Duplicate keys would collide in Application.form_data and lose an answer."""
        with pytest.raises(ValueError, match="Duplicate field key 'field_2'"):
            self._save([
                {"key": "field_2", "label": "One", "type": "text"},
                {"key": "field_2", "label": "Two", "type": "text"},
            ])

    def test_blank_key_is_refused(self, markets, applications):
        with pytest.raises(ValueError, match="non-empty key"):
            self._save([{"key": "   ", "label": "Nameless", "type": "text"}])

    def test_blank_label_is_refused(self, markets, applications):
        with pytest.raises(ValueError, match="non-empty label"):
            self._save([{"key": "x", "label": "", "type": "text"}])

    def test_market_put_validates_a_form_it_carries(self, markets, applications):
        bad = ApplicationForm(fields=[
            FormField(key="dupe", label="One", type="text"),
            FormField(key="dupe", label="Two", type="text"),
        ])

        with pytest.raises(ValueError, match="Duplicate field key"):
            MarketsApi.update_market("market-123", _client_market(application_form=bad), "user-1")


class TestGetApplicationForm:
    def test_returns_camel_case_form_and_editable_state(self, markets, applications):
        MarketsApi.save_application_form("market-123", VALID_FORM, "user-1")
        markets.doc = _stored_market(applicationForm=markets.last_update["$set"]["applicationForm"])

        result = MarketsApi.get_application_form("market-123", "user-1")

        assert result["application_form"]["fields"][0]["helpText"] == "As it appears on your permit"
        assert result["editable"] is True
        assert result["lock_reason"] is None

    def test_reports_no_form(self, markets, applications):
        result = MarketsApi.get_application_form("market-123", "user-1")

        assert result["application_form"] is None
        assert result["editable"] is True

    def test_reports_the_lock_reason_when_applications_exist(self, markets, applications):
        applications.count = 2

        result = MarketsApi.get_application_form("market-123", "user-1")

        assert result["editable"] is False
        assert "2 application(s)" in result["lock_reason"]

    def test_reports_the_lock_reason_out_of_draft(self, monkeypatch, applications):
        monkeypatch.setattr(
            MarketsApi, "markets_collection",
            FakeMarketsCollection(_stored_market(phase=MarketPhase.ARCHIVED.value)),
        )
        monkeypatch.setattr(PermissionsApi, "user_has_permission", lambda *_a, **_kw: True)

        result = MarketsApi.get_application_form("market-123", "user-1")

        assert result["editable"] is False
        assert "draft phase" in result["lock_reason"]

    def test_requires_viewer_permission(self, markets, applications, monkeypatch):
        monkeypatch.setattr(PermissionsApi, "user_has_permission", lambda *_a, **_kw: False)

        with pytest.raises(PermissionError):
            MarketsApi.get_application_form("market-123", "user-1")
