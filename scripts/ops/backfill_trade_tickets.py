#!/usr/bin/env python3
"""Backfill pilot trade tickets for 2026-06-03.

This script is intentionally scoped to the reviewed pilot day. The Markdown
ticket draft is a reference artifact only; SQLite remains the SSOT.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

try:
    from scripts import db
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from scripts import db


ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_REFERENCE = Path("/Users/yimu/Documents/YM_Capital/ai-rule-system/daily-runtime/trade_tickets_2026-06-03.md")

PILOT_DATE = "2026-06-03"
PILOT_TICKETS = [
    {
        "ticket_id": "TICKET-20260603-600726-EXIT",
        "trade_group_id": "TG-20260603-600726-EXIT",
        "trade_ids": [42, 45, 46],
        "code": "600726",
        "name": "华电能源",
        "action_type": "clear",
        "status": "closed_with_conflict",
        "window": "W2",
        "leg_type": "risk_exit",
        "conflict": {
            "conflict_type": "T1_SELLABLE_MISMATCH",
            "severity": "high",
            "expected": {"sellable": 7000},
            "actual": {"sell": 10000},
            "note": "盘前可卖口径 7000 vs 今日卖出 10000，需核验 T+1。",
        },
    },
    {
        "ticket_id": "TICKET-20260603-002281-T",
        "trade_group_id": "TG-20260603-002281-T",
        "trade_ids": [43, 44, 48],
        "code": "002281",
        "name": "光迅科技",
        "action_type": "do_t",
        "status": "filled",
        "window": "W1",
        "leg_type": "do_t",
    },
    {
        "ticket_id": "TICKET-20260603-002475-W2-BUY",
        "trade_group_id": "TG-20260603-002475-W2-BUY",
        "trade_ids": [47],
        "code": "002475",
        "name": "立讯精密",
        "action_type": "buy",
        "status": "filled",
        "window": "W2",
        "leg_type": "buy_add",
    },
]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Backfill 2026-06-03 pilot trade tickets")
    parser.add_argument("--date", required=True)
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--reference", default=str(DEFAULT_REFERENCE))
    return parser.parse_args(argv)


def _trade_ids_text(ids):
    return ",".join(str(i) for i in ids)


def _ensure_pilot_date(date_str):
    if date_str != PILOT_DATE:
        raise SystemExit(f"Only {PILOT_DATE} pilot backfill is supported, got {date_str}")


def _create_ticket(ticket):
    existing = db.query_trade_ticket(ticket["ticket_id"])
    if existing:
        return False
    db.create_trade_ticket({
        "ticket_id": ticket["ticket_id"],
        "trade_date": PILOT_DATE,
        "code": ticket["code"],
        "name": ticket["name"],
        "action_type": ticket["action_type"],
        "status": ticket["status"],
        "window": ticket.get("window"),
        "intent_text": "2026-06-03 pilot backfill",
        "triggered_rule_ids": ["BACKFILL-PILOT-20260603"],
        "review_note": "pilot backfill from reference_only Markdown",
    })
    return True


def _link_trades(ticket):
    for trade_id in ticket["trade_ids"]:
        db.link_trade_to_ticket(
            trade_id,
            ticket["ticket_id"],
            ticket["trade_group_id"],
            ticket["leg_type"],
        )


def _write_conflict(ticket):
    conflict = ticket.get("conflict")
    if not conflict:
        return False
    existing = db._exec("""
        SELECT 1 FROM ticket_conflict_log
        WHERE trade_date = ? AND ticket_id = ? AND conflict_type = ?
        LIMIT 1
    """, (PILOT_DATE, ticket["ticket_id"], conflict["conflict_type"]))
    if existing:
        return False
    db._exec_write("""
        INSERT INTO ticket_conflict_log
        (trade_date, ticket_id, code, conflict_type, severity, expected_json,
         actual_json, resolution_status, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        PILOT_DATE,
        ticket["ticket_id"],
        ticket["code"],
        conflict["conflict_type"],
        conflict.get("severity"),
        json.dumps(conflict.get("expected"), ensure_ascii=False),
        json.dumps(conflict.get("actual"), ensure_ascii=False),
        "open",
        conflict.get("note"),
    ))
    return True


def _archive_reference(reference):
    ref = Path(reference)
    if not ref.exists():
        return None
    archive_dir = ref.parent.parent.parent if "ai-rule-system" in str(ref) else ref.parent
    if "ai-rule-system" in str(ref):
        out_dir = ROOT / "data" / "reference_archive"
    else:
        out_dir = ref.parent / "reference_archive"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "trade_tickets_2026-06-03.reference_only.md"
    content = ref.read_text(encoding="utf-8")
    out.write_text("reference_only: true\n\n" + content, encoding="utf-8")
    return out


def dry_run():
    for ticket in PILOT_TICKETS:
        ids = _trade_ids_text(ticket["trade_ids"])
        label = "trades" if len(ticket["trade_ids"]) > 1 else "trade"
        print(f"Would create ticket {ticket['ticket_id']} from {label} {ids}")
        if ticket.get("conflict"):
            c = ticket["conflict"]
            print(f"Would create conflict ticket {ticket['ticket_id']} with status=closed_with_conflict")
            print("Would write ticket_conflict_log: "
                  f"conflict_type={c['conflict_type']}, expected sellable=7000, actual sell=10000")


def apply(reference):
    db.init_db()
    created = 0
    for ticket in PILOT_TICKETS:
        if _create_ticket(ticket):
            created += 1
        _link_trades(ticket)
        _write_conflict(ticket)
    archived = _archive_reference(reference)
    print(f"Creates {created} trade_tickets.")
    print("Links all 7 trade_records.")
    print("For 600726 T+1 conflict, ticket status=closed_with_conflict, not filled/executable.")
    print("Writes one ticket_conflict_log row.")
    print("Does not change price, qty, action, or created_at of original trades.")
    if archived:
        print(f"Archived reference_only Markdown: {archived}")


def main(argv=None):
    args = parse_args(argv)
    _ensure_pilot_date(args.date)
    if args.apply:
        apply(args.reference)
    else:
        dry_run()


if __name__ == "__main__":
    main()
