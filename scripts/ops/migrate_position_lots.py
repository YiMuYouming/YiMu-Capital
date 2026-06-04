#!/usr/bin/env python3
"""Migrate account baseline positions and same-day trades into position lots."""
import argparse
from datetime import datetime, timedelta
import sys
from pathlib import Path

try:
    from scripts import db
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from scripts import db


def _number(value):
    try:
        return float(str(value or 0).replace("股", ""))
    except (TypeError, ValueError):
        return 0.0


def next_trade_date(date_str):
    day = datetime.strptime(date_str, "%Y-%m-%d").date() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day.isoformat()


def _lot_id_for_anchor(date_str, code):
    return f"overnight:{date_str}:{code}"


def _lot_id_for_trade(trade_id):
    return f"trade:{trade_id}"


def _print(out, text):
    if out is not None:
        print(text, file=out)


def get_sellable_qty(code, trade_date):
    rows = db._exec("""
        SELECT COALESCE(SUM(open_qty), 0) AS qty
        FROM position_lots
        WHERE code = ? AND status = 'open' AND open_qty > 0 AND locked_until <= ?
    """, (str(code), str(trade_date)))
    return int(rows[0]["qty"] or 0) if rows else 0


def _query_day_trades(conn, trade_date):
    return [dict(row) for row in conn.execute("""
        SELECT * FROM trade_records
        WHERE trade_date = ?
        ORDER BY trade_date ASC, COALESCE(trade_time, '') ASC, id ASC
    """, (trade_date,)).fetchall()]


def _create_overnight_lots(conn, date_str, anchor, dry_run, out, actions):
    for position in anchor.get("positions") or []:
        code = str(position.get("代码") or "")
        qty = int(_number(position.get("数量")))
        if not code or qty <= 0:
            continue
        name = str(position.get("标的") or position.get("name") or "")
        cost = _number(position.get("成本") or position.get("成本价"))
        lot_id = _lot_id_for_anchor(date_str, code)
        exists = conn.execute("SELECT 1 FROM position_lots WHERE lot_id = ?", (lot_id,)).fetchone()
        if exists:
            continue
        actions.append({"action": "create_overnight_lot", "code": code, "qty": qty})
        _print(out, f"Would create overnight lot for {code} {name} qty={qty} cost={cost:g}")
        if dry_run:
            continue
        conn.execute("""
            INSERT INTO position_lots
            (lot_id, code, name, buy_date, original_qty, open_qty, cost_price,
             locked_until, lot_source, migration_source, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (lot_id, code, name, date_str, qty, qty, cost, date_str,
              "overnight_anchor", f"account_baseline:{date_str}", "open"))


def _create_buy_lot(conn, trade, dry_run, out, actions):
    trade_id = int(trade.get("id") or 0)
    if trade_id <= 0:
        return
    lot_id = _lot_id_for_trade(trade_id)
    exists = conn.execute("SELECT 1 FROM position_lots WHERE lot_id = ?", (lot_id,)).fetchone()
    if exists:
        return
    trade_date = str(trade.get("trade_date"))
    code = str(trade.get("code") or "")
    qty = int(_number(trade.get("qty")))
    price = _number(trade.get("price"))
    name = str(trade.get("name") or "")
    if not code or qty <= 0:
        return
    locked_until = next_trade_date(trade_date)
    actions.append({"action": "create_same_day_lot", "trade_id": trade_id, "code": code, "qty": qty})
    _print(out, f"Would replay buy trade {trade_id}: create locked lot for {code} qty={qty} locked_until={locked_until}")
    if dry_run:
        return
    conn.execute("""
        INSERT INTO position_lots
        (lot_id, code, name, source_trade_id, source_ticket_id, buy_date,
         original_qty, open_qty, cost_price, locked_until, lot_source,
         migration_source, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (lot_id, code, name, trade_id, trade.get("ticket_id"), trade_date,
          qty, qty, price, locked_until, "same_day_trade",
          f"trade_records:{trade_id}", "open"))


def _allocate_sell(conn, trade, dry_run, out, actions):
    trade_id = int(trade.get("id") or 0)
    if trade_id <= 0:
        return
    exists = conn.execute(
        "SELECT 1 FROM trade_lot_allocations WHERE sell_trade_id = ?",
        (trade_id,),
    ).fetchone()
    if exists:
        return
    trade_date = str(trade.get("trade_date"))
    code = str(trade.get("code") or "")
    sell_qty = int(_number(trade.get("qty")))
    sell_price = _number(trade.get("price"))
    if not code or sell_qty <= 0:
        return
    lots = [dict(row) for row in conn.execute("""
        SELECT * FROM position_lots
        WHERE code = ? AND status = 'open' AND open_qty > 0 AND locked_until <= ?
        ORDER BY buy_date ASC, created_at ASC, lot_id ASC
    """, (code, trade_date)).fetchall()]
    sellable = sum(int(row["open_qty"] or 0) for row in lots)
    if sell_qty > sellable:
        raise ValueError(f"sell qty {sell_qty} exceeds sellable lot qty {sellable} for {code}")

    remaining = sell_qty
    for lot in lots:
        if remaining <= 0:
            break
        lot_qty = int(lot["open_qty"] or 0)
        alloc_qty = min(remaining, lot_qty)
        cost_price = _number(lot.get("cost_price"))
        realized = round((sell_price - cost_price) * alloc_qty, 2) if cost_price else None
        actions.append({
            "action": "allocate_sell",
            "sell_trade_id": trade_id,
            "lot_id": lot["lot_id"],
            "qty": alloc_qty,
        })
        _print(out, f"Would replay sell trade {trade_id}: allocate {alloc_qty} from lot {lot['lot_id']}")
        if not dry_run:
            new_open_qty = lot_qty - alloc_qty
            new_status = "closed" if new_open_qty == 0 else "open"
            conn.execute("""
                INSERT INTO trade_lot_allocations
                (sell_trade_id, lot_id, qty, cost_price, sell_price, realized_pnl)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (trade_id, lot["lot_id"], alloc_qty, cost_price, sell_price, realized))
            conn.execute(
                "UPDATE position_lots SET open_qty = ?, status = ? WHERE lot_id = ?",
                (new_open_qty, new_status, lot["lot_id"]),
            )
        remaining -= alloc_qty


def _reconcile(conn, date_str, anchor=None):
    if anchor is None:
        row = conn.execute(
            "SELECT * FROM account_baselines WHERE date = ?",
            (date_str,),
        ).fetchone()
        if row:
            import json
            anchor = dict(row)
            anchor["positions"] = json.loads(anchor.pop("positions_json") or "[]")
    if not anchor:
        return [{"message": f"account baseline missing for {date_str}"}]
    expected = {}
    for position in anchor.get("positions") or []:
        code = str(position.get("代码") or "")
        qty = int(_number(position.get("数量")))
        if code and qty > 0:
            expected[code] = expected.get(code, 0) + qty
    for trade in _query_day_trades(conn, date_str):
        code = str(trade.get("code") or "")
        qty = int(_number(trade.get("qty")))
        action = str(trade.get("action") or "")
        if not code or qty <= 0:
            continue
        if "卖" in action:
            expected[code] = expected.get(code, 0) - qty
        elif "买" in action or "追涨" in action:
            expected[code] = expected.get(code, 0) + qty
    actual_rows = conn.execute("""
        SELECT code, COALESCE(SUM(open_qty), 0) AS qty
        FROM position_lots
        WHERE status = 'open'
        GROUP BY code
    """).fetchall()
    actual = {str(row["code"]): int(row["qty"] or 0) for row in actual_rows}
    errors = []
    for code in sorted(set(expected) | set(actual)):
        if int(expected.get(code, 0)) != int(actual.get(code, 0)):
            errors.append({
                "code": code,
                "expected_qty": int(expected.get(code, 0)),
                "actual_qty": int(actual.get(code, 0)),
                "message": f"lot/account quantity mismatch for {code}: lots={int(actual.get(code, 0))}, account={int(expected.get(code, 0))}",
            })
    return errors


def run_migration(date_str, dry_run=False, apply=False, out=None):
    if not dry_run and not apply:
        dry_run = True
    anchor = db.query_account_baseline(date_str)
    if not anchor:
        raise ValueError(f"account_baselines missing for {date_str}")

    conn = db.get_conn()
    actions = []
    try:
        if apply:
            conn.execute("BEGIN IMMEDIATE")
        _create_overnight_lots(conn, date_str, anchor, dry_run, out, actions)
        _print(out, "Would replay same-day trade_records into lots.")
        for trade in _query_day_trades(conn, date_str):
            action = str(trade.get("action") or "")
            if "卖" in action:
                _allocate_sell(conn, trade, dry_run, out, actions)
            elif "买" in action or "追涨" in action:
                _create_buy_lot(conn, trade, dry_run, out, actions)
        reconciliation_errors = _reconcile(conn, date_str, anchor=anchor)
        if reconciliation_errors:
            _print(out, f"Would report reconciliation differences: {reconciliation_errors}")
        if apply:
            conn.commit()
    except Exception:
        if apply:
            conn.rollback()
        raise
    return {
        "status": "applied" if apply else "dry_run",
        "actions": actions,
        "reconciliation_ok": not reconciliation_errors,
        "reconciliation_errors": reconciliation_errors,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    db.init_db()
    try:
        result = run_migration(args.date, dry_run=args.dry_run, apply=args.apply, out=sys.stdout)
    except ValueError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
