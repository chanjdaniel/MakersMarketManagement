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
"""
from typing import Any, Dict

from assignment.utils import convert_keys_to_camel_case, snake_to_camel

MONGO_ID_KEY = "_id"


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
