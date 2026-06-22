"""
One-time migration script: load existing JSON catalog files into MongoDB.
Run this once on the VM after MongoDB is set up.

Usage:
    python scripts/migrate_json_to_mongo.py
"""
import json
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db import mongo
from core.settings import get_settings

COMPETENCIES = ["aiml", "dsa", "devops", "cloud", "mcq"]


def main():
    s = get_settings()
    print(f"Migrating catalog data to MongoDB: {s.mongodb_uri}")
    print(f"Database: {s.mongodb_db_name}\n")

    for competency in COMPETENCIES:
        catalog_path = s.catalog_path(competency)
        if not catalog_path.exists():
            print(f"[SKIP] No catalog.json for '{competency}'")
            continue

        with open(catalog_path, encoding="utf-8") as f:
            catalog = json.load(f)

        print(f"[{competency.upper()}] Loading {len(catalog)} entries...")
        upserted = mongo.sync_from_json(competency, catalog)
        total = mongo.count(competency)
        print(f"[{competency.upper()}] ✅ Upserted {upserted}, total in DB: {total}\n")

    print("Migration complete.")


if __name__ == "__main__":
    main()
