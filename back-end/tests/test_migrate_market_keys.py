"""The key migration must leave every market under exactly one spelling of each field.

A document that carries both spellings keeps a snake_case value no write path ever refreshes,
so whichever reader still matches it acts on stale data. camelCase is the canonical spelling
and the one the last write set, so it wins.
"""
import copy
from types import SimpleNamespace

from migrate_market_keys import migrate


class FakeCollection:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query):
        assert query == {}
        return [copy.deepcopy(doc) for doc in self.docs]

    def replace_one(self, query, replacement):
        for index, doc in enumerate(self.docs):
            if doc["_id"] == query["_id"]:
                modified = doc != replacement
                self.docs[index] = replacement
                return SimpleNamespace(modified_count=1 if modified else 0)
        return SimpleNamespace(modified_count=0)


class FakeDatabase:
    def __init__(self, docs):
        self.markets = FakeCollection(docs)


def only(db):
    return db.markets.docs[0]


def test_legacy_keys_are_rewritten_under_the_canonical_spelling():
    db = FakeDatabase([{"_id": 1, "id": "m1", "organization_id": "org-a", "is_draft": False}])

    migrate(db)

    assert only(db) == {"_id": 1, "id": "m1", "organizationId": "org-a", "isDraft": False}


def test_stale_legacy_key_loses_to_the_canonical_one():
    db = FakeDatabase([
        {"_id": 1, "id": "m1", "organization_id": "org-a", "organizationId": "org-b"},
    ])

    migrate(db)

    assert only(db) == {"_id": 1, "id": "m1", "organizationId": "org-b"}


def test_nested_legacy_keys_are_rewritten_too():
    db = FakeDatabase([
        {"_id": 1, "id": "m1", "setup_object": {"col_names": ["a"], "num_tables": 2}},
    ])

    migrate(db)

    assert only(db) == {"_id": 1, "id": "m1", "setupObject": {"colNames": ["a"], "numTables": 2}}


def test_canonical_market_is_left_alone():
    db = FakeDatabase([{"_id": 1, "id": "m1", "organizationId": "org-a", "isDraft": True}])

    migrate(db)

    assert only(db) == {"_id": 1, "id": "m1", "organizationId": "org-a", "isDraft": True}


def test_migration_is_idempotent():
    db = FakeDatabase([{"_id": 1, "id": "m1", "organization_id": "org-a"}])

    migrate(db)
    migrate(db)

    assert only(db) == {"_id": 1, "id": "m1", "organizationId": "org-a"}


def test_dry_run_writes_nothing():
    db = FakeDatabase([{"_id": 1, "id": "m1", "organization_id": "org-a"}])

    migrate(db, dry_run=True)

    assert only(db) == {"_id": 1, "id": "m1", "organization_id": "org-a"}
