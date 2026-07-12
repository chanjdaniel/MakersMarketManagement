"""Reads of raw market documents must use the keys the documents are actually stored under.

Every write camel-cases the whole market document, so a read that names ``organization_id``
by hand matches nothing: the organization name never attached to a list entry, and a user
whose only access to a market was org membership saw an empty list, even though the detail
endpoint would happily serve them the same market by id.

camelCase is the one canonical spelling, and ``migrations/migrate_market_keys.py`` rewrites
the documents that predate it -- so nothing here reads or queries a legacy key. A read-time
fallback would not converge: a write only refreshes the camelCase key, so a market moved from
one organization to another keeps its old ``organization_id`` and a filter matching that
spelling would keep listing it for the organization it left.
"""
from types import SimpleNamespace

import pytest

import api.markets as MarketsApi
import api.organizations as OrgsApi
import api.permissions as PermissionsApi
import api.users as UsersApi
from datatypes import MarketRole
from market_documents import (
    LEGACY_MARKET_KEY_QUERY,
    LegacyMarketDocumentsError,
    assert_market_documents_migrated,
    market_doc_field,
    market_doc_filter,
    market_doc_set,
)
from migrate_market_keys import migrate

USER_ID = "user-1"
USER_EMAIL = "member@example.com"
ORG_ID = "org-1"
OTHER_ORG_ID = "org-2"


def _market(market_id, org_key="organizationId", org_id=ORG_ID, roles=None):
    """A stored market owned by an org, keyed the way the given write path spelled it."""
    return {
        "_id": f"mongo-{market_id}",
        "id": market_id,
        "name": f"Market {market_id}",
        "creationDate": "2026-01-01T00:00:00Z",
        "roles": roles if roles is not None else {},
        "modificationList": [],
        "assignmentObject": {"vendorAssignments": [], "assignmentStatistics": None},
        "isDraft": True,
        org_key: org_id,
    }


def _organization(org_id):
    """An organization as ``get_organization`` and ``get_organizations_for_user`` return it."""
    return {"id": org_id, "_id": f"mongo-{org_id}", "name": "Test Org"}


class FakeMarketsCollection:
    """Enough of Mongo to tell a filter that matches from one that quietly does not."""

    def __init__(self, docs):
        self.docs = docs

    def _matches(self, doc, query):
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

    def replace_one(self, query, replacement):
        for index, doc in enumerate(self.docs):
            if self._matches(doc, query):
                self.docs[index] = replacement
                return SimpleNamespace(modified_count=1)
        return SimpleNamespace(modified_count=0)

    def update_many(self, query, update):
        matched = [doc for doc in self.docs if self._matches(doc, query)]
        for doc in matched:
            doc.update(update.get("$set", {}))
            for key in update.get("$unset", {}):
                doc.pop(key, None)
        return SimpleNamespace(matched_count=len(matched))

    def count_documents(self, query):
        assert query == LEGACY_MARKET_KEY_QUERY, "only the legacy-key census is modelled here"
        return sum(
            1 for doc in self.docs
            if any(key != "_id" and "_" in key for key in doc)
        )

    def aggregate(self, _pipeline):
        return iter([])


@pytest.fixture
def collection(monkeypatch):
    fake = FakeMarketsCollection([_market("camel-market")])
    monkeypatch.setattr(MarketsApi, "markets_collection", fake)
    monkeypatch.setattr(
        UsersApi, "get_user", lambda _email: SimpleNamespace(id=USER_ID, email=USER_EMAIL)
    )
    monkeypatch.setattr(
        UsersApi, "get_user_by_id", lambda _uid: SimpleNamespace(id=USER_ID, email=USER_EMAIL)
    )
    monkeypatch.setattr(
        OrgsApi, "get_organizations_for_user", lambda _email: [_organization(ORG_ID)]
    )
    monkeypatch.setattr(
        OrgsApi, "get_organization", lambda oid: _organization(oid) if oid == ORG_ID else None
    )
    monkeypatch.setattr(
        PermissionsApi, "get_user_market_role", lambda *_args, **_kwargs: MarketRole.VIEWER
    )
    return fake


def test_org_membership_alone_lists_the_org_markets(collection):
    listed = {m["id"]: m for m in MarketsApi.get_markets_for_user(USER_EMAIL)}

    assert listed["camel-market"]["user_role"] == MarketRole.VIEWER.value


def test_org_name_attaches_to_the_list_entry(collection):
    listed = {m["id"]: m for m in MarketsApi.get_markets_for_user(USER_EMAIL)}

    assert listed["camel-market"]["organization_name"] == "Test Org"


def test_migrated_legacy_market_is_listed_by_its_org(collection):
    legacy = _market("legacy-market", org_key="organization_id")
    collection.docs.append(legacy)

    migrate(SimpleNamespace(markets=collection))
    listed = {m["id"]: m for m in MarketsApi.get_markets_for_user(USER_EMAIL)}

    assert listed["legacy-market"]["organization_name"] == "Test Org"


def test_market_moved_between_orgs_stops_being_listed_by_the_old_one(collection):
    """The stale key a legacy write left behind must not keep the market visible to org 1."""
    moved = _market("moved-market", org_key="organization_id")
    moved["organizationId"] = OTHER_ORG_ID
    collection.docs.append(moved)

    migrate(SimpleNamespace(markets=collection))
    listed = {m["id"] for m in MarketsApi.get_markets_for_user(USER_EMAIL)}

    assert "moved-market" not in listed


@pytest.fixture
def org_delete(monkeypatch):
    """delete_organization wired to a fake markets collection, with its guards satisfied."""
    fake = FakeMarketsCollection([_market("camel-market")])
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


def test_deleting_an_org_detaches_its_markets(org_delete):
    OrgsApi.delete_organization(ORG_ID, USER_EMAIL)

    market = next(doc for doc in org_delete.docs if doc["id"] == "camel-market")
    assert market_doc_field(market, "organization_id") is None


def test_market_list_reads_each_org_and_member_once(collection, monkeypatch):
    """A list of N markets must not cost N organization reads and N member reads."""
    org_reads, user_reads = [], []
    monkeypatch.setattr(
        OrgsApi, "get_organization",
        lambda oid: org_reads.append(oid) or _organization(oid),
    )
    monkeypatch.setattr(
        UsersApi, "get_user_by_id",
        lambda uid: user_reads.append(uid) or SimpleNamespace(id=uid, email=USER_EMAIL),
    )
    collection.docs = [
        _market(f"market-{i}", roles={USER_ID: MarketRole.OWNER.value}) for i in range(5)
    ]

    listed = MarketsApi.get_markets_for_user(USER_EMAIL)

    assert len(listed) == 5
    assert all(m["organization_name"] == "Test Org" for m in listed)
    assert all(m["role_emails"] == {USER_ID: USER_EMAIL} for m in listed)
    assert org_reads == [], "the org was already fetched to resolve the user's memberships"
    assert user_reads == [USER_ID]


class TestStartupCheck:
    """Unmigrated documents are invisible to every camelCase-only read, so booting on them
    would silently hide markets. The app refuses to serve instead."""

    def test_legacy_document_refuses_to_serve(self, collection):
        collection.docs.append(_market("legacy-market", org_key="organization_id"))

        with pytest.raises(LegacyMarketDocumentsError) as excinfo:
            assert_market_documents_migrated(collection)

        assert excinfo.value.count == 1
        assert "migrations/migrate_market_keys.py" in str(excinfo.value)

    def test_canonical_documents_boot(self, collection):
        assert_market_documents_migrated(collection)

    def test_migration_clears_the_refusal(self, collection):
        collection.docs.append(_market("legacy-market", org_key="organization_id"))

        migrate(SimpleNamespace(markets=collection))

        assert_market_documents_migrated(collection)


def test_deleting_an_org_detaches_a_migrated_legacy_market(org_delete):
    org_delete.docs.append(_market("legacy-market", org_key="organization_id"))
    migrate(SimpleNamespace(markets=org_delete))

    OrgsApi.delete_organization(ORG_ID, USER_EMAIL)

    market = next(doc for doc in org_delete.docs if doc["id"] == "legacy-market")
    assert market_doc_field(market, "organization_id") is None
    assert "organization_id" not in market


def test_market_doc_field_reads_the_persisted_key():
    assert market_doc_field({"organizationId": ORG_ID}, "organization_id") == ORG_ID


def test_market_doc_field_default_when_absent():
    assert market_doc_field({}, "organization_id", "fallback") == "fallback"


def test_market_doc_filter_names_the_persisted_key():
    assert market_doc_filter("organization_id", {"$in": [ORG_ID]}) == {
        "organizationId": {"$in": [ORG_ID]}
    }


def test_market_doc_filter_leaves_single_word_fields_alone():
    assert market_doc_filter("id", "m-1") == {"id": "m-1"}


def test_market_doc_set_writes_the_persisted_key():
    assert market_doc_set("organization_id", None) == {"$set": {"organizationId": None}}


def test_market_doc_set_leaves_single_word_fields_alone():
    assert market_doc_set("name", "x") == {"$set": {"name": "x"}}
