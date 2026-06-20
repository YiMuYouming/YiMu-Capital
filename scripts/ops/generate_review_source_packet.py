#!/usr/bin/env python3
"""Generate Wenmi's close-day review source packet.

The packet is an input evidence bundle for WorkBuddy daily-review. It is not
the Vault review note and must not become the next-day dashboard SSOT.
"""

import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_API_BASE = "http://127.0.0.1:8088"
PACKET_SCHEMA = "review_source_packet.v1"
AI_CONTEXT_SCHEMA = "ai_context.v1"


def _iso_now():
    return datetime.now().isoformat(timespec="seconds")


def _copy_keys(source, keys):
    return {key: source.get(key) for key in keys if key in source}


def _freshness_statuses(ai_context):
    freshness = (ai_context or {}).get("freshness") or {}
    result = {}
    for key, value in freshness.items():
        if isinstance(value, dict):
            result[key] = value.get("status") or "unknown"
    return result


def _ai_context_status(ai_context, date_str):
    if not ai_context:
        return "missing"
    if ai_context.get("schema_version") != AI_CONTEXT_SCHEMA:
        return "schema_mismatch"
    if ai_context.get("date") != date_str:
        return "date_mismatch"
    return "ok"


def _is_bad_status(status):
    return str(status or "").lower() in {
        "stale", "dead", "missing", "error", "untrusted", "unknown"
    }


def _ai_context_contract_manual(ai_context, date_str):
    if not ai_context:
        return [{
            "code": "AI_CONTEXT_MISSING",
            "title": "AI context 缺失",
            "reason": "收盘事实包未能读取 /api/ai/context",
        }]
    items = []
    if ai_context.get("schema_version") != AI_CONTEXT_SCHEMA:
        items.append({
            "code": "AI_CONTEXT_SCHEMA_MISMATCH",
            "title": "AI context 版本不匹配",
            "reason": (
                f"expected {AI_CONTEXT_SCHEMA}, got "
                f"{ai_context.get('schema_version') or 'missing'}"
            ),
        })
    if ai_context.get("date") != date_str:
        items.append({
            "code": "AI_CONTEXT_DATE_MISMATCH",
            "title": "AI context 日期不匹配",
            "reason": f"expected {date_str}, got {ai_context.get('date') or 'missing'}",
        })
    return items


def _manual_required(ai_context, freshness, date_str):
    items = []
    items.extend(_ai_context_contract_manual(ai_context, date_str))
    trusted_ai_context = ai_context if _ai_context_status(ai_context, date_str) == "ok" else None
    for item in (trusted_ai_context or {}).get("human_required") or []:
        if isinstance(item, dict):
            items.append(_copy_keys(item, ["code", "title", "reason", "ticket_id"]))
    bad_sources = [name for name, status in freshness.items() if _is_bad_status(status)]
    if bad_sources:
        items.append({
            "code": "DATA_FRESHNESS_REVIEW",
            "title": "复核过期或不可用数据",
            "reason": "bad freshness: " + ", ".join(sorted(bad_sources)),
        })
    items.extend([
        {
            "code": "YIMU_PAN_FEEL_REQUIRED",
            "title": "补充弈沐盘感",
            "reason": "盘感、预期差和关键异动仍需人工确认",
        },
        {
            "code": "OPERATION_REASON_REQUIRED",
            "title": "确认操作原因",
            "reason": "成交事实可由 dashboard 提供，买卖原因仍以弈沐确认为准",
        },
        {
            "code": "TONGHUASHUN_FIELD_REQUIRED",
            "title": "补充同花顺独家字段",
            "reason": "沸点/冰点、连板风险等同花顺字段不由 dashboard packet 自动生成",
        },
    ])
    seen = set()
    deduped = []
    for item in items:
        code = item.get("code") or item.get("title")
        if code in seen:
            continue
        seen.add(code)
        deduped.append(item)
    return deduped


def _account_from_ai_context(ai_context, pnl_summary):
    situation = (ai_context or {}).get("situation") or {}
    pnl = situation.get("pnl") or {}
    position = situation.get("position") or {}
    return {
        "total_asset": pnl.get("total_asset", (pnl_summary or {}).get("total_asset")),
        "pnl_amount": pnl.get("pnl_amount", (pnl_summary or {}).get("pnl_amount")),
        "pnl_pct": pnl.get("pnl_pct", (pnl_summary or {}).get("pnl_pct")),
        "pos_pct": position.get("pos_pct", (pnl_summary or {}).get("pos_pct")),
        "valuation_complete": pnl.get("valuation_complete"),
        "position_count": position.get("position_count"),
        "sellable_count": position.get("sellable_count"),
    }


def _compact_ai_context(ai_context):
    if not ai_context:
        return None
    situation = ai_context.get("situation") or {}
    return {
        "schema_version": ai_context.get("schema_version"),
        "generated_at": ai_context.get("generated_at"),
        "mode": ai_context.get("mode"),
        "trade_entry_allowed": situation.get("trade_entry_allowed"),
        "trade_entry_reason": situation.get("trade_entry_reason"),
        "risks": ai_context.get("risks") or [],
        "alerts": ai_context.get("alerts") or [],
        "human_required": ai_context.get("human_required") or [],
        "freshness": ai_context.get("freshness") or {},
    }


def _review_hints(ai_context, account, trades, tickets):
    hints = []
    if account.get("total_asset") is not None:
        hints.append({
            "code": "ACCOUNT_ASSET",
            "text": f"当前资产 {account.get('total_asset')}，今日盈亏 {account.get('pnl_amount')}",
        })
    if account.get("pos_pct") is not None:
        hints.append({
            "code": "POSITION_PCT",
            "text": f"当前仓位 {account.get('pos_pct')}%",
        })
    if trades:
        hints.append({
            "code": "TRADES_RECORDED",
            "text": f"今日有 {len(trades)} 条成交记录，原因需弈沐确认",
        })
    ticket_total = (tickets or {}).get("total")
    if ticket_total is not None:
        hints.append({
            "code": "TICKET_LOOP",
            "text": f"今日票据总数 {ticket_total}",
        })
    if (ai_context or {}).get("risks"):
        hints.append({
            "code": "AI_CONTEXT_RISKS",
            "text": "存在 AI context 风险项，复盘需保留阻断/复核事实",
        })
    return hints


def build_review_source_packet(
    *,
    date_str,
    ai_context,
    pnl_summary,
    trades,
    tickets,
    now=None,
):
    generated_at = now or _iso_now()
    ai_context_status = _ai_context_status(ai_context, date_str)
    trusted_ai_context = ai_context if ai_context_status == "ok" else None
    freshness = _freshness_statuses(ai_context)
    account = _account_from_ai_context(trusted_ai_context, pnl_summary or {})
    positions = (trusted_ai_context or {}).get("positions") or []
    source_status = {
        "ai_context": ai_context_status,
        "freshness": freshness,
        "trades": "ok" if isinstance(trades, list) else "unknown",
        "tickets": (tickets or {}).get("status", "unknown"),
    }
    return {
        "schema_version": PACKET_SCHEMA,
        "date": date_str,
        "generated_at": generated_at,
        "source_status": source_status,
        "ai_context": _compact_ai_context(ai_context),
        "account": account,
        "positions": positions,
        "trades": trades or [],
        "tickets": tickets or {"status": "unknown"},
        "pnl": pnl_summary or {},
        "review_hints": _review_hints(trusted_ai_context, account, trades or [], tickets or {}),
        "manual_required": _manual_required(ai_context, freshness, date_str),
    }


def write_review_source_packet(packet, data_dir, *, apply=False):
    date_str = packet["date"]
    out_path = Path(data_dir) / "review_packets" / date_str / "review_source_packet.json"
    if not apply:
        return {"path": str(out_path), "written": False}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"path": str(out_path), "written": True}


def fetch_ai_context(api_base=DEFAULT_API_BASE, timeout=8):
    url = api_base.rstrip("/") + "/api/ai/context"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None


def _table_exists(conn, table):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def _rows(conn, sql, params=()):
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def collect_local_facts(data_dir, date_str):
    db_path = Path(data_dir) / "pnl.db"
    if not db_path.exists():
        return {
            "pnl": {},
            "trades": [],
            "tickets": {"status": "missing_db", "total": 0, "items": []},
        }
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        trades = []
        if _table_exists(conn, "trade_records"):
            trades = _rows(
                conn,
                """
                SELECT *
                FROM trade_records
                WHERE trade_date = ?
                ORDER BY id DESC
                LIMIT 10000
                """,
                (date_str,),
            )
        tickets = {"status": "missing_table", "total": 0, "items": []}
        if _table_exists(conn, "trade_tickets"):
            count_rows = _rows(
                conn,
                """
                SELECT status, COUNT(*) AS n
                FROM trade_tickets
                WHERE trade_date = ?
                GROUP BY status
                """,
                (date_str,),
            )
            items = _rows(
                conn,
                """
                SELECT ticket_id, status, action_type, window, code, name
                FROM trade_tickets
                WHERE trade_date = ?
                ORDER BY created_at DESC, ticket_id DESC
                LIMIT 100
                """,
                (date_str,),
            )
            total = sum(int(row.get("n") or 0) for row in count_rows)
            tickets = {
                "status": "ok",
                "total": total,
                "by_status": {row["status"]: row["n"] for row in count_rows},
                "items": items,
            }
        pnl = {}
        if _table_exists(conn, "daily_summary"):
            row = conn.execute(
                """
                SELECT date, nav, pnl_pct, sh_pct, sz_pct, cy_pct, pos_pct, deposit
                FROM daily_summary
                WHERE date = ?
                """,
                (date_str,),
            ).fetchone()
            if row:
                pnl = dict(row)
        if _table_exists(conn, "intraday_snapshots"):
            row = conn.execute(
                """
                SELECT ts, total_asset, mv, pnl_pct, pos_pct, nav
                FROM intraday_snapshots
                WHERE date = ?
                ORDER BY ts DESC
                LIMIT 1
                """,
                (date_str,),
            ).fetchone()
            if row:
                pnl.update(dict(row))
        return {"pnl": pnl, "trades": trades, "tickets": tickets}
    finally:
        conn.close()


def generate_review_source_packet(date_str, data_dir=DEFAULT_DATA_DIR,
                                  api_base=DEFAULT_API_BASE, now=None):
    ai_context = fetch_ai_context(api_base=api_base)
    local = collect_local_facts(data_dir, date_str)
    return build_review_source_packet(
        date_str=date_str,
        ai_context=ai_context,
        pnl_summary=local.get("pnl") or {},
        trades=local.get("trades") or [],
        tickets=local.get("tickets") or {"status": "unknown"},
        now=now,
    )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="生成 WorkBuddy 日复盘 source packet")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    apply = bool(args.apply)
    packet = generate_review_source_packet(
        args.date,
        data_dir=Path(args.data_dir),
        api_base=args.api_base,
    )
    result = write_review_source_packet(packet, Path(args.data_dir), apply=apply)
    print("[STEP] 生成 review_source_packet")
    print(f"  date: {packet['date']}")
    print(f"  output: {result['path']}")
    print(f"  ai_context: {packet['source_status'].get('ai_context')}")
    print(f"  tickets: {packet['source_status'].get('tickets')}")
    print(f"  manual_required: {len(packet.get('manual_required') or [])}")
    print("  ✅ 已写入" if result["written"] else "  [DRY-RUN] 未写入")
    return packet


if __name__ == "__main__":
    main(sys.argv[1:])
