#!/usr/bin/env python3
"""Create a posthoc trade ticket for an existing orphan trade_record."""

import argparse
import json
import sys
from pathlib import Path

try:
    from scripts import db
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from scripts import db


def _snapshot_meta():
    try:
        from scripts.bridge import _execution_card_metadata
        return _execution_card_metadata()
    except Exception:
        return {}


def _json_loads(value):
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None


def _action_type(action):
    text = str(action or "")
    if "卖" in text:
        return "sell"
    if "买" in text or "追涨" in text:
        return "buy"
    return "observe"


def _leg_type(action_type, action):
    text = str(action or "")
    if action_type == "sell":
        return "sell_reduce"
    if "T" in text.upper():
        return "buy_add"
    if action_type == "buy":
        return "buy_add"
    return "posthoc"


def _ticket_id(trade):
    return f"TICKET-{str(trade['trade_date']).replace('-', '')}-{trade['code']}-POSTHOC-{trade['id']}"


def run(trade_id, apply=False, snapshot_meta=None):
    db.init_db()
    rows = db._exec("SELECT * FROM trade_records WHERE id = ?", (int(trade_id),))
    if not rows:
        raise ValueError(f"trade_record not found: {trade_id}")
    trade = dict(rows[0])
    if trade.get("ticket_id"):
        return {
            "status": "already_linked",
            "trade_id": int(trade_id),
            "ticket_id": trade.get("ticket_id"),
        }

    meta = dict(snapshot_meta or _snapshot_meta() or {})
    if not meta.get("rule_snapshot_hash") or not meta.get("today_execution_card_id"):
        raise ValueError("rule_snapshot_hash and today_execution_card_id are required")

    action_type = _action_type(trade.get("action"))
    leg_type = _leg_type(action_type, trade.get("action"))
    ticket_id = _ticket_id(trade)
    group_id = f"POSTHOC-{str(trade['trade_date']).replace('-', '')}-{trade['code']}-{trade['id']}"
    result = {
        "status": "dry_run",
        "trade_id": int(trade_id),
        "ticket_id": ticket_id,
        "trade_group_id": group_id,
        "leg_type": leg_type,
        "rule_snapshot_hash": meta.get("rule_snapshot_hash"),
    }
    if not apply:
        return result

    created = False
    if not db.query_trade_ticket(ticket_id):
        db.create_trade_ticket({
            "ticket_id": ticket_id,
            "trade_date": trade["trade_date"],
            "code": trade["code"],
            "name": trade.get("name"),
            "action_type": action_type,
            "status": "filled",
            "window": trade.get("window"),
            "intent_text": trade.get("reason") or "posthoc orphan trade backfill",
            "rule_state_json": _json_loads(trade.get("rule_state_json")),
            "market_snapshot_json": _json_loads(trade.get("market_snapshot_json")),
            "max_qty": trade.get("qty"),
            "triggered_rule_ids_json": ["POSTHOC-ORPHAN-TRADE"],
            "blocking_rule_ids_json": ["snapshot_captured_after_trade"],
            "human_override_reason": trade.get("reason"),
            "review_note": "posthoc ticket backfill; not a pre-trade authorization ticket",
            "rule_pack_version": meta.get("rule_pack_version"),
            "rule_snapshot_hash": meta.get("rule_snapshot_hash"),
            "today_execution_card_id": meta.get("today_execution_card_id"),
        })
        created = True
    db.link_trade_to_ticket(int(trade_id), ticket_id, group_id, leg_type)
    db._exec_write("""
        UPDATE position_lots
        SET source_ticket_id = COALESCE(source_ticket_id, ?)
        WHERE source_trade_id = ?
    """, (ticket_id, int(trade_id)))
    result.update({"status": "applied", "created": created})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Backfill one orphan trade_record into a posthoc ticket")
    parser.add_argument("--trade-id", required=True, type=int)
    parser.add_argument("--rule-snapshot-hash")
    parser.add_argument("--today-execution-card-id")
    parser.add_argument("--rule-pack-version")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    snapshot_meta = None
    if args.rule_snapshot_hash or args.today_execution_card_id or args.rule_pack_version:
        snapshot_meta = {
            "rule_snapshot_hash": args.rule_snapshot_hash,
            "today_execution_card_id": args.today_execution_card_id,
            "rule_pack_version": args.rule_pack_version,
        }
    try:
        result = run(args.trade_id, apply=args.apply, snapshot_meta=snapshot_meta)
    except ValueError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
