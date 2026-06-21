#!/usr/bin/env python3
"""rule_engine.py — 实时规则引擎 v1（Gate 1A 冻结）
Pure function; no I/O, no global cache, no file/db access.
"""
from datetime import datetime

RULE_VERSION = "g1a-v1"


def _number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def base_total_cap(score):
    score = _number(score)
    if score is not None and score >= 80:
        return 60
    if score is not None and score >= 60:
        return 50
    if score is not None and score >= 40:
        return 40
    return 20


def lianban_side_cap(emotion):
    """Vault Core-连板 §L3.1：连板侧按大盘情绪阶段给仓位上限。"""
    emotion = _number(emotion)
    if emotion is None:
        return 0
    if emotion < 20:
        return 0
    if emotion < 40:
        return 40
    if emotion < 80:
        return 60
    return 0


def trend_side_cap(trend_score=None, score=None):
    """Vault Core-趋势 §T7.1 的简化映射。

    当前管线没有完整的板块20日线/方向确认结构化字段，先用风格检测
    维度三分数近似趋势强度：弱=20，中=40，强=60。
    """
    trend_score = _number(trend_score)
    if trend_score is not None:
        if trend_score >= 18:
            return 60
        if trend_score >= 10:
            return 40
        return 20
    score = _number(score)
    if score is not None and score >= 60:
        return 40
    return 20


def _finding(code, scope, message, **evidence):
    return {"code": code, "scope": scope, "message": message, "evidence": evidence}


def _opposite_sign(a, b):
    if a is None or b is None:
        return False
    if a == 0 or b == 0:
        return False
    return (a > 0) != (b > 0)


def _boolish(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in ("1", "true", "yes", "y", "on", "是", "确认", "已确认")


def _pct(value, default=0, low=0, high=100):
    number = _number(value)
    if number is None:
        number = default
    number = max(low, min(high, number))
    return int(number) if float(number).is_integer() else round(number, 2)


def _position_pnl_pct(position):
    for key in ("floating_pnl_pct", "total_pnl_pct", "today_pnl_pct", "浮盈%", "浮盈pct", "pnl_pct"):
        number = _number((position or {}).get(key))
        if number is not None:
            return number
    price = _number((position or {}).get("price")) or _number((position or {}).get("现价"))
    cost = _number((position or {}).get("cost")) or _number((position or {}).get("成本"))
    if price is not None and cost and cost > 0:
        return (price - cost) / cost * 100
    return None


def _target_single_cap(target_role=None, target_is_mainline=False):
    role = str(target_role or "").lower()
    if not _boolish(target_is_mainline):
        return 10
    if any(key in role for key in ("leader", "unique", "dragon", "龙头", "唯一", "高度")):
        return 30
    if any(key in role for key in ("capacity", "core", "strong_trend", "trend_core", "容量", "中军", "强趋势", "核心")):
        return 25
    return 20


def _profitable_mainline_count(position_control, mainline_confirmed):
    explicit = _number((position_control or {}).get("profitable_mainline_positions"))
    if explicit is not None:
        return max(0, int(explicit))
    count = 0
    for position in (position_control or {}).get("positions") or []:
        is_mainline = position.get("is_mainline")
        if is_mainline is False:
            continue
        if is_mainline is None and not mainline_confirmed:
            continue
        pnl_pct = _position_pnl_pct(position)
        if pnl_pct is not None and pnl_pct > 0:
            count += 1
    return count


def _earned_cap(position_control, mainline_confirmed, profitable_count):
    explicit = _number((position_control or {}).get("earned_cap_pct"))
    if explicit is not None:
        return _pct(explicit)
    if not mainline_confirmed:
        return 10
    if profitable_count <= 0:
        return 20
    if profitable_count == 1:
        return 40
    if profitable_count == 2:
        return 60
    return 80 if _boolish((position_control or {}).get("protection_raised")) else 60


def _opportunity_cap(position_control, base_cap, mainline_confirmed):
    pc = position_control or {}
    explicit = _number(pc.get("opportunity_cap_pct"))
    cap = explicit if explicit is not None else base_cap
    if _boolish(pc.get("market_breadth_polarization")) and not mainline_confirmed:
        cap = min(cap, 10)
    return _pct(cap)


def _floating_loss_add_blocked(position_control, mainline_confirmed, profitable_count):
    pc = position_control or {}
    target_pnl = _number(pc.get("target_floating_pnl_pct"))
    if target_pnl is None:
        target_pnl = _number(pc.get("target_pnl_pct"))
    if target_pnl is not None and target_pnl < 0:
        return True
    if profitable_count > 0:
        return False
    for position in pc.get("positions") or []:
        is_mainline = position.get("is_mainline")
        if is_mainline is False:
            continue
        if is_mainline is None and not mainline_confirmed:
            continue
        pnl_pct = _position_pnl_pct(position)
        if pnl_pct is not None and pnl_pct < 0:
            return True
    return False


def _position_control_caps(position_control, base_cap, current_total_cap, globally_blocked):
    pc = position_control or {}
    enabled = _boolish(pc.get("enabled"))
    current_position_pct = _pct(pc.get("current_position_pct"), 0)
    target_is_mainline = _boolish(pc.get("target_is_mainline", pc.get("mainline_confirmed")))
    single_cap = _target_single_cap(pc.get("target_role"), target_is_mainline)
    common = {
        "account_cap_pct": 0 if globally_blocked else _pct(pc.get("account_cap_pct"), current_total_cap),
        "opportunity_cap_pct": 0 if globally_blocked else _pct(pc.get("opportunity_cap_pct"), current_total_cap),
        "earned_cap_pct": 0 if globally_blocked else current_total_cap,
        "current_position_pct": current_position_pct,
        "available_add_pct": 0 if globally_blocked else max(0, _pct(current_total_cap) - current_position_pct),
        "single_stock_cap_pct": 0,
        "add_step_pct": 0 if globally_blocked else _pct(pc.get("add_step_pct"), 10),
        "max_positions": int(_number(pc.get("max_positions")) or 3),
        "max_mixed_positions": int(_number(pc.get("max_mixed_positions")) or 5),
        "profitable_mainline_positions": 0,
        "mainline_confirmed": False,
        "market_breadth_polarization": _boolish(pc.get("market_breadth_polarization")),
        "add_allowed": False if globally_blocked else current_total_cap > current_position_pct,
        "add_block_reason": "",
        "position_control_mode": "legacy",
    }
    if not enabled:
        return current_total_cap, common

    mainline_confirmed = _boolish(pc.get("mainline_confirmed"))
    profitable_count = _profitable_mainline_count(pc, mainline_confirmed)
    earned_cap = 0 if globally_blocked else _earned_cap(pc, mainline_confirmed, profitable_count)
    account_cap = 0 if globally_blocked else _pct(pc.get("account_cap_pct"), 80)
    opportunity_cap = 0 if globally_blocked else _opportunity_cap(pc, base_cap, mainline_confirmed)
    final_cap = 0 if globally_blocked else min(account_cap, opportunity_cap, earned_cap)
    floating_loss_blocked = not globally_blocked and _floating_loss_add_blocked(pc, mainline_confirmed, profitable_count)
    available_add = max(0, final_cap - current_position_pct)
    if floating_loss_blocked:
        available_add = 0

    common.update({
        "account_cap_pct": account_cap,
        "opportunity_cap_pct": opportunity_cap,
        "earned_cap_pct": earned_cap,
        "available_add_pct": available_add,
        "single_stock_cap_pct": single_cap,
        "profitable_mainline_positions": profitable_count,
        "mainline_confirmed": mainline_confirmed,
        "add_allowed": available_add > 0,
        "add_block_reason": "floating_loss" if floating_loss_blocked else "",
        "position_control_mode": "earned_mainline",
    })
    return final_cap, common


def evaluate_rule_state(inputs, now=None):
    now = now or datetime.now()
    account = inputs.get("account") or {}
    risk = inputs.get("risk") or {}
    style = inputs.get("style") or {}
    sentiment = inputs.get("sentiment") or {}
    funds = inputs.get("funds") or {}
    freshness = inputs.get("freshness") or {}
    time_window = inputs.get("time_window") or {}
    position_control = inputs.get("position_control") or {}

    legacy_pnl_pct = _number(account.get("pnl_pct"))
    account_day_return_pct = _number(account.get("account_day_return_pct"))
    if account_day_return_pct is None:
        account_day_return_pct = legacy_pnl_pct
    trade_return_pct = _number(account.get("trade_return_pct"))
    valuation_complete = account.get("valuation_complete") is True
    losing_account_days_raw = _number(risk.get("losing_account_days"))
    if losing_account_days_raw is None:
        losing_account_days_raw = _number(risk.get("loss_streak"))
    loss_streak = int(losing_account_days_raw or 0)
    loss_streak_hard_stop = risk.get("loss_streak_hard_stop") is not False
    weekly_drawdown = _number(risk.get("weekly_drawdown_pct"))
    monthly_drawdown = _number(risk.get("monthly_drawdown_pct"))
    score = _number(style.get("score"))
    style_score_raw = _number(style.get("style_score_raw"))
    style_score_adjusted = _number(style.get("style_score_adjusted"))
    adjustment_reason = str(style.get("adjustment_reason") or "").strip()
    style_approver = str(style.get("approver") or "").strip()
    style_script_version = str(style.get("script_version") or "").strip()
    lianban_pct = _number(style.get("lianban_pct")) or 0
    trend_pct = _number(style.get("trend_pct")) or 0
    trend_score = _number(style.get("trend_score"))
    emotion = _number(sentiment.get("emotion_pct"))
    previous_emotion = _number(sentiment.get("previous_emotion_pct"))
    limit_up_profit = _number(sentiment.get("limit_up_profit_pct"))
    broken_board = _number(sentiment.get("broken_board_pct"))
    promotion = _number(sentiment.get("promotion_pct"))
    lianban_risk = _number(sentiment.get("lianban_risk"))
    main_inflow = _number(funds.get("main_inflow"))
    dde_big_order_net = _number(funds.get("dde_big_order_net"))

    blocks = []
    warnings = []
    lb_side_cap = lianban_side_cap(emotion)
    tr_side_cap = trend_side_cap(trend_score, score)
    base_cap = max(lb_side_cap, tr_side_cap)
    total_cap = base_cap

    # ── 数据可信度 ──
    if account_day_return_pct is None or not valuation_complete or freshness.get("quotes") == "dead":
        blocks.append(_finding(
            "DATA_UNTRUSTED", "all", "账户估值或行情数据不可信",
            account_day_return_pct=account_day_return_pct,
            pnl_pct=legacy_pnl_pct,
            valuation_complete=valuation_complete,
            quotes_freshness=freshness.get("quotes"),
        ))
    elif freshness.get("quotes") == "stale":
        warnings.append(_finding(
            "QUOTE_STALE", "position", "行情短暂延迟，按最新账户估值提示",
            quotes_freshness=freshness.get("quotes"),
        ))

    required_sentiment = {
        "emotion_pct": emotion,
        "limit_up_profit_pct": limit_up_profit,
        "broken_board_pct": broken_board,
        "promotion_pct": promotion,
    }
    missing_sentiment = sorted(key for key, value in required_sentiment.items() if value is None)
    if missing_sentiment:
        blocks.append(_finding(
            "SENTIMENT_STALE", "all", "情绪数据不完整或过期",
            sentiment_freshness=freshness.get("sentiment"),
            missing=missing_sentiment,
        ))
    elif freshness.get("sentiment") in ("stale", "dead"):
        warnings.append(_finding(
            "SENTIMENT_STALE", "position", "情绪数据延迟，按最新基线值提示",
            sentiment_freshness=freshness.get("sentiment"),
        ))

    if _opposite_sign(main_inflow, dde_big_order_net):
        blocks.append(_finding(
            "DATA-FUNDS-001", "all", "主力净流入与 DDE 大单净额方向冲突，资金证据不得授权买入",
            main_inflow=main_inflow,
            dde_big_order_net=dde_big_order_net,
            source=funds.get("source"),
            query=funds.get("query"),
        ))

    if style_score_adjusted is not None:
        missing_style_audit = []
        if style_score_raw is None:
            missing_style_audit.append("style_score_raw")
        if not adjustment_reason:
            missing_style_audit.append("adjustment_reason")
        if not style_approver:
            missing_style_audit.append("approver")
        if not style_script_version:
            missing_style_audit.append("script_version")
        if missing_style_audit:
            blocks.append(_finding(
                "STYLE-SCORE-AUDIT-001", "all", "风格分数手动修正缺少可审计字段",
                style_score_raw=style_score_raw,
                style_score_adjusted=style_score_adjusted,
                missing=missing_style_audit,
            ))

    # ── 全局风控 ──
    if account_day_return_pct is not None and account_day_return_pct <= -3.0:
        blocks.append(_finding("DAY_STOP", "all", "单日熔断触发",
                               account_day_return_pct=account_day_return_pct,
                               pnl_pct=legacy_pnl_pct,
                               trade_return_pct=trade_return_pct,
                               min_pct=-3.0))
    if loss_streak >= 2 and loss_streak_hard_stop:
        blocks.append(_finding("LOSS_STREAK", "all", "连亏触发强制空仓",
                               losing_account_days=loss_streak,
                               loss_streak=loss_streak,
                               max_days=2))
    elif loss_streak >= 2:
        warnings.append(_finding("LOSS_STREAK", "position", "连亏计数提示，盘前预案已覆盖",
                                 losing_account_days=loss_streak,
                                 loss_streak=loss_streak,
                                 max_days=2))
    if weekly_drawdown is not None and weekly_drawdown <= -6:
        blocks.append(_finding("WEEK_STOP", "all", "周回撤触发当周停止",
                               weekly_drawdown_pct=weekly_drawdown, max_drawdown_pct=-6))
    if monthly_drawdown is not None and monthly_drawdown <= -10:
        blocks.append(_finding("MONTH_STOP", "all", "月回撤触发当月停止",
                               monthly_drawdown_pct=monthly_drawdown, max_drawdown_pct=-10))
    if emotion is not None and previous_emotion is not None and emotion < 20 and previous_emotion < 20:
        blocks.append(_finding("DOUBLE_ICE", "all", "连续双冰禁止新开仓",
                               emotion_pct=emotion, previous_emotion_pct=previous_emotion, max_pct=20))
    if emotion is not None and emotion >= 85:
        blocks.append(_finding("CLIMAX_STOP", "all", "极端高潮禁止新开仓",
                               emotion_pct=emotion, min_pct=85))
    elif emotion is not None and emotion >= 80:
        total_cap = base_cap // 2
        warnings.append(_finding("CLIMAX_REDUCE", "position", "高潮保护降半仓",
                                 emotion_pct=emotion, min_pct=80, reduced_total_pct=total_cap))

    # ── W1 窗口 ──
    if lb_side_cap == 0 and lianban_pct > 0:
        blocks.append(_finding("LIANBAN_SIDE_CLOSED", "lianban", "连板侧仓位关闭",
                               emotion_pct=emotion, side_cap_pct=lb_side_cap))
    if emotion is not None and emotion < 35:
        blocks.append(_finding("WIN-ICE-W1-001", "w1", "冰点禁止 W1 新开仓，附加条件不能重新开放",
                               emotion_pct=emotion, max_pct=35,
                               main_inflow=main_inflow,
                               volume_ratio=funds.get("volume_ratio")))
    if emotion is not None and emotion < 60:
        blocks.append(_finding("W1_EMOTION", "w1", "W1 情绪不足",
                               emotion_pct=emotion, min_pct=60))
    if limit_up_profit is not None and limit_up_profit <= 2:
        blocks.append(_finding("W1_LIMIT_UP_PROFIT", "w1", "W1 涨停收益不足",
                               limit_up_profit_pct=limit_up_profit, min_pct=2))
    if broken_board is not None and broken_board > 30:
        blocks.append(_finding("W1_BROKEN_BOARD", "w1", "炸板率超过 W1 上限",
                               broken_board_pct=broken_board, max_pct=30))
    if emotion is not None and promotion is not None:
        promotion_min = 15 if emotion < 40 else 18
        if promotion < promotion_min:
            blocks.append(_finding("W1_PROMOTION", "w1", "W1 晋级率不足",
                                   promotion_pct=promotion, min_pct=promotion_min))

    # ── W2 窗口 ──
    if emotion is not None and emotion < 20 and (lianban_risk is None or lianban_risk >= 0.5):
        blocks.append(_finding("W2_ICE_RISK", "w2", "W2 冰点风险过高",
                               emotion_pct=emotion, lianban_risk=lianban_risk, max_risk=0.5))
    if broken_board is not None and broken_board > 40:
        blocks.append(_finding("W2_BROKEN_BOARD", "w2", "炸板率超过 W2 上限",
                               broken_board_pct=broken_board, max_pct=40))

    # ── 整理输出 ──
    globally_blocked = any(item["scope"] == "all" for item in blocks)
    lianban_closed = any(item["scope"] == "lianban" for item in blocks)
    if lianban_closed and not globally_blocked and lianban_pct > 0:
        trend_pct = 100
        lianban_pct = 0
    if globally_blocked:
        total_cap = 0
        lianban_pct = 0
        trend_pct = 0
    total_cap, position_caps = _position_control_caps(position_control, base_cap, total_cap, globally_blocked)

    w1_blocks = [item["code"] for item in blocks if item["scope"] in ("all", "w1")]
    w2_blocks = [item["code"] for item in blocks if item["scope"] in ("all", "w2")]

    in_w1 = (now.replace(hour=9, minute=30, second=0, microsecond=0) <= now <
             now.replace(hour=10, minute=1, second=0, microsecond=0))
    in_w2 = (now.replace(hour=14, minute=0, second=0, microsecond=0) <= now <
             now.replace(hour=14, minute=51, second=0, microsecond=0))

    regime = "unknown" if emotion is None else (
        "冰点" if emotion < 20 else "低迷" if emotion < 40 else
        "主升" if emotion < 60 else "强势" if emotion < 80 else "高潮"
    )

    return {
        "version": RULE_VERSION,
        "evaluated_at": now.isoformat(timespec="seconds"),
        "tradable": not globally_blocked,
        "market_regime": regime,
        "caps": {
            "base_total_pct": base_cap,
            "lianban_side_cap_pct": lb_side_cap,
            "trend_side_cap_pct": tr_side_cap,
            "total_pct": total_cap,
            "lianban_pct": lianban_pct,
            "trend_pct": trend_pct,
            "first_entry_pct": 0 if globally_blocked else 10,
            **position_caps,
        },
        "windows": {
            "w1": {"in_session": in_w1, "buy_allowed": in_w1 and not w1_blocks, "blocks": w1_blocks},
            "w2": {"in_session": in_w2, "buy_allowed": in_w2 and not w2_blocks, "blocks": w2_blocks},
        },
        "blocks": blocks,
        "warnings": warnings,
    }
