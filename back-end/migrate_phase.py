#!/usr/bin/env python3
"""One-time migration: add ``phase`` field to existing market documents.

Idempotent -- running it twice is harmless.

Mapping:
    is_draft: true  -> phase: "draft"
    is_draft: false -> phase: "archived"  (safe default per D7 read-only archives)

Usage:
    python migrate_phase.py
    python migrate_phase.py --dry-run
"""

import argparse
import sys
from db_config import get_database


def migrate(db, dry_run=False):
    collection = db.markets
    cursor = collection.find({"phase": {"$exists": False}})
    count = 0
    updated = 0

    for doc in cursor:
        count += 1
        is_draft = doc.get("is_draft", True)
        phase = "draft" if is_draft else "archived"

        if dry_run:
            print(f"[DRY RUN] market {doc['id']}: is_draft={is_draft} -> phase={phase}")
        else:
            collection.update_one(
                {"_id": doc["_id"]},
                {"$set": {"phase": phase}},
            )
            updated += 1

    if dry_run:
        print(f"\nDRY RUN: would update {count} market(s)")
    else:
        print(f"Updated {updated} market(s) (scanned {count})")
        if count == 0:
            print("No markets without a phase field found -- migration already applied.")


def main():
    parser = argparse.ArgumentParser(description="Add phase field to existing market documents")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without applying")
    args = parser.parse_args()

    db = get_database()
    migrate(db, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
