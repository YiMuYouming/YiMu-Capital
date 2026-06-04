#!/usr/bin/env python3
"""Authoritative intraday account state derived from anchor, trades and quotes."""

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _number(value):
    try:
        return float(str(value or 0).replace("股", ""))
    except (TypeError, ValueError):
        return 0.0


def trade_cash_effect(trade):
    """Return settled cash movement for one executed trade event."""
    amount = round(_number(trade.get("price")) * _number(trade.get("qty")), 2)
    action = str(trade.get("action", ""))
    fee = _number(trade.get("fee"))
    if "卖出" in action:
        return round(amount - fee, 2)
    if "买入" in action or "追涨" in action:
        return round(-amount - fee, 2)
    return 0.0


def _fund_event_cash_effect(event):
    """Return cash movement for one fund event."""
    amount = float(event.get("amount") or 0)
    event_type = str(event.get("event_type", ""))
    if event_type in ("入金", "红利", "利息", "退款"):
        return amount
    if event_type in ("出金", "手续费", "税费", "其他"):
        return -amount
    return 0.0


def _event_timestamp(trade):
    time_value = str(trade.get("trade_time") or "00:00")
    if len(time_value) == 4:
        time_value = "0" + time_value
    return f"{trade.get('trade_date', '')}T{time_value}"


def _open_positions(positions):
    result = []
    for position in positions or []:
        if "清" in str(position.get("状态", "")) or "删" in str(position.get("状态", "")):
            continue
        copy = deepcopy(position)
        copy["数量"] = int(_number(copy.get("数量")))
        if copy["数量"] > 0:
            result.append(copy)
    return result


def _quote_status(quotes, now=None):
    """判断行情新鲜度：live / close_snapshot / stale / missing。

    规则：先看交易时段，再看 age。
    - 盘前(<9:15)：上一交易日15:00后的行情可作为 close_snapshot 展示
    - 盘中(9:30-15:00)：age≤300s→live，否则→stale
    - 收盘后(≥15:00)：当天≥15:00的行情→close_snapshot(可用)，否则→stale
    - 其他跨日/无_updated→stale/missing
    返回 (is_usable: bool, quote_status: str)
    """
    updated = (quotes or {}).get("_updated")
    if not updated:
        return False, "missing"
    try:
        quote_time = datetime.fromisoformat(updated)
        ref_time = datetime.fromisoformat(now) if now else datetime.now(quote_time.tzinfo)
        if quote_time.tzinfo and not ref_time.tzinfo:
            ref_time = ref_time.replace(tzinfo=quote_time.tzinfo)
        elif ref_time.tzinfo and not quote_time.tzinfo:
            quote_time = quote_time.replace(tzinfo=ref_time.tzinfo)
        age = (ref_time - quote_time).total_seconds()
        if age < 0:
            return False, "stale"  # 未来时间不可用

        quote_date = quote_time.date()
        ref_date = ref_time.date()
        quote_hhmm = quote_time.hour * 60 + quote_time.minute
        ref_hhmm = ref_time.hour * 60 + ref_time.minute
        PRE_MARKET = 9 * 60 + 15
        MARKET_CLOSE = 15 * 60  # 15:00

        if quote_date != ref_date:
            # 盘前看盘仍需要展示昨收账户快照；交易规则继续由 rule_state
            # 的 freshness 阻断控制，不把这类快照当作盘中实时行情。
            if (
                ref_hhmm < PRE_MARKET
                and quote_date < ref_date
                and quote_hhmm >= MARKET_CLOSE
                and age <= 4 * 86400
            ):
                return True, "close_snapshot"
            return False, "stale"

        if ref_hhmm < PRE_MARKET:
            # 09:15 前采集器尚未进入常规 5s 轮询；同日冷启动/盘前快照
            # 可用于估值展示，但不冒充盘中 live。
            if age <= 2 * 3600:
                return True, "premarket_snapshot"
            return False, "stale"

        if ref_hhmm < MARKET_CLOSE:
            # 盘中：严格 300s
            if age <= 300:
                return True, "live"
            return False, "stale"
        else:
            # 收盘后：当天≥15:00行情可用
            if quote_hhmm >= MARKET_CLOSE:
                return True, "close_snapshot"
            return False, "stale"
    except (TypeError, ValueError):
        return False, "missing"


def _json_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def _json_dict(value):
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def build_daily_ticket_review(date_str, eod_quotes=None):
    """Build a close-day ticket review from SQLite facts.

    This function reports only data derivable from persisted tickets, fills,
    lots and conflict logs. Missing EOD prices do not produce guessed outcomes.
    """
    from collections import defaultdict
    from scripts.db import init_db, query_trade_tickets, query_trades, _exec
    init_db()

    tickets = query_trade_tickets(date_from=date_str, date_to=date_str, limit=10000)
    trades = query_trades(date_from=date_str, date_to=date_str, limit=10000)
    fills = [dict(t) for t in trades if t.get("ticket_id")]
    conflicts = [dict(r) for r in _exec("""
        SELECT * FROM ticket_conflict_log
        WHERE trade_date = ?
        ORDER BY created_at ASC, id ASC
    """, (date_str,))]
    lots = [dict(r) for r in _exec("""
        SELECT * FROM position_lots
        WHERE buy_date <= ? AND status = 'open'
        ORDER BY code ASC, locked_until ASC, lot_id ASC
    """, (date_str,))]

    by_action_type = defaultdict(int)
    for ticket in tickets:
        by_action_type[str(ticket.get("action_type") or "unknown")] += 1

    blocked_statuses = {"blocked", "audit_degraded", "observe"}
    filled_statuses = {"filled", "partially_filled", "closed", "closed_with_conflict"}
    blocked_tickets = [t for t in tickets if str(t.get("status")) in blocked_statuses]
    filled_tickets = [t for t in tickets if str(t.get("status")) in filled_statuses]
    t1_conflicts = [
        c for c in conflicts
        if "T1" in str(c.get("conflict_type") or "").upper()
        or "SELLABLE" in str(c.get("conflict_type") or "").upper()
    ]
    do_t_results = [
        t for t in tickets
        if str(t.get("action_type") or "").lower() in {"t", "do_t"}
    ]
    w2_buys = [
        t for t in tickets
        if str(t.get("window") or "").upper() == "W2"
        and str(t.get("action_type") or "").lower() in {"buy", "add"}
    ]

    trades_by_ticket = defaultdict(list)
    for trade in fills:
        trades_by_ticket[trade.get("ticket_id")].append(trade)

    blocked_ticket_eod_outcomes = []
    eod_quotes = eod_quotes or {}
    for ticket in blocked_tickets:
        outcome = _json_dict(ticket.get("eod_outcome_json"))
        code = str(ticket.get("code") or "")
        q = eod_quotes.get(code) or eod_quotes.get(str(code).zfill(6)) or {}
        eod_price = _number(q.get("最新价") or q.get("close") or q.get("eod_price"))
        ticket_price = _number(ticket.get("stop_line") or ticket.get("max_amount"))
        if not outcome and eod_price > 0:
            outcome = {
                "eod_price": eod_price,
                "eod_return_from_ticket_price": None if ticket_price <= 0 else round((eod_price - ticket_price) / ticket_price * 100, 2),
                "would_have_hit_stop": None,
                "would_have_reached_target": None,
                "blocked_reason": (ticket.get("blocking_rule_ids") or ticket.get("close_reason") or ""),
            }
        if outcome:
            blocked_ticket_eod_outcomes.append({"ticket_id": ticket.get("ticket_id"), **outcome})

    rule_stats = {}
    for ticket in tickets:
        rule_ids = _json_list(ticket.get("triggered_rule_ids")) or ["UNSPECIFIED"]
        ticket_fills = trades_by_ticket.get(ticket.get("ticket_id"), [])
        realized = sum(_number(t.get("realized_pnl")) for t in ticket_fills)
        executed = 1 if ticket_fills or str(ticket.get("status")) in filled_statuses else 0
        manual_override = 1 if ticket.get("human_override_reason") else 0
        eod = _json_dict(ticket.get("eod_outcome_json"))
        would_win = None
        if eod:
            would_win = 1 if eod.get("would_have_reached_target") else 0
        for rule_id in rule_ids:
            row = rule_stats.setdefault(rule_id, {
                "rule_id": rule_id,
                "window": ticket.get("window"),
                "sentiment_bucket": None,
                "trigger_count": 0,
                "executed_count": 0,
                "win_rate": None,
                "avg_R": None,
                "total_realized_pnl": 0.0,
                "manual_override_count": 0,
                "manual_override_pnl": 0.0,
                "blocked_but_later_would_win_count": None,
            })
            row["trigger_count"] += 1
            row["executed_count"] += executed
            row["total_realized_pnl"] = round(row["total_realized_pnl"] + realized, 2)
            row["manual_override_count"] += manual_override
            if manual_override:
                row["manual_override_pnl"] = round(row["manual_override_pnl"] + realized, 2)
            if would_win is not None:
                if row["blocked_but_later_would_win_count"] is None:
                    row["blocked_but_later_would_win_count"] = 0
                row["blocked_but_later_would_win_count"] += would_win

    markdown = "\n".join([
        f"# {date_str} 交易票据复盘",
        "",
        f"- {len(tickets)} tickets",
        f"- {len(fills)} fills",
        f"- {len(t1_conflicts)} T+1 conflict candidate",
        f"- {len(do_t_results)} do-T group",
        f"- {len(w2_buys)} W2 buy",
    ])

    return {
        "date": date_str,
        "ticket_count": len(tickets),
        "fill_count": len(fills),
        "by_action_type": dict(by_action_type),
        "blocked_tickets": blocked_tickets,
        "filled_tickets": filled_tickets,
        "lot_locks": lots,
        "t1_conflicts": t1_conflicts,
        "do_t_results": do_t_results,
        "rule_id_stats": list(rule_stats.values()),
        "account_metric_errors": [],
        "funds_conflict_events": [
            t for t in tickets
            if any("DATA-FUNDS" in str(rule_id) for rule_id in _json_list(t.get("blocking_rule_ids")))
        ],
        "ice_w1_block_events": [
            t for t in tickets
            if any("WIN-ICE-W1" in str(rule_id) for rule_id in _json_list(t.get("blocking_rule_ids")))
        ],
        "style_score_adjustments": [
            t for t in tickets if t.get("style_score_adjusted") is not None
        ],
        "blocked_ticket_eod_outcomes": blocked_ticket_eod_outcomes,
        "review_markdown": markdown,
    }


def reduce_account_state(anchor, trades, quotes, now=None, fund_events=None):
    """Replay post-anchor trades and fund events; value open holdings with live quotes."""
    positions = _open_positions(anchor.get("positions", []))
    by_code = {str(position.get("代码", "")): position for position in positions}
    cash = _number(anchor.get("cash"))
    effective_at = str(anchor.get("effective_at") or "")
    trade_id_cutoff = anchor.get("trade_id_cutoff")

    def event_order_trade(trade):
        return (_event_timestamp(trade), int(trade.get("id") or 0))

    # Day-start prices per code from anchor (for overnight PnL)
    anchor_day_prices = {}
    anchor_meta = anchor.get("_meta")
    if isinstance(anchor_meta, dict):
        anchor_day_prices = anchor_meta.get("day_start_prices") or {}

    # Today PnL tracking per code
    today_pnl_map = {}      # code -> realized PnL from sells
    today_basis_map = {}    # code -> denominator (day-start basis + buy amounts, never shrinks on sells)
    closed_list = []        # fully-sold positions

    # Per-code overnight tracking (keyed by code from anchor open positions)
    overnight_remaining = {}  # code -> remaining overnight qty (shrinks on sells, FIFO)
    overnight_ref = {}        # code -> day_start_price
    original_anchor_codes = set()
    for position in positions:
        code = str(position.get("代码", ""))
        qty = int(position.get("数量", 0))
        original_anchor_codes.add(code)
        overnight_remaining[code] = qty
        ref = _number(anchor_day_prices.get(code))
        overnight_ref[code] = ref if ref > 0 else None
        if ref and ref > 0:
            today_basis_map[code] = round(ref * qty, 2)

    # Per-code bought tracking (new buys today, avg cost used for sell realized)
    bought_qty = {}    # code -> remaining bought qty (shrinks on sells, FIFO after overnight)
    bought_cost = {}   # code -> remaining bought cost basis

    # 1. 重放交易流水（含逐股日内收益）
    ledger_errors = []
    for trade in sorted(trades or [], key=event_order_trade):
        if trade_id_cutoff is not None and trade.get("id") is not None:
            if int(trade["id"]) <= int(trade_id_cutoff):
                continue
        elif effective_at and _event_timestamp(trade) < effective_at:
            continue
        code = str(trade.get("code", ""))
        qty = int(_number(trade.get("qty")))
        if not code or qty <= 0:
            continue
        position = by_code.get(code)
        action = str(trade.get("action", ""))
        if "卖出" in action:
            old_qty = int(position.get("数量", 0)) if position else 0
            # Oversell guard: qty > available → fail-closed, skip cash and position
            if qty > old_qty:
                ledger_errors.append({
                    "type": "oversell",
                    "trade_id": trade.get("id"),
                    "code": code,
                    "name": trade.get("name", ""),
                    "trade_time": trade.get("trade_time", ""),
                    "sell_qty": qty,
                    "available_qty": old_qty,
                })
                continue
            if position:
                cash += trade_cash_effect(trade)
                remaining_sell = min(qty, old_qty)
                new_qty = max(0, old_qty - remaining_sell)
                position["数量"] = new_qty
                sell_price = _number(trade.get("price"))

                # FIFO: deduct overnight first, then bought
                # — Overnight portion
                ov_qty = overnight_remaining.get(code, 0)
                sold_overnight = min(remaining_sell, ov_qty)
                if sold_overnight > 0 and overnight_ref.get(code) is not None:
                    realized = round((sell_price - overnight_ref[code]) * sold_overnight, 2)
                    today_pnl_map[code] = today_pnl_map.get(code, 0) + realized
                overnight_remaining[code] = ov_qty - sold_overnight
                remaining_sell -= sold_overnight

                # — Bought portion (avg cost)
                if remaining_sell > 0:
                    bq = bought_qty.get(code, 0)
                    bc = bought_cost.get(code, 0)
                    sold_bought = min(remaining_sell, bq)
                    if sold_bought > 0 and bq > 0 and bc > 0:
                        avg_bought = bc / bq
                        realized = round((sell_price - avg_bought) * sold_bought, 2)
                        today_pnl_map[code] = today_pnl_map.get(code, 0) + realized
                        # Shrink bought tracking proportionally
                        bought_qty[code] = bq - sold_bought
                        bought_cost[code] = round(bc - avg_bought * sold_bought, 2)

                # Fully sold -> closed position
                if new_qty == 0 and old_qty > 0:
                    has_valid_ref = overnight_ref.get(code) is not None
                    has_overnight = code in original_anchor_codes
                    if has_overnight and not has_valid_ref:
                        rpnl = None  # 缺日初基准，收益不可用
                    else:
                        rpnl = today_pnl_map.get(code, 0)
                    closed_list.append({
                        "name": position.get("标的", trade.get("name", "")),
                        "code": code,
                        "sell_time": str(trade.get("trade_time", "")),
                        "sell_price": sell_price,
                        "sell_qty": qty,
                        "reason": str(trade.get("reason", "")),
                        "realized_today_pnl": rpnl,
                        "closed_date": str(trade.get("trade_date", "")),
                        "close_trade_id": trade.get("id"),
                    })
        elif "买入" in action or "追涨" in action:
            cash += trade_cash_effect(trade)
            trade_price = _number(trade.get("price"))
            if not position:
                position = {
                    "标的": trade.get("name", ""),
                    "代码": code,
                    "数量": 0,
                    "成本": trade_price,
                    "现价": trade_price,
                    "状态": "持有",
                }
                positions.append(position)
                by_code[code] = position
            old_qty = int(position.get("数量", 0))
            old_cost = _number(position.get("成本"))
            new_qty = old_qty + qty
            if new_qty:
                position["成本"] = round(
                    (old_cost * old_qty + trade_price * qty) / new_qty, 2
                )
            position["数量"] = new_qty
            # 若之前已标记为清仓，买入重新开仓后移除 stale closed entry
            if old_qty == 0:
                closed_list[:] = [c for c in closed_list if c.get("code") != code]
            # Track bought
            bought_qty[code] = bought_qty.get(code, 0) + qty
            bought_cost[code] = bought_cost.get(code, 0) + round(trade_price * qty, 2)
            # Today basis: add buy amount to denominator
            today_basis_map[code] = today_basis_map.get(code, 0) + round(trade_price * qty, 2)

    # 2. 重放资金事件
    for event in sorted(fund_events or [], key=lambda e: (str(e.get("event_date", "")), int(e.get("id") or 0))):
        event_date = str(event.get("event_date", ""))
        if effective_at and event_date < effective_at[:10]:
            continue
        cash += _fund_event_cash_effect(event)

    positions = [position for position in positions if int(position.get("数量", 0)) > 0]
    mv = 0
    quotes_ok, quote_status = _quote_status(quotes, now)
    valuation_complete = not positions or quotes_ok

    for position in positions:
        code = str(position.get("代码", ""))
        quote = (quotes or {}).get(code, {})
        price = _number(quote.get("最新价"))
        if price <= 0:
            valuation_complete = False
            price = _number(position.get("现价")) or _number(position.get("成本"))
        position["现价"] = price
        qty = int(position.get("数量", 0))
        position["市值"] = round(price * qty, 2)
        mv += position["市值"]

        avg_cost = _number(position.get("成本"))
        position["成本价"] = round(avg_cost, 2)

        # Total PnL (cumulative)
        total_pnl = round((price - avg_cost) * qty, 2)
        total_pnl_pct = round((price - avg_cost) / avg_cost * 100, 2) if avg_cost > 0 else None
        position["total_pnl"] = total_pnl
        position["total_pnl_pct"] = total_pnl_pct

        # Today PnL: unrealized (overnight + bought portions) + realized (from sells)
        realized = today_pnl_map.get(code, 0)
        basis = today_basis_map.get(code, 0)
        has_overnight = code in original_anchor_codes
        has_valid_ref = overnight_ref.get(code) is not None

        if has_overnight and not has_valid_ref:
            # Overnight position without day_start_price — cannot compute
            position["today_pnl"] = None
            position["today_pnl_pct"] = None
            position["_day_start_price"] = None
        else:
            # Compute unrealized: overnight residual + bought residual
            unrealized = 0
            ov_qty = overnight_remaining.get(code, 0)
            if ov_qty > 0 and has_valid_ref:
                unrealized += round((price - overnight_ref[code]) * ov_qty, 2)
            bq = bought_qty.get(code, 0)
            bc = bought_cost.get(code, 0)
            if bq > 0 and bc > 0:
                avg_bought = bc / bq
                unrealized += round((price - avg_bought) * bq, 2)

            if basis > 0:
                position["today_pnl"] = round(realized + unrealized, 2)
                position["today_pnl_pct"] = round(position["today_pnl"] / basis * 100, 2)
            else:
                position["today_pnl"] = None
                position["today_pnl_pct"] = None
            position["_day_start_price"] = overnight_ref.get(code) if has_valid_ref else None

    cash = round(cash, 2)
    total_asset = round(cash + mv, 2)
    day_start_asset = _number(anchor.get("day_start_asset"))
    pnl_amount = round(total_asset - day_start_asset, 2) if day_start_asset else None
    pnl_pct = round(pnl_amount / day_start_asset * 100, 2) if day_start_asset else None
    pos_pct = round(mv / total_asset * 100, 2) if total_asset else 0

    return {
        "date": anchor.get("date"),
        "effective_at": anchor.get("effective_at"),
        "source": anchor.get("source"),
        "cash": cash,
        "positions": positions,
        "mv": mv,
        "total_asset": total_asset,
        "day_start_asset": day_start_asset or None,
        "pnl_amount": pnl_amount,
        "pnl_pct": pnl_pct,
        "pos_pct": pos_pct,
        "total_deposit": _number(anchor.get("total_deposit")),
        "valuation_complete": False if ledger_errors else valuation_complete,
        "quote_status": quote_status,
        "closed_positions": closed_list,
        "ledger_ok": not ledger_errors,
        "ledger_errors": ledger_errors,
        "anchor_blocked": bool(ledger_errors),
        "block_reason": "ledger_error: oversell detected" if ledger_errors else None,
    }


def update_account_baseline_meta(date_str, meta, update_anchor=None):
    """追加或更新锚点的 _meta 结算信息（收盘日结用）。"""
    from scripts.db import query_account_baseline, _exec_write
    anchor = query_account_baseline(date_str)
    existing = dict((anchor or {}).get("_meta") or {})
    merged = {**existing, **(meta or {})}
    if update_anchor is None:
        _exec_write(
            "UPDATE account_baselines SET _meta_json = ? WHERE date = ?",
            (json.dumps(merged, ensure_ascii=False), date_str)
        )
    else:
        _exec_write(
            "UPDATE account_baselines SET _meta_json = ? WHERE date = ?",
            (json.dumps(merged, ensure_ascii=False), date_str)
        )


def backfill_day_start_price(date_str, code, price, source, reason,
                            dry_run=False, get_anchor=None, update_meta=None):
    """受控补录缺失的日初基准价到 account_baselines._meta.day_start_prices。

    day_start_prices 只保存 code -> number。
    审计信息写入独立的 _meta.day_start_price_repairs 数组。

    Args:
        date_str: 锚点日期 (YYYY-MM-DD)
        code: 股票代码
        price: 日初价 (>0，人工确认后传入)
        source: 价格来源，不可为空
        reason: 修复原因，不可为空
        dry_run: True 时只输出差异，不写入
        get_anchor: fn(date_str) -> anchor dict，默认 db.query_account_baseline
        update_meta: fn(date_str, new_meta_dict) -> None，默认写默认库

    Returns:
        dict: {action, code, price, before_prices, after_prices, repair_entry, error, dry_run}
    """
    if get_anchor is None:
        from scripts.db import query_account_baseline as _qab
        get_anchor = _qab
    if update_meta is None:
        from scripts.db import _exec_write as _ew
        def _default_update(d, m):
            _ew("UPDATE account_baselines SET _meta_json = ? WHERE date = ?",
                (json.dumps(m, ensure_ascii=False), d))
        update_meta = _default_update

    # 校验 source / reason
    if not source or not str(source).strip():
        return {"action": "rejected", "code": code, "price": price,
                "error": "source 不能为空"}
    if not reason or not str(reason).strip():
        return {"action": "rejected", "code": code, "price": price,
                "error": "reason 不能为空"}

    # 校验 price
    try:
        price_f = round(float(price), 2)
    except (TypeError, ValueError):
        return {"action": "rejected", "code": code, "price": price,
                "error": f"price 非法: {price!r}"}
    if price_f <= 0:
        return {"action": "rejected", "code": code, "price": price_f,
                "error": "price 必须 > 0"}

    # 查询锚点
    anchor = get_anchor(date_str)
    if not anchor:
        return {"action": "rejected", "code": code, "price": price_f,
                "error": f"日期 {date_str} 无锚点"}

    # 校验 code 在锚点持仓中
    anchor_positions = anchor.get("positions") or []
    anchor_codes = {str(p.get("代码", "")) for p in anchor_positions}
    if code not in anchor_codes:
        return {"action": "rejected", "code": code, "price": price_f,
                "error": f"代码 {code} 不在 {date_str} 锚点持仓中 (codes: {sorted(anchor_codes)})"}

    # 读取已有 _meta
    existing_meta = anchor.get("_meta") or {}
    existing_prices = dict(existing_meta.get("day_start_prices") or {})

    # 幂等：已有价格时拒绝覆盖
    if code in existing_prices:
        return {"action": "idempotent", "code": code, "price": price_f,
                "existing_price": existing_prices[code],
                "error": f"代码 {code} 已有日初价 {existing_prices[code]}，拒绝覆盖"}

    # 构建新 _meta
    new_meta = dict(existing_meta)
    # day_start_prices 只保存 code -> number
    new_prices = dict(existing_prices)
    new_prices[code] = price_f
    new_meta["day_start_prices"] = new_prices

    # 审计信息放入独立 day_start_price_repairs 数组
    repair_entry = {
        "code": code,
        "price": price_f,
        "source": str(source).strip(),
        "reason": str(reason).strip(),
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }
    repairs = list(existing_meta.get("day_start_price_repairs") or [])
    repairs.append(repair_entry)
    new_meta["day_start_price_repairs"] = repairs

    result = {
        "action": "would_write" if dry_run else "written",
        "code": code,
        "price": price_f,
        "date": date_str,
        "source": str(source).strip(),
        "reason": str(reason).strip(),
        "before_prices": existing_prices,
        "after_prices": new_prices,
        "repair_entry": repair_entry,
        "dry_run": dry_run,
        "error": None,
    }

    if dry_run:
        return result

    try:
        update_meta(date_str, new_meta)
        result["action"] = "written"
    except Exception as e:
        result["action"] = "rejected"
        result["error"] = str(e)

    return result


def compute_max_drawdown(date_str):
    """从当日快照计算最大回撤及其起止时间。"""
    from scripts.db import _exec
    rows = _exec(
        "SELECT ts, total_asset FROM intraday_snapshots WHERE date = ? ORDER BY ts",
        (date_str,),
    )
    if not rows or len(rows) < 2:
        return None, None, None
    peak = rows[0]["total_asset"] or 0
    peak_ts = rows[0]["ts"]
    max_dd = 0.0
    dd_start, dd_end, dd_end_ts = None, None, None
    for r in rows:
        asset = r["total_asset"] or 0
        if asset >= peak:
            peak = asset
            peak_ts = r["ts"]
        dd = (peak - asset) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
            dd_start = peak_ts
            dd_end = r["ts"]
            dd_end_ts = r["ts"]
    if max_dd <= 0:
        return None, None, None
    return round(max_dd * 100, 4), dd_start, dd_end


def generate_closing_anchor(live_quotes, now=None, insert_anchor=None,
                            pnl_history_path=None):
    """固化当日收盘账户状态，写次日 previous_close 锚点，更新 daily_summary（含 max_dd）。

    Args:
        live_quotes: 收盘行情 dict
        now: 结算时间戳，默认当前时间
        insert_anchor: 锚点写入函数，默认使用 db.insert_account_baseline
        pnl_history_path: pnl_history.json 输出路径，默认写入 data/pnl_history.json
                         测试应传入 tempfile 路径以避免污染真实文件。
    """
    from scripts.db import query_account_baseline, query_trades, query_fund_events, insert_daily_summary, update_trade_outcomes
    if insert_anchor is None:
        from scripts.db import insert_account_baseline
        insert_anchor = insert_account_baseline

    effective_at = now or datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    date_str = effective_at[:10]

    # 查询今日已有锚点
    today_anchor = query_account_baseline(date_str)
    if not today_anchor:
        print(f"  [account_ssot] No today anchor for {date_str}, skipping closing anchor")
        return None

    # 用当日锚点 + 全量流水 + 资金事件 + 收盘行情算出最终状态
    trades = query_trades(date_from=date_str, date_to=date_str, limit=10000)
    fund_events = query_fund_events(date_from=date_str, date_to=date_str, limit=10000)
    state = reduce_account_state(today_anchor, trades, live_quotes or {}, now=effective_at, fund_events=fund_events)

    # 结算 NAV = total_asset / total_deposit
    deposit = float(state.get("total_deposit") or 0)
    nav = round(state["total_asset"] / deposit, 6) if deposit > 0 else 1.0

    # 结算 PnL%
    if state.get("day_start_asset"):
        pnl_pct = round((state["total_asset"] - state["day_start_asset"]) / state["day_start_asset"] * 100, 4)
    else:
        pnl_pct = 0.0

    closing_meta = {
        "nav": nav,
        "pnl_pct": pnl_pct,
        "total_asset": state["total_asset"],
        "mv": state["mv"],
    }

    # 更新今日锚点的结算元数据
    update_account_baseline_meta(date_str, closing_meta)

    # 日结：固化 daily_summary（含 max_dd 计算）
    max_dd, dd_start, dd_end = compute_max_drawdown(date_str)
    live_index = live_quotes or {}
    insert_daily_summary({
        "date": date_str,
        "nav": nav,
        "pnl_pct": pnl_pct,
        "sh_pct": 0,  # 由 quotes.py 盘后批量补录
        "sz_pct": 0,
        "cy_pct": 0,
        "pos_pct": state.get("pos_pct", 0),
        "deposit": state["total_deposit"],
        "max_dd": max_dd,
        "max_dd_start": dd_start,
        "max_dd_end": dd_end,
    })

    # 日结：补写 trade_records 的 outcome（买入含收盘价，卖出含盈亏，只补不改变原成交事实）
    try:
        day_trades = query_trades(date_from=date_str, date_to=date_str, limit=10000)
        quotes = live_quotes or {}
        outcomes = {}
        for t in day_trades:
            tid = t.get('id')
            if not tid or t.get('outcome', ''):
                continue
            act = str(t.get('action', ''))
            code = str(t.get('code', ''))
            name = str(t.get('name', ''))
            price = float(t.get('price') or 0)
            pnl = float(t.get('realized_pnl') or 0)
            q = quotes.get(code, {}) if code else {}
            close_px = float(q.get('最新价') or 0) if q else 0
            if '买入' in act or '追涨' in act:
                if close_px and price:
                    ret = round((close_px - price) / price * 100, 2)
                    tag = '浮盈' if ret >= 0 else '浮亏'
                    outcomes[tid] = f"买入 {name} {code} @{price} 收盘{close_px} {tag}{ret:+.2f}%"
                else:
                    outcomes[tid] = f"买入 {name} {code} @{price} 收盘无行情"
            elif '卖出' in act:
                tag = '盈利' if pnl > 0 else ('亏损' if pnl < 0 else '平出')
                outcomes[tid] = f"卖出 {name} {code} {tag} {pnl:+.1f}" if pnl else f"卖出 {name} {code}"
            elif '纠错' in str(t.get('reason', '')):
                outcomes[tid] = f"纠错 {name} {code}"
        if outcomes:
            update_trade_outcomes(date_str, outcomes)
    except Exception as e:
        print(f"  [account_ssot] outcome update skipped: {e}")

    # 日结：更新 pnl_history.json（收盘权威值）
    # 可注入路径，避免测试污染真实 data/ 文件
    pnl_hist_file = pnl_history_path if pnl_history_path else (ROOT / "data" / "pnl_history.json")
    ph_data = {}
    if pnl_hist_file.exists():
        try:
            with open(pnl_hist_file) as handle:
                ph_data = json.load(handle)
        except Exception:
            pass
    ph_data["meta"] = ph_data.get("meta", {})
    ph_data["meta"].update({
        "last_total_asset": state["total_asset"],
        "last_mv": state["mv"],
        "last_twr_nav": nav,
        "last_updated": effective_at,
        "closed_date": date_str,
    })
    # 追加日结算录（去重）
    daily_records = ph_data.get("daily", [])
    date_found = False
    for i, rec in enumerate(daily_records):
        if rec.get("date") == date_str:
            daily_records[i] = {
                "date": date_str,
                "nav": nav,
                "pnl_pct": pnl_pct,
                "total_asset": state["total_asset"],
                "mv": state["mv"],
                "pos_pct": state.get("pos_pct", 0),
                "max_dd": max_dd,
            }
            date_found = True
            break
    if not date_found:
        daily_records.append({
            "date": date_str,
            "nav": nav,
            "pnl_pct": pnl_pct,
            "total_asset": state["total_asset"],
            "mv": state["mv"],
            "pos_pct": state.get("pos_pct", 0),
            "max_dd": max_dd,
        })
    ph_data["daily"] = daily_records[-90:]
    from scripts.file_utils import atomic_write_json
    atomic_write_json(pnl_hist_file, ph_data)

    # 生成次日锚点
    import datetime as _dt
    next_date = _dt.datetime.strptime(date_str, "%Y-%m-%d") + _dt.timedelta(days=1)
    while next_date.weekday() >= 5:
        next_date += _dt.timedelta(days=1)
    next_str = next_date.strftime("%Y-%m-%d")

    # 固化次日日初参考价
    day_start_prices = {}
    for pos in state.get("positions", []):
        code = str(pos.get("代码", ""))
        px = _number(pos.get("现价")) or _number(pos.get("成本"))
        if code and px > 0:
            day_start_prices[code] = px

    inserted = insert_anchor({
        "date": next_str,
        "effective_at": f"{next_str}T09:25:00",
        "trade_id_cutoff": 0,
        "cash": state["cash"],
        "day_start_asset": state["total_asset"],
        "total_deposit": state["total_deposit"],
        "positions": state["positions"],
        "source": "previous_close",
        "_meta": {"day_start_prices": day_start_prices} if day_start_prices else None,
    })
    if inserted:
        print(f"  [account_ssot] Closing anchor: {next_str} written, cash={state['cash']}, total_asset={state['total_asset']}, nav={nav}, pnl={pnl_pct}%")
    return {
        "next_date": next_str,
        "nav": nav,
        "pnl_pct": pnl_pct,
        "total_asset": state["total_asset"],
        "inserted": inserted,
    }


def query_previous_close_anchor(date_str, get_anchor=None):
    """查询指定日期的 previous_close 锚点（供次日开盘使用）。"""
    if get_anchor is None:
        from scripts.db import query_account_baseline
        get_anchor = query_account_baseline
    anchor = get_anchor(date_str)
    if anchor and anchor.get("source") == "previous_close":
        return anchor
    return None


def ensure_today_anchor(data, day_start_asset, now=None, get_anchor=None, insert_anchor=None, get_last_trade_id=None):
    """Create one immutable account anchor and return the persisted version.

    优先级：已有锚点 > previous_close 锚点 > 从 data 新建（recovery）
    """
    if get_anchor is None or insert_anchor is None:
        from scripts.db import insert_account_baseline, query_account_baseline
        get_anchor = query_account_baseline
        insert_anchor = insert_account_baseline
    if get_last_trade_id is None:
        from scripts.db import query_last_trade_id
        get_last_trade_id = query_last_trade_id
    effective_at = now or datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    date_str = effective_at[:10]
    existing = get_anchor(date_str)
    if existing:
        src = existing.get("source", "")
        positions = existing.get("positions") or []
        if src == "recovery" and len(positions) > 0:
            return {
                "date": date_str,
                "source": "blocked",
                "block_reason": "existing recovery anchor with positions — untrusted",
                "existing_source": src,
                "positions": positions,
            }
        return existing

    # 优先用 previous_close 锚点（次日开盘锁定）
    prev_anchor = query_previous_close_anchor(date_str, get_anchor)
    if prev_anchor:
        anchor = {
            "date": date_str,
            "effective_at": effective_at,
            "trade_id_cutoff": prev_anchor.get("trade_id_cutoff", 0),
            "cash": _number(prev_anchor.get("cash")),
            "day_start_asset": _number(prev_anchor.get("day_start_asset")),
            "total_deposit": _number(prev_anchor.get("total_deposit")),
            "positions": prev_anchor.get("positions", []),
            "source": "previous_close",
        }
        insert_anchor(anchor)
        return get_anchor(date_str) or anchor

    # 无 previous_close anchor：只允许首次初始化或显式 manual_correction
    # 持仓账户缺 previous_close → 阻断，不允许自动生成可交易 anchor
    pnl = (data or {}).get("pnl", {})
    positions = _open_positions((data or {}).get("positions", []))
    pos_cost = sum(_number(p.get("成本", 0)) * _number(p.get("数量", 0)) for p in positions)
    has_positions = len(positions) > 0

    if has_positions:
        # 持仓账户必须有 previous_close 或 manual_correction；
        # 不可从 dashboard/pnl_history 自动推算 cash
        print(f"  [account_ssot] BLOCKED: {date_str} has {len(positions)} positions but no previous_close anchor")
        return {
            "date": date_str,
            "source": "blocked",
            "block_reason": "positions without previous_close anchor",
            "positions": positions,
        }

    # 首次初始化（无持仓）：允许 recovery
    raw_cash = _number(pnl.get("可用资金"))
    total_deposit = _number(pnl.get("累计入金"))
    anchor = {
        "date": date_str,
        "effective_at": effective_at,
        "trade_id_cutoff": get_last_trade_id(date_str),
        "cash": raw_cash,
        "day_start_asset": _number(day_start_asset),
        "total_deposit": total_deposit,
        "positions": positions,
        "source": "recovery",
    }
    insert_anchor(anchor)
    return get_anchor(date_str) or anchor


def _recent_trading_dates(date_str, count=7):
    """Return recent trading dates, approximated by weekdays when no exchange calendar exists."""
    from datetime import datetime as _dt, timedelta as _td

    current = _dt.strptime(date_str, "%Y-%m-%d")
    dates = []
    while len(dates) < count:
        if current.weekday() < 5:
            dates.append(current.strftime("%Y-%m-%d"))
        current -= _td(days=1)
    return dates


def query_7day_closed_positions(date_str, get_anchor=None, get_trades=None):
    """查询近7个交易日（含当日）完全卖清的持仓，仅来自 SSOT 账本回放。

    返回 list[dict]: 每项 {code, name, closed_date, sell_price, reason, ...}
    去重：同一 code 只保留最近一次清仓日期。
    """

    if get_anchor is None:
        from scripts.db import query_account_baseline
        get_anchor = query_account_baseline
    if get_trades is None:
        from scripts.db import query_trades
        get_trades = query_trades

    trading_dates = _recent_trading_dates(date_str, 7)
    all_closed = {}  # code -> closed entry

    # 收集7个交易日窗口内所有含 is_reversal=1 的纠错交易，提取被撤销的原始交易 ID
    start_date = trading_dates[-1] if trading_dates else date_str
    all_trades = get_trades(date_from=start_date, date_to=date_str, limit=10000)
    reversed_trade_ids = set()
    for t in (all_trades or []):
        if int(t.get("is_reversal") or 0) == 1:
            orig_id = t.get("reversal_of_id")
            if orig_id is not None:
                reversed_trade_ids.add(int(orig_id))

    # 逐交易日回放，收集 closed_positions
    for day in trading_dates:
        anchor = get_anchor(day)
        if not anchor:
            continue
        trades = get_trades(date_from=day, date_to=day, limit=10000)
        if not trades:
            continue
        state = reduce_account_state(anchor, trades, {}, now=f"{day}T23:59:59")
        for closed in state.get("closed_positions") or []:
            code = closed.get("code")
            if not code:
                continue
            # 若清仓交易被纠错链撤销，排除
            close_tid = closed.get("close_trade_id")
            if close_tid is not None and int(close_tid) in reversed_trade_ids:
                continue
            if code not in all_closed or closed.get("closed_date", "") > all_closed[code].get("closed_date", ""):
                all_closed[code] = closed

    return sorted(all_closed.values(), key=lambda c: c.get("closed_date", ""), reverse=True)


def _lot_reconciliation_for_positions(positions):
    """Compare current account position quantity with open lot quantity by code."""
    try:
        from scripts.db import get_conn
        conn = get_conn()
        rows = conn.execute("""
            SELECT code, COALESCE(SUM(open_qty), 0) AS qty
            FROM position_lots
            WHERE status = 'open'
            GROUP BY code
        """).fetchall()
    except Exception as exc:
        return False, [{
            "code": None,
            "account_qty": None,
            "lot_qty": None,
            "message": f"lot/account quantity mismatch: lot table unavailable ({exc})",
        }]

    lot_qty = {str(row["code"]): int(row["qty"] or 0) for row in rows}
    account_qty = {}
    for position in positions or []:
        code = str(position.get("代码") or "")
        qty = int(_number(position.get("数量")))
        if code and qty > 0:
            account_qty[code] = account_qty.get(code, 0) + qty

    errors = []
    for code in sorted(set(account_qty) | set(lot_qty)):
        aq = int(account_qty.get(code, 0))
        lq = int(lot_qty.get(code, 0))
        if aq != lq:
            errors.append({
                "code": code,
                "account_qty": aq,
                "lot_qty": lq,
                "message": f"lot/account quantity mismatch for {code}: account={aq}, lots={lq}",
            })
    return not errors, errors


def _lot_summary_by_code(trade_date):
    try:
        from scripts.db import get_conn, is_trading_day
        conn = get_conn()
        rows = [dict(row) for row in conn.execute("""
            SELECT *
            FROM position_lots
            WHERE status = 'open' AND open_qty > 0
            ORDER BY code ASC, buy_date ASC, created_at ASC, lot_id ASC
        """).fetchall()]
    except Exception:
        return {}

    summaries = {}
    trade_day_open = is_trading_day(trade_date)
    for lot in rows:
        code = str(lot.get("code") or "")
        if not code:
            continue
        entry = summaries.setdefault(code, {"lots": [], "sellable_qty": 0, "locked_qty": 0})
        open_qty = int(_number(lot.get("open_qty")))
        locked_until = str(lot.get("locked_until") or "")
        sellable = trade_day_open and locked_until <= trade_date
        lot_copy = dict(lot)
        lot_copy["sellable"] = sellable
        entry["lots"].append(lot_copy)
        if sellable:
            entry["sellable_qty"] += open_qty
        else:
            entry["locked_qty"] += open_qty
    return summaries


def load_current_account_state(live_quotes, now=None, data_file=None, history_file=None):
    """Load the locked daily anchor and replay new trade records and fund events."""
    from scripts.db import insert_account_baseline, query_account_baseline, query_last_trade_id, query_trades, query_fund_events

    effective_at = now or datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    date_str = effective_at[:10]
    dashboard_path = Path(data_file) if data_file else ROOT / "data" / "dashboard_data.json"
    history_path = Path(history_file) if history_file else ROOT / "data" / "pnl_history.json"
    with open(dashboard_path, encoding="utf-8") as handle:
        data = json.load(handle)
    day_start_asset = 0
    if history_path.exists():
        with open(history_path, encoding="utf-8") as handle:
            meta = json.load(handle).get("meta", {})
        if meta.get("day_start_date") == date_str:
            day_start_asset = meta.get("day_start_asset", 0)
        else:
            day_start_asset = meta.get("last_total_asset", 0)
    anchor = ensure_today_anchor(
        data,
        day_start_asset,
        now=effective_at,
        get_anchor=query_account_baseline,
        insert_anchor=insert_account_baseline,
        get_last_trade_id=query_last_trade_id,
    )
    if isinstance(anchor, dict) and anchor.get("source") == "blocked":
        return {
            "date": date_str,
            "anchor_blocked": True,
            "block_reason": anchor.get("block_reason", ""),
            "valuation_complete": False,
            "total_asset": None,
            "cash": None,
            "mv": None,
            "pnl_pct": None,
            "positions": [],
            "closed_positions": [],
            "trades": [],
            "quote_status": "missing",
            "source": "blocked",
        }
    trades = query_trades(date_from=date_str, date_to=date_str, limit=10000)
    fund_events = query_fund_events(date_from=date_str, date_to=date_str, limit=10000)
    state = reduce_account_state(anchor, trades, live_quotes or {}, now=effective_at, fund_events=fund_events)
    # 扩展为7日内清仓（含当日 + 前6日）
    seven_day = query_7day_closed_positions(date_str,
                                            get_anchor=query_account_baseline,
                                            get_trades=query_trades)
    # 当日 closed_positions 已由 reduce_account_state 精确计算，优先保留
    today_codes = {c.get("code") for c in state.get("closed_positions") or []}
    for c in seven_day:
        if c.get("code") not in today_codes:
            state.setdefault("closed_positions", []).append(c)
    state["trades"] = sorted(trades, key=lambda trade: (_event_timestamp(trade), int(trade.get("id") or 0)))
    lot_summary = _lot_summary_by_code(date_str)
    for position in state.get("positions") or []:
        code = str(position.get("代码") or "")
        summary = lot_summary.get(code, {"lots": [], "sellable_qty": 0, "locked_qty": 0})
        position["sellable_qty"] = int(summary["sellable_qty"])
        position["locked_qty"] = int(summary["locked_qty"])
        position["lots"] = summary["lots"]
        position["lot_reconciliation_ok"] = (
            int(_number(position.get("数量"))) == position["sellable_qty"] + position["locked_qty"]
        )
    lot_ok, lot_errors = _lot_reconciliation_for_positions(state.get("positions") or [])
    state["lot_reconciliation_ok"] = lot_ok
    state["lot_reconciliation_errors"] = lot_errors
    state["lot_reconciliation_block_actions"] = ["sell", "do_t"] if lot_errors else []
    state["_updated"] = (live_quotes or {}).get("_updated") or effective_at
    anchor_source = anchor.get("source", "recovery")
    anchor_positions = anchor.get("positions") or []
    state["anchor"] = {
        "date": anchor["date"],
        "effective_at": anchor["effective_at"],
        "trade_id_cutoff": anchor.get("trade_id_cutoff", 0),
        "source": anchor_source,
    }
    state["anchor_trusted"] = (anchor_source in ("previous_close", "manual_correction")
                               or (anchor_source == "recovery" and len(anchor_positions) == 0))
    return state
