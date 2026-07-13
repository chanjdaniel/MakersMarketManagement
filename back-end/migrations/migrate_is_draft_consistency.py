#!/usr/bin/env python3
"""One-time migration: bring ``isDraft`` into agreement with ``phase`` on every stored market.

Idempotent -- running it twice is harmless.

After PR 4 (publish-advance-phase), ``isDraft`` is derived strictly from ``phase``:
   phase == "draft"  ->  isDraft: true
   phase != "draft"  ->  isDraft: false

Some documents may disagree -- a market published before this change carries
``phase: "draft"`` and ``isDraft: false``, or a market whose phase was advanced by
the transition endpoint before ``isDraft`` was added to the atomic update.

Only documents that actually store a ``phase`` are touched. A document without one has no
lifecycle state to agree with: ``phase_from_market_document`` derives its phase *from*
``isDraft``, so it is already consistent, and rewriting ``isDraft`` would be rewriting the
phase. ``migrations/migrate_phase.py`` is what backfills those, with the same mapping.

Server-side update operators only (no scan-then-replace). The old app keeps serving
writes while this runs; a whole-document replace would silently revert concurrent edits,
so every fix is a targeted ``$set``.

Usage:
    python migrations/migrate_is_draft_consistency.py
    python migrations/migrate_is_draft_consistency.py --dry-run
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db_config import get_database


def migrate(db, dry_run=False):
    collection = db.markets

    # Every query below is scoped to documents that carry a `phase`. `$ne` alone would also
    # match a document with no `phase` field -- a market written before the field existed --
    # and flipping its `isDraft` would rewrite the only lifecycle state it has:
    # `phase_from_market_document` reads a phase-less document as draft when isDraft is true and
    # archived when it is false, so setting isDraft=false here would silently archive every
    # legacy draft, with no transition out of `archived` to undo it. Those documents are already
    # self-consistent under that mapping and are backfilled by `migrations/migrate_phase.py`.

    # Markets with a phase other than draft and isDraft still true: fix to false.
    draft_pending = list(
        collection.find({"phase": {"$exists": True, "$ne": "draft"}, "isDraft": True})
    )
    # Markets with phase == draft and isDraft still false: fix to true.
    published_pending = list(collection.find({"phase": "draft", "isDraft": False}))
    # Markets with phase set but no isDraft at all: add it.
    missing_pending = list(collection.find({"phase": {"$exists": True}, "isDraft": {"$exists": False}}))

    if dry_run:
        for doc in draft_pending:
            print(
                f"[DRY RUN] market {doc.get('id')}: phase={doc.get('phase')} "
                f"but isDraft=true -> would set isDraft=false"
            )
        for doc in published_pending:
            print(
                f"[DRY RUN] market {doc.get('id')}: phase={doc.get('phase')} "
                f"but isDraft=false -> would set isDraft=true"
            )
        for doc in missing_pending:
            target = doc.get("phase") == "draft"
            print(
                f"[DRY RUN] market {doc.get('id')}: phase={doc.get('phase')} "
                f"but isDraft missing -> would set isDraft={str(target).lower()}"
            )
        total = len(draft_pending) + len(published_pending) + len(missing_pending)
        print(f"\nDRY RUN: would update {total} market(s)")
        return

    updated = 0

    if draft_pending:
        ids = [doc["_id"] for doc in draft_pending]
        result = collection.update_many(
            {"_id": {"$in": ids}}, {"$set": {"isDraft": False}}
        )
        updated += result.modified_count
        print(f"  phase != draft, isDraft=true -> false: {result.modified_count}")

    if published_pending:
        ids = [doc["_id"] for doc in published_pending]
        result = collection.update_many(
            {"_id": {"$in": ids}}, {"$set": {"isDraft": True}}
        )
        updated += result.modified_count
        print(f"  phase == draft, isDraft=false -> true: {result.modified_count}")

    if missing_pending:
        # Split by the target value so we can use a single update_many per group.
        draft_ids = [doc["_id"] for doc in missing_pending if doc.get("phase") == "draft"]
        non_draft_ids = [doc["_id"] for doc in missing_pending if doc.get("phase") != "draft"]

        if draft_ids:
            result = collection.update_many(
                {"_id": {"$in": draft_ids}}, {"$set": {"isDraft": True}}
            )
            updated += result.modified_count
            print(f"  isDraft missing, phase=draft -> true: {result.modified_count}")

        if non_draft_ids:
            result = collection.update_many(
                {"_id": {"$in": non_draft_ids}}, {"$set": {"isDraft": False}}
            )
            updated += result.modified_count
            print(f"  isDraft missing, phase!=draft -> false: {result.modified_count}")

    print(f"Updated {updated} market(s) total")
    if updated == 0:
        print("All markets already consistent -- migration was already applied.")


def main():
    parser = argparse.ArgumentParser(
        description="Bring isDraft into agreement with phase on every stored market"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without applying")
    args = parser.parse_args()

    db = get_database()
    migrate(db, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
