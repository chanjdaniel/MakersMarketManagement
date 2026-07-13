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

Server-side update operators only (no scan-then-replace). The old app keeps serving writes
while this runs; a whole-document replace would silently revert concurrent edits, so every fix
is a targeted ``$set`` whose filter still names the disagreement it repairs. Matching on
``_id`` alone would not: a market the app transitions between the survey read and the write
would have the value computed for its *old* phase written back onto its new one, recreating the
very disagreement this exists to remove. Each ``update_many`` is handed the same predicate that
selected the group, so Mongo re-checks it per document as it writes.

Usage:
    python migrations/migrate_is_draft_consistency.py
    python migrations/migrate_is_draft_consistency.py --dry-run
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db_config import get_database


# Every query below is scoped to documents that carry a `phase`. `$ne` alone would also match a
# document with no `phase` field -- a market written before the field existed -- and flipping its
# `isDraft` would rewrite the only lifecycle state it has: `phase_from_market_document` reads a
# phase-less document as draft when isDraft is true and archived when it is false, so setting
# isDraft=false here would silently archive every legacy draft, with no transition out of
# `archived` to undo it. Those documents are already self-consistent under that mapping and are
# backfilled by `migrations/migrate_phase.py`.
PHASE_SET = {"$exists": True}
NON_DRAFT_PHASE = {"$exists": True, "$ne": "draft"}

REPAIRS = [
    (
        {"phase": NON_DRAFT_PHASE, "isDraft": True},
        False,
        "phase != draft, isDraft=true -> false",
    ),
    (
        {"phase": "draft", "isDraft": False},
        True,
        "phase == draft, isDraft=false -> true",
    ),
    (
        {"phase": "draft", "isDraft": {"$exists": False}},
        True,
        "isDraft missing, phase=draft -> true",
    ),
    (
        {"phase": NON_DRAFT_PHASE, "isDraft": {"$exists": False}},
        False,
        "isDraft missing, phase!=draft -> false",
    ),
]


def migrate(db, dry_run=False):
    collection = db.markets

    if dry_run:
        total = 0
        for query, target, label in REPAIRS:
            for doc in collection.find(query):
                total += 1
                print(
                    f"[DRY RUN] market {doc.get('id')}: phase={doc.get('phase')} "
                    f"-> would set isDraft={str(target).lower()} ({label})"
                )
        print(f"\nDRY RUN: would update {total} market(s)")
        return

    updated = 0
    for query, target, label in REPAIRS:
        result = collection.update_many(query, {"$set": {"isDraft": target}})
        if result.modified_count:
            print(f"  {label}: {result.modified_count}")
        updated += result.modified_count

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
