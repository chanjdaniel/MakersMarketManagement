"""Reads of raw market documents must use the keys the documents are actually stored under.

Every write camel-cases the whole market document, so a read that names ``organization_id``
by hand matches nothing: the organization name never attached to a list entry, and a user
whose only access to a market was org membership saw an empty list, even though the detail
endpoint would happily serve them the same market by id.
"""
from types import SimpleNamespace

import pytest

import api.markets as MarketsApi
import api.organizations as OrgsApi
import api.permissions as PermissionsApi
import api.users as UsersApi
from datatypes import MarketRole
from market_documents import market_doc_field, market_doc_filter, market_doc_set

USER_ID = "user-1"
USER_EMAIL = "member@example.com"
ORG_ID = "org-1"


def _market(market_id, org_key):
    """A stored market owned by an org, keyed the way the given write path spelled it."""
    return {
        "_id": f"mongo-{market_id}",
        "id": market_id,
        "name": f"Market {market_id}",
        "creationDate": "2026-01-01T00:00:00Z",
        "roles": {},
        "modificationList": [],
        "assignmentObject": {"vendorAssignments": [], "assignmentStatistics": None},
        "isDraft": True,
        org_key: ORG_ID,
    }


class FakeMarketsCollection:
    """Enough of Mongo to tell a filter that matches from one that quietly does not."""

    def __init__(self, docs):
        self.docs = docs

    def _matches(self, doc, query):
        if "$or" in query:
            return any(self._matches(doc, clause) for clause in query["$or"])
        for key, condition in query.items():
            if isinstance(condition, dict) and "$in" in condition:
                if doc.get(key) not in condition["$in"]:
                    return False
            elif doc.get(key) != condition:
                return False
        return True

    def find(self, query):
        return iter([dict(doc) for doc in self.docs if self._matches(doc, query)])

    def find_one(self, query):
        return next(self.find(query), None)

    def update_many(self, query, update):
        matched = [doc for doc in self.docs if self._matches(doc, query)]
        for doc in matched:
            doc.update(update.get("$set", {}))
            for key in update.get("$unset", {}):
                doc.pop(key, None)
        return SimpleNamespace(matched_count=len(matched))

    def aggregate(self, _pipeline):
        return iter([])


@pytest.fixture
def collection(monkeypatch):
    docs = [
        _market("camel-market", "organizationId"),
        _market("legacy-market", "organization_id"),
    ]
    fake = FakeMarketsCollection(docs)
    monkeypatch.setattr(MarketsApi, "markets_collection", fake)
    monkeypatch.setattr(
        UsersApi, "get_user", lambda _email: SimpleNamespace(id=USER_ID, email=USER_EMAIL)
    )
    monkeypatch.setattr(
        UsersApi, "get_user_by_id", lambda _uid: SimpleNamespace(id=USER_ID, email=USER_EMAIL)
    )
    monkeypatch.setattr(
        OrgsApi, "get_organizations_for_user", lambda _email: [{"id": ORG_ID}]
    )
    monkeypatch.setattr(
        OrgsApi, "get_organization", lambda oid: {"id": oid, "name": "Test Org"} if oid == ORG_ID else None
    )
    monkeypatch.setattr(
        PermissionsApi, "get_user_market_role", lambda *_args, **_kwargs: MarketRole.VIEWER
    )
    return fake


@pytest.mark.parametrize("market_id", ["camel-market", "legacy-market"])
def test_org_membership_alone_lists_the_org_markets(collection, market_id):
    listed = {m["id"]: m for m in MarketsApi.get_markets_for_user(USER_EMAIL)}

    assert market_id in listed
    assert listed[market_id]["user_role"] == MarketRole.VIEWER.value


@pytest.mark.parametrize("market_id", ["camel-market", "legacy-market"])
def test_org_name_attaches_to_the_list_entry(collection, market_id):
    listed = {m["id"]: m for m in MarketsApi.get_markets_for_user(USER_EMAIL)}

    assert listed[market_id]["organization_name"] == "Test Org"


@pytest.fixture
def org_delete(monkeypatch):
    """delete_organization wired to a fake markets collection, with its guards satisfied."""
    docs = [
        _market("camel-market", "organizationId"),
        _market("legacy-market", "organization_id"),
    ]
    fake = FakeMarketsCollection(docs)
    monkeypatch.setattr(OrgsApi, "markets_collection", fake)
    monkeypatch.setattr(
        OrgsApi.organizations_collection, "find_one", lambda _q: {"id": ORG_ID, "owner": USER_ID},
        raising=False,
    )
    monkeypatch.setattr(
        OrgsApi.organizations_collection, "delete_one", lambda _q: SimpleNamespace(deleted_count=1),
        raising=False,
    )
    monkeypatch.setattr(
        OrgsApi.users_collection, "update_many", lambda *_a, **_k: None, raising=False
    )
    monkeypatch.setattr(
        OrgsApi.UsersApi, "get_user", lambda _email: SimpleNamespace(id=USER_ID, email=USER_EMAIL)
    )
    return fake


@pytest.mark.parametrize("market_id", ["camel-market", "legacy-market"])
def test_deleting_an_org_detaches_its_markets(org_delete, market_id):
    OrgsApi.delete_organization(ORG_ID, USER_EMAIL)

    market = next(doc for doc in org_delete.docs if doc["id"] == market_id)
    assert market_doc_field(market, "organization_id") is None


def test_deleting_an_org_leaves_no_stale_legacy_key(org_delete):
    OrgsApi.delete_organization(ORG_ID, USER_EMAIL)

    legacy = next(doc for doc in org_delete.docs if doc["id"] == "legacy-market")
    assert "organization_id" not in legacy


@pytest.mark.parametrize("stored_key", ["organizationId", "organization_id"])
def test_market_doc_field_reads_either_spelling(stored_key):
    doc = {stored_key: ORG_ID}

    assert market_doc_field(doc, "organization_id") == ORG_ID


def test_market_doc_field_default_when_absent():
    assert market_doc_field({}, "organization_id", "fallback") == "fallback"


def test_market_doc_filter_matches_both_spellings():
    query = market_doc_filter("organization_id", {"$in": [ORG_ID]})
    collection = FakeMarketsCollection(
        [_market("camel-market", "organizationId"), _market("legacy-market", "organization_id")]
    )

    assert {doc["id"] for doc in collection.find(query)} == {"camel-market", "legacy-market"}


def test_market_doc_filter_leaves_single_word_fields_alone():
    assert market_doc_filter("id", "m-1") == {"id": "m-1"}


def test_market_doc_set_writes_the_persisted_key_and_drops_the_legacy_one():
    assert market_doc_set("organization_id", None) == {
        "$set": {"organizationId": None},
        "$unset": {"organization_id": ""},
    }


def test_market_doc_set_leaves_single_word_fields_alone():
    assert market_doc_set("name", "x") == {"$set": {"name": "x"}}
