#!/usr/bin/env python3
"""Restore local pnl.db files from a backup directory."""

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DATA_DIR = ROOT / "data"
TICKET_MIGRATION_TABLES = [
    "pending_fill_confirmations",
    "trade_lot_allocations",
    "ticket_conflict_log",
    "position_lots",
    "trade_tickets",
]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Rollback local ticket migration from backup")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", required=True)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    dry_run = not args.apply
    backup_dir = Path(args.backup)
    data_dir = Path(args.data_dir)
    if not (backup_dir / "pnl.db").exists():
        print(f"Backup missing pnl.db: {backup_dir}", file=sys.stderr)
        raise SystemExit(1)

    print(f"{'[DRY-RUN] ' if dry_run else ''}Restore pnl.db from {backup_dir} -> {data_dir}")
    for name in ["pnl.db", "pnl.db-wal", "pnl.db-shm"]:
        src = backup_dir / name
        if not src.exists():
            print(f"  skip missing {name}")
            continue
        dst = data_dir / name
        print(f"  restore {src} -> {dst}")
        if not dry_run:
            data_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    print("  clean ticket migration tables")
    if not dry_run:
        _drop_ticket_migration_tables(data_dir / "pnl.db")


def _drop_ticket_migration_tables(db_path):
    try:
        if db_path.read_bytes()[:16] != b"SQLite format 3\x00":
            print("  skip ticket table cleanup: pnl.db is not a SQLite database")
            return
    except OSError as exc:
        print(f"  skip ticket table cleanup: {exc}")
        return
    conn = sqlite3.connect(db_path)
    try:
        for table in TICKET_MIGRATION_TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
    except sqlite3.DatabaseError as exc:
        print(f"  skip ticket table cleanup: {exc}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
