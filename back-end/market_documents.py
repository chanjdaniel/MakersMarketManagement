"""The key convention raw market documents are stored under.

Every market write camel-cases the whole document (``convert_keys_to_camel_case`` in
``create_market`` and ``update_market``), so ``organization_id`` is persisted as
``organizationId``; documents last written before that convention still carry the
snake_case spelling. Nothing about a raw Mongo document announces which one it uses, so
naming a key by hand quietly matches nothing - a filter returns no documents and a ``$set``
never fires, with no error either way.

Code that goes through ``convert_keys_to_snake_case`` (``load_market_context``) never has to
think about this. Code that touches a raw document or writes a Mongo filter does, and it uses
these helpers rather than a string literal, so the spelling is decided in exactly one place.
"""
from typing import Any, Dict

from assignment.utils import snake_to_camel


def market_doc_key(field: str) -> str:
    """The key a market field is written under today."""
    return snake_to_camel(field)


def market_doc_field(document: Dict[str, Any], field: str, default: Any = None) -> Any:
    """Read a model field off a raw stored market document, under either spelling."""
    camel_key = market_doc_key(field)
    if camel_key in document:
        return document[camel_key]
    return document.get(field, default)


def market_doc_filter(field: str, condition: Any) -> Dict[str, Any]:
    """Mongo filter matching a market field under either persisted spelling.

    Counterpart to :func:`market_doc_field` for queries, which cannot fall back after the
    fact the way a dict read can.
    """
    camel_key = market_doc_key(field)
    if camel_key == field:
        return {field: condition}
    return {"$or": [{camel_key: condition}, {field: condition}]}


def market_doc_set(field: str, value: Any) -> Dict[str, Any]:
    """Mongo update writing a market field under the persisted spelling.

    A legacy document carrying the snake_case spelling would otherwise keep its stale value
    alongside the new camelCase one, and :func:`market_doc_field` prefers whichever it finds
    first - so the old key is dropped in the same update.
    """
    camel_key = market_doc_key(field)
    update: Dict[str, Any] = {"$set": {camel_key: value}}
    if camel_key != field:
        update["$unset"] = {field: ""}
    return update
