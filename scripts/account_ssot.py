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


def _quotes_are_current(quotes, now=None):
    updated = (quotes or {}).get("_updated")
    if not updated:
        return False
    try:
        quote_time = datetime.fromisoformat(updated)
        ref_time = datetime.fromisoformat(now) if now else datetime.now(quote_time.tzinfo)
        if quote_time.tzinfo and not ref_time.tzinfo:
            ref_time = ref_time.replace(tzinfo=quote_time.tzinfo)
        elif ref_time.tzinfo and not quote_time.tzinfo:
            quote_time = quote_time.replace(tzinfo=ref_time.tzinfo)
        return 0 <= (ref_time - quote_time).total_seconds() <= 300
    except (TypeError, ValueError):
        return False


def reduce_account_state(anchor, trades, quotes, now=None, fund_events=None):
    """Replay post-anchor trades and fund events; value open holdings with live quotes."""
    positions = _open_positions(anchor.get("positions", []))
    by_code = {str(position.get("代码", "")): position for position in positions}
    cash = _number(anchor.get("cash"))
    effective_at = str(anchor.get("effective_at") or "")
    trade_id_cutoff = anchor.get("trade_id_cutoff")

    def event_order_trade(trade):
        return (_event_timestamp(trade), int(trade.get("id") or 0))

    # 1. 重放交易流水
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
        cash += trade_cash_effect(trade)
        position = by_code.get(code)
        action = str(trade.get("action", ""))
        if "卖出" in action:
            if position:
                position["数量"] = max(0, int(position.get("数量", 0)) - qty)
        elif "买入" in action or "追涨" in action:
            if not position:
                position = {
                    "标的": trade.get("name", ""),
                    "代码": code,
                    "数量": 0,
                    "成本": _number(trade.get("price")),
                    "现价": _number(trade.get("price")),
                    "状态": "持有",
                }
                positions.append(position)
                by_code[code] = position
            old_qty = int(position.get("数量", 0))
            old_cost = _number(position.get("成本"))
            new_qty = old_qty + qty
            if new_qty:
                position["成本"] = round(
                    (old_cost * old_qty + _number(trade.get("price")) * qty) / new_qty, 2
                )
            position["数量"] = new_qty

    # 2. 重放资金事件
    for event in sorted(fund_events or [], key=lambda e: (str(e.get("event_date", "")), int(e.get("id") or 0))):
        event_date = str(event.get("event_date", ""))
        if effective_at and event_date < effective_at[:10]:
            continue
        cash += _fund_event_cash_effect(event)

    positions = [position for position in positions if int(position.get("数量", 0)) > 0]
    mv = 0
    valuation_complete = not positions or _quotes_are_current(quotes, now)
    for position in positions:
        quote = (quotes or {}).get(str(position.get("代码", "")), {})
        price = _number(quote.get("最新价"))
        if price <= 0:
            valuation_complete = False
            price = _number(position.get("现价")) or _number(position.get("成本"))
        position["现价"] = price
        mv += round(price * int(position["数量"]))

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
        "valuation_complete": valuation_complete,
    }


def update_account_baseline_meta(date_str, meta, update_anchor=None):
    """追加或更新锚点的 _meta 结算信息（收盘日结用）。"""
    if update_anchor is None:
        from scripts.db import insert_account_baseline, _exec_write
        _exec_write(
            "UPDATE account_baselines SET _meta_json = ? WHERE date = ?",
            (json.dumps(meta, ensure_ascii=False), date_str)
        )
    else:
        from scripts.db import _exec_write
        _exec_write(
            "UPDATE account_baselines SET _meta_json = ? WHERE date = ?",
            (json.dumps(meta, ensure_ascii=False), date_str)
        )


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
    from scripts.db import query_account_baseline, query_trades, query_fund_events, insert_daily_summary
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

    inserted = insert_anchor({
        "date": next_str,
        "effective_at": f"{next_str}T09:25:00",
        "trade_id_cutoff": 0,
        "cash": state["cash"],
        "day_start_asset": state["total_asset"],
        "total_deposit": state["total_deposit"],
        "positions": state["positions"],
        "source": "previous_close",
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

    # 无锚点时从 data 新建（仅用于事故恢复或首次初始化）
    pnl = (data or {}).get("pnl", {})
    anchor = {
        "date": date_str,
        "effective_at": effective_at,
        "trade_id_cutoff": get_last_trade_id(date_str),
        "cash": _number(pnl.get("可用资金")),
        "day_start_asset": _number(day_start_asset),
        "total_deposit": _number(pnl.get("累计入金")),
        "positions": _open_positions((data or {}).get("positions", [])),
        "source": "recovery",
    }
    insert_anchor(anchor)
    return get_anchor(date_str) or anchor


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
    trades = query_trades(date_from=date_str, date_to=date_str, limit=10000)
    fund_events = query_fund_events(date_from=date_str, date_to=date_str, limit=10000)
    state = reduce_account_state(anchor, trades, live_quotes or {}, now=effective_at, fund_events=fund_events)
    state["trades"] = sorted(trades, key=lambda trade: (_event_timestamp(trade), int(trade.get("id") or 0)))
    state["_updated"] = (live_quotes or {}).get("_updated") or effective_at
    state["anchor"] = {
        "date": anchor["date"],
        "effective_at": anchor["effective_at"],
        "trade_id_cutoff": anchor.get("trade_id_cutoff", 0),
        "source": anchor.get("source", "recovery"),
    }
    return state
