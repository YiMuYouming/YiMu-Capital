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


def _finding(code, scope, message, **evidence):
    return {"code": code, "scope": scope, "message": message, "evidence": evidence}


def evaluate_rule_state(inputs, now=None):
    now = now or datetime.now()
    account = inputs.get("account") or {}
    risk = inputs.get("risk") or {}
    style = inputs.get("style") or {}
    sentiment = inputs.get("sentiment") or {}
    freshness = inputs.get("freshness") or {}

    pnl_pct = _number(account.get("pnl_pct"))
    valuation_complete = account.get("valuation_complete") is True
    loss_streak = int(_number(risk.get("loss_streak")) or 0)
    score = _number(style.get("score"))
    lianban_pct = _number(style.get("lianban_pct")) or 0
    trend_pct = _number(style.get("trend_pct")) or 0
    emotion = _number(sentiment.get("emotion_pct"))
    previous_emotion = _number(sentiment.get("previous_emotion_pct"))
    limit_up_profit = _number(sentiment.get("limit_up_profit_pct"))
    broken_board = _number(sentiment.get("broken_board_pct"))
    promotion = _number(sentiment.get("promotion_pct"))

    blocks = []
    warnings = []
    base_cap = base_total_cap(score)
    total_cap = base_cap

    # ── 数据可信度 ──
    if pnl_pct is None or not valuation_complete or freshness.get("quotes") in ("stale", "dead"):
        blocks.append(_finding(
            "DATA_UNTRUSTED", "all", "账户估值或行情数据不可信",
            pnl_pct=pnl_pct,
            valuation_complete=valuation_complete,
            quotes_freshness=freshness.get("quotes"),
        ))

    required_sentiment = {
        "emotion_pct": emotion,
        "limit_up_profit_pct": limit_up_profit,
        "broken_board_pct": broken_board,
        "promotion_pct": promotion,
    }
    missing_sentiment = sorted(key for key, value in required_sentiment.items() if value is None)
    if freshness.get("sentiment") in ("stale", "dead") or missing_sentiment:
        blocks.append(_finding(
            "SENTIMENT_STALE", "all", "情绪数据不完整或过期",
            sentiment_freshness=freshness.get("sentiment"),
            missing=missing_sentiment,
        ))

    # ── 全局风控 ──
    if pnl_pct is not None and pnl_pct <= -3.0:
        blocks.append(_finding("DAY_STOP", "all", "单日熔断触发",
                               pnl_pct=pnl_pct, min_pct=-3.0))
    if loss_streak >= 2:
        blocks.append(_finding("LOSS_STREAK", "all", "连亏触发强制空仓",
                               loss_streak=loss_streak, max_days=2))
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

    # ── 周五 ──
    if now.weekday() == 4:
        blocks.append(_finding("FRIDAY_W1", "w1", "周五关闭 W1", weekday="周五"))
        if trend_pct > 15:
            trend_pct = 15
            blocks.append(_finding("FRIDAY_TREND_CAP", "position", "周五趋势占比上限 15%",
                                   trend_pct=style.get("trend_pct"), max_pct=15))

    # ── W1 窗口 ──
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
    if emotion is not None and emotion < 20:
        blocks.append(_finding("W2_ICE", "w2", "W2 冰点禁止买入",
                               emotion_pct=emotion, min_pct=20))
    if broken_board is not None and broken_board > 40:
        blocks.append(_finding("W2_BROKEN_BOARD", "w2", "炸板率超过 W2 上限",
                               broken_board_pct=broken_board, max_pct=40))

    # ── 整理输出 ──
    globally_blocked = any(item["scope"] == "all" for item in blocks)
    if globally_blocked:
        total_cap = 0
        lianban_pct = 0
        trend_pct = 0

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
            "total_pct": total_cap,
            "lianban_pct": lianban_pct,
            "trend_pct": trend_pct,
            "first_entry_pct": 0 if globally_blocked else 10,
        },
        "windows": {
            "w1": {"in_session": in_w1, "buy_allowed": in_w1 and not w1_blocks, "blocks": w1_blocks},
            "w2": {"in_session": in_w2, "buy_allowed": in_w2 and not w2_blocks, "blocks": w2_blocks},
        },
        "blocks": blocks,
        "warnings": warnings,
    }
