#!/usr/bin/env python3
"""Controlled repair for one account baseline position missed by a late trade.

Dry-run is the default.  ``--apply`` creates and verifies an SQLite online
backup before updating only the selected ``account_baselines`` row.  Trade and
lot facts are read-only inputs and are never rewritten.
"""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _connect(db_path, read_only=False):
    if read_only:
        return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    return sqlite3.connect(str(db_path))


def _decode_anchor(row):
    if row is None:
        return None
    anchor = dict(row)
    anchor["positions"] = json.loads(anchor.pop("positions_json", "[]") or "[]")
    anchor["_meta"] = json.loads(anchor.pop("_meta_json", "{}") or "{}")
    return anchor


def _query_inputs(conn, date_str, code, late_trade_id):
    conn.row_factory = sqlite3.Row
    anchor = _decode_anchor(conn.execute(
        "SELECT * FROM account_baselines WHERE date = ?",
        (date_str,),
    ).fetchone())
    trade_row = conn.execute(
        "SELECT * FROM trade_records WHERE id = ?",
        (late_trade_id,),
    ).fetchone()
    lots = conn.execute(
        """SELECT * FROM position_lots
           WHERE code = ? AND status = 'open'
           ORDER BY buy_date ASC, lot_id ASC""",
        (code,),
    ).fetchall()
    return anchor, (dict(trade_row) if trade_row else None), [dict(row) for row in lots]


def build_plan(db_path, args, conn=None):
    from scripts.account_ssot import build_account_baseline_position_correction

    owns_connection = conn is None
    if owns_connection:
        conn = _connect(db_path, read_only=True)
    try:
        anchor, trade, lots = _query_inputs(
            conn,
            args.date,
            args.code,
            args.late_trade_id,
        )
        result = build_account_baseline_position_correction(
            anchor=anchor,
            late_trade=trade,
            open_lots=lots,
            expected_actual_qty=args.expected_actual_qty,
            source=args.source,
            reason=args.reason,
        )
        result["inputs"] = {
            "date": args.date,
            "code": args.code,
            "late_trade_id": args.late_trade_id,
            "open_lot_qty": sum(int(row.get("open_qty") or 0) for row in lots),
        }
        return result
    finally:
        if owns_connection:
            conn.close()


def _sqlite_backup(src_path, dst_path):
    src = sqlite3.connect(str(src_path))
    dst = sqlite3.connect(str(dst_path))
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()


def _integrity_check(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("PRAGMA integrity_check").fetchall()
        detail = "; ".join(str(row[0]) for row in rows)
        return detail.strip().lower() == "ok", detail
    finally:
        conn.close()


def apply_plan(db_path, args):
    preflight = build_plan(db_path, args)
    if preflight.get("action") != "would_write":
        return preflight

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = db_path.parent / (
        f"{db_path.name}.bak.account-position-{args.code}-{timestamp}"
    )
    _sqlite_backup(db_path, backup)
    ok, detail = _integrity_check(backup)
    if not ok:
        backup.unlink(missing_ok=True)
        return {
            "action": "rejected",
            "error": f"backup integrity_check failed: {detail}",
        }

    conn = _connect(db_path, read_only=False)
    try:
        conn.execute("BEGIN IMMEDIATE")
        result = build_plan(db_path, args, conn=conn)
        if result.get("action") == "already_correct":
            conn.rollback()
            result["backup"] = str(backup)
            result["backup_integrity"] = detail
            return result
        if result.get("action") != "would_write":
            conn.rollback()
            result["backup"] = str(backup)
            result["backup_integrity"] = detail
            return result

        corrected = result["corrected_anchor"]
        cursor = conn.execute(
            """UPDATE account_baselines
               SET cash = ?, day_start_asset = ?, positions_json = ?,
                   source = ?, _meta_json = ?
               WHERE date = ?""",
            (
                corrected["cash"],
                corrected["day_start_asset"],
                json.dumps(corrected["positions"], ensure_ascii=False),
                corrected["source"],
                json.dumps(corrected["_meta"], ensure_ascii=False),
                args.date,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("target account baseline changed or disappeared")
        conn.commit()
        result["action"] = "written"
        result["backup"] = str(backup)
        result["backup_size"] = os.path.getsize(backup)
        result["backup_integrity"] = detail
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _position_summary(anchor, code):
    position = next(
        (row for row in (anchor or {}).get("positions", [])
         if str(row.get("代码") or "") == code),
        {},
    )
    return {
        "code": code,
        "qty": position.get("数量"),
        "cost": position.get("成本"),
        "cash": (anchor or {}).get("cash"),
        "day_start_asset": (anchor or {}).get("day_start_asset"),
        "source": (anchor or {}).get("source"),
    }


def main():
    parser = argparse.ArgumentParser(
        description="受控修复被晚补买入或卖出漏掉的账户持仓基线",
    )
    parser.add_argument("--date", required=True, help="锚点日期 YYYY-MM-DD")
    parser.add_argument("--code", required=True, help="股票代码")
    parser.add_argument("--late-trade-id", required=True, type=int,
                        help="被收盘锚点漏掉的已落库成交记录 ID")
    parser.add_argument("--expected-actual-qty", required=True, type=int,
                        help="券商确认的实际持仓数量")
    parser.add_argument("--source", required=True, help="人工确认来源")
    parser.add_argument("--reason", required=True, help="修复原因")
    parser.add_argument("--db", default=str(ROOT / "data" / "pnl.db"),
                        help="SQLite 账本路径")
    parser.add_argument("--apply", action="store_true",
                        help="显式写入；省略时只做只读预览")
    args = parser.parse_args()
    db_path = Path(args.db).expanduser().resolve()
    if not db_path.exists():
        parser.error(f"数据库不存在: {db_path}")

    result = apply_plan(db_path, args) if args.apply else build_plan(db_path, args)
    public_result = {
        "mode": "apply" if args.apply else "dry-run",
        "action": result.get("action"),
        "error": result.get("error"),
        "inputs": result.get("inputs"),
        "corrected": _position_summary(result.get("corrected_anchor"), args.code),
        "repair_entry": result.get("repair_entry"),
        "backup": result.get("backup"),
        "backup_integrity": result.get("backup_integrity"),
    }
    print(json.dumps(public_result, ensure_ascii=False, indent=2))
    if result.get("action") == "rejected":
        return 1
    if not args.apply and result.get("action") == "would_write":
        print("DRY-RUN 通过；只有追加 --apply 才会写入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
