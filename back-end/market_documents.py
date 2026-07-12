"""The key convention raw market documents are stored under.

Every market write camel-cases the whole document (``convert_keys_to_camel_case`` in
``create_market`` and ``update_market``), so ``organization_id`` is persisted as
``organizationId``. camelCase is the one canonical spelling: documents written before that
convention used snake_case, and ``migrations/migrate_market_keys.py`` rewrites them, so no
stored document carries both spellings and no read has to guess.

Tolerating both spellings at read time does not converge - a write only ever refreshes the
camelCase key, so a legacy snake_case key keeps its value forever and any filter that still
matches it keeps acting on stale data (an organization a market was moved away from would go
on seeing it). The data is normalized once instead, and readers name one key.

Code that goes through ``convert_keys_to_snake_case`` (``load_market_context``) never has to
think about this. Code that touches a raw document or writes a Mongo filter does, and it uses
these helpers rather than a string literal, so the spelling is decided in exactly one place.

Reading one key only means the data has to be normalized first, and nothing auto-runs the
migration: rewriting stored documents is a deliberate operator action. The migration records a
marker document in ``schema_migrations`` when it completes, and the app refuses to boot unless
that marker is there (``assert_market_key_migration_recorded``, called from ``app.py``).
Serving unmigrated data would hide markets from the check-in lookup and from org-scoped lists
with no error anywhere; a loud refusal at startup is the only failure mode that cannot be
deployed by accident. The marker is a single document read by ``_id``, so the check is one
indexed lookup rather than a scan over every market - cheap enough to fail closed on, which is
what it does: an unknown migration state is not a migrated one.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from assignment.utils import convert_keys_to_camel_case, snake_to_camel

MONGO_ID_KEY = "_id"

MARKETS_COLLECTION = "markets"
SCHEMA_COLLECTION = "schema_migrations"
MARKET_KEY_MIGRATION_ID = "market_document_keys"

MARKET_KEY_MIGRATION = "migrations/migrate_market_keys.py"


class MarketKeyMigrationError(RuntimeError):
    """The market-key migration could not be confirmed as applied to this database."""


class MarketKeyMigrationMissingError(MarketKeyMigrationError):
    """The migration has demonstrably not run: its marker is absent."""

    def __init__(self) -> None:
        super().__init__(
            f"The market-key migration has not been applied to this database: no "
            f"'{MARKET_KEY_MIGRATION_ID}' marker in the '{SCHEMA_COLLECTION}' collection. "
            f"Readers name the canonical camelCase key only, so any market still stored under "
            f"legacy snake_case keys is invisible to the public check-in lookup and to "
            f"organization-scoped market lists. Run `python {MARKET_KEY_MIGRATION}` against "
            f"this database, then restart."
        )


class MarketKeyMigrationUnverifiableError(MarketKeyMigrationError):
    """The marker could not be read at all, so the migration state is unknown."""

    def __init__(self, cause: BaseException) -> None:
        super().__init__(
            f"Could not read the '{MARKET_KEY_MIGRATION_ID}' marker from the "
            f"'{SCHEMA_COLLECTION}' collection: {cause!r}. An unknown migration state is not a "
            f"migrated one, so this refuses to serve rather than risk hiding every market "
            f"stored under legacy keys. Make the database reachable, ensure `python "
            f"{MARKET_KEY_MIGRATION}` has been run against it, then restart."
        )
        self.cause = cause


def read_market_key_migration_marker(db: Any) -> Optional[Dict[str, Any]]:
    """The migration's marker document, or None if the migration has not run."""
    return db[SCHEMA_COLLECTION].find_one({MONGO_ID_KEY: MARKET_KEY_MIGRATION_ID})


def assert_market_key_migration_recorded(db: Any) -> None:
    """Refuse to serve a database whose market documents may predate the canonical keys.

    Any failure to read the marker is a failure to confirm the migration, and is fatal for the
    same reason a missing marker is: the alternative is serving markets nobody can see. A
    database that cannot answer a single ``_id`` lookup cannot serve a request either, so
    nothing is lost by refusing.
    """
    try:
        marker = read_market_key_migration_marker(db)
    except Exception as e:
        raise MarketKeyMigrationUnverifiableError(e) from e
    if marker is None:
        raise MarketKeyMigrationMissingError()


def record_market_key_migration(db: Any) -> None:
    """Record that every market document is stored under the canonical keys."""
    db[SCHEMA_COLLECTION].update_one(
        {MONGO_ID_KEY: MARKET_KEY_MIGRATION_ID},
        {"$set": {"appliedAt": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )


def pending_market_key_rewrites(db: Any) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Every stored market that is not already under the canonical keys, with its rewrite."""
    rewrites = (
        (doc, normalize_market_document(doc)) for doc in db[MARKETS_COLLECTION].find({})
    )
    return [(doc, normalized) for doc, normalized in rewrites if normalized != doc]


def apply_market_key_migration(db: Any) -> int:
    """Rewrite every market under the canonical keys and record that it happened.

    Idempotent: a database that is already canonical has nothing to rewrite, and the marker is
    upserted either way, so re-recording it is harmless.
    """
    rewritten = 0
    for doc, normalized in pending_market_key_rewrites(db):
        result = db[MARKETS_COLLECTION].replace_one(
            {MONGO_ID_KEY: doc[MONGO_ID_KEY]}, normalized
        )
        rewritten += result.modified_count
    record_market_key_migration(db)
    return rewritten


def market_doc_key(field: str) -> str:
    """The canonical key a market field is persisted under."""
    return snake_to_camel(field)


def market_doc_field(document: Dict[str, Any], field: str, default: Any = None) -> Any:
    """Read a model field off a raw stored market document."""
    return document.get(market_doc_key(field), default)


def market_doc_filter(field: str, condition: Any) -> Dict[str, Any]:
    """Mongo filter matching a market field under its persisted spelling."""
    return {market_doc_key(field): condition}


def market_doc_set(field: str, value: Any) -> Dict[str, Any]:
    """Mongo update writing a market field under its persisted spelling."""
    return {"$set": {market_doc_key(field): value}}


def normalize_market_document(document: Dict[str, Any]) -> Dict[str, Any]:
    """Rewrite a stored market document under the canonical keys.

    Where a document carries both spellings of a field, the canonical one wins: it is the
    only one any write path has refreshed, so the snake_case value is stale by definition.
    ``_id`` is Mongo's own key and is left exactly as it is.
    """
    normalized: Dict[str, Any] = {}
    for key, value in document.items():
        if key == MONGO_ID_KEY:
            normalized[key] = value
            continue
        canonical_key = market_doc_key(key)
        if canonical_key != key and canonical_key in document:
            continue
        normalized[canonical_key] = convert_keys_to_camel_case(value)
    return normalized
