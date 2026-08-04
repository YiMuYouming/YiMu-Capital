#!/usr/bin/env python3
"""rule_engine.py — 实时规则引擎 v1（Gate 1A 冻结）
Pure function; no I/O, no global cache, no file/db access.
"""
from datetime import datetime

RULE_VERSION = "g1a-v1"

POS_SIZE_008_FIELDS = (
    "entry_leg",
    "first_entry_trade_date",
    "trading_days_since_first_entry",
    "leg1_or_leg2_floating_pnl",
    "leg2_already_used",
    "volume_ratio",
    "pullback_ma_status",
    "sector_inflow_status",
    "sector_inflow_query_time",
    "planned_single_stock_cap_pct",
    "current_single_stock_pct",
    "acceleration_segment_confirmed",
)


def _number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def base_total_cap(score):
    """Legacy display helper; never use this table as final position authority."""
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


def trend_side_cap(market_trend_20d_direction, trend_score=None, score=None):
    """Vault Core-趋势 §T1/T7.1：方向先行，向下或缺失时趋势侧为零。"""
    if market_trend_20d_direction not in {"向上", "走平"}:
        return 0
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


def evaluate_position_evidence(action_type, evidence):
    """Evaluate POS-SIZE-008 evidence for entry actions without inventing facts."""
    action = str(action_type or "").strip().lower()
    if action not in {"buy", "add", "do_t"}:
        return {"allowed": True, "code": None, "missing_fields": [], "blocking_reasons": []}
    evidence = evidence if isinstance(evidence, dict) else {}
    missing = [field for field in POS_SIZE_008_FIELDS if evidence.get(field) is None or evidence.get(field) == ""]
    reasons = []
    if missing:
        return {
            "allowed": False,
            "code": "POS-SIZE-008",
            "missing_fields": missing,
            "blocking_reasons": ["missing_evidence"],
        }

    leg = int(_number(evidence.get("entry_leg")) or 0)
    days = _number(evidence.get("trading_days_since_first_entry"))
    pnl = _number(evidence.get("leg1_or_leg2_floating_pnl"))
    volume_ratio = _number(evidence.get("volume_ratio"))
    planned_cap = _number(evidence.get("planned_single_stock_cap_pct"))
    current_pct = _number(evidence.get("current_single_stock_pct"))
    pullback = str(evidence.get("pullback_ma_status") or "").strip().lower()
    sector = str(evidence.get("sector_inflow_status") or "").strip().lower()

    if leg not in {1, 2, 3}:
        reasons.append("entry_leg_invalid")
    if action == "add" and leg == 1:
        reasons.append("add_cannot_be_leg1")
    if planned_cap is None or current_pct is None or current_pct >= planned_cap:
        reasons.append("single_stock_cap_reached")
    if _boolish(evidence.get("acceleration_segment_confirmed")) and leg in {2, 3}:
        reasons.append("acceleration_segment_no_add")
    if leg == 2:
        if _boolish(evidence.get("leg2_already_used")):
            reasons.append("leg2_already_used")
        if days is None or days < 0 or days > 2:
            reasons.append("leg2_outside_0_2_trading_days")
        if volume_ratio is None or volume_ratio >= 1:
            reasons.append("leg2_not_volume_contracted")
        if not any(token in pullback for token in ("support", "supported", "企稳", "不破", "ma5", "ma10")):
            reasons.append("leg2_pullback_ma_unconfirmed")
        if sector in {"large_outflow", "大额流出", "outflow", "missing", "unknown", "n"}:
            reasons.append("leg2_sector_inflow_failed")
    if leg == 3 and (pnl is None or pnl <= 0):
        reasons.append("leg3_requires_floating_profit")

    return {
        "allowed": not reasons,
        "code": None if not reasons else "POS-SIZE-008",
        "missing_fields": [],
        "blocking_reasons": reasons,
    }


def _role_side(role):
    text = str(role or "").strip().lower()
    if any(token in text for token in ("lianban", "limit", "leader", "dragon", "连板", "龙头", "高度")):
        return "lianban"
    if any(token in text for token in ("trend", "capacity", "middle", "core", "趋势", "容量", "中军", "核心")):
        return "trend"
    return None


def _role_lianban_layer(role):
    text = str(role or "").strip().lower().replace("→", "to")
    compact = text.replace("_", "").replace("-", "").replace(" ", "")
    for layer, tokens in {
        "1_to_2": ("1to2", "1进2", "一进二"),
        "2_to_3": ("2to3", "2进3", "二进三"),
        "3_to_4": ("3to4", "3进4", "三进四"),
    }.items():
        if any(token in compact for token in tokens):
            return layer
    return None


def classify_source_gap(raw_gap: str) -> dict:
    """Parse a typed source gap without widening its impact scope."""
    raw = str(raw_gap or "").strip()
    parts = raw.split(":")
    token = parts[0].strip().lower() if parts else ""
    result = {
        "raw": raw,
        "scope": "advisory",
        "severity": "advisory",
        "affected_candidate": None,
        "affected_side": None,
        "code": raw,
        "mapped": False,
    }
    if token in {"global_hard", "global_soft", "candidate_hard", "candidate_soft", "side_hard", "side_soft"}:
        scope_name, severity = token.rsplit("_", 1)
        result["scope"] = {
            "global": "global",
            "candidate": "candidate",
            "side": "side",
        }[scope_name]
        result["severity"] = "hard" if severity == "hard" else "soft"
        result["mapped"] = True
        if result["scope"] == "candidate" and len(parts) >= 2:
            result["affected_candidate"] = parts[1].strip()
            result["code"] = ":".join(parts[2:]).strip() or raw
        elif result["scope"] == "side" and len(parts) >= 2:
            result["affected_side"] = parts[1].strip().lower()
            result["code"] = ":".join(parts[2:]).strip() or raw
        else:
            result["code"] = ":".join(parts[1:]).strip() or raw
        return result

    # Existing missing_rule_input values are deliberately not promoted to a
    # global hard gate. A producer must emit an explicit typed mapping first.
    if raw.startswith("missing_rule_input:"):
        result.update({
            "code": raw.split(":", 1)[1] or raw,
            "severity": "soft",
            "mapped": False,
            "requires_explicit_mapping": True,
        })
        return result

    if raw in {"RULE_SNAPSHOT_STALE", "PLAN_NOT_CURRENT"}:
        # A plan/card mismatch invalidates only the execution plan.  It must
        # close buy/add/do_t while leaving recommendation candidates visible.
        # An explicitly typed ``global_hard:...`` value above remains global;
        # only the untyped runtime plan marker gets this narrow meaning.
        result.update({
            "scope": "execution_plan",
            "severity": "hard",
            "code": raw,
            "mapped": True,
        })
    elif raw in {
        "ACCOUNT_TRUST_FAILED",
        "QUOTE_DEAD",
        "SYSTEM_RISK",
        "T1_INTEGRITY_ERROR",
    }:
        result.update({
            "scope": "global",
            "severity": "hard",
            "code": raw,
            "mapped": True,
        })
    return result


def _candidate_side(candidate):
    value = (candidate or {}).get("side") or (candidate or {}).get("source")
    side = str(value or "").strip().lower()
    if side in {"trend", "lianban"}:
        return side
    return _role_side((candidate or {}).get("role") or value)


def _recommendation_gap_matches(gap, candidate_code, candidate_side):
    if gap["scope"] == "global":
        return True
    if gap["scope"] == "candidate":
        return str(gap.get("affected_candidate") or "").strip() == candidate_code
    if gap["scope"] == "side":
        return str(gap.get("affected_side") or "").strip().lower() == candidate_side
    return False


def evaluate_recommendation_candidate(candidate: dict, health: dict, rule_state: dict) -> dict:
    """Evaluate advice eligibility independently from the execution gate."""
    item = candidate if isinstance(candidate, dict) else {}
    code = str(item.get("code") or item.get("代码") or "").strip()
    side = _candidate_side(item)
    raw_gaps = []
    for value in (item.get("source_gaps") or [], (rule_state or {}).get("source_gaps") or [], (health or {}).get("source_gaps") or []):
        if isinstance(value, (list, tuple)):
            raw_gaps.extend(str(gap) for gap in value if str(gap).strip())
        elif value:
            raw_gaps.append(str(value))
    parsed_gaps = [classify_source_gap(gap) for gap in dict.fromkeys(raw_gaps)]
    applicable_gaps = [
        gap
        for gap in parsed_gaps
        if gap["scope"] == "advisory"
        or _recommendation_gap_matches(gap, code, side)
    ]
    blocking = [
        gap["code"]
        for gap in applicable_gaps
        if gap["severity"] == "hard"
    ]
    missing_evidence = [
        gap["raw"]
        for gap in applicable_gaps
        if gap["severity"] != "hard"
    ]

    for block in (rule_state or {}).get("blocks") or []:
        if not isinstance(block, dict):
            continue
        block_code = str(block.get("code") or "").strip()
        block_scope = str(block.get("scope") or "").strip().lower()
        if not block_code:
            continue
        # ``entry`` is the legacy buy-side execution scope. It must not erase
        # an otherwise useful paper recommendation; only explicit global/all
        # blocks are recommendation-wide hard blocks.
        if block_scope in {"all", "global"}:
            blocking.append(block_code)
        elif block_scope in {"trend", "lianban"} and block_scope == side:
            blocking.append(block_code)
        elif str(block.get("candidate") or block.get("code_value") or "").strip() == code:
            blocking.append(block_code)

    plan_valid = (rule_state or {}).get("execution_plan_valid")
    if plan_valid is None:
        plan_valid = not any(
            gap["scope"] == "execution_plan" and gap["severity"] == "hard"
            for gap in parsed_gaps
        )
    blocking = list(dict.fromkeys(blocking))
    missing_evidence = list(dict.fromkeys(missing_evidence))
    execution_allowed = (
        bool((health or {}).get("trade_entry_allowed", False))
        and bool(plan_valid)
        and not blocking
    )
    if blocking:
        disposition = "blocked"
    elif not execution_allowed:
        disposition = "paper_only"
    elif missing_evidence:
        disposition = "guarded_experiment"
    else:
        disposition = "standard"
    result = {
        "code": code,
        "side": side,
        "eligible": not blocking,
        "execution_allowed": execution_allowed,
        "execution_plan_valid": bool(plan_valid),
        "blocking_codes": blocking,
        "missing_evidence": missing_evidence,
        "source_gaps": [gap["raw"] for gap in applicable_gaps],
        "disposition": disposition,
    }
    if any(key in item for key in ("position", "risk_action", "sell_action")):
        position = dict(item.get("position") or {})
        for key in ("quantity", "qty", "sellable_qty", "t1_locked", "risk_action", "sell_action", "trigger", "evidence", "rule_ids"):
            if key not in position and key in item:
                position[key] = item[key]
        result["sell_action"] = build_sell_action(
            position,
            buy_side_source_gaps=raw_gaps,
        )
    return result


def build_recommendation_state(candidates: list[dict], health: dict, rule_state: dict) -> dict:
    """Build recommendation_state.v1 beside, never inside, decision_gate.v1."""
    values = candidates if isinstance(candidates, list) else []
    evaluated = [evaluate_recommendation_candidate(item, health or {}, rule_state or {}) for item in values]
    for original, result in zip(values, evaluated):
        if isinstance(original, dict):
            result.update({
                key: original.get(key)
                for key in ("name", "sector", "role", "source", "setup", "trigger", "invalidation")
                if key in original
            })
    has_eligible = any(item.get("eligible") for item in evaluated)
    guarded = any(item.get("disposition") == "guarded_experiment" for item in evaluated)
    status = "guarded" if guarded else ("ranked" if has_eligible else "blocked")
    execution_allowed = bool((health or {}).get("trade_entry_allowed", False)) and any(
        item.get("execution_allowed") for item in evaluated
    )
    return {
        "schema_version": "recommendation_state.v1",
        "status": status,
        "execution_allowed": execution_allowed,
        "candidates": evaluated,
        "source_gaps": list(dict.fromkeys(
            item for candidate in evaluated for item in candidate.get("source_gaps") or []
        )),
    }


SELL_ACTIONS = {
    "hold",
    "reduce_one_third",
    "reduce_half",
    "clear",
    "t1_locked_next_open_review",
}


def build_sell_action(position: dict, buy_side_source_gaps=None) -> dict:
    """Map a risk signal to an explicit exit advice without using buy-side gates."""
    item = position if isinstance(position, dict) else {}
    supplied = item.get("sell_action")
    if isinstance(supplied, dict):
        item = {**supplied, **item}
        item.pop("sell_action", None)
    requested = str(
        item.get("risk_action")
        or item.get("sell_action")
        or item.get("action")
        or "hold"
    ).strip().lower()
    aliases = {"reduce": "reduce_one_third", "sell": "clear", "close": "clear"}
    requested = aliases.get(requested, requested)
    if requested not in SELL_ACTIONS:
        requested = "hold"

    quantity = _number(item.get("quantity") or item.get("qty"))
    sellable_raw = item.get("sellable_qty")
    sellable = _number(sellable_raw) if sellable_raw is not None else None
    t1_locked = bool(item.get("t1_locked")) or (
        quantity is not None and quantity > 0 and sellable is not None and sellable <= 0
    )
    if sellable is None:
        sellable_status = "unknown"
    elif t1_locked:
        sellable_status = "t1_locked"
    elif sellable > 0:
        sellable_status = "sellable"
    else:
        sellable_status = "no_position"

    action = requested
    result = {
        "action": action,
        "requested_action": requested,
        "sellable_qty_status": sellable_status,
        "buy_side_source_gaps": list(dict.fromkeys(str(item) for item in (buy_side_source_gaps or []) if str(item).strip())),
        "buy_side_gaps_do_not_block": True,
    }
    if requested != "hold":
        result.update({
            "trigger": item.get("trigger") or item.get("risk_trigger") or item.get("reason") or "",
            "evidence": item.get("evidence") or item.get("risk_evidence") or {},
            "rule_ids": [str(rule_id) for rule_id in (item.get("rule_ids") or item.get("sell_rule_ids") or [])],
        })
    if requested != "hold" and t1_locked:
        result["action"] = "t1_locked_next_open_review"
        result["executable_qty"] = 0
        result["next_open_action"] = requested
    elif requested != "hold":
        result["executable_qty"] = int(sellable) if sellable is not None and float(sellable).is_integer() else sellable
    return result


def evaluate_decision_gate(action_type, window_name, role, entry_leg, health, rule_state):
    """Final action-specific gate. Exit/risk handling ignores buy-only blocks."""
    action = str(action_type or "").strip().lower()
    exits = {"sell", "reduce", "close", "clear"}
    if action in exits:
        return {"allowed": True, "reason": None, "blocking_codes": [], "action_type": action}

    entry_actions = {"buy", "add", "do_t"}
    if action not in entry_actions:
        return {"allowed": True, "reason": None, "blocking_codes": [], "action_type": action}

    rule = rule_state or {}
    codes = []
    if not bool((health or {}).get("trade_entry_allowed", False)):
        codes.append("HEALTH_TRADE_ENTRY_BLOCKED")
    candidate = rule.get("candidate") or {}
    ticket_context = rule.get("ticket_context") or {}
    candidate_code = str(
        (candidate.get("code") if isinstance(candidate, dict) else None)
        or ticket_context.get("candidate_code")
        or rule.get("candidate_code")
        or ""
    ).strip()
    candidate_side = _role_side(role)
    for raw_gap in rule.get("source_gaps") or []:
        gap = classify_source_gap(raw_gap)
        if gap["severity"] != "hard":
            continue
        if gap["scope"] in {"global", "execution_plan"}:
            codes.append(gap["code"])
        elif gap["scope"] == "side" and gap.get("affected_side") == candidate_side:
            codes.append(gap["code"])
        elif (
            gap["scope"] == "candidate"
            and gap.get("affected_candidate") == candidate_code
        ):
            codes.append(gap["code"])
    if rule.get("execution_plan_valid") is False:
        codes.append(str(
            rule.get("execution_plan_reason")
            or (rule.get("execution_plan") or {}).get("stale_reason")
            or "PLAN_NOT_CURRENT"
        ))
    for block in rule.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        if block.get("scope") in {"all", "entry", "execution_plan"} and block.get("code"):
            codes.append(str(block["code"]))
    if rule.get("tradable") is False and not codes:
        codes.append("RULE_STATE_BLOCKED")

    wkey = str(window_name or "").strip().lower()
    window = ((rule.get("windows") or {}).get(wkey) or {}) if wkey else {}
    if not wkey:
        codes.append("WINDOW_REQUIRED")
    else:
        if window.get("in_session") is not True:
            codes.append("WINDOW_CLOSED")
        side = _role_side(role)
        side_allowed = window.get("side_buy_allowed") or {}
        if side and side in side_allowed:
            if side_allowed.get(side) is not True:
                side_blocks = (window.get("side_blocks") or {}).get(side) or []
                codes.extend(str(code) for code in side_blocks)
                if not side_blocks:
                    codes.append(f"{wkey.upper()}_{side.upper()}_BLOCKED")
            if side == "lianban":
                layer = _role_lianban_layer(role)
                layer_allowed = window.get("lianban_layer_buy_allowed") or {}
                if layer and layer_allowed.get(layer) is not True:
                    layer_blocks = (window.get("lianban_layer_blocks") or {}).get(layer) or []
                    codes.extend(str(code) for code in layer_blocks)
                    if not layer_blocks:
                        codes.append(f"{wkey.upper()}_LIANBAN_{layer.upper()}_BLOCKED")
        elif window.get("buy_allowed") is not True:
            codes.extend(str(code) for code in window.get("blocks") or [])
            if not window.get("blocks"):
                codes.append(f"{wkey.upper()}_BUY_BLOCKED")

    if action in {"add", "do_t"} and (rule.get("caps") or {}).get("add_allowed") is False:
        codes.append("POSITION_ADD_BLOCKED")
    position_result = rule.get("position_evidence") or {}
    if position_result.get("allowed") is False:
        codes.append(position_result.get("code") or "POS-SIZE-008")
    if entry_leg is not None and position_result.get("entry_leg") not in (None, entry_leg):
        codes.append("POS_SIZE_ENTRY_LEG_MISMATCH")
    codes.extend(str(code) for code in ((rule.get("t1") or {}).get("blocking_codes") or []))

    codes = list(dict.fromkeys(code for code in codes if code))
    return {
        "allowed": not codes,
        "reason": None if not codes else ",".join(codes),
        "blocking_codes": codes,
        "action_type": action,
        "window_name": wkey or None,
        "role": role,
        "entry_leg": entry_leg,
    }


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


def _position_detail(position, pnl_pct):
    value = round(pnl_pct, 2) if pnl_pct is not None else None
    if value is not None and float(value).is_integer():
        value = int(value)
    return {
        "code": str((position or {}).get("code") or ""),
        "name": str((position or {}).get("name") or ""),
        "pnl_pct": value,
    }


def _profitable_position_details(position_control, mainline_confirmed):
    mainline = []
    non_mainline = []
    for position in (position_control or {}).get("positions") or []:
        pnl_pct = _position_pnl_pct(position)
        if pnl_pct is None or pnl_pct <= 0:
            continue
        is_mainline = position.get("is_mainline")
        if is_mainline is False:
            non_mainline.append(_position_detail(position, pnl_pct))
            continue
        if is_mainline is None and not mainline_confirmed:
            non_mainline.append(_position_detail(position, pnl_pct))
            continue
        mainline.append(_position_detail(position, pnl_pct))
    return mainline, non_mainline


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


def _ice_polar_manual_review_allowed(context, account_day_return_pct):
    """冰点 W1 极化主线黄灯：只做人工复核，不改变 buy_allowed。"""
    ctx = context or {}
    distance = _number(ctx.get("current_price_distance_pct"))
    profitable_mainline_positions = _number(ctx.get("profitable_mainline_positions")) or 0
    sector_fund_flow = _number(ctx.get("sector_fund_flow"))
    mainline_strength = str(ctx.get("mainline_strength") or "").strip().lower()
    strong_mainline = (
        mainline_strength in ("strong", "主线强", "强", "confirmed", "确认")
        or (sector_fund_flow is not None and sector_fund_flow > 0)
    )
    account_or_position_verified = (
        profitable_mainline_positions > 0
        or (account_day_return_pct is not None and account_day_return_pct > 0)
    )
    return (
        _boolish(ctx.get("market_breadth_polarization"))
        and _boolish(ctx.get("mainline_confirmed"))
        and strong_mainline
        and _boolish(ctx.get("core_stock_confirmation"))
        and account_or_position_verified
        and _boolish(ctx.get("pullback_confirmed"))
        and _boolish(ctx.get("intraday_stabilization"))
        and distance is not None
        and distance <= 3
    )


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
        "profitable_mainline_position_details": [],
        "profitable_non_mainline_position_details": [],
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
    profitable_mainline_details, profitable_non_mainline_details = _profitable_position_details(pc, mainline_confirmed)
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
        "profitable_mainline_position_details": profitable_mainline_details,
        "profitable_non_mainline_position_details": profitable_non_mainline_details,
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
    manual_review_context = inputs.get("manual_review_context") or {}
    source_gaps = list(dict.fromkeys(
        list(inputs.get("source_gaps") or []) + list(style.get("source_gaps") or [])
    ))

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
    lianban_pct_raw = _number(style.get("lianban_pct"))
    trend_pct_raw = _number(style.get("trend_pct"))
    lianban_pct = lianban_pct_raw if lianban_pct_raw is not None else 0
    trend_pct = trend_pct_raw if trend_pct_raw is not None else 0
    previous_lianban_pct = _number(style.get("previous_lianban_pct"))
    style_shift_same_direction_days = int(_number(style.get("style_shift_same_direction_days")) or 0)
    trend_score = _number(style.get("trend_score"))
    market_trend_20d_direction = str(
        style.get("market_trend_20d_direction") or ""
    ).strip() or None
    emotion = _number(sentiment.get("emotion_pct"))
    previous_emotion = _number(sentiment.get("previous_emotion_pct"))
    sentiment_basis = "current"
    if emotion is None and previous_emotion is not None:
        emotion = previous_emotion
        sentiment_basis = "previous_close_soft"
        previous_gap = "side_soft:lianban:emotion_previous_close"
        if previous_gap not in source_gaps:
            source_gaps.append(previous_gap)
    limit_up_profit = _number(sentiment.get("limit_up_profit_pct"))
    broken_board = _number(sentiment.get("broken_board_pct"))
    promotion = _number(sentiment.get("promotion_pct"))
    promotion_2_to_3_avg_3d = _number(sentiment.get("promotion_2_to_3_avg_3d"))
    highest_board = _number(sentiment.get("highest_board"))
    limit_up_count_avg_3d = _number(sentiment.get("limit_up_count_avg_3d"))
    promotion_1_to_2_pct = _number(sentiment.get("promotion_1_to_2_pct"))
    promotion_2_to_3_pct = _number(sentiment.get("promotion_2_to_3_pct"))
    promotion_3_to_4_pct = _number(sentiment.get("promotion_3_to_4_pct"))
    emotion_regime = str(sentiment.get("emotion_regime") or "").strip() or None
    auction_emotion = _number(sentiment.get("auction_emotion_pct"))
    lianban_risk = _number(sentiment.get("lianban_risk"))
    main_inflow = _number(funds.get("main_inflow"))
    dde_big_order_net = _number(funds.get("dde_big_order_net"))

    blocks = []
    warnings = []
    parsed_source_gaps = [classify_source_gap(gap) for gap in source_gaps]
    for gap in parsed_source_gaps:
        if gap["severity"] != "hard":
            continue
        if gap["scope"] == "global":
            blocks.append(_finding(gap["code"], "all", "全局硬事实缺口", raw=gap["raw"]))
        elif gap["scope"] == "side" and gap.get("affected_side"):
            blocks.append(_finding(
                gap["code"],
                gap["affected_side"],
                "策略侧硬事实缺口",
                raw=gap["raw"],
            ))
        elif gap["scope"] == "candidate" and gap.get("affected_candidate"):
            blocks.append(_finding(
                gap["code"],
                "candidate",
                "候选硬事实缺口",
                candidate=gap["affected_candidate"],
                raw=gap["raw"],
            ))
    style_shift_buffer = {"active": False}
    if (
        previous_lianban_pct is not None
        and abs(lianban_pct - previous_lianban_pct) > 30
        and style_shift_same_direction_days < 3
    ):
        original_lianban_pct = lianban_pct
        lianban_pct = round((previous_lianban_pct + lianban_pct) / 2, 6)
        trend_pct = round(100 - lianban_pct, 6)
        style_shift_buffer = {
            "active": True,
            "previous_lianban_pct": previous_lianban_pct,
            "current_lianban_pct": original_lianban_pct,
            "buffered_lianban_pct": lianban_pct,
            "buffered_trend_pct": trend_pct,
        }
        blocks.append(_finding(
            "STYLE_SHIFT_BUFFER", "entry", "风格单日变化超过30pp，缓冲期只减仓不新开",
            **style_shift_buffer,
        ))
    lb_side_cap = lianban_side_cap(emotion)
    tr_side_cap = trend_side_cap(market_trend_20d_direction, trend_score, score)
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
    }
    missing_sentiment = sorted(key for key, value in required_sentiment.items() if value is None)
    if missing_sentiment:
        blocks.append(_finding(
            "SENTIMENT_STALE", "lianban", "连板与一进二情绪证据不完整",
            sentiment_freshness=freshness.get("sentiment"),
            missing=missing_sentiment,
            sentiment_basis=sentiment_basis,
        ))
    elif freshness.get("sentiment") in ("stale", "dead"):
        warnings.append(_finding(
            "SENTIMENT_STALE", "lianban", "连板情绪数据延迟，按最新基线值提示",
            sentiment_freshness=freshness.get("sentiment"),
            sentiment_basis=sentiment_basis,
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
    if (
        sentiment_basis == "current"
        and emotion is not None
        and previous_emotion is not None
        and emotion < 20
        and previous_emotion < 20
    ):
        blocks.append(_finding("DOUBLE_ICE", "all", "连续双冰禁止新开仓",
                               emotion_pct=emotion, previous_emotion_pct=previous_emotion, max_pct=20))
    if emotion is not None and emotion > 80:
        blocks.append(_finding("CLIMAX_STOP", "entry", "当前/收盘情绪高潮，只卖不买",
                               emotion_pct=emotion, min_exclusive_pct=80))

    lianban_environment_required = {
        "promotion_2_to_3_avg_3d": promotion_2_to_3_avg_3d,
        "highest_board": highest_board,
        "limit_up_count_avg_3d": limit_up_count_avg_3d,
    }
    missing_lianban_environment = sorted(
        field for field, value in lianban_environment_required.items() if value is None
    )
    if missing_lianban_environment:
        source_gaps.extend(
            f"missing_rule_input:{field}" for field in missing_lianban_environment
        )
        source_gaps = list(dict.fromkeys(source_gaps))
        blocks.append(_finding(
            "LIANBAN_GATE_SOURCE_GAP", "lianban",
            "连板环境关键字段缺失，连板买入侧 fail-closed",
            missing=missing_lianban_environment,
        ))

    lianban_strategy_required = {
        "1_to_2": {
            "promotion_1_to_2_pct": promotion_1_to_2_pct,
            "emotion_regime": emotion_regime,
        },
        "2_to_3": {"promotion_2_to_3_pct": promotion_2_to_3_pct},
        "3_to_4": {"promotion_3_to_4_pct": promotion_3_to_4_pct},
    }
    for layer, fields in lianban_strategy_required.items():
        missing = sorted(field for field, value in fields.items() if value is None)
        if not missing:
            continue
        source_gaps.extend(f"missing_rule_input:{field}" for field in missing)
        source_gaps = list(dict.fromkeys(source_gaps))
        blocks.append(_finding(
            f"LIANBAN_{layer.upper()}_SOURCE_GAP", f"lianban_{layer}",
            "连板策略关键字段缺失，对应板层买入 fail-closed",
            missing=missing,
            layer=layer,
        ))

    environment_triggers = []
    if promotion_2_to_3_avg_3d is not None and promotion_2_to_3_avg_3d < 20:
        environment_triggers.append("promotion_2_to_3_avg_3d<20")
    if highest_board is not None and highest_board <= 2:
        environment_triggers.append("highest_board<=2")
    if limit_up_count_avg_3d is not None and limit_up_count_avg_3d < 30:
        environment_triggers.append("limit_up_count_avg_3d<30")
    if environment_triggers:
        blocks.append(_finding(
            "LIANBAN_ENV_CLOSED", "lianban", "连板环境硬卡触发，关闭连板买入侧",
            promotion_2_to_3_avg_3d=promotion_2_to_3_avg_3d,
            highest_board=highest_board,
            limit_up_count_avg_3d=limit_up_count_avg_3d,
            triggers=environment_triggers,
        ))

    if market_trend_20d_direction == "向下":
        blocks.append(_finding(
            "TREND_DIRECTION_DOWN", "trend", "上证20日线向下，仅关闭趋势买入侧",
            market_trend_20d_direction=market_trend_20d_direction,
        ))
    elif market_trend_20d_direction not in {"向上", "走平"}:
        gap = "missing_rule_input:market_trend_20d_direction"
        if gap not in source_gaps:
            source_gaps.append(gap)
        blocks.append(_finding(
            "TREND_DIRECTION_SOURCE_GAP", "trend",
            "市场20日趋势方向缺失，趋势买入侧 fail-closed",
            market_trend_20d_direction=market_trend_20d_direction,
        ))

    # ── W1 窗口 ──
    if str(time_window.get("w1_status") or "").strip() in {"关闭", "closed", "blocked"}:
        blocks.append(_finding("PLAN_W1_CLOSED", "w1", "执行卡/开盘指令关闭 W1 买入",
                               w1_status=time_window.get("w1_status")))
    if str(time_window.get("w2_status") or "").strip() in {"关闭", "closed", "blocked"}:
        blocks.append(_finding("PLAN_W2_CLOSED", "w2", "执行卡/开盘指令关闭 W2 买入",
                               w2_status=time_window.get("w2_status")))
    if lb_side_cap == 0 and lianban_pct > 0:
        blocks.append(_finding("LIANBAN_SIDE_CLOSED", "lianban", "连板侧仓位关闭",
                               emotion_pct=emotion, side_cap_pct=lb_side_cap))
    if emotion is not None and emotion < 35:
        blocks.append(_finding("WIN-ICE-W1-001", "w1", "冰点 W1 新买入默认关闭",
                               emotion_pct=emotion, max_pct=35,
                               main_inflow=main_inflow,
                               volume_ratio=funds.get("volume_ratio")))
    if limit_up_profit is not None and limit_up_profit <= 2:
        blocks.append(_finding("W1_LIMIT_UP_PROFIT", "w1_lianban", "W1 连板涨停收益不足",
                               limit_up_profit_pct=limit_up_profit, min_pct=2))
    if broken_board is not None and broken_board > 30:
        blocks.append(_finding("W1_BROKEN_BOARD", "w1_lianban", "炸板率超过连板 W1 上限",
                               broken_board_pct=broken_board, max_pct=30))
    one_to_two_threshold = {"低迷": 15, "主升": 18}.get(emotion_regime)
    if (
        one_to_two_threshold is not None
        and promotion_1_to_2_pct is not None
        and promotion_1_to_2_pct <= one_to_two_threshold
    ):
        blocks.append(_finding(
            "LIANBAN_1_TO_2_STRATEGY", "lianban_1_to_2",
            "一进二当日晋级率未严格通过当前情绪档位阈值",
            emotion_regime=emotion_regime,
            promotion_1_to_2_pct=promotion_1_to_2_pct,
            min_exclusive_pct=one_to_two_threshold,
        ))
    if promotion_2_to_3_pct is not None and promotion_2_to_3_pct <= 25:
        blocks.append(_finding(
            "LIANBAN_2_TO_3_STRATEGY", "lianban_2_to_3", "二进三当日晋级率未严格大于25%",
            promotion_2_to_3_pct=promotion_2_to_3_pct,
            min_exclusive_pct=25,
        ))
    if promotion_3_to_4_pct is not None and promotion_3_to_4_pct <= 35:
        blocks.append(_finding(
            "LIANBAN_3_TO_4_STRATEGY", "lianban_3_to_4", "三进四当日晋级率未严格大于35%",
            promotion_3_to_4_pct=promotion_3_to_4_pct,
            min_exclusive_pct=35,
        ))

    # ── W2 窗口 ──
    if emotion is not None and emotion < 20 and (lianban_risk is None or lianban_risk >= 0.5):
        blocks.append(_finding("W2_ICE_RISK", "w2", "W2 冰点风险过高",
                               emotion_pct=emotion, lianban_risk=lianban_risk, max_risk=0.5))
    if broken_board is not None and broken_board > 40:
        blocks.append(_finding("W2_BROKEN_BOARD", "w2_lianban", "炸板率超过连板 W2 上限",
                               broken_board_pct=broken_board, max_pct=40))

    auction_factors = {
        "w1": {"lianban": 1.0, "trend": 1.0},
        "w2": {"lianban": 1.0, "trend": 1.0},
    }
    if auction_emotion is not None and auction_emotion >= 90:
        auction_factors["w1"]["lianban"] = 0.0
        auction_factors["w1"]["trend"] = 0.0
        auction_factors["w2"]["lianban"] = 0.0
        auction_factors["w2"]["trend"] = 0.0
        blocks.append(_finding("AUCTION_CLIMAX_90", "entry", "竞价情绪>=90%，全天只卖不买",
                               auction_emotion_pct=auction_emotion))
    elif auction_emotion is not None and auction_emotion >= 85:
        auction_factors["w1"]["lianban"] = 0.0
        auction_factors["w2"]["trend"] = 0.5
        blocks.append(_finding("AUCTION_CLIMAX_W1_LIANBAN", "w1_lianban", "竞价情绪85-90%，连板W1全关",
                               auction_emotion_pct=auction_emotion))
    elif auction_emotion is not None and auction_emotion >= 80:
        auction_factors["w1"]["lianban"] = 0.5
        warnings.append(_finding("AUCTION_CLIMAX_W1_HALF", "w1_lianban", "竞价情绪80-85%，连板W1半仓",
                                 auction_emotion_pct=auction_emotion))

    # ── 整理输出 ──
    globally_blocked = any(item["scope"] == "all" for item in blocks)
    entry_blocked = any(item["scope"] == "entry" for item in blocks)
    lianban_closed = any(item["scope"] == "lianban" for item in blocks)
    applicable_lianban_layers = {
        "1_to_2": emotion_regime in {"低迷", "主升"} or emotion_regime is None,
        "2_to_3": True,
        "3_to_4": True,
    }
    lianban_layer_scopes = {
        "1_to_2": "lianban_1_to_2",
        "2_to_3": "lianban_2_to_3",
        "3_to_4": "lianban_3_to_4",
    }
    lianban_layer_block_codes = {
        layer: [
            item["code"] for item in blocks
            if item["scope"] == scope
        ]
        for layer, scope in lianban_layer_scopes.items()
    }
    lianban_strategy_all_blocked = all(
        not applicable_lianban_layers[layer] or lianban_layer_block_codes[layer]
        for layer in applicable_lianban_layers
    )
    lianban_closed = lianban_closed or lianban_strategy_all_blocked
    trend_closed = any(item["scope"] == "trend" for item in blocks)
    if lianban_closed and trend_closed and not globally_blocked:
        trend_pct = 0
        lianban_pct = 0
    elif lianban_closed and not globally_blocked and lianban_pct > 0:
        trend_pct = 100
        lianban_pct = 0
    elif trend_closed and not globally_blocked and trend_pct > 0:
        lianban_pct = 100
        trend_pct = 0
    if globally_blocked:
        total_cap = 0
        lianban_pct = 0
        trend_pct = 0
    total_cap, position_caps = _position_control_caps(position_control, base_cap, total_cap, globally_blocked)

    ice_manual_review_allowed = (
        emotion is not None
        and emotion < 35
        and not globally_blocked
        and _ice_polar_manual_review_allowed(manual_review_context, account_day_return_pct)
    )
    ice_manual_review_rules = ["WIN-ICE-POLAR-MAINLINE-001"] if ice_manual_review_allowed else []
    if ice_manual_review_allowed:
        warnings.append(_finding(
            "WIN-ICE-POLAR-MAINLINE-001", "w1",
            "冰点 W1 极化主线强回踩仅人工复核，不自动授权买入",
            emotion_pct=emotion,
            buy_allowed=False,
            mainline_confirmed=manual_review_context.get("mainline_confirmed"),
            market_breadth_polarization=manual_review_context.get("market_breadth_polarization"),
            pullback_confirmed=manual_review_context.get("pullback_confirmed"),
            current_price_distance_pct=manual_review_context.get("current_price_distance_pct"),
        ))

    in_w1 = (now.replace(hour=9, minute=30, second=0, microsecond=0) <= now <
             now.replace(hour=10, minute=1, second=0, microsecond=0))
    in_w2 = (now.replace(hour=14, minute=0, second=0, microsecond=0) <= now <
             now.replace(hour=14, minute=51, second=0, microsecond=0))

    w1_blocks = [item["code"] for item in blocks if item["scope"] in ("all", "entry", "w1")]
    w2_blocks = [item["code"] for item in blocks if item["scope"] in ("all", "entry", "w2")]
    w1_side_blocks = {
        "lianban": w1_blocks + [item["code"] for item in blocks if item["scope"] in ("lianban", "w1_lianban")],
        "trend": w1_blocks + [item["code"] for item in blocks if item["scope"] in ("trend", "w1_trend")],
    }
    w2_side_blocks = {
        "lianban": w2_blocks + [item["code"] for item in blocks if item["scope"] in ("lianban", "w2_lianban")],
        "trend": w2_blocks + [item["code"] for item in blocks if item["scope"] in ("trend", "w2_trend")],
    }
    if auction_factors["w1"]["lianban"] == 0:
        w1_side_blocks["lianban"].append("AUCTION_CLIMAX_W1_LIANBAN")
    if auction_factors["w1"]["trend"] == 0:
        w1_side_blocks["trend"].append("AUCTION_CLIMAX_90")
    if auction_factors["w2"]["lianban"] == 0:
        w2_side_blocks["lianban"].append("AUCTION_CLIMAX_90")
    if auction_factors["w2"]["trend"] == 0:
        w2_side_blocks["trend"].append("AUCTION_CLIMAX_90")

    def _window_lianban_layers(window_blocks, side_blocks, in_session):
        layer_blocks = {
            layer: list(dict.fromkeys(
                side_blocks + lianban_layer_block_codes[layer]
            ))
            for layer in lianban_layer_scopes
        }
        allowed = {
            layer: bool(
                in_session
                and applicable_lianban_layers[layer]
                and not layer_blocks[layer]
            )
            for layer in lianban_layer_scopes
        }
        any_layer_available = any(
            applicable_lianban_layers[layer] and not layer_blocks[layer]
            for layer in lianban_layer_scopes
        )
        summary_blocks = list(side_blocks)
        if not any_layer_available:
            summary_blocks.extend(
                code for codes in lianban_layer_block_codes.values() for code in codes
            )
            if not summary_blocks:
                summary_blocks.append("LIANBAN_STRATEGIES_CLOSED")
        return (
            {layer: list(dict.fromkeys(codes)) for layer, codes in layer_blocks.items()},
            allowed,
            list(dict.fromkeys(summary_blocks)),
        )

    w1_lianban_layer_blocks, w1_lianban_layer_allowed, w1_side_blocks["lianban"] = (
        _window_lianban_layers(w1_blocks, w1_side_blocks["lianban"], in_w1)
    )
    w2_lianban_layer_blocks, w2_lianban_layer_allowed, w2_side_blocks["lianban"] = (
        _window_lianban_layers(w2_blocks, w2_side_blocks["lianban"], in_w2)
    )

    regime = "unknown" if emotion is None else (
        "冰点" if emotion < 20 else "低迷" if emotion < 40 else
        "主升" if emotion < 60 else "强势" if emotion < 80 else "高潮"
    )

    position_evidence = evaluate_position_evidence(
        inputs.get("action_type"), inputs.get("position_evidence")
    ) if inputs.get("action_type") in {"buy", "add", "do_t"} else {
        "allowed": True, "code": None, "missing_fields": [], "blocking_reasons": []
    }
    if inputs.get("position_evidence") and isinstance(position_evidence, dict):
        position_evidence["entry_leg"] = (inputs.get("position_evidence") or {}).get("entry_leg")

    return {
        "version": RULE_VERSION,
        "evaluated_at": now.isoformat(timespec="seconds"),
        "tradable": not globally_blocked,
        "market_regime": regime,
        "sentiment_basis": sentiment_basis,
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
            "w1": {
                "in_session": in_w1,
                "buy_allowed": in_w1 and not w1_blocks and not any(w1_side_blocks.values()),
                "side_buy_allowed": {
                    side: in_w1 and not side_blocks
                    for side, side_blocks in w1_side_blocks.items()
                },
                "lianban_layer_buy_allowed": w1_lianban_layer_allowed,
                "lianban_layer_blocks": w1_lianban_layer_blocks,
                "side_blocks": w1_side_blocks,
                "side_cap_factor": auction_factors["w1"],
                "manual_review_allowed": ice_manual_review_allowed,
                "manual_review_rules": ice_manual_review_rules,
                "blocks": w1_blocks,
            },
            "w2": {
                "in_session": in_w2,
                "buy_allowed": in_w2 and not w2_blocks and not any(w2_side_blocks.values()),
                "side_buy_allowed": {
                    side: in_w2 and not side_blocks
                    for side, side_blocks in w2_side_blocks.items()
                },
                "lianban_layer_buy_allowed": w2_lianban_layer_allowed,
                "lianban_layer_blocks": w2_lianban_layer_blocks,
                "side_blocks": w2_side_blocks,
                "side_cap_factor": auction_factors["w2"],
                "blocks": w2_blocks,
            },
        },
        "style_shift_buffer": style_shift_buffer,
        "source_gaps": source_gaps,
        "position_evidence": position_evidence,
        "blocks": blocks,
        "warnings": warnings,
        "execution_plan_valid": inputs.get("execution_plan_valid") is not False,
        "execution_plan": inputs.get("execution_plan") or {},
    }
