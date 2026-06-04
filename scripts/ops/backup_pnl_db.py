#!/usr/bin/env python3
"""Create a local backup of pnl.db and SQLite sidecar files."""

import argparse
import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DATA_DIR = ROOT / "data"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Backup local pnl.db before ticket migration")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--stamp", default=None, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    dry_run = not args.apply
    data_dir = Path(args.data_dir)
    stamp = args.stamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = data_dir / "backups" / stamp
    files = ["pnl.db", "pnl.db-wal", "pnl.db-shm"]

    print(f"{'[DRY-RUN] ' if dry_run else ''}Backup pnl.db -> {backup_dir}")
    for name in files:
        src = data_dir / name
        if not src.exists():
            print(f"  skip missing {name}")
            continue
        print(f"  copy {src} -> {backup_dir / name}")
        if not dry_run:
            backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, backup_dir / name)

    print("Restore command:")
    print(f"  python3 scripts/ops/rollback_ticket_migration.py --backup {backup_dir} --apply")


if __name__ == "__main__":
    main()
