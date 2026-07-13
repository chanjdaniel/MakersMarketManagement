"""The isDraft/phase consistency migration may only touch markets that store a phase."""
import copy
from types import SimpleNamespace

from migrate_is_draft_consistency import migrate


def _matches(doc, query):
    """Evaluate a Mongo filter the way the server does.

    `$ne` and `$exists` are modelled exactly. Mongo matches `{"$ne": "draft"}` against a
    document with no such field at all, which is what made the unscoped query dangerous: a
    market written before `phase` existed looked like a market whose phase was not draft.
    """
    for key, condition in (query or {}).items():
        present = key in doc
        if isinstance(condition, dict):
            if "$exists" in condition and present != condition["$exists"]:
                return False
            if "$ne" in condition and doc.get(key) == condition["$ne"]:
                return False
            if "$in" in condition and doc.get(key) not in condition["$in"]:
                return False
        elif not present or doc[key] != condition:
            return False
    return True


class FakeCollection:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query):
        return [copy.deepcopy(doc) for doc in self.docs if _matches(doc, query)]

    def update_many(self, query, update):
        modified = 0
        for doc in self.docs:
            if not _matches(doc, query):
                continue
            for key, value in update["$set"].items():
                if doc.get(key) != value or key not in doc:
                    doc[key] = value
                    modified += 1
        return SimpleNamespace(modified_count=modified)


class FakeDatabase:
    def __init__(self, docs):
        self.markets = FakeCollection(docs)


def only(db):
    return db.markets.docs[0]


def test_legacy_draft_without_phase_is_left_alone():
    """Regression: `{"phase": {"$ne": "draft"}}` also matches a document with no phase.

    A market written before the phase field existed carries only `isDraft: true`. Flipping it
    to false rewrites the only lifecycle state the document has -- `phase_from_market_document`
    would then read the market as `archived`, which has no transition out of it, so every legacy
    draft would be published and unrecoverable.
    """
    db = FakeDatabase([{"_id": 1, "id": "m1", "isDraft": True}])
    migrate(db)
    assert only(db) == {"_id": 1, "id": "m1", "isDraft": True}


def test_legacy_published_without_phase_is_left_alone():
    db = FakeDatabase([{"_id": 1, "id": "m1", "isDraft": False}])
    migrate(db)
    assert only(db) == {"_id": 1, "id": "m1", "isDraft": False}


def test_non_draft_phase_with_stale_is_draft_true_is_corrected():
    db = FakeDatabase([{"_id": 1, "id": "m1", "phase": "archived", "isDraft": True}])
    migrate(db)
    assert only(db)["isDraft"] is False


def test_draft_phase_with_stale_is_draft_false_is_corrected():
    db = FakeDatabase([{"_id": 1, "id": "m1", "phase": "draft", "isDraft": False}])
    migrate(db)
    assert only(db)["isDraft"] is True


def test_missing_is_draft_is_backfilled_from_phase():
    db = FakeDatabase([
        {"_id": 1, "id": "m1", "phase": "draft"},
        {"_id": 2, "id": "m2", "phase": "archived"},
    ])
    migrate(db)
    assert db.markets.docs[0]["isDraft"] is True
    assert db.markets.docs[1]["isDraft"] is False


def test_consistent_markets_are_untouched_and_migration_is_idempotent():
    docs = [
        {"_id": 1, "id": "m1", "phase": "draft", "isDraft": True},
        {"_id": 2, "id": "m2", "phase": "archived", "isDraft": False},
        {"_id": 3, "id": "m3", "phase": "applications_open", "isDraft": True},
    ]
    db = FakeDatabase(docs)
    migrate(db)
    migrate(db)
    assert db.markets.docs[0]["isDraft"] is True
    assert db.markets.docs[1]["isDraft"] is False
    assert db.markets.docs[2]["isDraft"] is False


class RacingCollection(FakeCollection):
    """A collection whose documents are transitioned by the live app mid-migration."""

    def __init__(self, docs, concurrent_write):
        super().__init__(docs)
        self.concurrent_write = concurrent_write

    def update_many(self, query, update):
        if self.concurrent_write is not None:
            self.concurrent_write(self.docs)
            self.concurrent_write = None
        return super().update_many(query, update)


def test_concurrent_phase_change_is_not_overwritten():
    """Every repair filter must still name the disagreement it repairs, not just an _id.

    A market the app publishes while the migration runs must not have the isDraft computed for
    its old phase written back onto its new one -- that would recreate the exact disagreement
    the migration exists to remove, invisibly.
    """
    db = FakeDatabase([{"_id": 1, "id": "m1", "phase": "draft", "isDraft": False}])

    def publish(docs):
        docs[0].update({"phase": "archived", "isDraft": False})

    db.markets = RacingCollection(db.markets.docs, publish)
    migrate(db)

    assert only(db) == {"_id": 1, "id": "m1", "phase": "archived", "isDraft": False}


def test_dry_run_changes_nothing():
    db = FakeDatabase([{"_id": 1, "id": "m1", "phase": "archived", "isDraft": True}])
    migrate(db, dry_run=True)
    assert only(db)["isDraft"] is True
