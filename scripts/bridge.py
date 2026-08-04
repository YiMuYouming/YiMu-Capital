#!/usr/bin/env python3
"""bridge.py — 看板 ↔ JSON 桥接服务
在看板目录运行: python3 scripts/bridge.py
然后浏览器打开 http://localhost:8080
W15 记流水时自动 POST 到 /api/sync，实时写入 JSON
LLM Hook: POST /api/llm → Anthropic API → 研判文本
"""

import atexit, hashlib, json, os, re, sys, time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
from pathlib import Path
from datetime import datetime, time as _time, timedelta
from urllib.parse import parse_qs, urlparse
from threading import Lock, Thread

try:
    from apscheduler.schedulers.background import BackgroundScheduler
except ImportError:
    class BackgroundScheduler:
        """Minimal fallback so DB/API code remains importable without APScheduler."""
        def __init__(self, *args, **kwargs):
            self._jobs = []

        def add_job(self, func, trigger=None, **kwargs):
            self._jobs.append({"func": func, "trigger": trigger, **kwargs})

        def start(self):
            return None

        def get_jobs(self):
            return list(self._jobs)

        def shutdown(self, wait=False):
            self._jobs = []

ROOT = Path(__file__).resolve().parent.parent
AI_RULE_SYSTEM_ROOT = ROOT.parent / "ai-rule-system"

try:
    from scripts.file_utils import atomic_write_json
except ImportError:
    _s = str(ROOT)
    if _s not in sys.path: sys.path.insert(0, _s)
    from scripts.file_utils import atomic_write_json

try:
    from scripts.attack_direction import build_attack_direction
except ImportError:
    _s = str(ROOT)
    if _s not in sys.path: sys.path.insert(0, _s)
    try:
        from scripts.attack_direction import build_attack_direction
    except ImportError:
        def build_attack_direction(*_args, **_kwargs):
            return {}

try:
    from scripts.limitboard_report import load_latest_limitboard_report
except ImportError:
    def load_latest_limitboard_report():
        return {}

# 内存缓存（APScheduler 采集线程写入，HTTP handler 读取）
CACHE = {}
CACHE_FILE = ROOT / "data" / "cache_dump.json"
DATA_FILE = ROOT / "data/dashboard_data.json"
LLM_INSIGHTS_FILE = ROOT / "data/llm_insights.json"
_PERSIST_KEYS = [
    "live_index", "live_quotes", "breadth", "live_sectors", "iwencai",
    "northbound", "hot_list", "limit_counts", "limit_up_detail", "sector_inflow",
    "上证15min", "深证15min", "创业15min", "kline_15m_date",
]

_llm_rate_lock = Lock()
_llm_conv_lock = Lock()


def _sanitize_iwencai_cache_entry(entry):
    """Drop invalid derived emotion values before exposing or using iwencai cache."""
    if not isinstance(entry, dict):
        return entry
    cleaned = dict(entry)
    if cleaned.get("_emotion_source") == "iwencai_up_down":
        counts = cleaned.get("_emotion_counts") or {}
        up = counts.get("up")
        down = counts.get("down")
        try:
            invalid = float(up or 0) <= 0 or float(down or 0) <= 0
        except Exception:
            invalid = True
        if invalid:
            cleaned.pop("情绪值", None)
            cleaned.pop("_emotion_source", None)
            cleaned.pop("_emotion_counts", None)
    return cleaned


def _load_cache():
    """冷启动：从磁盘恢复 CACHE，避免重启后短暂空白"""
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE) as f:
                saved = json.load(f)
            for k in _PERSIST_KEYS:
                if k in saved:
                    v = saved[k]
                    # 向后兼容：hot_list 旧格式 {"data": {...}} → 直接取 data
                    if k == 'hot_list' and isinstance(v, dict) and 'data' in v and 'reason_stats' not in v:
                        if isinstance(v['data'], dict):
                            v = v['data']
                            v['_updated'] = saved[k].get('_updated', '')
                    if k == 'iwencai':
                        v = _sanitize_iwencai_cache_entry(v)
                    CACHE[k] = v
            print(f'[bridge] Cache restored from disk ({len(saved)} keys)')
        except Exception:
            pass


def _dump_cache():
    """定期落盘：将 CACHE 中可序列化的 key 写入磁盘"""
    try:
        dump = {}
        for k in _PERSIST_KEYS:
            v = CACHE.get(k)
            if v is not None and (isinstance(v, (dict, list))):
                dump[k] = v
        if dump:
            atomic_write_json(CACHE_FILE, dump)
    except Exception:
        pass


def _normalize_stock_code(value):
    code = str(value or "").strip()
    return code if re.fullmatch(r"\d{6}", code) else None


def _repair_shifted_pool_row(row):
    if not isinstance(row, dict):
        return row
    fixed = dict(row)
    code_val = str(fixed.get("代码") or "").strip()
    board_val = str(fixed.get("板块") or "").strip()
    if code_val and not _normalize_stock_code(code_val) and _normalize_stock_code(board_val):
        original_role = str(fixed.get("标的") or "").strip()
        original_sector = fixed.get("今日定位")
        original_positioning = fixed.get("窗口")
        fixed["池内角色"] = original_role
        fixed["标的"] = code_val
        fixed["代码"] = board_val
        fixed["板块"] = original_sector
        if original_positioning:
            fixed["今日定位"] = original_positioning
    return fixed


def _repair_dashboard_pool_rows(data):
    if not isinstance(data, dict):
        return data
    for key in ("lianban_pool", "trend_pool"):
        rows = data.get(key)
        if isinstance(rows, list):
            data[key] = [_repair_shifted_pool_row(row) for row in rows]
    return data


def _collect_stock_codes(data):
    """Collect all instruments that must stay subscribed to live quotes."""
    data = _repair_dashboard_pool_rows(dict(data or {}))
    raw_codes = (
        [s.get('代码') for s in data.get('lianban_pool', []) if s.get('代码')] +
        [s.get('代码') for s in data.get('trend_pool', []) if s.get('代码')] +
        [a.get('代码') for a in data.get('decision', {}).get('锚定股状态', []) if a.get('代码')] +
        [p.get('代码') for p in data.get('positions', []) if p.get('代码')]
    )
    return list({code for code in (_normalize_stock_code(c) for c in raw_codes) if code})


def _collect_runtime_stock_codes(data, today=None):
    """Collect baseline watchlist plus same-day traded codes for live quote subscription."""
    codes = set(_collect_stock_codes(data or {}))
    trade_date = today or datetime.now().strftime("%Y-%m-%d")
    try:
        from scripts.db import query_account_baseline
        anchor = query_account_baseline(trade_date)
        for position in (anchor or {}).get("positions") or []:
            code = _normalize_stock_code(position.get("代码"))
            qty_raw = str(position.get("数量") or 0).replace("股", "")
            try:
                qty = int(float(qty_raw))
            except (TypeError, ValueError):
                qty = 0
            if code and qty > 0:
                codes.add(code)
    except Exception:
        pass
    try:
        for trade in query_trades(date_from=trade_date, date_to=trade_date, limit=10000):
            code = _normalize_stock_code(trade.get("code"))
            if code:
                codes.add(code)
    except Exception:
        pass
    try:
        for closed in query_7day_closed_positions(trade_date):
            code = _normalize_stock_code(closed.get("code"))
            if code:
                codes.add(code)
    except Exception:
        pass
    return sorted(codes)


def _refresh_stock_codes(data=None):
    """Refresh collector subscription codes after startup or ticket-aware fills."""
    if data is None:
        data = _load_dashboard_data()
    codes = _collect_runtime_stock_codes(data or {})
    CACHE["_stock_codes"] = codes
    return codes


def _trade_cash_effect(op):
    """Return the cash movement for one executed trade."""
    amount = round(float(op.get('价格', 0) or 0) * float(op.get('数量', 0) or 0), 2)
    action = str(op.get('动作', ''))
    if '卖出' in action:
        return amount
    if '买入' in action or '追涨' in action:
        return -amount
    return 0


def _ensure_db():
    """Lazy DB initialization on first use; also registers atexit hook."""
    global _db_inited
    if not _db_inited:
        init_db()
        _db_inited = True
        atexit.register(_shutdown_db)


_db_inited = False


def _shutdown_db():
    """Shutdown hook: close DB connection on process exit."""
    from scripts.db import close_conn
    close_conn()


def _payload_overwrites_account(payload):
    """Asset state is server-owned; legacy browser PnL writes are forbidden."""
    return isinstance(payload, dict) and 'pnl' in payload

# SQLite db — deferred init (lazy, avoids module-level connection leak at shutdown)
try:
    from scripts.db import init_db, query_pnl, query_trades, query_pnl_summary
    from scripts.account_ssot import load_current_account_state, query_7day_closed_positions
except ImportError:
    _s = str(ROOT)
    if _s not in sys.path: sys.path.insert(0, _s)
    from scripts.db import init_db, query_pnl, query_trades, query_pnl_summary
    from scripts.account_ssot import load_current_account_state, query_7day_closed_positions


def _merge_pnl_summary(snapshot_summary, account_state):
    """Keep chart metadata, but source all live asset values from account SSOT."""
    result = dict(snapshot_summary or {})
    for key in [
        'cash', 'positions', 'trades', 'mv', 'total_asset', 'day_start_asset',
        'pnl_amount', 'pnl_pct', 'pos_pct', 'total_deposit',
        'valuation_complete', 'anchor', '_updated', 'closed_positions',
        'quote_status',
    ]:
        if key in account_state:
            result[key] = account_state[key]
    return result


def _load_current_account_state(live_quotes=None, now=None, create_anchor=True):
    return load_current_account_state(
        live_quotes if live_quotes is not None else CACHE.get('live_quotes', {}),
        now=now,
        data_file=DATA_FILE,
        create_anchor=create_anchor,
    )


def _current_pnl_summary():
    legacy = query_pnl_summary()
    state = _load_current_account_state(CACHE.get('live_quotes', {}))
    return _merge_pnl_summary(legacy, state)


def _number_or_none(value):
    try:
        if value is None:
            return None
        return float(str(value).replace("%", "").replace("+", ""))
    except (TypeError, ValueError):
        return None


def _hhmm_to_minutes(label):
    try:
        h, m = str(label)[:5].split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None


def _slot_label_from_timestamp(timestamp, now):
    raw = str(timestamp or "")
    match = re.search(r"(\d{2}):(\d{2})", raw)
    if match:
        h, m = int(match.group(1)), int(match.group(2))
    else:
        h, m = now.hour, now.minute
    minute_of_day = h * 60 + (m // 5) * 5
    if 11 * 60 + 30 <= minute_of_day < 13 * 60:
        minute_of_day = 11 * 60 + 25
    elif minute_of_day > 14 * 60 + 55:
        minute_of_day = 14 * 60 + 55
    return f"{minute_of_day // 60:02d}:{minute_of_day % 60:02d}"


def _today_trade_overlay_timestamp(live_summary, today):
    stamps = []
    for trade in live_summary.get('trades') or []:
        if str(trade.get('trade_date') or '') != today:
            continue
        raw = str(trade.get('created_at') or '').strip()
        if raw.startswith(today):
            stamps.append(raw.replace(" ", "T", 1))
            continue
        trade_time = str(trade.get('trade_time') or '').strip()
        if re.match(r"^\d{2}:\d{2}(:\d{2})?$", trade_time):
            if len(trade_time) == 5:
                trade_time += ":00"
            stamps.append(f"{today}T{trade_time}")
    return max(stamps) if stamps else None


def _overlay_live_today_pnl_point(chart, live_summary, range_val, index_val,
                                  live_index=None, now=None):
    """Expose today's SSOT point without writing untrusted valuation to snapshots."""
    if range_val != 'today' or not isinstance(chart, dict) or not isinstance(live_summary, dict):
        return chart
    if chart.get('type') != 'intraday':
        return chart

    now = now or datetime.now()
    today = now.strftime("%Y-%m-%d")
    try:
        from scripts.db import is_trading_day, TRADING_HOUR_START
        if not is_trading_day(today) or (now.hour, now.minute) < TRADING_HOUR_START:
            return chart
    except Exception:
        pass

    updated = str(live_summary.get('_updated') or '')
    overlay_source = 'account_ssot'
    overlay_updated = updated if updated.startswith(today) else None
    if not overlay_updated:
        overlay_updated = _today_trade_overlay_timestamp(live_summary, today)
        overlay_source = 'account_trade_ledger' if overlay_updated else overlay_source
    if not overlay_updated:
        return chart
    pnl_pct = _number_or_none(live_summary.get('pnl_pct'))
    if pnl_pct is None:
        return chart

    labels = list(chart.get('labels') or [])
    if not labels:
        return chart

    target_label = _slot_label_from_timestamp(overlay_updated, now)
    target_idx = labels.index(target_label) if target_label in labels else None
    if target_idx is None:
        target_min = _hhmm_to_minutes(target_label)
        candidates = [
            (i, _hhmm_to_minutes(label)) for i, label in enumerate(labels)
            if _hhmm_to_minutes(label) is not None
        ]
        past = [item for item in candidates if item[1] <= target_min]
        if not past:
            return chart
        target_idx = past[-1][0]

    chart_is_today = chart.get('data_date') == today and not chart.get('is_fallback')
    if chart_is_today:
        existing_portfolio = list(chart.get('portfolio') or [])
        last_existing_idx = -1
        for i, value in enumerate(existing_portfolio):
            if value is not None:
                last_existing_idx = i
        if target_idx < last_existing_idx:
            return chart

    idx_key = {'sh': '上证指数涨幅', 'sz': '深证指数涨幅', 'cy': '创业板指涨幅'}.get(index_val, '上证指数涨幅')
    live_index = live_index or {}
    benchmark = _number_or_none(live_index.get(idx_key))
    if benchmark is None and index_val == 'cy':
        benchmark = _number_or_none(live_index.get('创业指数涨幅'))
    if benchmark is None:
        benchmark = 0.0

    pos_pct = _number_or_none(live_summary.get('pos_pct'))
    if pos_pct is None:
        pos_pct = 0.0
    total_asset = _number_or_none(live_summary.get('total_asset'))
    total_deposit = _number_or_none(live_summary.get('total_deposit'))
    nav = total_asset / total_deposit if total_asset and total_deposit and total_deposit > 0 else None
    if nav is None:
        nav = _number_or_none(live_summary.get('nav')) or 1.0

    def series(fill_value, live_value):
        return [fill_value if i < target_idx else live_value if i == target_idx else None
                for i in range(len(labels))]

    def overlay_existing_series(values, live_value):
        out = list(values or [])
        if len(out) < len(labels):
            out.extend([None] * (len(labels) - len(out)))
        elif len(out) > len(labels):
            out = out[:len(labels)]
        out[target_idx] = live_value
        for i in range(target_idx + 1, len(out)):
            out[i] = None
        return out

    result = dict(chart)
    result.update({
        'data_date': today,
        'is_fallback': False,
        'is_live_overlay': True,
        'overlay_source': overlay_source,
        'snapshot_authority': 'temporary_live_overlay',
        'valuation_complete': bool(live_summary.get('valuation_complete')),
        'quote_status': live_summary.get('quote_status'),
        'portfolio': overlay_existing_series(chart.get('portfolio'), round(pnl_pct, 4)) if chart_is_today else series(0.0, round(pnl_pct, 4)),
        'benchmark': overlay_existing_series(chart.get('benchmark'), round(benchmark, 4)) if chart_is_today else series(0.0, round(benchmark, 4)),
        'position': overlay_existing_series(chart.get('position'), round(pos_pct, 4)) if chart_is_today else series(0.0, round(pos_pct, 4)),
        'nav': overlay_existing_series(chart.get('nav'), round(nav, 6)) if chart_is_today else series(1.0, round(nav, 6)),
        '_updated': overlay_updated,
    })
    return result


def _closed_daily_loss_streak(now=None):
    """Count consecutive losing closed days from daily_summary, excluding today."""
    from datetime import datetime as _dt
    from scripts.db import get_conn

    today = (now or _dt.now()).strftime("%Y-%m-%d")
    rows = get_conn().execute(
        "SELECT date, pnl_pct FROM daily_summary WHERE date < ? ORDER BY date DESC LIMIT 60",
        (today,),
    ).fetchall()
    if not rows:
        return None
    streak = 0
    for row in rows:
        try:
            pnl = float(row["pnl_pct"])
        except (TypeError, ValueError, KeyError):
            break
        if pnl < 0:
            streak += 1
        else:
            break
    return streak

# === LLM System Prompt ===
SYSTEM_PROMPT_HEADER = """你是弈沐盯盘助手，严格遵循弈沐交易规则做研判。
每次研判你会收到: ①交易规则(LLM_RULES) ②项目约定(CLAUDE) ③全盘实时数据。
结论优先，引用具体数据点。操作建议必须对照规则逐条验证。"""

OUTPUT_FORMAT = """## 输出格式（严格 JSON）
只输出一个 JSON 对象，不要任何 markdown 包裹或额外文字：
{"text":"3-5句中文研判，结论优先","signals":[{"type":"BUY|WATCH|RISK|INFO","target":"标的名称","code":"代码可空","window":"W1|W2|—","direction":"多|空|—","confidence":"高|中|低","basis":["依据1"]}]}
type/window/direction/confidence 只允许列出的枚举值。signals 可为空数组。"""


def _build_system_prompt():
    """每次研判前动态读 LLM_RULES.md + CLAUDE.md，拼成完整 system prompt"""
    parts = [SYSTEM_PROMPT_HEADER]
    for name, rel_path in [("LLM_RULES", "LLM_RULES.md"), ("CLAUDE", "CLAUDE.md")]:
        path = ROOT / rel_path
        try:
            with open(path) as f:
                content = f.read()
            # 总和截断保护（~6000 chars ≈ 1500 tokens，留足给快照和对话）
            total = sum(len(p) for p in parts)
            remaining = 8000 - total
            if len(content) > remaining:
                content = content[:remaining] + "\n...(truncated)"
            parts.append(f"\n=== {name} ===\n{content}")
        except Exception:
            pass
    parts.append("\n---\n" + OUTPUT_FORMAT)
    return "\n".join(parts)


def _load_api_config():
    """从 ~/.claude/settings.json 读取 DeepSeek API 配置"""
    settings_path = Path.home() / ".claude" / "settings.json"
    if settings_path.exists():
        try:
            with open(settings_path) as f:
                s = json.load(f)
            env = s.get("env", {})
            return {
                "base_url": env.get("ANTHROPIC_BASE_URL", "").rstrip("/"),
                "token": env.get("ANTHROPIC_AUTH_TOKEN", ""),
                "model": env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL", "DeepSeek-V4-Flash"),
            }
        except Exception:
            pass
    return {}


ALLOWED_TYPES = frozenset(["BUY", "WATCH", "RISK", "INFO"])
ALLOWED_WINDOWS = frozenset(["W1", "W2", "—"])
ALLOWED_DIRECTIONS = frozenset(["多", "空", "—"])
ALLOWED_CONFIDENCE = frozenset(["高", "中", "低"])
SIGNAL_REQUIRED = ["type", "target", "window", "direction", "confidence"]


def _parse_llm_response(raw_text):
    """解析 LLM 输出：标准 JSON（支持空格/换行/任意字段顺序）优先；
    [TEXT]/[SIGNALS] 降级并标记 legacy warning。"""
    text_part = raw_text
    signals_raw = []
    parse_warnings = []
    # 检查是否是纯 JSON（修剪空白后以 { 开始 } 结束）
    trimmed = raw_text.strip()
    json_obj = None; extra_text = False
    brace_idx = trimmed.find("{")
    if brace_idx > 0:
        extra_text = True  # JSON 前有非空白字符
    if brace_idx >= 0:
        depth = 0; in_str = False; esc = False
        for i in range(brace_idx, len(trimmed)):
            ch = trimmed[i]
            if esc: esc = False; continue
            if ch == '\\': esc = True; continue
            if ch == '"' and not esc: in_str = not in_str; continue
            if in_str: continue
            if ch == '{': depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    json_obj = trimmed[brace_idx:i+1]
                    # JSON 后面不应有非空白内容
                    rest = trimmed[i+1:].strip()
                    if rest: extra_text = True
                    break
    if json_obj:
        if extra_text:
            parse_warnings.append("JSON has extra text before/after — output should be pure JSON")
        try:
            obj = json.loads(json_obj)
        except (json.JSONDecodeError, ValueError) as e:
            parse_warnings.append(f"JSON parse failed: {str(e)[:60]}")
            obj = None
        if isinstance(obj, dict):
            if "text" not in obj:
                parse_warnings.append("JSON missing 'text' field")
            text_part = str(obj.get("text", raw_text))
            raw_signals = obj.get("signals")
            if not isinstance(raw_signals, list):
                parse_warnings.append("signals is not an array")
            else:
                for si, s in enumerate(raw_signals):
                    if not isinstance(s, dict):
                        parse_warnings.append(f"signal[{si}] is not an object")
                        continue
                    s["_schema_errors"] = []
                    for f in SIGNAL_REQUIRED:
                        if f not in s or s[f] is None:
                            s["_schema_errors"].append(f"missing '{f}'")
                    # basis 必填数组
                    basis = s.get("basis")
                    if isinstance(basis, list):
                        if not basis:
                            s["_schema_errors"].append("basis is empty")
                    else:
                        s["_schema_errors"].append("basis missing or not an array")
                        s["basis"] = []
                    stype = str(s.get("type", ""))
                    swindow = str(s.get("window", ""))
                    sdirection = str(s.get("direction", ""))
                    sconfidence = str(s.get("confidence", ""))
                    if stype and stype not in ALLOWED_TYPES:
                        s["_schema_errors"].append(f"unknown type: {stype}")
                    if swindow and swindow not in ALLOWED_WINDOWS:
                        s["_schema_errors"].append(f"unknown window: {swindow}")
                    if sdirection and sdirection not in ALLOWED_DIRECTIONS:
                        s["_schema_errors"].append(f"unknown direction: {sdirection}")
                    if sconfidence and sconfidence not in ALLOWED_CONFIDENCE:
                        s["_schema_errors"].append(f"unknown confidence: {sconfidence}")
                    signals_raw.append(s)
                # Extra text degrades BUY signals
                if extra_text:
                    for s in signals_raw:
                        if s.get("type") == "BUY":
                            s["_schema_errors"].append("parse: output has extra text")
    # 降级：[TEXT]/[SIGNALS] — 标记为 legacy
    if not signals_raw and "[TEXT]" in raw_text:
        parse_warnings.append("legacy [TEXT]/[SIGNALS] format — prefer JSON")
        parts = raw_text.split("[SIGNALS]")
        text_part = parts[0].replace("[TEXT]", "").strip()
        sig_text = parts[1].strip() if len(parts) > 1 else ""
        for line in sig_text.split("\n"):
            line = line.strip()
            if not line or "|" not in line: continue
            fields = [p.strip() for p in line.split("|")]
            if len(fields) >= 4:
                entry = {"type": fields[0], "target": fields[1],
                         "direction": fields[2], "confidence": fields[3]}
                if len(fields) >= 5: entry["code"] = fields[4]
                if len(fields) >= 6: entry["window"] = fields[5]
                if fields[0] == "BUY":
                    entry["_schema_errors"] = ["parse: legacy format"]
                signals_raw.append(entry)
    if not signals_raw and not json_obj and "[TEXT]" not in raw_text and raw_text.strip():
        parse_warnings.append("unrecognized output format")
    return text_part, signals_raw, parse_warnings


def _verify_signals(signals_list, snapshot):
    """验证 LLM 信号：BUY 先过 rule_state 硬校验，再按窗口验证实际组件技术条件。"""
    verified = []
    if not isinstance(signals_list, list):
        return verified

    rule_state = snapshot.get("rule_state") or {}
    rs_tradable = rule_state.get("tradable")
    rs_windows = rule_state.get("windows") or {}
    rs_w1 = rs_windows.get("w1") or {}
    rs_w2 = rs_windows.get("w2") or {}
    rs_missing = "tradable" not in rule_state

    lb_pool = snapshot.get("连板池") or []
    trend_pool = snapshot.get("趋势池") or []
    positions = snapshot.get("持仓") or []
    sectors = snapshot.get("板块") or []
    sentiment_snap = snapshot.get("情绪") or {}

    lb_by_name = {str(s.get("标的", "")): s for s in lb_pool}
    tr_by_name = {str(s.get("标的", "")): s for s in trend_pool}
    pos_by_name = {str(p.get("标的", "")): p for p in positions}

    for sig in signals_list:
        sig_type = str(sig.get("type", ""))
        target = str(sig.get("target", ""))
        code = str(sig.get("code", ""))
        window = str(sig.get("window", "—"))
        direction = str(sig.get("direction", "—"))
        confidence = str(sig.get("confidence", "中"))

        check = {"type": sig_type, "target": target, "code": code, "status": "✅", "note": ""}
        warnings = []

        # Per-signal schema errors from parse (missing fields, basis, enums, extra text, legacy)
        for e in (sig.get("_schema_errors") or []):
            warnings.append(e)

        try:
            if sig_type == "BUY":
                if not target.strip():
                    warnings.append("BUY target is empty")
                if window not in ("W1", "W2"):
                    warnings.append(f"BUY window must be W1 or W2, got: {window}")
                if rs_missing:
                    warnings.append("rule_state missing")
                elif not rs_tradable:
                    warnings.append("tradable is false")
                elif window == "W1" and rs_w1.get("buy_allowed") is not True:
                    warnings.append("W1 buy_allowed is not true")
                elif window == "W2" and rs_w2.get("buy_allowed") is not True:
                    warnings.append("W2 buy_allowed is not true")

                in_lb = target in lb_by_name
                in_tr = target in tr_by_name
                if not in_lb and not in_tr and target.strip():
                    warnings.append(f"目标 {target} 不在连板池/趋势池")

                if not warnings and target.strip():
                    found = tr_by_name.get(target) or lb_by_name.get(target)
                    if not found:
                        warnings.append(f"目标 {target} 无池数据")
                    elif window == "W1":
                        _validate_w1_buy(found, warnings)
                    elif window == "W2":
                        if in_tr:
                            _validate_trend_w2_buy(found, warnings)
                        elif in_lb:
                            _validate_lianban_w2_buy(found, lb_pool, sentiment_snap, warnings)

                if warnings:
                    check["status"] = "⚠️"
                    check["note"] = "；".join(warnings)
                else:
                    check["note"] = "BUY 通过规则校验"

            elif sig_type == "RISK":
                if not target.strip():
                    warnings.append("RISK target is empty")
                found = pos_by_name.get(target) if target.strip() else None
                if found:
                    cost = float(found.get("成本", 0) or 0)
                    price = float(found.get("现价", 0) or 0)
                    if cost and price:
                        check["note"] = f"浮盈{round((price-cost)/cost*100,2)}%"
                    else:
                        warnings.append(f"目标 {target} 缺成本/现价")
                elif target.strip():
                    warnings.append(f"目标 {target} 不在持仓中")
                if warnings:
                    check["status"] = "⚠️"; check["note"] = "；".join(warnings)

            elif sig_type == "WATCH":
                if not target.strip():
                    warnings.append("WATCH target is empty")
                elif target not in lb_by_name and target not in tr_by_name:
                    warnings.append(f"目标 {target} 不在候选池")
                if warnings:
                    check["status"] = "⚠️"; check["note"] = "；".join(warnings)
                else:
                    check["note"] = "目标在候选池"

            elif sig_type == "INFO":
                found_sec = any(target in str(s.get("板块", "")) for s in sectors)
                if not found_sec and target.strip():
                    warnings.append(f"板块 {target} 未在数据中")
                if warnings:
                    check["status"] = "⚠️"; check["note"] = "；".join(warnings)
                else:
                    check["note"] = "数据可查"

            else:
                warnings.append(f"unknown type: {sig_type}")
                check["status"] = "⚠️"; check["note"] = "；".join(warnings)

        except Exception as e:
            check["status"] = "⚠️"
            check["note"] = f"验证异常: {str(e)[:80]}"

        verified.append(check)
    return verified


def _parse_field_float(raw, default=None):
    if raw is None or raw == "—" or raw == "":
        return default
    try:
        return float(str(raw).replace("%", "").replace("+", ""))
    except (ValueError, TypeError):
        return default


def _normalize_today_pool_contract(row):
    today_role = row.get("今日定位")
    today_check = row.get("今日检查")
    trigger_invalid = row.get("触发/失效") or row.get("触发失效")
    legacy_role = row.get("角色")
    legacy_action = row.get("操作")
    has_legacy = bool(legacy_role or legacy_action)
    has_today_role = bool(str(today_role or "").strip())
    has_trigger = bool(str(trigger_invalid or "").strip())
    derived = has_legacy and (not has_today_role or not has_trigger)
    return {
        "今日定位": today_role if has_today_role else ("观察标" if derived else "—"),
        "今日检查": today_check or ("旧字段兼容：需补今日检查" if derived else "—"),
        "触发/失效": trigger_invalid or "缺少新版触发/失效；只观察，不授权买卖",
        "derived_from_legacy_fields": derived,
        "legacy_role": legacy_role or "",
        "legacy_action": legacy_action or "",
    }


def _pool_row_observation_only(row):
    if not isinstance(row, dict):
        return True
    trigger = str(row.get("触发/失效") or row.get("触发失效") or row.get("操作") or "")
    has_legacy = bool(row.get("角色") or row.get("操作"))
    has_today_role = bool(str(row.get("今日定位") or "").strip())
    has_trigger = bool(str(row.get("触发/失效") or row.get("触发失效") or "").strip())
    has_pool_contract_context = any(k in row for k in (
        "今日定位", "今日检查", "触发/失效", "触发失效",
        "derived_from_legacy_fields", "legacy_role", "legacy_action", "角色", "操作",
    ))
    return (
        bool(row.get("derived_from_legacy_fields"))
        or (has_legacy and (not has_today_role or not has_trigger))
        or (has_pool_contract_context and not str(row.get("触发/失效") or row.get("触发失效") or "").strip())
        or "只观察" in trigger
        or "不授权" in trigger
        or "只盯" in trigger
        or "不买" in trigger
    )


def _validate_w1_buy(found, warnings):
    """W1 BUY: 涨幅 3-9.5%，量比、MA10 作为参考"""
    if _pool_row_observation_only(found):
        warnings.append("候选池行仅观察/缺少新版触发失效，不授权 BUY")
        return
    chg = _parse_field_float(found.get("涨幅"), None)
    if chg is None:
        warnings.append("W1 缺涨幅数据")
    elif not (3 <= chg <= 9.5):
        warnings.append(f"W1 涨幅 {chg}% 不在 3-9.5%")
    vr = _parse_field_float(found.get("量比"), None)
    if vr is None:
        warnings.append("W1 缺量比数据")


def _validate_trend_w2_buy(found, warnings):
    """趋势 W2 BUY（对齐 W09 条件）: MA方向向上 + 距MA10 -1.5%~1.0% + 缩量<0.8 + 未大跌 >-5%"""
    if _pool_row_observation_only(found):
        warnings.append("候选池行仅观察/缺少新版触发失效，不授权 BUY")
        return
    chg = _parse_field_float(found.get("涨幅"), None)
    vr = _parse_field_float(found.get("量比"), None)
    ma10 = _parse_field_float(found.get("MA10_60m"), None)
    ma_dir = str(found.get("MA10_60m_dir", "—"))
    price = _parse_field_float(found.get("最新价"), None)

    if chg is None:
        warnings.append("趋势W2 缺涨幅")
    if vr is None:
        warnings.append("趋势W2 缺量比")
    if ma10 is None:
        warnings.append("趋势W2 缺MA10_60m")
    if ma_dir == "—" or not ma_dir:
        warnings.append("趋势W2 缺MA10方向")

    if warnings: return

    # 1) MA方向向上 + 距离 MA10 在 -1.5% ~ 1.0%
    dir_ok = ma_dir == "向上"
    near_ma = False
    if ma10 > 0 and price is not None:
        dist = (price - ma10) / ma10 * 100
        near_ma = -1.5 <= dist <= 1.0
        if not near_ma and dir_ok:
            warnings.append(f"趋势W2 距MA10 {dist:.1f}%，需在 -1.5%~1.0%")
    elif not dir_ok:
        warnings.append(f"趋势W2 MA10方向={ma_dir}，需向上")
    near60m = dir_ok and near_ma
    # 2) 缩量：量比 < 0.8
    shrink_ok = vr < 0.8
    if not shrink_ok:
        warnings.append(f"趋势W2 量比={vr}，需<0.8")
    # 3) 未大跌：涨幅 > -5
    crash_ok = chg > -5
    if not crash_ok:
        warnings.append(f"趋势W2 涨幅={chg}%，需>-5%")

    hardMet = (1 if near60m else 0) + (1 if shrink_ok else 0) + (1 if crash_ok else 0)
    if hardMet < 3:
        warnings.append(f"趋势W2 条件满足{hardMet}/3（MA回踩/缩量/未大跌）")


def _validate_lianban_w2_buy(found, lb_pool, sentiment_snap, warnings):
    """连板 W2 BUY（对齐 W09 条件）: 分歧回落 + 缩量 + 龙头活 + 非冰点"""
    if _pool_row_observation_only(found):
        warnings.append("候选池行仅观察/缺少新版触发失效，不授权 BUY")
        return
    chg = _parse_field_float(found.get("涨幅"), None)
    vr = _parse_field_float(found.get("量比"), None)
    sector = str(found.get("板块", ""))

    if chg is None:
        warnings.append("连板W2 缺涨幅")
    if vr is None:
        warnings.append("连板W2 缺量比")

    if warnings: return

    # 1) 分歧回落：-7 < chg < 0
    diverge_ok = -7 < chg < 0
    if not diverge_ok:
        warnings.append(f"连板W2 涨幅={chg}%，需在-7%~0%")
    # 2) 缩量
    shrink_ok = vr < 0.8
    if not shrink_ok:
        warnings.append(f"连板W2 量比={vr}，需<0.8")
    # 3) 龙头存活：同板块存在情绪标且涨幅>=3
    leader_alive = False
    if sector:
        for s in lb_pool:
            if (not _pool_row_observation_only(s)
                    and str(s.get("板块", "")) == sector
                    and "情绪标" in str(s.get("今日定位") or s.get("角色", ""))):
                lchg = _parse_field_float(s.get("涨幅"), None)
                if lchg is not None and lchg >= 3:
                    leader_alive = True
                break
    if not leader_alive:
        leader_alive = True  # 找不到明确龙头时放行（对齐W09逻辑）
    # 4) 非冰点
    emotion = _parse_field_float(sentiment_snap.get("情绪值"), None)
    not_ice = False
    if emotion is None:
        warnings.append("连板W2 缺情绪数据")
    elif emotion >= 20:
        not_ice = True
    else:
        warnings.append(f"连板W2 情绪={emotion}%，需>=20%")

    hardMet = (1 if diverge_ok else 0) + (1 if shrink_ok else 0) + (1 if leader_alive else 0) + (1 if not_ice else 0)
    if hardMet < 3:
        warnings.append(f"连板W2 条件满足{hardMet}/4（分歧/缩量/龙头/非冰）")



def _process_llm_result(raw_text, snapshot, today_str, node_ts, mode, userMsg=None):
    """共用 LLM 结果处理：解析 → 验证 → user→assistant 持久化 → 返回。"""
    text_part, signals_raw, parse_warnings = _parse_llm_response(raw_text)
    verified_signals = _verify_signals(signals_raw, snapshot)
    for w in parse_warnings:
        verified_signals.append({
            "type": "INFO", "target": "—", "code": "",
            "status": "⚠️", "note": f"[parse] {w}",
        })
    verified_count = sum(1 for v in verified_signals if v.get("status") == "✅")
    warning_count = sum(1 for v in verified_signals if v.get("status") == "⚠️")
    insight = {
        "timestamp": node_ts, "node": node_ts, "mode": mode,
        "text": text_part, "signals": verified_signals,
        "verified_count": verified_count, "warning_count": warning_count,
    }
    # 单次写入（持锁防并发丢失）：user → assistant 顺序
    with _llm_conv_lock:
        insights = {}
        if LLM_INSIGHTS_FILE.exists():
            try:
                with open(LLM_INSIGHTS_FILE) as f:
                    insights = json.load(f)
            except Exception:
                pass
        if today_str not in insights:
            insights[today_str] = {"meta": {}, "conversation": []}
        meta = insights[today_str].setdefault("meta", {})
        if "started_at" not in meta:
            meta["started_at"] = node_ts
        meta["last_assistant_ts"] = node_ts
        if mode == "auto":
            meta["auto_trigger_count"] = meta.get("auto_trigger_count", 0) + 1
        else:
            meta["manual_question_count"] = meta.get("manual_question_count", 0) + 1
        if userMsg and isinstance(userMsg, dict) and userMsg.get("text"):
            insights[today_str]["conversation"].append({
                "role": "user", "ts": userMsg.get("ts", node_ts),
                "text": userMsg.get("text", ""), "auto": False,
            })
        insights[today_str]["conversation"].append({
            "role": "assistant", "ts": node_ts, "text": text_part,
            "signals": verified_signals, "auto": mode == "auto",
        })
        LLM_INSIGHTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(LLM_INSIGHTS_FILE, insights)
    return insight, verified_signals, verified_count, warning_count


def _call_llm_api(messages):
    """调用 DeepSeek Anthropic-compatible API。messages 为对话数组（含历史+当前快照）"""
    cfg = _load_api_config()
    if not cfg.get("token"):
        return {"error": "API token not found in ~/.claude/settings.json"}

    import urllib.request
    url = cfg["base_url"] + "/v1/messages"
    body = json.dumps({
        "model": cfg["model"],
        "max_tokens": 2000,
        "system": _build_system_prompt(),
        "messages": messages,
    }).encode()

    req = urllib.request.Request(url, data=body, headers={
        "x-api-key": cfg["token"],
        "Content-Type": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            content = result.get("content", [])
            # 只取 text 类型 block（忽略 thinking）
            text = "".join(
                c.get("text", "") for c in content
                if c.get("type") == "text" and c.get("text", "").strip()
            )
            return {"ok": True, "text": text}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}

def _add_freshness(data, data_type, fetched_at=None):
    """为 API 响应附加 _freshness 字段（live/delayed/stale/dead）"""
    from datetime import datetime as _dt, time as _time, timedelta as _td
    now = _dt.now()
    fetched_dt = None
    if fetched_at:
        try:
            fetched_dt = _dt.fromisoformat(fetched_at)
            compare_now = _dt.now(fetched_dt.tzinfo) if fetched_dt.tzinfo else now
            age = max(0, (compare_now - fetched_dt).total_seconds())
        except (TypeError, ValueError):
            age = None
    else:
        age = None

    freshness_rules = {
        'live_quote':   {'live': 15, 'delayed': 60, 'stale': 300},
        'iwencai':      {'live': 180, 'delayed': 600, 'stale': 1800},
        'auction':      None,  # 特殊处理：基于时段时间
        'baseline':     None,  # 特殊处理：基于天数
        'pnl':          {'live': 300, 'delayed': 3600, 'stale': 86400},
        'llm':          {'live': 1200, 'delayed': 3600, 'stale': 86400},
    }

    if data_type == 'auction':
        today = _dt.now().date()
        t = now.time()
        d = fetched_dt.date() if fetched_dt else None
        if d is None:
            level = 'dead'
        elif d == today and _time(9, 25) <= t <= _time(10, 0):
            level = 'live'
        elif d == today and t <= _time(15, 0):
            level = 'delayed'
        elif d == today:
            level = 'stale'
        else:
            level = 'dead'
    elif data_type == 'baseline':
        today = _dt.now().date()
        if fetched_dt:
            diff = (today - fetched_dt.date()).days
            level = 'live' if diff == 0 else ('delayed' if diff <= 1 else ('stale' if diff <= 2 else 'dead'))
        else:
            level = 'dead'
    else:
        rule = freshness_rules.get(data_type, {'live': 300, 'delayed': 3600, 'stale': 86400})
        level = 'dead' if age is None else ('live' if age < rule['live'] else ('delayed' if age < rule['delayed'] else ('stale' if age < rule['stale'] else 'dead')))

    if isinstance(data, dict):
        data['_freshness'] = {'level': level, 'type': data_type, 'age_seconds': int(age) if age is not None else None}
    return data


# ===== 实时规则引擎适配 =====

def _rule_num(value):
    try:
        if value in (None, "", "—"):
            return None
        return float(str(value).replace("%", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def _rule_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on", "是", "确认", "已确认")


def _pool_identity_set(dash):
    ids = set()
    for key in ("lianban_pool", "trend_pool"):
        for item in (dash.get(key) or []):
            if not isinstance(item, dict):
                continue
            for field in ("代码", "code"):
                value = str(item.get(field) or "").strip()
                if value:
                    ids.add(value)
            for field in ("标的", "名称", "name"):
                value = str(item.get(field) or "").strip()
                if value:
                    ids.add(value)
    for item in ((dash.get("decision") or {}).get("锚定股状态") or []):
        if not isinstance(item, dict):
            continue
        for field in ("代码", "code", "标的", "名称", "name"):
            value = str(item.get(field) or "").strip()
            if value:
                ids.add(value)
    return ids


def _market_breadth_polarized(breadth, breadth_fresh):
    if breadth_fresh not in ("live", "delayed"):
        return False
    up = _rule_num((breadth or {}).get("上涨家数"))
    down = _rule_num((breadth or {}).get("下跌家数"))
    if up is None:
        up = _rule_num((breadth or {}).get("0~3%"))
    if down is None:
        down = _rule_num((breadth or {}).get("-0~-3%"))
    if up is None or down is None or up + down <= 0:
        return False
    minor_ratio = min(up, down) / (up + down) * 100
    return minor_ratio <= 35


def _position_control_input(pnl_live, dash, score, lianban_pct, trend_pct, trend_score,
                            breadth, breadth_fresh):
    positions_raw = list((pnl_live or {}).get("positions") or [])
    total_asset = _rule_num((pnl_live or {}).get("total_asset"))
    mv = _rule_num((pnl_live or {}).get("mv"))
    if mv is None:
        mv = sum(_rule_num(p.get("市值")) or 0 for p in positions_raw if isinstance(p, dict))
    current_position_pct = _rule_num((pnl_live or {}).get("pos_pct"))
    if current_position_pct is None:
        current_position_pct = round(mv / total_asset * 100, 2) if total_asset and total_asset > 0 else 0

    pool_ids = _pool_identity_set(dash or {})
    style_mainline = (
        (trend_score is not None and trend_score >= 10)
        or (trend_pct is not None and trend_pct >= 60)
        or (lianban_pct is not None and lianban_pct >= 60)
        or (score is not None and score >= 60)
    )
    normalized_positions = []
    matched_mainline = False
    for position in positions_raw:
        if not isinstance(position, dict):
            continue
        code = str(position.get("代码") or position.get("code") or "").strip()
        name = str(position.get("标的") or position.get("名称") or position.get("name") or "").strip()
        explicit_mainline = position.get("is_mainline")
        is_mainline = _rule_bool(explicit_mainline) if explicit_mainline is not None else (
            code in pool_ids or name in pool_ids
        )
        matched_mainline = matched_mainline or is_mainline
        pnl_pct = _rule_num(position.get("floating_pnl_pct"))
        if pnl_pct is None:
            pnl_pct = _rule_num(position.get("total_pnl_pct"))
        if pnl_pct is None:
            pnl_pct = _rule_num(position.get("today_pnl_pct"))
        if pnl_pct is None:
            price = _rule_num(position.get("现价"))
            cost = _rule_num(position.get("成本")) or _rule_num(position.get("成本价"))
            if price is not None and cost and cost > 0:
                pnl_pct = round((price - cost) / cost * 100, 2)
        position_mv = _rule_num(position.get("市值"))
        normalized_positions.append({
            "code": code,
            "name": name,
            "target_role": position.get("target_role") or position.get("今日定位") or position.get("角色"),
            "is_mainline": is_mainline,
            "floating_pnl_pct": pnl_pct,
            "market_value_pct": round(position_mv / total_asset * 100, 2) if position_mv and total_asset else None,
        })

    account_cap = _rule_num((dash.get("style") or {}).get("account_hard_cap_pct"))
    if account_cap is None:
        account_cap = _rule_num((dash.get("style") or {}).get("账户硬上限"))
    opportunity_cap = _rule_num((dash.get("style") or {}).get("opportunity_cap_pct"))
    if opportunity_cap is None:
        opportunity_cap = _rule_num((dash.get("style") or {}).get("主线机会上限"))
    source_gaps = list((dash.get("style") or {}).get("source_gaps") or [])

    result = {
        "enabled": True,
        "account_cap_pct": account_cap if account_cap is not None else 80,
        "mainline_confirmed": bool(matched_mainline or style_mainline),
        "current_position_pct": current_position_pct,
        "positions": normalized_positions,
        "market_breadth_polarization": _market_breadth_polarized(breadth, breadth_fresh),
        "add_step_pct": 10,
        "max_positions": 3,
        "max_mixed_positions": 5,
        "source_gaps": source_gaps,
    }
    if opportunity_cap is not None:
        result["opportunity_cap_pct"] = opportunity_cap
    elif source_gaps:
        result["opportunity_cap_pct"] = 0
    return result


def _manual_review_context_input(pnl_live, dash, position_control, funds_raw):
    raw = (dash or {}).get("manual_review_context") or (dash or {}).get("人工复核上下文") or {}
    if not isinstance(raw, dict):
        raw = {}
    context = dict(raw)

    def _first_present(*values):
        for value in values:
            if value not in (None, "", "—"):
                return value
        return None

    context.setdefault("market_breadth_polarization", (position_control or {}).get("market_breadth_polarization"))
    context.setdefault("mainline_confirmed", (position_control or {}).get("mainline_confirmed"))
    context.setdefault("profitable_mainline_positions", (position_control or {}).get("profitable_mainline_positions"))
    context.setdefault("account_day_return_pct", (pnl_live or {}).get("pnl_pct"))
    context.setdefault("sector_fund_flow", _first_present(
        (funds_raw or {}).get("sector_fund_flow"),
        (funds_raw or {}).get("板块净流入"),
        (funds_raw or {}).get("main_inflow"),
        (funds_raw or {}).get("主力净流入"),
    ))
    return context


def _build_rule_inputs(now=None, account_state=None):
    """从 CACHE / baseline / SSOT 构建符合 rule_engine v1 契约的输入 dict。
    纯适配函数：不对值做业务判断，只做单位转换和缺省填充。
    """
    from datetime import datetime as _dt

    now = now or _dt.now()
    account_state = account_state or {}
    pnl_live = {}
    if not account_state:
        try:
            pnl_live = _current_pnl_summary()
        except Exception:
            pass
    else:
        pnl_live = account_state

    # ── account ──
    pnl_pct_raw = pnl_live.get("pnl_pct")
    try:
        pnl_pct = float(pnl_pct_raw) if pnl_pct_raw is not None else None
    except (TypeError, ValueError):
        pnl_pct = None
    anchor_trusted = bool(pnl_live.get("anchor_trusted", True))
    valuation_complete = bool(pnl_live.get("valuation_complete"))
    if not anchor_trusted:
        valuation_complete = False  # force DATA_UNTRUSTED for untrusted anchor
    elif "valuation_complete" not in pnl_live:
        valuation_complete = pnl_live.get("mv") is not None

    # ── risk ──
    dash = _load_dashboard_data()
    risk = dash.get("risk", {})
    style_raw = dash.get("style", {})
    funds_raw = dash.get("funds", {}) or dash.get("资金", {}) or {}
    time_window = dash.get("time_window", {})
    legacy_loss_streak = int(risk.get("连亏天数", 0) or 0)
    closed_loss_streak = None
    try:
        closed_loss_streak = _closed_daily_loss_streak(now=now)
    except Exception:
        closed_loss_streak = None
    if pnl_pct is not None and pnl_pct > 0:
        losing_account_days = 0
    elif closed_loss_streak is not None:
        losing_account_days = closed_loss_streak
    else:
        losing_account_days = legacy_loss_streak
    weekly_drawdown = risk.get("周累计回撤")
    monthly_drawdown = risk.get("月累计回撤")

    # ── style ──
    _score_raw = style_raw.get("总分")
    score = int(_score_raw) if _score_raw is not None else None
    _lianban_raw = style_raw.get("连板占比")
    lianban_pct = float(_lianban_raw) if _lianban_raw is not None else None
    _trend_raw = style_raw.get("趋势占比")
    trend_pct = float(_trend_raw) if _trend_raw is not None else None
    _trend_score_raw = style_raw.get("dim3_趋势")
    trend_score = float(_trend_score_raw) if _trend_score_raw is not None else None

    def _first_present(*values):
        for value in values:
            if value not in (None, "", "—"):
                return value
        return None

    style_score_raw = _first_present(
        style_raw.get("style_score_raw"),
        style_raw.get("原始分"),
        style_raw.get("脚本原始分"),
    )
    style_score_adjusted = _first_present(
        style_raw.get("style_score_adjusted"),
        style_raw.get("修正分"),
    )
    adjustment_reason = _first_present(
        style_raw.get("adjustment_reason"),
        style_raw.get("修正原因"),
    )
    style_approver = _first_present(
        style_raw.get("approver"),
        style_raw.get("审批人"),
    )
    style_script_version = _first_present(
        style_raw.get("script_version"),
        style_raw.get("脚本版本"),
    )

    # ── freshness ──
    quotes_fresh = _compute_freshness("live_quote", CACHE.get("live_quotes", {}), now=now)

    # ── sentiment ──
    iwencai = _sanitize_iwencai_cache_entry(CACHE.get("iwencai", {}))
    sentiment_fresh = _compute_freshness("iwencai", iwencai, now=now)
    sentiment_usable = sentiment_fresh in ("live", "delayed")
    base_sent = dash.get("sentiment", {})
    base_market = dash.get("market", {})
    # 晋级率 / 炸板率 在 CACHE 中可能是小数 (0.198)，转换为百分数
    _promotion_raw = iwencai.get("晋级率") if sentiment_usable else None
    if _promotion_raw is None:
        _promotion_raw = base_sent.get("晋级率") if sentiment_usable else None
    _broken_raw = iwencai.get("炸板率") if sentiment_usable else None
    if _broken_raw is None:
        _broken_raw = base_market.get("炸板率") if sentiment_usable else None
    _promotion_num = _rule_num(_promotion_raw)
    _broken_num = _rule_num(_broken_raw)
    if _promotion_num is not None and _promotion_num <= 1:
        promotion_pct = _promotion_num * 100
    else:
        promotion_pct = _promotion_num
    promotion_2_to_3_raw = _first_present(
        base_sent.get("二进三晋级率"),
        style_raw.get("promotion_2_to_3_pct"),
    )
    promotion_2_to_3_pct = _rule_num(promotion_2_to_3_raw)
    if promotion_2_to_3_pct is not None and promotion_2_to_3_pct <= 1:
        promotion_2_to_3_pct *= 100
    promotion_2_to_3_avg_3d = _rule_num(_first_present(
        base_sent.get("二进三晋级率近3日均值"),
        base_sent.get("二进三晋级率近 3 日均值"),
        style_raw.get("promotion_2_to_3_avg_3d"),
        ((style_raw.get("promotion_environment") or {}).get("avg_3d")
         if isinstance(style_raw.get("promotion_environment"), dict) else None),
    ))
    if promotion_2_to_3_avg_3d is not None and promotion_2_to_3_avg_3d <= 1:
        promotion_2_to_3_avg_3d *= 100

    def _promotion_pct(field_cn, field_key):
        value = _rule_num(_first_present(base_sent.get(field_cn), style_raw.get(field_key)))
        return value * 100 if value is not None and value <= 1 else value

    promotion_1_to_2_pct = _promotion_pct("一进二晋级率", "promotion_1_to_2_pct")
    promotion_3_to_4_pct = _promotion_pct("三进四晋级率", "promotion_3_to_4_pct")
    highest_board = _rule_num(_first_present(
        base_sent.get("最高板"), style_raw.get("highest_board")
    ))
    limit_up_count_avg_3d = _rule_num(_first_present(
        base_sent.get("涨停家数近3日均值"),
        base_sent.get("昨日涨停家数3日均值"),
        style_raw.get("limit_up_count_avg_3d"),
    ))
    if _broken_num is not None and _broken_num <= 1:
        broken_board_pct = _broken_num * 100
    else:
        broken_board_pct = _broken_num

    limit_up_profit_raw = iwencai.get("昨日涨停收益") if sentiment_usable else None
    if limit_up_profit_raw is None:
        limit_up_profit_raw = base_sent.get("昨日涨停收益") if sentiment_usable else None
    limit_up_profit_pct = float(limit_up_profit_raw) if limit_up_profit_raw is not None else None
    lianban_risk_raw = iwencai.get("连板风险值") if sentiment_usable else None
    if lianban_risk_raw is None:
        lianban_risk_raw = base_sent.get("连板风险值") if sentiment_usable else None
    lianban_risk = None
    if lianban_risk_raw is not None:
        import re as _re
        m = _re.search(r"[+-]?\d+(?:\.\d+)?", str(lianban_risk_raw))
        if m:
            lianban_risk = float(m.group(0))

    # 情绪值优先级：iwencai 实时值 > 可信 breadth 备用 > fresh live_index 广度。
    # 盘中不得用昨日 baseline 情绪伪装实时值；云端 PyTDX 禁用时 live_index 是可用实时广度源。
    breadth = CACHE.get("breadth", {})
    breadth_fresh = _compute_freshness("breadth", breadth, now=now)
    breadth_source = str(breadth.get("_source") or "")
    breadth_usable = (
        breadth_fresh in ("live", "delayed")
        and breadth_source != "live_index_fallback"
    )
    up_cnt = breadth.get("上涨家数")
    dn_cnt = breadth.get("下跌家数")
    live_index = CACHE.get("live_index", {})
    live_index_fresh = _compute_freshness("live_index", live_index, now=now)
    live_index_up = live_index.get("上涨家数")
    live_index_dn = live_index.get("下跌家数")
    em_raw = iwencai.get("情绪值") if sentiment_usable else None
    if em_raw is not None:
        emotion_pct = float(em_raw)
    elif breadth_usable and up_cnt is not None and dn_cnt is not None and (up_cnt + dn_cnt) > 0:
        emotion_pct = round(up_cnt / (up_cnt + dn_cnt) * 100, 1)
    elif live_index_fresh in ("live", "delayed") and live_index_up is not None and live_index_dn is not None:
        live_index_up = float(live_index_up)
        live_index_dn = float(live_index_dn)
        emotion_pct = round(live_index_up / (live_index_up + live_index_dn) * 100, 1) if (live_index_up + live_index_dn) > 0 else None
    else:
        emotion_pct = None

    emotion_regime = str(_first_present(
        base_sent.get("情绪区间"), style_raw.get("emotion_regime")
    ) or "").strip() or None
    if emotion_regime not in {"冰点", "低迷", "主升", "强势", "高潮"}:
        emotion_regime = None if emotion_pct is None else (
            "冰点" if emotion_pct < 20 else "低迷" if emotion_pct < 40 else
            "主升" if emotion_pct < 60 else "强势" if emotion_pct < 80 else "高潮"
        )

    # previous_emotion：从 sentiment_auto.json 日期分组中取前一日期最后节点
    prev_emotion_pct = None
    try:
        snap_file = ROOT / "data" / "sentiment_auto.json"
        if snap_file.exists():
            import json as _json
            with open(snap_file) as f:
                sentiment_auto = _json.load(f)
            # 日期分组格式: {"2026-05-19": [...], "2026-05-25": [...], ...}
            if isinstance(sentiment_auto, dict):
                dates = sorted(sentiment_auto.keys())
                today_str = (now or datetime.now()).strftime("%Y-%m-%d")
                # 找当前日期之前最近的一个日期
                prev_date = None
                for d in dates:
                    if d >= today_str:
                        break
                    prev_date = d
                if prev_date is not None:
                    nodes = sentiment_auto.get(prev_date)
                    if isinstance(nodes, list) and nodes:
                        last_node = nodes[-1]
                        prev_em = last_node.get("情绪值")
                        if prev_em is not None:
                            prev_emotion_pct = float(prev_em)
    except Exception:
        pass

    plan_source = style_raw.get("_source")
    plan_overrides_loss_streak = (
        plan_source in ("premarket_plan", "appendix_a_plan")
        and (style_raw.get("总仓位上限") or 0) > 0
    )
    position_control = _position_control_input(
        pnl_live, dash, score, lianban_pct, trend_pct, trend_score, breadth, breadth_fresh
    )
    manual_review_context = _manual_review_context_input(pnl_live, dash, position_control, funds_raw)

    return {
        "account": {
            "pnl_pct": pnl_pct,
            "account_day_return_pct": pnl_pct,
            "current_position_market_value": pnl_live.get("mv"),
            "valuation_complete": valuation_complete,
        },
        "risk": {
            "losing_account_days": losing_account_days,
            "loss_streak_hard_stop": not plan_overrides_loss_streak,
            "weekly_drawdown_pct": weekly_drawdown,
            "monthly_drawdown_pct": monthly_drawdown,
        },
        "style": {
            "score": score,
            "style_score_raw": style_score_raw,
            "style_score_adjusted": style_score_adjusted,
            "adjustment_reason": adjustment_reason,
            "approver": style_approver,
            "script_version": style_script_version,
            "lianban_pct": lianban_pct,
            "trend_pct": trend_pct,
            "trend_score": trend_score,
            "market_trend_20d_direction": style_raw.get("market_trend_20d_direction"),
            "previous_lianban_pct": style_raw.get("previous_lianban_pct"),
            "style_shift_same_direction_days": style_raw.get("style_shift_same_direction_days"),
            "source_gaps": list(style_raw.get("source_gaps") or []),
        },
        "funds": {
            "main_inflow": _first_present(funds_raw.get("main_inflow"), funds_raw.get("主力净流入")),
            "dde_big_order_net": _first_present(funds_raw.get("dde_big_order_net"), funds_raw.get("DDE大单净额")),
            "volume_ratio": _first_present(funds_raw.get("volume_ratio"), funds_raw.get("量比")),
            "source": _first_present(funds_raw.get("source"), funds_raw.get("来源")),
            "query": _first_present(funds_raw.get("query"), funds_raw.get("查询语句")),
        },
        "sentiment": {
            "emotion_pct": emotion_pct,
            "previous_emotion_pct": prev_emotion_pct,
            "limit_up_profit_pct": limit_up_profit_pct,
            "broken_board_pct": broken_board_pct,
            "promotion_pct": promotion_pct,
            "highest_board": highest_board,
            "limit_up_count_avg_3d": limit_up_count_avg_3d,
            "promotion_1_to_2_pct": promotion_1_to_2_pct,
            "promotion_2_to_3_pct": promotion_2_to_3_pct,
            "promotion_2_to_3_avg_3d": promotion_2_to_3_avg_3d,
            "promotion_3_to_4_pct": promotion_3_to_4_pct,
            "emotion_regime": emotion_regime,
            "auction_emotion_pct": _rule_num(base_sent.get("竞价情绪值")),
            "lianban_risk": lianban_risk,
        },
        "freshness": {
            "quotes": quotes_fresh,
            "sentiment": sentiment_fresh,
        },
        "time_window": {
            "w1_status": time_window.get("W1状态"),
            "w2_status": time_window.get("W2状态"),
        },
        "position_control": position_control,
        "manual_review_context": manual_review_context,
        "source_gaps": list(style_raw.get("source_gaps") or []),
    }


def _compute_freshness(data_type, cache_entry, now=None):
    """只读 freshness 计算：live/delayed/stale/dead；now 可注入用于测试。
    _updated 生产格式含 +08:00 时区；naive now 视作本地时间 (CST +08:00)。
    """
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td

    updated = cache_entry.get("_updated") if isinstance(cache_entry, dict) else None
    if not updated:
        return "dead"
    rules = {
        "live_quote": (15, 60, 300),
        "iwencai": (180, 600, 1800),
    }
    live_s, delayed_s, stale_s = rules.get(data_type, (300, 3600, 86400))
    CST = _tz(_td(hours=8))
    try:
        fetched = _dt.fromisoformat(str(updated).replace("Z", "+00:00"))
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=CST)
        fetched_utc = fetched.astimezone(_tz.utc)

        if now is None:
            ref_utc = _dt.now(_tz.utc)
        elif now.tzinfo is not None:
            ref_utc = now.astimezone(_tz.utc)
        else:
            # Naive → local time (CST +08:00)
            ref_utc = now.replace(tzinfo=CST).astimezone(_tz.utc)

        age = max(0, (ref_utc - fetched_utc).total_seconds())

        if data_type == "live_quote":
            fetched_cst = fetched.astimezone(CST)
            ref_cst = ref_utc.astimezone(CST)
            ref_hhmm = ref_cst.hour * 60 + ref_cst.minute
            PRE_MARKET = 9 * 60 + 15
            MARKET_CLOSE = 15 * 60
            fetched_hhmm = fetched_cst.hour * 60 + fetched_cst.minute
            if (
                fetched_cst.date() == ref_cst.date()
                and fetched_hhmm >= 14 * 60 + 55
                and ref_hhmm >= MARKET_CLOSE
            ):
                return "close_snapshot"
            if ref_hhmm < PRE_MARKET:
                same_day_premarket = (
                    fetched_cst.date() == ref_cst.date()
                    and age <= 2 * 3600
                )
                previous_close = (
                    fetched_cst.date() < ref_cst.date()
                    and fetched_cst.hour * 60 + fetched_cst.minute >= MARKET_CLOSE
                    and age <= 4 * 86400
                )
                if same_day_premarket or previous_close:
                    if age < live_s:
                        return "live"
                    if age < delayed_s:
                        return "delayed"
                    return "stale"
    except Exception:
        return "dead"
    if age < live_s:
        return "live"
    if age < delayed_s:
        return "delayed"
    if age < stale_s:
        return "stale"
    return "dead"


def _build_rule_state(now=None, account_state=None, manual_review_context=None):
    """构建 rule_state；account_state 已获取时传入避免重复查询 DB"""
    from scripts.rule_engine import evaluate_rule_state as _eval
    inputs = _build_rule_inputs(now=now, account_state=account_state)
    if manual_review_context is not None:
        inputs["manual_review_context"] = manual_review_context
    state = _eval(inputs, now=now)
    trade_date = (now or datetime.now()).strftime("%Y-%m-%d")
    card_meta = (
        _execution_card_metadata(trade_date=trade_date)
        if trade_date == datetime.now().strftime("%Y-%m-%d")
        else {}
    )
    if card_meta.get("execution_card_stale"):
        gaps = list(state.get("source_gaps") or [])
        if "RULE_SNAPSHOT_STALE" not in gaps:
            gaps.append("RULE_SNAPSHOT_STALE")
        state["source_gaps"] = gaps
        if not any((item or {}).get("code") == "RULE_SNAPSHOT_STALE" for item in state.get("blocks") or []):
            state.setdefault("blocks", []).append({
                "code": "RULE_SNAPSHOT_STALE",
                "scope": "entry",
                "message": "执行卡规则快照与当前 compiled/source 不一致",
                "evidence": card_meta,
            })
    return state


def _execution_card_metadata(trade_date=None):
    card_path = AI_RULE_SYSTEM_ROOT / "daily-runtime" / "today_execution_card.json"
    if not card_path.exists():
        return {}
    try:
        card = json.loads(card_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    expected_trade_date = str(trade_date or datetime.now().strftime("%Y-%m-%d"))
    card_trade_date = str(card.get("next_trade_date") or "").strip()
    if card_trade_date and card_trade_date != expected_trade_date:
        return {
            "execution_card_stale": True,
            "execution_card_trade_date": card_trade_date,
            "expected_trade_date": expected_trade_date,
            "stale_reason": "RULE_SNAPSHOT_STALE",
        }
    snapshot = card.get("rule_snapshot") or card.get("rule_state") or card
    snapshot_hash = card.get("rule_snapshot_hash") or (
        "sha256:" + hashlib.sha256(_canonical_json(snapshot).encode("utf-8")).hexdigest()
    )
    trade_date = str(card.get("next_trade_date") or expected_trade_date).replace("-", "")
    generated = str(card.get("generated_at") or "")
    try:
        generated_id = datetime.fromisoformat(generated.replace("Z", "+00:00")).strftime("%Y%m%dT%H%M%S%z")
    except Exception:
        generated_id = datetime.fromtimestamp(card_path.stat().st_mtime).strftime("%Y%m%dT%H%M%S")
    result = {
        "rule_snapshot_hash": snapshot_hash,
        "today_execution_card_id": card.get("today_execution_card_id") or f"EXEC-{trade_date}-{generated_id}",
        "rule_pack_version": str((card.get("source_rule_pack") or {}).get("mtime") or ""),
    }
    compiled_meta = snapshot.get("compiled_rules") if isinstance(snapshot, dict) else None
    declared_compiled_path = Path(str((compiled_meta or {}).get("path") or ""))
    if not declared_compiled_path.is_absolute():
        declared_compiled_path = AI_RULE_SYSTEM_ROOT / declared_compiled_path
    compiled_path = (
        declared_compiled_path
        if declared_compiled_path.is_file()
        else AI_RULE_SYSTEM_ROOT / "compiled" / "rules.v1.json"
    )
    result["compiled_rules_path"] = str(compiled_path)
    expected_compiled_hash = (compiled_meta or {}).get("sha256") if isinstance(compiled_meta, dict) else None
    current_compiled_hash = None
    try:
        current_compiled_hash = hashlib.sha256(compiled_path.read_bytes()).hexdigest()
    except OSError:
        pass
    stale_details = []
    if not expected_compiled_hash or not current_compiled_hash or expected_compiled_hash != current_compiled_hash:
        stale_details.append({
            "kind": "compiled_hash",
            "expected": expected_compiled_hash,
            "actual": current_compiled_hash,
            "path": str(compiled_path),
        })
    rules = (compiled_meta or {}).get("rules") if isinstance(compiled_meta, dict) else None
    compiled_root = compiled_path.parent.parent
    unavailable_source_paths = []
    for rule in rules or []:
        for source in rule.get("source_doc_hashes") or []:
            path = Path(str(source.get("path") or ""))
            physical_path = path
            try:
                mapped_candidate = compiled_root / path.relative_to(AI_RULE_SYSTEM_ROOT)
            except ValueError:
                mapped_candidate = None
            if mapped_candidate is not None and mapped_candidate.is_file():
                physical_path = mapped_candidate
            expected = source.get("sha256")
            try:
                actual = hashlib.sha256(physical_path.read_bytes()).hexdigest()
            except OSError:
                actual = None
            if expected and actual is None:
                # Hermes deliberately deploys the immutable compiled bundle and
                # execution card, not the private Vault checkout. The compiled
                # artifact hash above authenticates its embedded source-hash
                # manifest; absent builder-only source paths are therefore a
                # provenance mode, not a stale runtime snapshot.
                unavailable_source_paths.append(str(path))
                continue
            if expected and actual != expected:
                stale_details.append({
                    "kind": "source_hash", "path": str(physical_path),
                    "canonical_path": str(path),
                    "expected": expected, "actual": actual,
                })
    if unavailable_source_paths:
        result.update({
            "source_verification": "compiled_bundle_hash_only",
            "unavailable_source_paths": sorted(set(unavailable_source_paths)),
        })
    if stale_details:
        result.update({
            "execution_card_stale": True,
            "stale_reason": "RULE_SNAPSHOT_STALE",
            "stale_details": stale_details,
        })
    return result


# ===== 快照构建（供 LLM 和调试端点使用） =====

def _build_trade_context():
    """构建今日在线成交的可信上下文。

    返回 dict：
    {rule_state, market_snapshot, context_captured_at, context_status, context_unavailable_reason}
    context_status: 'trusted' | 'unavailable'
    """
    result = {
        'rule_state': None,
        'market_snapshot': None,
        'context_captured_at': None,
        'context_status': 'unavailable',
        'context_unavailable_reason': None,
    }

    live_quotes = CACHE.get('live_quotes', {})
    updated = (live_quotes or {}).get('_updated')
    if not updated:
        result['context_unavailable_reason'] = '行情数据不可用'
        return result
    try:
        qt = datetime.fromisoformat(updated.replace('Z', '+00:00'))
        age = (datetime.now().astimezone() - qt).total_seconds()
        if age > 600:
            result['context_unavailable_reason'] = '行情数据不可用'
            return result
    except (ValueError, TypeError):
        result['context_unavailable_reason'] = '行情数据不可用'
        return result

    # 构建规则状态和市场快照
    rule = _build_rule_state()
    iwencai = CACHE.get('iwencai', {}) or {}
    live_index = CACHE.get('live_index', {})
    mkt = {
        'iwencai': {'情绪值': iwencai.get('情绪值', '—')},
        'live_index': {
            '上证指数涨幅': live_index.get('上证指数涨幅', '—'),
            '深证指数涨幅': live_index.get('深证指数涨幅', '—'),
        },
    }

    # 检查 rule_state 中是否存在不可信阻断块
    blocks = (rule or {}).get('blocks', [])
    untrusted_codes = {'DATA_UNTRUSTED', 'SENTIMENT_STALE', 'QUOTE_STALE'}
    untrusted = [b for b in blocks if b.get('code') in untrusted_codes]
    if untrusted:
        codes = ','.join(b.get('code', '?') for b in untrusted)
        result['context_unavailable_reason'] = f'行情数据不可信 ({codes})'
        return result

    card_meta = _execution_card_metadata(trade_date=datetime.now().strftime("%Y-%m-%d"))

    # 全部检查通过 → trusted
    captured = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    result.update({
        'rule_state': rule,
        'market_snapshot': mkt,
        'context_captured_at': captured,
        'context_status': 'trusted',
        'rule_pack_version': (rule or {}).get('version') or card_meta.get('rule_pack_version'),
        'rule_snapshot_hash': card_meta.get('rule_snapshot_hash'),
        'today_execution_card_id': card_meta.get('today_execution_card_id'),
    })
    return result


def _send_json(handler, status, payload):
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json')
    handler.end_headers()
    handler.wfile.write(json.dumps(payload, ensure_ascii=False).encode())


def _blocking_codes_for_ticket(rule_state, action_type, window):
    if action_type in ("sell", "reduce", "clear"):
        return []
    blocks = []
    for block in (rule_state or {}).get("blocks") or []:
        scope = str(block.get("scope") or "")
        code = block.get("code")
        if not code:
            continue
        if scope == "all":
            blocks.append(code)
        elif action_type in ("buy", "add") and window and scope.lower() == str(window).lower():
            blocks.append(code)
    if action_type in ("buy", "add") and window:
        wkey = str(window).lower()
        win = ((rule_state or {}).get("windows") or {}).get(wkey) or {}
        for code in win.get("blocks") or []:
            if code not in blocks:
                blocks.append(code)
    return blocks


def _guarded_experiment_request(payload, code):
    """Extract a candidate-scoped guarded recommendation without granting execution."""
    recommendation = (payload or {}).get("recommendation_state")
    if not isinstance(recommendation, dict):
        return None
    if recommendation.get("schema_version") != "recommendation_state.v1":
        return None
    candidates = recommendation.get("candidates")
    if not isinstance(candidates, list):
        candidates = []
    candidate = recommendation.get("candidate")
    if not isinstance(candidate, dict):
        candidate = next(
            (item for item in candidates if isinstance(item, dict) and str(item.get("code") or "") == str(code)),
            None,
        )
    if not isinstance(candidate, dict):
        return None
    if str(candidate.get("code") or code) != str(code):
        return None
    if candidate.get("disposition") != "guarded_experiment":
        return None
    return recommendation, candidate


def _candidate_hard_gaps(recommendation, candidate):
    values = [
        *(str(item) for item in (candidate.get("blocking_codes") or [])),
        *(str(item) for item in (candidate.get("source_gaps") or [])),
    ]
    candidate_code = str(candidate.get("code") or "").strip()
    candidate_side = str(
        candidate.get("side") or candidate.get("source") or candidate.get("role") or ""
    ).strip().lower()
    for item in recommendation.get("source_gaps") or []:
        value = str(item).strip()
        lowered = value.lower()
        if lowered.startswith("candidate_hard:"):
            parts = value.split(":", 2)
            if len(parts) >= 2 and parts[1].strip() == candidate_code:
                values.append(value)
        elif lowered.startswith("side_hard:"):
            parts = value.split(":", 2)
            affected_side = parts[1].strip().lower() if len(parts) >= 2 else ""
            if affected_side and (
                candidate_side == affected_side
                or candidate_side.startswith(f"{affected_side}_")
            ):
                values.append(value)
        elif lowered.startswith("global_hard:"):
            values.append(value)
        elif not lowered.startswith(
            (
                "candidate_soft:",
                "side_soft:",
                "global_soft:",
                "advisory:",
                "missing_rule_input:",
            )
        ):
            values.append(value)
    values.extend(
        str(item)
        for item in (candidate.get("missing_evidence") or [])
        if str(item).lower().startswith(
            ("candidate_hard:", "side_hard:", "global_hard:")
        )
    )
    soft_prefixes = (
        "candidate_soft:",
        "side_soft:",
        "global_soft:",
        "advisory:",
        "missing_rule_input:",
    )
    return list(dict.fromkeys(
        value for value in values
        if value and not value.lower().startswith(soft_prefixes)
    ))


def _prepare_trade_ticket(payload):
    from scripts.db import (
        create_trade_ticket,
        query_trade_ticket,
        query_trade_tickets,
        get_sellable_qty,
        get_sellable_lots,
    )

    allowed = {"buy", "sell", "add", "reduce", "do_t", "clear", "observe"}
    exit_actions = {"sell", "reduce", "clear"}
    action_type = str((payload or {}).get("action_type") or "").strip()
    ticket_purpose = str((payload or {}).get("ticket_purpose") or "execution").strip()
    if ticket_purpose not in {"execution", "post_trade_reconciliation"}:
        raise ValueError(f"invalid ticket_purpose: {ticket_purpose}")
    if action_type == "t":
        raise ValueError("action_type=t is not accepted; use do_t")
    if action_type not in allowed:
        raise ValueError(f"invalid action_type: {action_type}")
    code = str((payload or {}).get("code") or "").strip()
    name = str((payload or {}).get("name") or "").strip()
    if not code:
        raise ValueError("code is required")

    ctx = _build_trade_context()
    rule_state = ctx.get("rule_state") or {}
    market_snapshot = ctx.get("market_snapshot") or {}
    account_state = _load_current_account_state(CACHE.get("live_quotes", {}))
    trade_date = str(account_state.get("date") or datetime.now().strftime("%Y-%m-%d"))
    account_snapshot = ctx.get("account_snapshot") or {
        "account_day_return_pct": account_state.get("account_day_return_pct", account_state.get("pnl_pct")),
        "lot_reconciliation_ok": account_state.get("lot_reconciliation_ok"),
    }

    window = str((payload or {}).get("window") or "").strip()
    blocking_rule_ids = _blocking_codes_for_ticket(rule_state, action_type, window)
    missing_data = []
    guarded_request = _guarded_experiment_request(payload, code)
    guarded_policy = None
    guarded_request_blocks = []
    if guarded_request:
        recommendation_state, guarded_candidate = guarded_request
        guarded_max = guarded_candidate.get("max_position_pct", 5)
        try:
            guarded_max = float(guarded_max)
        except (TypeError, ValueError):
            guarded_max = None
        if guarded_max is None or not 2 <= guarded_max <= 5:
            guarded_request_blocks.append("GUARDED_CAP_INVALID")
        if action_type != "buy":
            guarded_request_blocks.append("GUARDED_FIRST_ENTRY_ONLY")
        if recommendation_state.get("hard_gate_override") is True or guarded_candidate.get("hard_gate_override") is True:
            guarded_request_blocks.append("GUARDED_OVERRIDE_FORBIDDEN")
        candidate_hard_gaps = _candidate_hard_gaps(recommendation_state, guarded_candidate)
        guarded_request_blocks.extend(candidate_hard_gaps)
        existing_guarded = query_trade_tickets(
            date_from=trade_date,
            date_to=trade_date,
            status="guarded_experiment",
            limit=1000,
        )
        existing_codes = {str(item.get("code") or "") for item in existing_guarded}
        if str(code) in existing_codes:
            guarded_request_blocks.append("GUARDED_SAME_DAY_SECOND_LEG")
        elif len(existing_codes) >= 1:
            guarded_request_blocks.append("GUARDED_DAILY_NAME_CAP")
        current_total = (
            guarded_candidate.get("current_total_position_pct")
            if guarded_candidate.get("current_total_position_pct") is not None
            else (payload or {}).get("current_total_position_pct")
        )
        try:
            if current_total is not None and float(current_total) + float(guarded_max or 0) > 10:
                guarded_request_blocks.append("GUARDED_TOTAL_CAP")
        except (TypeError, ValueError):
            guarded_request_blocks.append("GUARDED_TOTAL_CAP_INVALID")
        guarded_policy = {
            "ticket_status": "guarded_experiment",
            "max_position_pct": (
                int(guarded_max) if guarded_max is not None and float(guarded_max).is_integer()
                else guarded_max
            ),
            "guarded_total_cap_pct": 10,
            "new_guarded_names_today": len(existing_codes) + (0 if str(code) in existing_codes else 1),
            "max_new_guarded_names_per_day": 1,
            "same_day_add_allowed": False,
            "human_confirmation_required": True,
            "hard_gate_override": False,
            "candidate_gap_scope": "candidate",
            "candidate_gap_severity": "soft" if not candidate_hard_gaps else "hard",
            "blocking_codes": list(guarded_request_blocks),
        }
        if guarded_request_blocks:
            blocking_rule_ids.extend(guarded_request_blocks)
    target_role = str((payload or {}).get("role") or (payload or {}).get("target_role") or "").strip()
    position_evidence = (payload or {}).get("position_evidence")
    if not isinstance(position_evidence, dict):
        evidence_fields = (
            "entry_leg", "first_entry_trade_date", "trading_days_since_first_entry",
            "leg1_or_leg2_floating_pnl", "leg2_already_used", "volume_ratio",
            "pullback_ma_status", "sector_inflow_status", "sector_inflow_query_time",
            "planned_single_stock_cap_pct", "current_single_stock_pct",
            "acceleration_segment_confirmed",
        )
        position_evidence = {
            field: (payload or {}).get(field) for field in evidence_fields
            if field in (payload or {})
        }
    from scripts.rule_engine import evaluate_decision_gate, evaluate_position_evidence
    position_evaluation = evaluate_position_evidence(action_type, position_evidence)
    if position_evaluation.get("allowed") is False:
        blocking_rule_ids.append(position_evaluation.get("code") or "POS-SIZE-008")
        for field in position_evaluation.get("missing_fields") or []:
            missing_data.append({
                "field": field,
                "message": f"POS-SIZE-008 missing required evidence: {field}",
            })
    ticket_rule_state = dict(rule_state)
    ticket_rule_state["position_evidence"] = {
        **position_evaluation,
        "entry_leg": position_evidence.get("entry_leg"),
    }
    ticket_rule_state["ticket_context"] = {
        "role": target_role or None,
        "entry_leg": position_evidence.get("entry_leg"),
        "position_evidence": position_evidence,
    }
    if guarded_policy is not None:
        ticket_rule_state["guarded_experiment"] = guarded_policy
        ticket_rule_state["recommendation_state"] = guarded_request[0]
    action_gate = evaluate_decision_gate(
        action_type,
        window,
        target_role,
        position_evidence.get("entry_leg"),
        {"trade_entry_allowed": ctx.get("context_status") == "trusted"},
        ticket_rule_state,
    )
    blocking_rule_ids.extend(action_gate.get("blocking_codes") or [])
    leg_type = "sell_reduce" if action_type == "reduce" else action_type
    sellable_qty = None
    t1_risk = {}
    qty = (payload or {}).get("qty")
    try:
        qty = int(qty) if qty is not None else None
    except (TypeError, ValueError):
        raise ValueError("qty must be an integer when provided")

    if action_type in ("sell", "reduce", "do_t", "clear"):
        positions = account_state.get("positions") or []
        pos = next((p for p in positions if str(p.get("代码") or "") == code), None)
        if pos and pos.get("sellable_qty") is not None:
            sellable_qty = int(pos.get("sellable_qty") or 0)
        else:
            sellable_qty = get_sellable_qty(code, trade_date)
        if qty is not None and qty > sellable_qty:
            blocking_rule_ids.append("sellable_qty")
            missing_data.append({
                "field": "sellable_qty",
                "message": f"requested qty {qty} exceeds sellable_qty {sellable_qty}",
            })
        sellable_lots = get_sellable_lots(code, trade_date)
        requested_target = str((payload or {}).get("target_lot_id") or "").strip()
        target_lot_mode = "explicit" if requested_target else ""
        if not requested_target and qty:
            intent_text = " ".join([
                str((payload or {}).get("intent_text") or ""),
                str((payload or {}).get("human_override_reason") or ""),
            ])
            wants_add_lot = any(key in intent_text for key in ("加仓", "W2", "尾盘", "做T", "T出", "锁利"))
            if wants_add_lot:
                candidates = [
                    lot for lot in sellable_lots
                    if str(lot.get("lot_id") or "").startswith("trade:")
                    or str(lot.get("lot_source") or "") == "trade_record"
                ]
                candidates = [lot for lot in candidates if int(lot.get("open_qty") or 0) >= qty]
                if candidates:
                    requested_target = str(candidates[-1].get("lot_id") or "")
                    target_lot_mode = "inferred_add_lot"
        if requested_target:
            target_lot = next((lot for lot in sellable_lots if str(lot.get("lot_id") or "") == requested_target), None)
            if not target_lot:
                blocking_rule_ids.append("target_lot")
                missing_data.append({
                    "field": "target_lot_id",
                    "message": f"target lot {requested_target} is not sellable for {code} on {trade_date}",
                })
            elif qty is not None and qty > int(target_lot.get("open_qty") or 0):
                blocking_rule_ids.append("target_lot")
                missing_data.append({
                    "field": "target_lot_id",
                    "message": f"requested qty {qty} exceeds target lot open_qty {target_lot.get('open_qty')}",
                })
            else:
                account_qty = int(float(str((pos or {}).get("数量") or 0).replace("股", ""))) if pos else 0
                locked_qty = int((pos or {}).get("locked_qty") or 0) if pos else 0
                lot_total = int(sellable_qty or 0) + locked_qty
                t1_risk.update({
                    "target_lot_id": requested_target,
                    "target_lot_mode": target_lot_mode or "explicit",
                    "target_lot_open_qty": int(target_lot.get("open_qty") or 0),
                    "target_lot_cost_price": target_lot.get("cost_price"),
                    "account_effect": "realized_pnl_only" if account_qty < lot_total else "normal",
                })
    if action_type in ("buy", "add", "do_t") and account_state.get("lot_reconciliation_ok") is False:
        blocking_rule_ids.append("lot_reconciliation")
    if action_type in ("buy", "add", "do_t"):
        if account_state.get("anchor_missing") or account_state.get("anchor_blocked") or account_state.get("anchor_trusted") is False:
            blocking_rule_ids.append("account_anchor")
        if str(account_state.get("quote_status") or "").lower() in {"stale", "dead", "missing"}:
            blocking_rule_ids.append("quote_freshness")

    context_degraded = False
    if ctx.get("context_status") != "trusted":
        blocking_rule_ids.append("context_status")
        context_degraded = action_type in exit_actions
    audit_degraded = False
    trade_time = str((payload or {}).get("trade_time") or "").strip()
    if trade_time and _snapshot_captured_after_trade(trade_date, trade_time, ctx.get("context_captured_at")):
        blocking_rule_ids.append("snapshot_captured_after_trade")
        audit_degraded = True
    rule_snapshot_hash = ctx.get("rule_snapshot_hash")
    today_execution_card_id = ctx.get("today_execution_card_id")
    if action_type in ("buy", "add", "do_t") and (not rule_snapshot_hash or not today_execution_card_id):
        blocking_rule_ids.append("rule_snapshot_hash")

    blocking_rule_ids = list(dict.fromkeys(blocking_rule_ids))
    human_override_reason = str((payload or {}).get("human_override_reason") or "").strip()
    if ticket_purpose == "post_trade_reconciliation":
        if not trade_time:
            raise ValueError("post_trade_reconciliation requires trade_time")
        if not human_override_reason:
            raise ValueError("post_trade_reconciliation requires human_override_reason")
    hard_blocks = [
        code for code in blocking_rule_ids
        if not (ticket_purpose == "post_trade_reconciliation" and code == "snapshot_captured_after_trade")
        and not (context_degraded and code == "context_status")
    ]
    non_overridable_blocks = {"context_status", "rule_snapshot_hash", "sellable_qty", "lot_reconciliation"}
    has_non_overridable_blocks = any(code in non_overridable_blocks for code in hard_blocks)
    override_to_audit = (
        ticket_purpose == "post_trade_reconciliation"
        and
        audit_degraded
        and human_override_reason
        and hard_blocks
        and not has_non_overridable_blocks
    )
    wkey = str(window or "").lower()
    win_state = ((rule_state or {}).get("windows") or {}).get(wkey) or {}
    manual_review_candidate = (
        action_type in ("buy", "add")
        and bool(hard_blocks)
        and win_state.get("manual_review_allowed") is True
        and not has_non_overridable_blocks
    )
    guarded_candidate_ready = (
        guarded_policy is not None
        and action_type == "buy"
        and not hard_blocks
        and guarded_policy.get("candidate_gap_severity") == "soft"
    )
    if ticket_purpose == "post_trade_reconciliation":
        status = "reconciliation_ready"
    else:
        status = (
            "blocked" if hard_blocks and not (override_to_audit or manual_review_candidate)
            else (
                "audit_degraded" if audit_degraded or context_degraded or override_to_audit
                else (
                    "guarded_experiment" if guarded_candidate_ready
                    else ("manual_review" if manual_review_candidate else ("draft" if action_type == "observe" else "executable"))
                )
            )
        )

    ticket_id = create_trade_ticket({
        "trade_date": trade_date,
        "code": code,
        "name": name,
        "action_type": action_type,
        "ticket_purpose": ticket_purpose,
        "status": status,
        "window": window,
        "trade_time": trade_time or None,
        "intent_text": (payload or {}).get("intent_text"),
        "rule_state_json": ticket_rule_state,
        "market_snapshot_json": market_snapshot,
        "account_snapshot_json": account_snapshot,
        "max_qty": qty,
        "stop_line": (payload or {}).get("stop_line"),
        "expected_r": (payload or {}).get("expected_r"),
        "missing_data_json": missing_data,
        "blocking_rule_ids_json": blocking_rule_ids,
        "triggered_rule_ids_json": (payload or {}).get("triggered_rule_ids") or [],
        "account_day_return_pct": account_snapshot.get("account_day_return_pct"),
        "sellable_quantity": sellable_qty,
        "t1_risk_json": t1_risk,
        "rule_pack_version": ctx.get("rule_pack_version"),
        "rule_snapshot_hash": rule_snapshot_hash,
        "today_execution_card_id": today_execution_card_id,
        "human_override_reason": human_override_reason,
    })
    ticket = query_trade_ticket(ticket_id)
    ticket["leg_type"] = leg_type
    return ticket


def _close_trade_ticket(ticket_id, payload):
    from scripts.db import query_trade_ticket, update_trade_ticket_status

    ticket_id = str(ticket_id or "").strip()
    if not ticket_id:
        raise ValueError("ticket_id required")
    ticket = query_trade_ticket(ticket_id)
    if not ticket:
        raise LookupError(f"ticket not found: {ticket_id}")

    status = str((payload or {}).get("status") or "closed").strip()
    if status not in {"closed", "cancelled", "closed_with_conflict"}:
        raise ValueError(f"invalid close status: {status}")
    close_reason = str((payload or {}).get("close_reason") or "").strip()
    if not close_reason:
        raise ValueError("close_reason required")
    review_note = str((payload or {}).get("review_note") or "").strip() or None

    if str(ticket.get("status") or "") == "filled":
        raise ValueError("filled ticket cannot be closed manually")
    ok = update_trade_ticket_status(
        ticket_id,
        status,
        close_reason=close_reason,
        review_note=review_note,
    )
    if not ok:
        raise LookupError(f"ticket not found: {ticket_id}")
    return query_trade_ticket(ticket_id)


def _snapshot_captured_after_trade(trade_date, trade_time, context_captured_at, grace_minutes=5):
    if not trade_date or not trade_time or not context_captured_at:
        return False
    try:
        trade_dt = datetime.fromisoformat(f"{trade_date}T{trade_time}:00" if len(trade_time) == 5 else f"{trade_date}T{trade_time}")
        captured = datetime.fromisoformat(str(context_captured_at).replace("Z", "+00:00"))
        if captured.tzinfo is not None:
            captured = captured.replace(tzinfo=None)
        if trade_dt.tzinfo is not None:
            trade_dt = trade_dt.replace(tzinfo=None)
    except Exception:
        return False
    return (captured - trade_dt).total_seconds() > grace_minutes * 60


def _canonical_json(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _ticket_live_price(ticket):
    code = str((ticket or {}).get("code") or "")
    quote = (CACHE.get("live_quotes") or {}).get(code) or {}
    for key in ("最新价", "现价", "price"):
        try:
            price = float(quote.get(key) or 0)
        except (TypeError, ValueError):
            price = 0
        if price > 0:
            return price
    return None


def _auto_fill_input_from_ticket(ticket):
    action_type = str((ticket or {}).get("action_type") or "")
    qty = (ticket or {}).get("max_qty") or (ticket or {}).get("qty")
    try:
        qty = int(qty)
    except (TypeError, ValueError):
        qty = 0
    if qty <= 0:
        raise ValueError("ticket qty required for automatic fill preview")
    price = _ticket_live_price(ticket)
    if not price:
        raise ValueError("live quote price required for automatic fill preview")
    verb = "已卖" if action_type in {"sell", "reduce", "clear"} else "已买"
    name = (ticket or {}).get("name") or (ticket or {}).get("code") or ""
    return f"{verb} {name} {qty}股 {price:.2f}", "auto_from_ticket_live_quote"


def _parse_fill_input(input_text, ticket):
    import re
    text = str(input_text or "")
    action = "卖出" if "卖" in text else "买入" if "买" in text else ""
    if not action:
        raise ValueError("input_text must include 已买 or 已卖")
    qty_match = re.search(r"(\d+)\s*股", text)
    nums = re.findall(r"\d+(?:\.\d+)?", text)
    if not qty_match or not nums:
        raise ValueError("input_text must include qty and price")
    qty = int(qty_match.group(1))
    price_candidates = [float(n) for n in nums if int(float(n)) != qty or "." in n]
    price = price_candidates[-1] if price_candidates else float(nums[-1])
    action_type = str(ticket.get("action_type") or "")
    if action == "卖出":
        t1_risk = ticket.get("t1_risk") or {}
        target_lot_id = str(t1_risk.get("target_lot_id") or "").strip()
        account_effect = str(t1_risk.get("account_effect") or "").strip()
        if target_lot_id and account_effect == "realized_pnl_only":
            leg_type = "sell_target_lot_realized_pnl_only"
        elif target_lot_id:
            leg_type = "sell_target_lot"
        else:
            leg_type = "sell_t_old_lot" if action_type in ("do_t", "reduce", "sell") else "sell"
    else:
        leg_type = "buy_add" if action_type in ("add", "buy") else "buy"
    trade_time = datetime.now().strftime("%H:%M:%S")
    if str(ticket.get("ticket_purpose") or "") == "post_trade_reconciliation":
        declared_trade_time = str(ticket.get("trade_time") or "").strip()
        if declared_trade_time:
            trade_time = declared_trade_time
    parsed = {
        "时间": trade_time,
        "动作": action,
        "代码": ticket.get("code"),
        "标的": ticket.get("name"),
        "价格": price,
        "数量": qty,
        "ticket_id": ticket.get("ticket_id"),
        "leg_type": leg_type,
        "input_source": "spoken_confirmed",
        "input_text": text,
    }
    if action == "卖出":
        t1_risk = ticket.get("t1_risk") or {}
        target_lot_id = str(t1_risk.get("target_lot_id") or "").strip()
        account_effect = str(t1_risk.get("account_effect") or "").strip()
        if target_lot_id:
            parsed["target_lot_id"] = target_lot_id
        if account_effect:
            parsed["account_effect"] = account_effect
    return parsed


def _ticket_can_accept_fills(ticket):
    return str((ticket or {}).get("status") or "") in {
        "executable", "confirmed", "partially_filled", "audit_degraded", "reconciliation_ready"
    }


def _ticket_fill_gate(ticket):
    purpose = str((ticket or {}).get("ticket_purpose") or "execution")
    action_type = str((ticket or {}).get("action_type") or "")
    if purpose == "post_trade_reconciliation":
        return True, None, None
    if action_type not in {"buy", "add", "do_t"}:
        return True, None, {
            "schema_version": "decision_gate.v1",
            "allowed": True,
            "reason": None,
            "blocking_codes": [],
            "action_type": action_type,
        }
    context = _build_ai_context()
    rule_state = (context or {}).get("rule_state")
    health = (context or {}).get("health")
    if isinstance(rule_state, dict) and isinstance(health, dict):
        from scripts.rule_engine import evaluate_decision_gate, evaluate_position_evidence
        ticket_rule = (ticket or {}).get("rule_state") or {}
        ticket_context = ticket_rule.get("ticket_context") or {}
        position_result = evaluate_position_evidence(
            action_type, ticket_context.get("position_evidence")
        )
        current_rule = dict(rule_state)
        current_rule["position_evidence"] = {
            **position_result,
            "entry_leg": ticket_context.get("entry_leg"),
        }
        gate = evaluate_decision_gate(
            action_type,
            (ticket or {}).get("window"),
            ticket_context.get("role"),
            ticket_context.get("entry_leg"),
            health,
            current_rule,
        )
        return gate["allowed"], gate.get("reason"), gate
    gate = (context or {}).get("decision_gate") or {}
    allowed = gate.get("allowed") is True
    reason = gate.get("reason") or "final decision gate is not available"
    return allowed, reason, gate


def _create_fill_preview(payload):
    import hashlib
    import secrets
    import uuid
    from scripts.db import query_trade_ticket, get_conn

    ticket_id = str((payload or {}).get("ticket_id") or "")
    input_text = str((payload or {}).get("input_text") or "")
    input_source = "spoken_confirmed"
    ticket = query_trade_ticket(ticket_id)
    if not ticket:
        raise ValueError(f"ticket not found: {ticket_id}")
    if not _ticket_can_accept_fills(ticket):
        raise ValueError(f"ticket {ticket_id} cannot accept fills in status {ticket.get('status')}")
    gate_allowed, gate_reason, _ = _ticket_fill_gate(ticket)
    if not gate_allowed:
        raise ValueError(f"decision gate blocked: {gate_reason}")
    if not input_text.strip():
        input_text, input_source = _auto_fill_input_from_ticket(ticket)
    parsed = _parse_fill_input(input_text, ticket)
    parsed["input_source"] = input_source
    parsed["input_text"] = input_text
    if str(ticket.get("ticket_purpose") or "execution") == "post_trade_reconciliation":
        parsed["input_source"] = "post_trade_reconciliation"
    confirmation_id = f"CONFIRM-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:10]}"
    preview_token = secrets.token_urlsafe(24)
    preview_hash = "sha256:" + hashlib.sha256(
        (ticket_id + input_text + _canonical_json(parsed) + preview_token).encode("utf-8")
    ).hexdigest()
    now = datetime.now()
    expires_at = (now + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S")
    conn = get_conn()
    conn.execute("""
        INSERT INTO pending_fill_confirmations
        (confirmation_id, created_at, expires_at, ticket_id, input_text,
         parsed_entry_json, preview_token, preview_hash, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (confirmation_id, now.strftime("%Y-%m-%dT%H:%M:%S"), expires_at,
          ticket_id, input_text, json.dumps(parsed, ensure_ascii=False),
          preview_token, preview_hash, "pending"))
    conn.commit()
    return {
        "parsed": {
            "action": parsed["动作"],
            "code": parsed["代码"],
            "name": parsed["标的"],
            "price": parsed["价格"],
            "qty": parsed["数量"],
            "leg_type": parsed["leg_type"],
            "input_source": parsed.get("input_source"),
            **({"target_lot_id": parsed["target_lot_id"]} if parsed.get("target_lot_id") else {}),
            **({"account_effect": parsed["account_effect"]} if parsed.get("account_effect") else {}),
        },
        "requires_confirmation": True,
        "confirmation_id": confirmation_id,
        "preview_token": preview_token,
        "preview_hash": preview_hash,
    }


def _confirm_fill(payload, headers):
    from scripts.db import get_conn, close_conn, record_confirmed_fill

    allowed_actors = {"yimu", "agent:oumi", "agent:yangmi", "manual_backfill", "correction"}
    confirmed_by = str((payload or {}).get("confirmed_by") or "")
    if confirmed_by not in allowed_actors:
        return 403, {"ok": False, "error": f"unknown confirmed_by: {confirmed_by}"}
    if confirmed_by.startswith("agent:"):
        actor_header = headers.get("X-YM-Confirm-Actor")
        if actor_header != confirmed_by:
            return 403, {"ok": False, "error": "X-YM-Confirm-Actor mismatch"}

    confirmation_id = str((payload or {}).get("confirmation_id") or "")
    preview_token = str((payload or {}).get("preview_token") or "")
    preview_hash = str((payload or {}).get("preview_hash") or "")
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM pending_fill_confirmations WHERE confirmation_id = ?",
        (confirmation_id,),
    ).fetchone()
    if not row:
        return 404, {"ok": False, "error": "confirmation not found"}
    pending = dict(row)
    if pending.get("status") != "pending":
        return 409, {"ok": False, "error": f"confirmation status is {pending.get('status')}"}
    if str(pending.get("preview_token") or "") != preview_token:
        return 409, {"ok": False, "error": "preview_token mismatch"}
    if str(pending.get("preview_hash") or "") != preview_hash:
        return 409, {"ok": False, "error": "preview_hash mismatch"}
    if str(pending.get("expires_at") or "") < datetime.now().strftime("%Y-%m-%dT%H:%M:%S"):
        return 409, {"ok": False, "error": "confirmation expired"}
    ticket_row = conn.execute(
        "SELECT * FROM trade_tickets WHERE ticket_id = ?",
        (pending["ticket_id"],),
    ).fetchone()
    ticket = dict(ticket_row) if ticket_row else None
    if not ticket or not _ticket_can_accept_fills(ticket):
        return 409, {"ok": False, "error": "ticket cannot accept fills"}
    purpose = str(ticket.get("ticket_purpose") or "execution")
    if purpose == "post_trade_reconciliation" and confirmed_by != "yimu":
        return 403, {"ok": False, "error": "post_trade_reconciliation requires confirmed_by=yimu"}
    gate_allowed, gate_reason, gate = _ticket_fill_gate(ticket)
    if not gate_allowed:
        return 409, {
            "ok": False,
            "error": f"decision gate blocked: {gate_reason}",
            "decision_gate": gate,
        }
    parsed = json.loads(pending.get("parsed_entry_json") or "{}")
    parsed["confirmed_by"] = confirmed_by
    parsed["audit_note"] = f"confirmed via {confirmation_id}"
    parsed["event_id"] = confirmation_id
    ctx = _build_trade_context()
    close_conn()
    try:
        result = record_confirmed_fill(
            parsed,
            rule_state=ctx.get("rule_state"),
            market_snapshot=ctx.get("market_snapshot"),
            confirmation={
                "context_captured_at": ctx.get("context_captured_at"),
                "context_status": ctx.get("context_status"),
                "context_unavailable_reason": ctx.get("context_unavailable_reason"),
            },
        )
    except ValueError as e:
        return 409, {"ok": False, "error": str(e)}
    conn = get_conn()
    now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    conn.execute(
        "UPDATE pending_fill_confirmations SET status = 'confirmed', confirmed_at = ?, confirmed_by = ? WHERE confirmation_id = ?",
        (now_str, confirmed_by, confirmation_id),
    )
    # Auto-cancel other pending confirmations for the same ticket
    cancelled = conn.execute(
        "UPDATE pending_fill_confirmations SET status = 'cancelled_superseded' "
        "WHERE ticket_id = ? AND status = 'pending' AND confirmation_id != ?",
        (pending["ticket_id"], confirmation_id),
    ).rowcount
    if cancelled:
        conn.execute(
            "UPDATE pending_fill_confirmations SET confirmed_at = ? WHERE "
            "ticket_id = ? AND status = 'cancelled_superseded' AND confirmed_at IS NULL",
            (now_str, pending["ticket_id"]),
        )
    conn.commit()
    _refresh_stock_codes()
    return 200, {"ok": True, **result}


def _load_dashboard_data():
    """读取 dashboard_data.json，带缓存避免重复读盘"""
    try:
        if DATA_FILE.exists():
            with open(DATA_FILE) as f:
                return _repair_dashboard_pool_rows(json.load(f))
    except Exception:
        pass
    return {}


def _baseline_payload(now=None):
    """Return baseline data with live risk overlays for fields known to go stale.

    dashboard_data.json is a D-1 baseline and can miss close/open refreshes.
    Keep the baseline content, but never expose stale account-risk gates such as
    loss streak when pnl.db can derive a fresher value.
    """
    from datetime import datetime as _dt

    now = now or _dt.now()
    raw = _load_dashboard_data()
    result = json.loads(json.dumps(raw, ensure_ascii=False)) if isinstance(raw, dict) else {}
    meta = result.setdefault('meta', {})
    risk = result.setdefault('risk', {})

    today = now.strftime("%Y-%m-%d")
    meta['_served_date'] = today
    meta['_baseline_stale'] = not _baseline_generated_today(meta, today)

    try:
        _refresh_stock_codes(result)
    except Exception:
        pass

    try:
        rule_inputs = _build_rule_inputs(now=now)
        rule_risk = (rule_inputs.get('risk') or {})
        live_loss_streak = rule_risk.get('losing_account_days')
        if live_loss_streak is not None:
            legacy = risk.get('连亏天数')
            risk['连亏天数'] = int(live_loss_streak)
            risk['_source'] = 'rule_inputs_live_overlay'
            if legacy is not None and int(legacy or 0) != int(live_loss_streak):
                risk['_legacy_连亏天数'] = legacy
        if rule_risk.get('weekly_drawdown_pct') is not None:
            risk['周累计回撤'] = rule_risk.get('weekly_drawdown_pct')
        if rule_risk.get('monthly_drawdown_pct') is not None:
            risk['月累计回撤'] = rule_risk.get('monthly_drawdown_pct')
    except Exception as e:
        risk['_overlay_error'] = str(e)[:120]

    return _add_freshness(result, 'baseline', meta.get('updated') or meta.get('date'))


def _format_pct_for_live_index(value):
    if value in (None, '', '—'):
        return None
    s = str(value).strip()
    if s.endswith('%'):
        return s if s.startswith(('+', '-')) else f'+{s}'
    try:
        n = float(s)
    except (TypeError, ValueError):
        return s
    return f'{n:+.2f}%'


def _format_amount_for_live_index(value):
    if value in (None, '', '—'):
        return None
    s = str(value).strip()
    if '万亿' in s or s.endswith('亿'):
        return s
    try:
        n = float(s)
    except (TypeError, ValueError):
        return s
    if n < 100:
        return f'{n:g}万亿'
    if n >= 10000:
        return f'{n / 10000:.2f}万亿'
    return f'{n:g}亿'


def _parse_up_down_ratio(value):
    if not value:
        return None, None
    parts = str(value).replace('：', '/').split('/')
    if len(parts) != 2:
        return None, None
    try:
        return int(float(parts[0])), int(float(parts[1]))
    except (TypeError, ValueError):
        return None, None


def _live_index_with_baseline():
    """Return live_index with dashboard close baseline as post-restart fallback.

    After market close, collectors stop. If the bridge restarts, in-memory
    live_index may be empty while dashboard_data.json still has the close
    baseline. W04 should continue showing the close state instead of blanks.
    """
    li = dict(CACHE.get('live_index') or {})
    market = (_load_dashboard_data().get('market') or {})

    def fill(target, *sources, transform=None):
        if li.get(target) not in (None, '', '—'):
            return
        for source in sources:
            raw = market.get(source)
            if raw not in (None, '', '—'):
                li[target] = transform(raw) if transform else raw
                li.setdefault('_source', 'baseline_close_fallback')
                return

    fill('上证指数', '上证指数')
    fill('上证指数涨幅', '上证指数涨幅', '上证涨幅', transform=_format_pct_for_live_index)
    fill('上证指数振幅', '上证指数振幅', '上证振幅', transform=_format_pct_for_live_index)
    fill('上证指数成交额', '上证指数成交额', '上证成交额', '市场量能', transform=_format_amount_for_live_index)
    fill('成交额', '成交额', '市场量能', transform=_format_amount_for_live_index)
    fill('深证指数', '深证指数', '深圳指数')
    fill('深证指数涨幅', '深证指数涨幅', '深证涨幅', '深圳涨幅', transform=_format_pct_for_live_index)
    fill('深证指数振幅', '深证指数振幅', '深证振幅', '深圳振幅', transform=_format_pct_for_live_index)
    fill('深证指数成交额', '深证指数成交额', '深证成交额', '深圳成交额', transform=_format_amount_for_live_index)
    fill('创业指数', '创业指数', '创业板指', '创业板指数')
    fill('创业指数涨幅', '创业指数涨幅', '创业板指涨幅', '创业涨幅', '创业板涨幅', transform=_format_pct_for_live_index)
    fill('创业指数振幅', '创业指数振幅', '创业板指振幅', '创业振幅', '创业板振幅', transform=_format_pct_for_live_index)
    fill('创业指数成交额', '创业指数成交额', '创业板成交额', '创业成交额', transform=_format_amount_for_live_index)

    up, down = _parse_up_down_ratio(market.get('涨跌比'))
    if li.get('上涨家数') in (None, '', '—') and up is not None:
        li['上涨家数'] = up
        li.setdefault('_source', 'baseline_close_fallback')
    if li.get('下跌家数') in (None, '', '—') and down is not None:
        li['下跌家数'] = down
        li.setdefault('_source', 'baseline_close_fallback')
    if li.get('_updated') in (None, '', '—'):
        updated = (_load_dashboard_data().get('meta') or {}).get('updated')
        if updated:
            li['_updated'] = updated
    return li


def _kline_15m_payload(key, now=None):
    """Return W11 15min rows only when they are marked as today's data."""
    rows = CACHE.get(key, [])
    if not rows:
        return []
    ref = now or datetime.now()
    today = ref.strftime("%Y-%m-%d")
    if CACHE.get("kline_15m_date") != today:
        return []
    return rows


def _build_live_quotes_payload(rule_state=None):
    """Build the live payload shared by polling and SSE endpoints."""
    hot_list = CACHE.get('hot_list', {})
    limit_up_detail = CACHE.get('limit_up_detail', {})
    sector_inflow = CACHE.get('sector_inflow', {})
    live_sectors = CACHE.get('live_sectors', {})
    return {
        'live_index': _live_index_with_baseline(),
        'live_quotes': CACHE.get('live_quotes', {}),
        'breadth': CACHE.get('breadth', {}),
        'limit_counts': CACHE.get('limit_counts', {}),
        'live_sectors': live_sectors,
        'hot_list': hot_list,
        'limit_up_detail': limit_up_detail,
        'limitboard_report': load_latest_limitboard_report(),
        'sector_inflow': sector_inflow,
        'attack_direction': build_attack_direction(hot_list, sector_inflow, live_sectors, limit_up_detail=limit_up_detail),
        'northbound': CACHE.get('northbound', {}),
        'iwencai': _iwencai_live_payload(),
        '上证15min': _kline_15m_payload('上证15min'),
        '深证15min': _kline_15m_payload('深证15min'),
        '创业15min': _kline_15m_payload('创业15min'),
        'rule_state': rule_state if rule_state is not None else _build_rule_state(),
    }


def _is_same_day_iwencai_close_snapshot(iwencai, now=None):
    """Keep today's near-close iwencai snapshot visible after market close."""
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    updated = (iwencai or {}).get("_updated")
    if not updated:
        return False
    CST = _tz(_td(hours=8))
    try:
        fetched = _dt.fromisoformat(str(updated).replace("Z", "+00:00"))
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=CST)
        ref = now or _dt.now(CST)
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=CST)
        fetched_cst = fetched.astimezone(CST)
        ref_cst = ref.astimezone(CST)
    except Exception:
        return False

    ref_minutes = ref_cst.hour * 60 + ref_cst.minute
    fetched_minutes = fetched_cst.hour * 60 + fetched_cst.minute
    return (
        fetched_cst.date() == ref_cst.date()
        and ref_minutes >= 15 * 60
        and fetched_minutes >= 14 * 60 + 45
        and (ref_cst - fetched_cst).total_seconds() <= 6 * 3600
    )


def _iwencai_live_payload(now=None):
    """Return iwencai live payload; stale/dead data carries metadata only."""
    iwencai = dict(_sanitize_iwencai_cache_entry(CACHE.get('iwencai', {}) or {}) or {})
    if not iwencai:
        return iwencai
    _add_freshness(iwencai, 'iwencai', iwencai.get('_updated'))
    level = ((iwencai.get('_freshness') or {}).get('level') or '').lower()
    if level not in ('stale', 'dead'):
        return iwencai
    if _is_same_day_iwencai_close_snapshot(iwencai, now=now):
        freshness = iwencai.get('_freshness') or {}
        freshness['level'] = 'stale'
        iwencai['_freshness'] = freshness
        iwencai['_close_snapshot'] = True
        iwencai['_available'] = True
        return iwencai
    masked = {k: v for k, v in iwencai.items() if str(k).startswith('_')}
    masked['_stale'] = True
    masked['_available'] = False
    return masked


def _trade_entry_gate(health, rule_state):
    """Combine health gate with real-time rule_state gate."""
    health_allowed = bool((health or {}).get("trade_entry_allowed", False))
    if not health_allowed:
        reasons = (health or {}).get("critical_reasons") or (health or {}).get("degraded_reasons") or []
        return False, "; ".join(str(r) for r in reasons) if reasons else "系统健康检查未通过"

    from scripts.rule_engine import classify_source_gap

    rule = rule_state or {}
    global_codes = []
    for raw_gap in rule.get("source_gaps") or []:
        gap = classify_source_gap(raw_gap)
        if gap["scope"] == "global" and gap["severity"] == "hard":
            global_codes.append(gap["code"])
    for item in rule.get("blocks") or []:
        if isinstance(item, dict) and item.get("scope") in {"all", "global"}:
            code = str(item.get("code") or "")
            if code:
                global_codes.append(code)
    global_codes = list(dict.fromkeys(global_codes))
    if global_codes:
        return False, "全局硬门阻断 (" + ",".join(global_codes) + ")"

    return True, None


def _is_market_session_open(now=None):
    """Return whether the A-share continuous trading session is open."""
    ref = now or datetime.now()
    current = ref.time()
    return (
        _time(9, 30) <= current < _time(11, 30)
        or _time(13, 0) <= current < _time(15, 0)
    )


def _decision_gate_payload(allowed, reason, evaluated_at):
    """Canonical final trade-decision contract for every consumer."""
    return {
        "schema_version": "decision_gate.v1",
        "allowed": bool(allowed),
        "reason": reason,
        "evaluated_at": evaluated_at.isoformat() if hasattr(evaluated_at, "isoformat") else str(evaluated_at),
        "source": "/api/ai/context",
    }


def _ai_current_mode(now=None):
    ref = now or datetime.now()
    t = ref.time()
    if t < _time(9, 25):
        return "preopen"
    if _time(9, 25) <= t <= _time(15, 0):
        return "intraday"
    if t <= _time(18, 0):
        return "closed"
    return "review"


def _ai_freshness_summary(health, account_state):
    health = health or {}
    account_state = account_state or {}
    def json_timestamp(value):
        return value.isoformat() if hasattr(value, "isoformat") else value
    return {
        "quotes": {
            "status": (health.get("quotes") or {}).get("status", "unknown"),
            "detail": (health.get("quotes") or {}).get("detail"),
            "updated_at": json_timestamp((CACHE.get("live_quotes") or {}).get("_updated")),
        },
        "iwencai": {
            "status": (health.get("iwencai") or {}).get("status", "unknown"),
            "updated_at": json_timestamp((CACHE.get("iwencai") or {}).get("_updated")),
        },
        "account": {
            "status": (health.get("account") or {}).get("status", "unknown"),
            "updated_at": json_timestamp(account_state.get("_updated")),
            "quote_status": account_state.get("quote_status"),
            "detail": account_state.get("error") or account_state.get("block_reason"),
            "anchor_source": (account_state.get("anchor") or {}).get("source"),
        },
        "baseline": {
            "status": (health.get("baseline") or {}).get("status", "unknown"),
        },
    }


def _ai_candidate_list(dashboard_data, limit=12):
    candidates = []
    for source_key, source_label in (("lianban_pool", "lianban"), ("trend_pool", "trend")):
        for item in (dashboard_data or {}).get(source_key) or []:
            if not isinstance(item, dict):
                continue
            candidates.append({
                "source": source_label,
                "code": str(item.get("代码") or item.get("code") or ""),
                "name": str(item.get("标的") or item.get("名称") or item.get("name") or ""),
                "sector": item.get("板块"),
                "role": item.get("角色"),
            })
            if len(candidates) >= limit:
                return candidates
    return candidates


def _ai_account_error_state(date_str, ref, error):
    return {
        "date": date_str,
        "anchor_missing": True,
        "anchor_trusted": False,
        "valuation_complete": False,
        "total_asset": None,
        "cash": None,
        "mv": None,
        "pnl_amount": None,
        "pnl_pct": None,
        "pos_pct": None,
        "positions": [],
        "closed_positions": [],
        "trades": [],
        "quote_status": "missing",
        "source": "account_load_error",
        "error": str(error)[:200],
        "_updated": ref.isoformat(),
        "anchor": {
            "date": date_str,
            "effective_at": None,
            "trade_id_cutoff": 0,
            "source": "account_load_error",
        },
    }


def _ai_ticket_summary(date_str, limit=30):
    try:
        from scripts.db import _exec, query_trade_tickets
        tickets = query_trade_tickets(date_from=date_str, date_to=date_str, limit=limit)
        count_rows = _exec("""
            SELECT status, COUNT(*) AS n
            FROM trade_tickets
            WHERE trade_date = ?
            GROUP BY status
        """, (date_str,))
        query_status = "ok"
        error = None
    except Exception as e:
        tickets = []
        count_rows = []
        query_status = "error"
        error = str(e)[:160]
    pending_statuses = {"draft", "confirmed", "manual_review", "guarded_experiment"}
    executable_statuses = {"executable", "audit_degraded", "partially_filled"}
    reconciliation_statuses = {"reconciliation_ready"}
    completed_statuses = {"filled", "closed", "closed_with_conflict", "cancelled"}
    items = []
    counts = {"pending": 0, "executable": 0, "reconciliation": 0, "completed": 0, "blocked": 0, "other": 0}
    total = 0
    for row in count_rows:
        status = str(row["status"] if hasattr(row, "__getitem__") else row.get("status") or "")
        n = int(row["n"] if hasattr(row, "__getitem__") else row.get("n") or 0)
        total += n
        if status == "blocked":
            counts["blocked"] += n
        elif status in pending_statuses:
            counts["pending"] += n
        elif status in executable_statuses:
            counts["executable"] += n
        elif status in reconciliation_statuses:
            counts["reconciliation"] += n
        elif status in completed_statuses:
            counts["completed"] += n
        else:
            counts["other"] += n
    for ticket in tickets:
        status = str(ticket.get("status") or "")
        items.append({
            "ticket_id": ticket.get("ticket_id"),
            "status": status,
            "action_type": ticket.get("action_type"),
            "ticket_purpose": ticket.get("ticket_purpose") or "execution",
            "window": ticket.get("window"),
            "code": ticket.get("code"),
            "name": ticket.get("name"),
        })
    return {
        "status": query_status,
        "error": error,
        "pending": counts["pending"],
        "executable": counts["executable"],
        "reconciliation": counts["reconciliation"],
        "completed": counts["completed"],
        "blocked": counts["blocked"],
        "other": counts["other"],
        "total": total,
        "limit": int(limit),
        "has_more": total > len(items),
        "items": items,
    }


def _ai_open_ticket_conflicts(date_str, limit=20):
    try:
        from scripts.db import _exec
        rows = _exec("""
            SELECT trade_date, ticket_id, code, conflict_type, severity, note
            FROM ticket_conflict_log
            WHERE trade_date = ?
              AND COALESCE(resolution_status, 'open') = 'open'
            ORDER BY id DESC
            LIMIT ?
        """, (date_str, int(limit)))
        error = None
    except Exception as e:
        rows = []
        error = str(e)[:160]
    return {
        "status": "error" if error else "ok",
        "error": error,
        "items": [dict(row) for row in rows],
    }


def _ai_context_risks_alerts_human(health, rule_state, freshness, tickets, conflicts):
    risks = []
    alerts = []
    human_required = []

    health = health or {}
    rule_state = rule_state or {}
    freshness = freshness or {}

    quote_status = ((freshness.get("quotes") or {}).get("status") or "unknown").lower()
    if quote_status in ("stale", "dead", "missing"):
        code = "QUOTE_DEAD" if quote_status in ("dead", "missing") else "QUOTE_STALE"
        risks.append({
            "code": code,
            "scope": "market_data",
            "title": "行情数据不可交易",
            "reason": (freshness.get("quotes") or {}).get("detail") or quote_status,
        })
        human_required.append({
            "code": "DATA_REVIEW_REQUIRED",
            "title": "复核行情数据",
            "reason": "行情 stale/dead 时不能让 AI 直接给可交易动作",
        })

    for reason in health.get("degraded_reasons") or []:
        alerts.append({
            "code": "HEALTH_DEGRADED",
            "title": "健康降级",
            "reason": str(reason),
        })

    if health.get("critical_ok") is False:
        risks.append({
            "code": "HEALTH_CRITICAL",
            "scope": "system",
            "title": "系统关键链路阻断",
            "reason": "; ".join(str(r) for r in (health.get("critical_reasons") or [])) or health.get("status"),
        })

    for block in rule_state.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        risks.append({
            "code": block.get("code") or "RULE_BLOCK",
            "scope": block.get("scope") or "rule_state",
            "title": block.get("title") or "规则阻断",
            "reason": block.get("reason") or block.get("message") or "",
        })

    for warning in rule_state.get("warnings") or []:
        if not isinstance(warning, dict):
            continue
        if warning.get("code") != "WIN-ICE-POLAR-MAINLINE-001":
            continue
        alerts.append({
            "code": "WIN-ICE-POLAR-MAINLINE-001",
            "title": "冰点主线人工复核",
            "reason": warning.get("reason") or warning.get("message") or "W1 黄灯只允许人工复核",
        })
        human_required.append({
            "code": "ICE_POLAR_MAINLINE_REVIEW",
            "title": "复核极化主线强回踩",
            "reason": "黄灯不等于买入授权，不能自动生成 executable ticket",
        })

    if health.get("trade_entry_allowed") is False or rule_state.get("tradable") is False:
        human_required.append({
            "code": "TRADE_BLOCKED",
            "title": "交易阻断需人工复核",
            "reason": "健康门禁或规则状态不允许自动推进交易动作",
        })

    if tickets.get("status") == "error":
        risks.append({
            "code": "TICKET_QUERY_ERROR",
            "scope": "tickets",
            "title": "票据读取失败",
            "reason": tickets.get("error") or "ticket query failed",
        })
        human_required.append({
            "code": "TICKET_DATA_REVIEW",
            "title": "复核票据数据",
            "reason": "票据读取失败，不能假定无票据",
        })

    if (conflicts or {}).get("status") == "error":
        risks.append({
            "code": "TICKET_CONFLICT_QUERY_ERROR",
            "scope": "tickets",
            "title": "票据冲突读取失败",
            "reason": conflicts.get("error") or "ticket conflict query failed",
        })
        human_required.append({
            "code": "TICKET_CONFLICT_DATA_REVIEW",
            "title": "复核票据冲突数据",
            "reason": "票据冲突读取失败，不能假定无未解决冲突",
        })

    conflict_items = (conflicts or {}).get("items") or []
    for conflict in conflict_items:
        alerts.append({
            "code": "TICKET_CONFLICT",
            "title": "票据冲突",
            "ticket_id": conflict.get("ticket_id"),
            "target": conflict.get("code"),
            "reason": conflict.get("note") or conflict.get("conflict_type"),
            "severity": conflict.get("severity"),
        })
    if conflict_items:
        human_required.append({
            "code": "TICKET_CONFLICT_REVIEW",
            "title": "复核票据冲突",
            "reason": f"{len(conflict_items)} 条未解决票据冲突",
        })

    actionable = [
        item for item in (tickets or {}).get("items") or []
        if str(item.get("status") or "") in {
            "draft", "confirmed", "manual_review", "guarded_experiment", "executable", "audit_degraded", "partially_filled",
            "reconciliation_ready"
        }
    ]
    for item in actionable[:5]:
        human_required.append({
            "code": "TICKET_REVIEW_REQUIRED",
            "title": "票据需人工确认",
            "ticket_id": item.get("ticket_id"),
            "reason": f"{item.get('status')} {item.get('action_type') or ''}".strip(),
        })

    return risks, alerts, human_required


def _ai_context_error_payload(error, now=None):
    ref = now or datetime.now()
    date_str = ref.strftime("%Y-%m-%d")
    reason = str(error)[:200]
    return {
        "schema_version": "ai_context.v1",
        "generated_at": ref.isoformat(),
        "date": date_str,
        "mode": _ai_current_mode(ref),
        "decision_gate": _decision_gate_payload(False, f"AI context build error: {reason}", ref),
        "recommendation_state": {
            "schema_version": "recommendation_state.v1",
            "status": "blocked",
            "execution_allowed": False,
            "candidates": [],
            "source_gaps": ["global_hard:AI_CONTEXT_BUILD_ERROR"],
        },
        "trade_entry_allowed": False,
        "trade_entry_reason": f"AI context build error: {reason}",
        "situation": {
            "health": {
                "status": "unhealthy",
                "critical_ok": False,
                "critical_reasons": [f"ai_context: {reason}"],
                "degraded_reasons": [],
            },
            "connection": {
                "bridge": "ok",
                "db": "unknown",
                "quotes": "unknown",
            },
            "trade_entry_allowed": False,
            "trade_entry_reason": f"AI context build error: {reason}",
            "pnl": {
                "total_asset": None,
                "pnl_amount": None,
                "pnl_pct": None,
                "valuation_complete": False,
            },
            "position": {
                "pos_pct": None,
                "position_count": 0,
                "sellable_count": 0,
            },
            "sentiment": {
                "value": None,
                "available": False,
                "freshness": None,
            },
        },
        "evidence": [],
        "alerts": [],
        "risks": [{
            "code": "AI_CONTEXT_BUILD_ERROR",
            "scope": "system",
            "title": "AI 事实包构建失败",
            "reason": reason,
        }],
        "tickets": {
            "status": "unknown",
            "error": "context build failed before ticket summary completed",
            "pending": 0,
            "executable": 0,
            "reconciliation": 0,
            "completed": 0,
            "blocked": 0,
            "other": 0,
            "total": 0,
            "limit": 0,
            "has_more": False,
            "items": [],
        },
        "positions": [],
        "candidates": [],
        "freshness": {
            "quotes": {"status": "unknown", "detail": None, "updated_at": None},
            "iwencai": {"status": "unknown", "updated_at": None},
            "account": {"status": "error", "updated_at": None, "quote_status": None,
                        "detail": reason, "anchor_source": None},
            "baseline": {"status": "unknown"},
        },
        "next_actions": [{
            "code": "REVIEW_BLOCK",
            "title": "先复核 AI 事实包构建失败",
            "reason": reason,
        }],
        "human_required": [{
            "code": "AI_CONTEXT_REVIEW_REQUIRED",
            "title": "复核 AI 事实包",
            "reason": "AI context 构建失败，不能据此推进交易动作",
        }],
    }


def _build_ai_context(now=None):
    """Build the read-only fact contract consumed by AI agents.

    This function only composes existing dashboard state. It must not write DB,
    files, CACHE, or call trade mutation endpoints.
    """
    ref = now or datetime.now()
    date_str = ref.strftime("%Y-%m-%d")
    dashboard_data = _load_dashboard_data()
    try:
        account_state = _load_current_account_state(CACHE.get("live_quotes", {}), now=ref, create_anchor=False)
    except Exception as e:
        account_state = _ai_account_error_state(date_str, ref, e)
    health = _build_health(account_state=account_state, now=ref)
    rule_state = _build_rule_state(now=ref, account_state=account_state)
    trade_allowed, trade_reason = _trade_entry_gate(health, rule_state)
    if not _is_market_session_open(ref):
        trade_allowed = False
        trade_reason = (
            f"{trade_reason}; MARKET_SESSION_CLOSED"
            if trade_reason
            else "MARKET_SESSION_CLOSED"
        )
    w1_state = ((rule_state or {}).get("windows") or {}).get("w1") or {}
    if w1_state.get("manual_review_allowed") is True:
        trade_allowed = False
        trade_reason = "W1 黄灯人工复核，不允许自动推进买入票据"
    live_payload = _build_live_quotes_payload(rule_state=rule_state)
    iwencai = live_payload.get("iwencai") or {}
    tickets = _ai_ticket_summary(date_str)
    conflicts = _ai_open_ticket_conflicts(date_str)
    freshness = _ai_freshness_summary(health, account_state)
    quote_status = str((freshness.get("quotes") or {}).get("status") or "").lower()
    if quote_status in ("stale", "dead", "missing"):
        trade_allowed = False
        trade_reason = trade_reason or f"AI context blocks trading because quotes are {quote_status}"
    if tickets.get("status") == "error":
        trade_allowed = False
        trade_reason = tickets.get("error") or "ticket query failed"
    if conflicts.get("status") == "error":
        trade_allowed = False
        trade_reason = conflicts.get("error") or "ticket conflict query failed"
    candidate_list = _ai_candidate_list(dashboard_data)
    from scripts.rule_engine import build_recommendation_state
    recommendation_state = build_recommendation_state(candidate_list, health, rule_state)
    situation = {
        "health": {
            "status": health.get("status"),
            "critical_ok": health.get("critical_ok"),
            "critical_reasons": health.get("critical_reasons") or [],
            "degraded_reasons": health.get("degraded_reasons") or [],
        },
        "connection": {
            "bridge": (health.get("bridge") or {}).get("status"),
            "db": (health.get("db") or {}).get("status"),
            "quotes": (health.get("quotes") or {}).get("status"),
        },
        "trade_entry_allowed": bool(trade_allowed),
        "trade_entry_reason": trade_reason,
        "pnl": {
            "total_asset": account_state.get("total_asset"),
            "pnl_amount": account_state.get("pnl_amount"),
            "pnl_pct": account_state.get("pnl_pct"),
            "valuation_complete": account_state.get("valuation_complete"),
        },
        "position": {
            "pos_pct": account_state.get("pos_pct"),
            "position_count": len(account_state.get("positions") or []),
            "sellable_count": sum(1 for p in account_state.get("positions") or [] if p.get("sellable_qty")),
        },
        "sentiment": {
            "value": iwencai.get("情绪值"),
            "available": iwencai.get("_available", True) if iwencai else False,
            "freshness": iwencai.get("_freshness"),
        },
    }
    risks, alerts, human_required = _ai_context_risks_alerts_human(
        health, rule_state, freshness, tickets, conflicts
    )
    next_actions = []
    if not trade_allowed:
        next_actions.append({"code": "REVIEW_BLOCK", "title": "先复核阻断原因", "reason": trade_reason})
    elif tickets.get("executable"):
        next_actions.append({"code": "REVIEW_EXECUTABLE_TICKETS", "title": "复核可执行票据", "count": tickets.get("executable")})
    else:
        next_actions.append({"code": "OBSERVE", "title": "保持观察", "reason": "无阻断且暂无可执行票据"})

    return {
        "schema_version": "ai_context.v1",
        "generated_at": ref.isoformat(),
        "date": date_str,
        "mode": _ai_current_mode(ref),
        "health": health,
        "rule_state": rule_state,
        "decision_gate": _decision_gate_payload(trade_allowed, trade_reason, ref),
        "recommendation_state": recommendation_state,
        # Compatibility mirrors. New consumers must read decision_gate.v1.
        "trade_entry_allowed": bool(trade_allowed),
        "trade_entry_reason": trade_reason,
        "situation": situation,
        "evidence": [
            {"id": "E1", "title": "账户持仓", "source": "/api/account/state"},
            {"id": "E2", "title": "票据闭环", "source": f"/api/trade/tickets?date={date_str}"},
            {"id": "E3", "title": "市场情绪", "source": "/api/live/quotes"},
            {"id": "E4", "title": "账户收益", "source": "/api/pnl/summary"},
        ],
        "alerts": alerts,
        "risks": risks,
        "tickets": tickets,
        "positions": account_state.get("positions") or [],
        "candidates": candidate_list,
        "freshness": freshness,
        "next_actions": next_actions,
        "human_required": human_required,
    }


def _build_full_snapshot():
    """
    聚合所有数据源，构建供 LLM 研判使用的全盘快照。
    优先级：CACHE（实时） > dashboard_data.json（基线兜底）
    """
    dd = _load_dashboard_data()
    risk = dd.get('risk', {})
    live_quotes = CACHE.get('live_quotes', {})
    live_index = CACHE.get('live_index', {})
    iwencai = CACHE.get('iwencai', {}) or dd.get('sentiment', {})

    # ── 1. 指数 ──────────────────────────────────────────────
    def _idx(key, fallback=''):
        return live_index.get(key, dd.get('market', {}).get(key, fallback))

    def _idx_pct(key, fallback='—'):
        raw = _idx(key, fallback)
        if raw == '—':
            return '—'
        return str(raw)

    index_snap = {
        '上证': {'涨跌幅': _idx('上证指数涨幅', '—'), '成交额': _idx('上证指数成交额', '—')},
        '深证': {'涨跌幅': _idx('深证指数涨幅', '—'), '成交额': _idx('深证指数成交额', '—')},
        '创业': {'涨跌幅': _idx('创业指数涨幅', '—'), '成交额': _idx('创业指数成交额', '—')},
    }

    # ── 2. 情绪（实时 iwencai 优先，兜底 baseline sentiment） ──
    sentiment_snap = {
        '涨停收益':     iwencai.get('昨日涨停收益', 0),
        '连板收益':     iwencai.get('连板收益', 0),
        '炸板收益':     iwencai.get('炸板收益', 0),
        '晋级率':       iwencai.get('晋级率', 0),
        '赚钱效应':     iwencai.get('赚钱效应', '—'),
        '最高板':       iwencai.get('最高板', '—'),
        '封板率':       iwencai.get('封板率', '—'),
        '情绪值':       iwencai.get('情绪值', '—'),
    }

    # ── 3. 连板池（基线 + 实时涨幅/量比） ──────────────────────
    lianban_pool = []
    for s in (dd.get('lianban_pool') or []):
        code = str(s.get('代码', ''))
        q = live_quotes.get(code, {})
        pnl_str = str(q.get('涨幅', '—'))
        contract = _normalize_today_pool_contract(s)
        lianban_pool.append({
            '标的': s.get('标的', '—'),
            '代码': code,
            '板块': s.get('板块', '—'),
            '今日定位': contract['今日定位'],
            '窗口': s.get('窗口', '—'),
            '今日检查': contract['今日检查'],
            '触发/失效': contract['触发/失效'],
            'derived_from_legacy_fields': contract['derived_from_legacy_fields'],
            'legacy_role': contract['legacy_role'],
            'legacy_action': contract['legacy_action'],
            '角色': contract['今日定位'],
            '操作': contract['触发/失效'],
            '涨幅': pnl_str,
            '量比': q.get('量比', s.get('量比', '—')),
            'MA10_60m': q.get('MA10_60m', '—'),
            'MA10_60m_dir': q.get('MA10_60m_dir', '—'),
            '最新价': q.get('最新价', '—'),
        })

    # ── 4. 趋势池（基线 + 实时涨幅/量比） ──────────────────────
    trend_pool = []
    for s in (dd.get('trend_pool') or []):
        code = str(s.get('代码', ''))
        q = live_quotes.get(code, {})
        contract = _normalize_today_pool_contract(s)
        trend_pool.append({
            '标的': s.get('标的', '—'),
            '代码': code,
            '板块': s.get('板块', '—'),
            '今日定位': contract['今日定位'],
            '窗口': s.get('窗口', '—'),
            '今日检查': contract['今日检查'],
            '触发/失效': contract['触发/失效'],
            'derived_from_legacy_fields': contract['derived_from_legacy_fields'],
            'legacy_role': contract['legacy_role'],
            'legacy_action': contract['legacy_action'],
            '角色': contract['今日定位'],
            '操作': contract['触发/失效'],
            '涨幅': q.get('涨幅', '—'),
            '量比': q.get('量比', s.get('量比', '—')),
            'MA10_60m': q.get('MA10_60m', '—'),
            'MA10_60m_dir': q.get('MA10_60m_dir', '—'),
            '最新价': q.get('最新价', '—'),
        })

    # ── 5. 持仓（SSOT + 实时现价/浮盈） ─────────────────────
    try:
        pnl_live = _current_pnl_summary()
    except Exception:
        pnl_live = {}
    ssot_positions = pnl_live.get('positions', []) if pnl_live else []
    positions = []
    for p in ssot_positions:
        status = str(p.get('状态', ''))
        if '清' in status or '删' in status:
            continue
        code = str(p.get('代码', ''))
        q = live_quotes.get(code, {})
        cost = p.get('成本', 0)
        price = q.get('最新价') or p.get('现价') or 0
        qty_str = str(p.get('数量', '0'))
        try:
            qty = int(''.join(filter(str.isdigit, qty_str)))
        except Exception:
            qty = 0
        vc = pnl_live.get('valuation_complete', True) if pnl_live else True
        ab = pnl_live.get('anchor_blocked', False) if pnl_live else False
        data_trusted = bool(vc and not ab)
        risk_note = None
        if ab:
            risk_note = '锚点被阻断 — 数据不可信'
        elif not vc:
            risk_note = '估值不可信 — 行情缺失'
        if not data_trusted:
            price = None
            pnl_pct = 0
        else:
            pnl_pct = ((price - cost) / cost * 100) if cost and price else 0
        entry = {
            '标的': p.get('标的', '—'),
            '代码': code,
            '成本': cost,
            '现价': price,
            '数量': qty,
            '浮盈%': round(pnl_pct, 2) if price else None,
            '状态': p.get('状态', '—'),
            'data_trusted': data_trusted,
        }
        if risk_note:
            entry['risk_note'] = risk_note
        positions.append(entry)

    # ── 6. 板块（基线 sectors + hot_list 涨停梯队） ─────────
    sectors = []
    for sec in (dd.get('sectors') or []):
        sectors.append({
            '板块': sec.get('板块', '—'),
            '类型': sec.get('类型', '—'),
            '涨停数': sec.get('涨停数', 0),
            '梯队': sec.get('梯队', '—'),
            '龙头': sec.get('龙头', '—'),
        })

    # 附上 hot_list 涨停梯队 TOP5（精简字段）
    hot_rank = []
    for s in (CACHE.get('hot_list', {}).get('stocks') or [])[:5]:
        hot_rank.append({
            'name': s.get('name', '—'),
            'code': s.get('code', '—'),
            'reason': s.get('reason', '—'),
        })

    # ── 7. 风控（从 gen 算好的 risk 域读取） ─────────────────
    try:
        pnl_live = _current_pnl_summary()
    except Exception:
        pnl_live = {}
    total_asset = pnl_live.get('total_asset') or dd.get('pnl', {}).get('总资产', 0)
    total_mv = pnl_live.get('mv') or 0
    # 复用已获取的 pnl_live 避免重复 SSOT 查询，并确保 LLM 风控快照与 rule_state 同源。
    rule_inputs = _build_rule_inputs(account_state=pnl_live)
    from scripts.rule_engine import evaluate_rule_state as _eval_rule_state
    rule_state = _eval_rule_state(rule_inputs)
    rule_risk = rule_inputs.get('risk', {}) or {}
    risk_snap = {
        '连亏天数':    rule_risk.get('losing_account_days', risk.get('连亏天数', 0)),
        '周累计回撤':  rule_risk.get('weekly_drawdown_pct', risk.get('周累计回撤', 0)),
        '月累计回撤':  rule_risk.get('monthly_drawdown_pct', risk.get('月累计回撤', 0)),
        '仓位':        round(total_mv / total_asset * 100, 2) if total_asset else 0,
        '总资产':      total_asset,
    }
    # 顶层可信标记
    vc = pnl_live.get('valuation_complete', True) if pnl_live else True
    ab = pnl_live.get('anchor_blocked', False) if pnl_live else False
    data_trusted = bool(vc and not ab)
    snapshot_risk_notes = None
    if ab:
        snapshot_risk_notes = '锚点被阻断 — 数据不可信'
    elif not vc:
        snapshot_risk_notes = '估值不可信 — 行情缺失'
    return {
        '指数': index_snap,
        '情绪': sentiment_snap,
        '连板池': lianban_pool,
        '趋势池': trend_pool,
        '持仓': positions,
        '板块': sectors,
        '涨停梯队TOP5': hot_rank,
        '风控': risk_snap,
        'rule_state': rule_state,
        'data_trusted': data_trusted,
        'risk_notes': snapshot_risk_notes,
    }


def _baseline_freshness():
    """Read-only baseline freshness check; returns ok/stale/missing."""
    if not DATA_FILE.exists():
        return "missing"
    try:
        dd = _load_dashboard_data()
        meta = dd.get("meta", {}) if isinstance(dd, dict) else {}
        date_str = _baseline_generated_date(meta)
        if not date_str:
            return "stale"
        today = datetime.now().strftime("%Y-%m-%d")
        if date_str == today:
            return "ok"
        from datetime import timedelta as _td
        yesterday = (datetime.now() - _td(days=1)).strftime("%Y-%m-%d")
        if date_str == yesterday:
            return "delayed"
        return "stale"
    except Exception:
        return "stale"


def _date_part(value):
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", str(value or "").strip())
    return m.group(1) if m else ""


def _baseline_generated_date(meta):
    """Date when the baseline file was generated, not the source review date."""
    if not isinstance(meta, dict):
        return ""
    return (
        _date_part(meta.get("updated")) or
        _date_part(meta.get("generated_at")) or
        _date_part(meta.get("date"))
    )


def _baseline_generated_today(meta, today=None):
    today = today or datetime.now().strftime("%Y-%m-%d")
    return _baseline_generated_date(meta) == today


def _quotes_coverage(today=None):
    """Return (covered, total, missing_pos_codes) for tracked stocks in live_quotes."""
    dd = _load_dashboard_data()
    pos_codes = set()
    all_codes = set(_collect_runtime_stock_codes(dd, today=today))
    for p in dd.get('positions', []):
        code = str(p.get('代码', ''))
        if len(code) == 6:
            pos_codes.add(code)

    lq = CACHE.get('live_quotes', {})
    covered = 0
    missing_pos = []
    for code in all_codes:
        q = lq.get(code, {})
        if isinstance(q, dict) and q.get('最新价') is not None:
            covered += 1
        elif code in pos_codes:
            missing_pos.append(code)

    return covered, len(all_codes), missing_pos


def _build_account_audit(today=None):
    """只读 account basis audit：暴露今日锚点、隔夜持仓、当日清仓、day_start_prices 覆盖率。

    today 可传入指定日期（默认 datetime.now），用于测试。
    返回 dict 供 /api/account/audit + /api/health.account_basis 使用。
    严格只读，不创建/修改锚点。
    """
    from scripts.db import query_account_baseline, query_trades
    if today is None:
        today = datetime.now().strftime('%Y-%m-%d')
    result = {
        'basis_status': 'missing_anchor',
        'anchor_date': None,
        'anchor_source': None,
        'anchor_effective_at': None,
        'overnight_positions_count': 0,
        'overnight_codes': [],
        'overnight_positions': [],
        'day_start_prices_covered': 0,
        'day_start_prices_total': 0,
        'day_start_prices_coverage': None,
        'day_start_prices_missing_codes': [],
        'day_start_prices_missing': [],
        'closed_positions_today_count': 0,
        'closed_positions_today': [],
        'closed_positions_today_missing_realized': [],
    }

    anchor = query_account_baseline(today)
    if anchor:
        result['anchor_date'] = anchor.get('date', today)
        result['anchor_source'] = anchor.get('source', 'unknown')
        result['anchor_effective_at'] = anchor.get('effective_at')

        positions = anchor.get('positions') or []
        result['overnight_positions_count'] = len(positions)
        result['overnight_codes'] = [p.get('代码', '') for p in positions]

        meta = anchor.get('_meta') or {}
        prices = meta.get('day_start_prices') or {}
        total = len(positions)
        covered = sum(1 for p in positions if p.get('代码') in prices)
        result['day_start_prices_covered'] = covered
        result['day_start_prices_total'] = total
        result['day_start_prices_coverage'] = f'{covered}/{total}' if total else None
        missing_codes = [p.get('代码', '') for p in positions if p.get('代码') not in prices]
        result['day_start_prices_missing_codes'] = missing_codes

        # 增强：per-position detail + missing list with names
        result['overnight_positions'] = [
            {
                'code': p.get('代码', ''),
                'name': p.get('标的', ''),
                'has_day_start_price': p.get('代码') in prices if prices else False,
                'day_start_price': prices.get(p.get('代码')) if prices else None,
            }
            for p in positions
        ]
        result['day_start_prices_missing'] = [
            {'code': p.get('代码', ''), 'name': p.get('标的', '')}
            for p in positions if p.get('代码') not in prices
        ]

        # 当日清仓（纯只读：用 reduce 回放流水）
        from scripts.account_ssot import reduce_account_state
        trades = query_trades(date_from=today, date_to=today, limit=10000)
        if trades:
            state = reduce_account_state(anchor, trades, CACHE.get('live_quotes', {}))
            closed = state.get('closed_positions', [])
            result['closed_positions_today_count'] = len(closed)
            result['closed_positions_today'] = [
                {'code': c.get('code', ''), 'name': c.get('name', ''),
                 'sell_price': c.get('sell_price'), 'closed_date': c.get('closed_date', '')}
                for c in closed
            ]
            # 增强：列出 realized_today_pnl=null 的清仓
            result['closed_positions_today_missing_realized'] = [
                {'code': c.get('code', ''), 'name': c.get('name', ''),
                 'closed_date': c.get('closed_date', '')}
                for c in closed if c.get('realized_today_pnl') is None
            ]

        # basis_status
        if missing_codes or result['closed_positions_today_missing_realized']:
            result['basis_status'] = 'degraded'
        else:
            result['basis_status'] = 'ok'
    else:
        result['basis_status'] = 'missing_anchor'

    return result


def _build_health(account_state=None, now=None):
    """Build health status for all subsystems. Read-only, no side effects.
    Returns a dict with per-domain status and an overall status.
    """
    result = {}

    # bridge — always ok if we're serving
    result["bridge"] = {"status": "ok"}

    # db
    try:
        from scripts.db import get_conn
        conn = get_conn()
        result["db"] = {"status": "ok"}
    except Exception as e:
        result["db"] = {"status": "error", "detail": str(e)[:120]}

    # baseline
    ref = now or datetime.now()
    today_str = ref.strftime("%Y-%m-%d")
    bf = _baseline_freshness()
    result["baseline"] = {"status": bf}

    # quotes — freshness + coverage (先算裸缓存，后由 account quote_status 修正)
    qf = _compute_freshness("live_quote", CACHE.get("live_quotes", {}), now=ref)
    covered, total, missing_pos = _quotes_coverage(today=today_str)
    quotes_result = {"status": qf, "covered": covered, "total": total}
    if total > 0:
        if covered == 0:
            quotes_result["status"] = "dead"
            quotes_result["detail"] = f"zero coverage ({total} tracked)"
        elif missing_pos:
            quotes_result["detail"] = f"{len(missing_pos)} positions missing quotes"
            if quotes_result["status"] == "live":
                quotes_result["status"] = "delayed"
    elif qf == "live":
        quotes_result["detail"] = "no tracked codes; freshness only"
    result["quotes"] = quotes_result

    # iwencai
    if_ = _compute_freshness("iwencai", CACHE.get("iwencai", {}), now=ref)
    result["iwencai"] = {"status": if_}

    # account — 加载后同时修正 quotes status（收盘快照不应判dead）
    try:
        state = account_state if account_state is not None else _load_current_account_state(
            CACHE.get("live_quotes", {}),
            now=ref,
            create_anchor=False,
        )
        acct_quote_status = (state or {}).get("quote_status", "")
        if acct_quote_status == "close_snapshot":
            qr = result.setdefault("quotes", {})
            if qr.get("status") in ("dead", "stale"):
                if qr.get("covered", 0) > 0:
                    qr["status"] = "close_snapshot"
                    qr["detail"] = (qr.get("detail", "") + " (post-close snapshot)").strip()
        anchor_source = (state.get("anchor") or {}).get("source", "") if state else ""
        anchor_trusted = state.get("anchor_trusted", True) if state else True
        anchor_blocked = state.get("anchor_blocked") if state else False
        if anchor_blocked:
            result["account"] = {"status": "error",
                "detail": f"anchor blocked: {state.get('block_reason','')}"}
        elif not anchor_trusted:
            result["account"] = {"status": "error",
                "detail": f"untrusted anchor (source={anchor_source})"}
        elif state and state.get("total_asset") is not None:
            vc = state.get("valuation_complete")
            if vc is False:
                result["account"] = {"status": "incomplete", "detail": "valuation_complete is false"}
            elif anchor_source == "manual_correction":
                result["account"] = {"status": "ok", "detail": "manual_correction"}
            else:
                result["account"] = {"status": "ok"}
        else:
            result["account"] = {"status": "incomplete", "detail": "total_asset missing"}
    except Exception as e:
        result["account"] = {"status": "error", "detail": str(e)[:120]}

    # pnl
    try:
        summary = _merge_pnl_summary(query_pnl_summary(), account_state) if account_state is not None else _current_pnl_summary()
        if summary and summary.get("total_asset") is not None:
            vc = summary.get("valuation_complete")
            if vc is False:
                result["pnl"] = {"status": "incomplete", "detail": "valuation_complete is false"}
            else:
                result["pnl"] = {"status": "ok"}
        else:
            result["pnl"] = {"status": "incomplete", "detail": "total_asset missing"}
    except Exception as e:
        result["pnl"] = {"status": "error", "detail": str(e)[:120]}

    # auction — reuse snapshot_auction.is_auction_valid
    auction_file = ROOT / "data" / "auction_snapshot.json"
    if auction_file.exists():
        try:
            with open(auction_file) as f:
                ad = json.load(f)
        except Exception:
            ad = None
        if isinstance(ad, dict):
            from scripts.snapshot_auction import is_auction_valid
            try:
                valid = is_auction_valid(ad)
            except Exception:
                valid = False
            if valid:
                result["auction"] = {"status": "ok"}
            else:
                today = datetime.now().strftime("%Y-%m-%d")
                fetched = str(ad.get("fetched", ""))
                if today in fetched:
                    result["auction"] = {"status": "incomplete", "detail": "missing key dimensions"}
                else:
                    result["auction"] = {"status": "stale", "detail": "not from today"}
        else:
            result["auction"] = {"status": "stale", "detail": "unreadable"}
    else:
        result["auction"] = {"status": "missing"}

    # llm_config — only report whether configured, never expose token
    cfg = _load_api_config()
    has_cfg = bool(cfg.get("token") and cfg.get("base_url"))
    result["llm_config"] = {"status": "ok" if has_cfg else "missing", "configured": has_cfg}

    # Phase 4: 健康分层 — critical_ok / trade_entry_allowed / degraded_reasons
    critical_issues = []
    degraded_list = []

    # account 层 critical
    acct = result.get("account", {})
    acct_status = acct.get("status", "")
    if acct_status == "error":
        critical_issues.append(f"account: {acct.get('detail', 'error')}")
    elif acct_status == "incomplete":
        critical_issues.append(f"account: {acct.get('detail', acct_status)}")
    elif acct_status in ("stale", "delayed"):
        degraded_list.append(f"account: {acct.get('detail', acct_status)}")

    # pnl critical
    pnl_s = result.get("pnl", {}).get("status", "")
    if pnl_s == "error":
        critical_issues.append(f"pnl: {result['pnl'].get('detail', 'error')}")

    # quotes critical (dead/zero coverage = no trading)
    q = result.get("quotes", {})
    if q.get("status") in ("dead", "missing"):
        critical_issues.append(f"quotes: {q.get('detail', q.get('status', 'unavailable'))}")
    elif q.get("status") in ("stale", "delayed"):
        degraded_list.append(f"quotes: {q.get('detail', q.get('status', 'degraded'))}")

    # iwencai/baseline degraded (not critical)
    iw = result.get("iwencai", {}).get("status", "")
    if iw in ("stale", "delayed"):
        degraded_list.append(f"iwencai: {iw}")
    bf_s = result.get("baseline", {}).get("status", "")
    if bf_s in ("stale", "delayed"):
        degraded_list.append(f"baseline: {bf_s}")

    # llm_config is optional. Missing config should not make the dashboard
    # look degraded; it only disables LLM-specific actions/history.
    # account_basis — 集成账户基准审计
    try:
        audit = _build_account_audit(today=today_str)
        basis_status = audit.get("basis_status", "missing_anchor")
        ab = {
            "status": basis_status,
            "coverage": audit.get("day_start_prices_coverage"),
            "missing_codes": audit.get("day_start_prices_missing_codes", []),
        }
        closed_missing = [item.get("code") for item in audit.get("closed_positions_today_missing_realized", [])]
        if closed_missing:
            ab["closed_missing_realized_codes"] = closed_missing
        if basis_status == "missing_anchor":
            critical_issues.append("account_basis: missing_anchor")
        elif basis_status == "degraded":
            coverage = audit.get("day_start_prices_coverage", "?")
            degraded_list.append(f"account_basis: {coverage} day_start_prices covered")
            if closed_missing:
                degraded_list.append(f"account_basis: {len(closed_missing)} closed positions missing realized_pnl")
        result["account_basis"] = ab
    except Exception as e:
        result["account_basis"] = {"status": "error", "detail": str(e)[:120]}

    result["critical_ok"] = len(critical_issues) == 0
    result["trade_entry_allowed"] = len(critical_issues) == 0
    result["critical_reasons"] = critical_issues if critical_issues else None
    result["degraded_reasons"] = degraded_list if degraded_list else None

    # overall status — 在 Phase 4 收集完成后最后计算（跳过非 dict 字段）
    _STATUS_EXEMPT = {"llm_config", "auction", "iwencai"}
    statuses = []
    for k, v in result.items():
        if not isinstance(v, dict):
            continue
        s = v.get("status", "unknown")
        statuses.append((k, s))

    dead_or_missing = [k for k, s in statuses if s in ("dead", "missing", "error") and k not in _STATUS_EXEMPT]
    stale_or_delayed = [
        k for k, s in statuses
        if s in ("stale", "delayed", "incomplete") and k not in _STATUS_EXEMPT
    ]

    if dead_or_missing:
        result["status"] = "unhealthy"
    elif stale_or_delayed or degraded_list:
        result["status"] = "degraded"
    else:
        result["status"] = "healthy"

    return result


def _sentiment_history_payload(day):
    """Return one trading day's node snapshots instead of the 90-day file."""
    snap_file = ROOT / "data" / "sentiment_auto.json"
    rows = []
    if snap_file.exists():
        try:
            payload = json.loads(snap_file.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get(day), list):
                rows = payload[day]
        except (OSError, json.JSONDecodeError):
            rows = []
    return {
        "date": day,
        "rows": rows,
        "source": "sentiment_auto",
    }


class BridgeHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _serve_cached(self, key, data_type):
        if key == 'iwencai':
            result = _iwencai_live_payload()
        else:
            result = CACHE.get(key, {})
            fetched_at = result.get('_updated') if isinstance(result, dict) else None
            result = _add_freshness(result, data_type, fetched_at)
        body = json.dumps(result, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(body)

    def _db_close(self):
        """释放本线程的 SQLite 连接（在每个 DB handler 完成后调用）"""
        try:
            from scripts.db import close_conn
            close_conn()
        except Exception:
            pass

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/debug/snapshot':
            _ensure_db()
            try:
                snap = _build_full_snapshot()
                body = json.dumps(snap, ensure_ascii=False, indent=2).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(body)
            finally:
                self._db_close()
            return
        elif parsed.path == '/api/ai/context':
            try:
                _send_json(self, 200, _build_ai_context())
            except Exception as e:
                _send_json(self, 200, _ai_context_error_payload(e))
            finally:
                self._db_close()
            return
        elif parsed.path == '/api/trade/tickets':
            _ensure_db()
            try:
                from scripts.db import query_trade_tickets
                params = parse_qs(parsed.query)
                requested_date = (params.get('date') or [None])[0]
                date = requested_date or datetime.now().strftime('%Y-%m-%d')
                tickets = query_trade_tickets(
                    date_from=date,
                    date_to=date,
                    code=(params.get('code') or [None])[0],
                    status=(params.get('status') or [None])[0],
                )
                _send_json(self, 200, {
                    'ok': True,
                    'tickets': tickets,
                    'data_date': date,
                    'date_source': 'query_param' if requested_date else 'default_today',
                })
            finally:
                self._db_close()
            return
        elif parsed.path == '/api/health':
            _ensure_db()
            try:
                result = _build_health()
                body = json.dumps(result, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(body)
            finally:
                self._db_close()
            return
        elif parsed.path == '/api/sentiment/history':
            params = parse_qs(parsed.query)
            requested_date = (params.get('date') or [None])[0]
            day = requested_date or datetime.now().strftime('%Y-%m-%d')
            _send_json(self, 200, _sentiment_history_payload(day))
            return
        elif parsed.path == '/api/baseline':
            _ensure_db()
            try:
                result = _baseline_payload()
                body = json.dumps(result, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
            finally:
                self._db_close()
            return
        elif parsed.path == '/api/pnl':
            _ensure_db()
            try:
                qs = parse_qs(parsed.query)
                range_val = qs.get('range', ['today'])[0]
                index_val = qs.get('index', ['sh'])[0]
                result = query_pnl(range_val, index_val)
                if range_val == 'today':
                    result = _overlay_live_today_pnl_point(
                        result, _current_pnl_summary(), range_val, index_val,
                        live_index=CACHE.get('live_index') or {},
                    )
                result = _add_freshness(result, 'pnl', result.get('_updated'))
                body = json.dumps(result, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
            finally:
                self._db_close()
            return
        elif parsed.path == '/api/pnl/summary':
            _ensure_db()
            try:
                result = _current_pnl_summary()
                result = _add_freshness(result, 'pnl', result.get('_updated'))
                body = json.dumps(result, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
            finally:
                self._db_close()
            return
        elif parsed.path == '/api/account/state':
            _ensure_db()
            try:
                result = _load_current_account_state(CACHE.get('live_quotes', {}))
                result = _add_freshness(result, 'pnl', result.get('_updated'))
                body = json.dumps(result, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
            finally:
                self._db_close()
            return
        elif parsed.path == '/api/account/audit':
            _ensure_db()
            try:
                result = _build_account_audit()
                body = json.dumps(result, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)[:200]}).encode())
            finally:
                self._db_close()
            return

        elif parsed.path == '/api/account/correct':
            self.send_response(405)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Allow', 'POST')
            self.end_headers()
            self.wfile.write(json.dumps({'ok': False, 'error': 'Method Not Allowed: use POST'}).encode())
            self._db_close()
            return
        elif parsed.path == '/api/trades/review':
            _ensure_db()
            try:
                qs = parse_qs(parsed.query)
                date_str = qs.get('date', [datetime.now().strftime('%Y-%m-%d')])[0]
                from scripts.db import query_trade_reviews
                result = query_trade_reviews(date_str)
                body = json.dumps(result, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
            finally:
                self._db_close()
            return
        elif parsed.path == '/api/trades':
            _ensure_db()
            try:
                result = query_trades(limit=50)
                result = _add_freshness(result, 'pnl')
                body = json.dumps(result, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
            finally:
                self._db_close()
            return
        elif parsed.path == '/api/live/iwencai':
            self._serve_cached('iwencai', 'iwencai')
            return
        elif parsed.path == '/api/live/sectors':
            self._serve_cached('sector_inflow', 'live_quote')
            return
        elif parsed.path == '/api/live/news':
            self._serve_cached('news', 'llm')
            return
        elif parsed.path == '/api/live/quotes':
            _ensure_db()
            try:
                result = _build_live_quotes_payload()
                # Phase 4: 健康门禁状态（供 W1/W2 按 trade_entry_allowed 开关入口）
                # 直接复用 /api/health 的 critical 分层，避免两套逻辑不一致
                try:
                    h = _build_health()
                    allowed, reason = _trade_entry_gate(h, result.get('rule_state'))
                    result['trade_entry_allowed'] = allowed
                    result['trade_entry_reason'] = reason
                except Exception:
                    result['trade_entry_allowed'] = False
                    result['trade_entry_reason'] = '健康检查失败'
                result = _add_freshness(result, 'live_quote', CACHE.get('live_quotes', {}).get('_updated'))
                body = json.dumps(result, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(body)
            finally:
                self._db_close()
            return
        elif parsed.path == '/api/live/stream':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                while True:
                    import time as _time_lib
                    _ensure_db()
                    try:
                        rule = _build_rule_state()
                    finally:
                        self._db_close()
                    result = _build_live_quotes_payload(rule_state=rule)
                    result['_freshness'] = {'level': 'live', 'type': 'sse_stream'}
                    data = json.dumps(result, ensure_ascii=False)
                    self.wfile.write(f"data: {data}\n\n".encode())
                    self.wfile.flush()
                    _time_lib.sleep(5)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            return
        elif parsed.path == '/api/llm/history':
            today = datetime.now().strftime('%Y-%m-%d')
            insights = {}
            if LLM_INSIGHTS_FILE.exists():
                try:
                    with open(LLM_INSIGHTS_FILE) as f:
                        insights = json.load(f)
                except Exception:
                    pass
            day_data = insights.get(today, {})
            # 旧格式兼容 → v2
            if 'conversation' not in day_data:
                conv = []
                for node, entry in sorted(day_data.items()):
                    if isinstance(entry, dict) and 'text' in entry:
                        conv.append({
                            'role': 'assistant',
                            'ts': entry.get('timestamp', ''),
                            'text': entry['text'],
                            'signals': entry.get('signals', []),
                            'auto': True,
                        })
                day_data = {'meta': {}, 'conversation': conv}
            result = {
                'today': today,
                'meta': day_data.get('meta', {}),
                'conversation': day_data.get('conversation', []),
            }
            body = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        super().end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/trade/tickets/prepare':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body or b'{}')
            except Exception as e:
                _send_json(self, 400, {'ok': False, 'error': str(e)})
                return
            _ensure_db()
            try:
                ticket = _prepare_trade_ticket(payload)
                _send_json(self, 200, {'ok': True, 'ticket': ticket})
            except ValueError as e:
                _send_json(self, 400, {'ok': False, 'error': str(e)})
            except Exception as e:
                _send_json(self, 500, {'ok': False, 'error': str(e)})
            finally:
                self._db_close()
            return

        _re = __import__("re")
        close_match = _re.fullmatch(r"/api/trade/tickets/([^/]+)/close", parsed.path)
        if close_match:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body or b'{}')
            except Exception as e:
                _send_json(self, 400, {'ok': False, 'error': str(e)})
                return
            _ensure_db()
            try:
                ticket = _close_trade_ticket(close_match.group(1), payload)
                _send_json(self, 200, {'ok': True, 'ticket': ticket})
            except LookupError as e:
                _send_json(self, 404, {'ok': False, 'error': str(e)})
            except ValueError as e:
                _send_json(self, 400, {'ok': False, 'error': str(e)})
            except Exception as e:
                _send_json(self, 500, {'ok': False, 'error': str(e)})
            finally:
                self._db_close()
            return

        if parsed.path == '/api/trade/fills/preview':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body or b'{}')
            except Exception as e:
                _send_json(self, 400, {'ok': False, 'error': str(e)})
                return
            _ensure_db()
            try:
                result = _create_fill_preview(payload)
                _send_json(self, 200, {'ok': True, **result})
            except ValueError as e:
                _send_json(self, 400, {'ok': False, 'error': str(e)})
            except Exception as e:
                _send_json(self, 500, {'ok': False, 'error': str(e)})
            finally:
                self._db_close()
            return

        if parsed.path == '/api/trade/fills/confirm':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body or b'{}')
            except Exception as e:
                _send_json(self, 400, {'ok': False, 'error': str(e)})
                return
            _ensure_db()
            try:
                status, result = _confirm_fill(payload, self.headers)
                _send_json(self, status, result)
            except Exception as e:
                _send_json(self, 500, {'ok': False, 'error': str(e)})
            finally:
                self._db_close()
            return

        if self.path == '/api/sync':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body)
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
                print(f"  [bridge] Error: {e}")
                return

            if _payload_overwrites_account(payload):
                self.send_response(409)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'ok': False,
                    'error': 'account asset fields are server-owned; submit trade events only',
                }).encode())
                return

            _ensure_db()
            try:
                if DATA_FILE.exists():
                    with open(DATA_FILE) as f:
                        data = json.load(f)
                else:
                    data = {}

                # 单笔新成交事件写入
                entry = payload.get('entry')
                tlist = payload.get('今日操作')
                has_entry = bool(entry and not tlist)

                # entry 请求不接受客户端 positions
                if has_entry and 'positions' in payload:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        'ok': False, 'error': 'entry request must not include positions'
                    }).encode())
                    return

                # positions-only sync rejected BEFORE any mutation
                if not has_entry and not tlist and 'positions' in payload:
                    self.send_response(409)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        'ok': False, 'error': 'positions-only sync deprecated; use entry for trades'
                    }).encode())
                    return

                positions_updated = False
                if not has_entry and 'positions' in payload:
                    existing = {p.get('标的'): p for p in data.get('positions', [])}
                    for p in payload['positions']:
                        existing[p.get('标的')] = p
                    data['positions'] = list(existing.values())
                    _refresh_stock_codes(data)
                    positions_updated = True

                if has_entry:
                    # —— 成交输入校验 ——
                    now = datetime.now()
                    validation_error = None

                    # 动作枚举
                    action = str(entry.get('动作', '') or '')
                    ALLOWED_ACTIONS = {'W1追涨', 'W2买入', '买入', '卖出'}
                    if action not in ALLOWED_ACTIONS:
                        validation_error = f'动作非法: {action!r}，允许 {sorted(ALLOWED_ACTIONS)}'

                    # 代码非空
                    code = str(entry.get('代码', '') or '').strip()
                    if not validation_error and not code:
                        validation_error = '代码不能为空'

                    # 名称非空
                    name = str(entry.get('标的', '') or '').strip()
                    if not validation_error and not name:
                        validation_error = '标的名称不能为空'

                    # 价格：有限正数
                    import math as _math
                    try:
                        raw_price = entry.get('价格', 0)
                        price = float(raw_price or 0)
                        if not validation_error:
                            if not _math.isfinite(price) or price <= 0:
                                validation_error = f'价格必须为有限正数，收到 {raw_price!r}'
                    except (TypeError, ValueError):
                        validation_error = f'价格非法: {entry.get("价格")!r}'

                    # 数量：严格正整数（拒绝小数/字符串小数/布尔值）
                    try:
                        raw_qty = entry.get('数量', 0)
                        if isinstance(raw_qty, bool):
                            validation_error = f'数量必须为正整数，收到布尔值'
                        elif not validation_error:
                            qty_f = float(raw_qty)
                            qty = int(qty_f)
                            if qty_f != qty or qty_f <= 0:
                                validation_error = f'数量必须为正整数，收到 {raw_qty!r}'
                    except (TypeError, ValueError):
                        validation_error = f'数量非法: {entry.get("数量")!r}'

                    # 时间 HH:MM 或 HH:MM:SS，不在未来
                    trade_time = str(entry.get('时间', '') or '').strip()
                    if not validation_error:
                        import re
                        if not re.match(r'^\d{2}:\d{2}(:\d{2})?$', trade_time):
                            validation_error = f'时间格式非法: {trade_time!r}，期望 HH:MM 或 HH:MM:SS'
                        else:
                            try:
                                parts = trade_time.split(':')
                                h, m = int(parts[0]), int(parts[1])
                                if h < 0 or h > 23 or m < 0 or m > 59:
                                    validation_error = f'时间值非法: {trade_time!r}'
                                elif len(parts) == 3:
                                    s = int(parts[2])
                                    if s < 0 or s > 59:
                                        validation_error = f'秒值非法: {trade_time!r}'
                                if not validation_error:
                                    t_min = h * 60 + m
                                    now_min = now.hour * 60 + now.minute + 1
                                    if t_min > now_min:
                                        validation_error = 'trade time is in the future'
                            except (ValueError, IndexError):
                                validation_error = f'时间解析失败: {trade_time!r}'

                    if validation_error:
                        self.send_response(400)
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            'ok': False, 'error': validation_error,
                        }).encode())
                        return

                    input_source = str(entry.get('input_source', '') or '')
                    ticket_id = str(entry.get('ticket_id', '') or '')
                    if not ticket_id:
                        if input_source not in ('manual_backfill', 'correction'):
                            self.send_response(409)
                            self.send_header('Content-Type', 'application/json')
                            self.end_headers()
                            self.wfile.write(json.dumps({
                                'ok': False,
                                'error': 'ticket_id required; /api/sync is recovery-only without ticket',
                            }).encode())
                            return
                        missing = [
                            key for key in ('confirmed_by', 'audit_note')
                            if not str(entry.get(key, '') or '').strip()
                        ]
                        if not str(entry.get('原因', '') or '').strip():
                            missing.append('reason')
                        if missing:
                            self.send_response(400)
                            self.send_header('Content-Type', 'application/json')
                            self.end_headers()
                            self.wfile.write(json.dumps({
                                'ok': False,
                                'error': f"manual_backfill missing required fields: {missing}",
                            }).encode())
                            return

                    _ensure_db()
                    try:
                        from scripts.db import create_trade_ticket, record_confirmed_fill
                        today = now.strftime('%Y-%m-%d')
                        ctx = _build_trade_context()
                        if not ticket_id:
                            action_type = 'sell' if '卖' in action else 'buy'
                            ticket_id = create_trade_ticket({
                                'trade_date': today,
                                'code': entry.get('代码', ''),
                                'name': entry.get('标的', ''),
                                'action_type': action_type,
                                'ticket_purpose': 'post_trade_reconciliation',
                                'status': 'confirmed',
                                'intent_text': entry.get('原因', ''),
                                'human_override_reason': entry.get('原因', ''),
                                'review_note': entry.get('audit_note', ''),
                                'rule_state_json': ctx.get('rule_state'),
                                'market_snapshot_json': ctx.get('market_snapshot'),
                                'rule_pack_version': ctx.get('rule_pack_version'),
                                'rule_snapshot_hash': ctx.get('rule_snapshot_hash'),
                                'today_execution_card_id': ctx.get('today_execution_card_id'),
                            })
                            entry['ticket_id'] = ticket_id
                            entry.setdefault('trade_group_id', f'BACKFILL-{today}-{entry.get("代码", "")}')
                            entry.setdefault('leg_type', 'manual_backfill')
                        result = record_confirmed_fill(
                            entry,
                            rule_state=ctx.get('rule_state'),
                            market_snapshot=ctx.get('market_snapshot'),
                            confirmation={
                                'context_captured_at': ctx.get('context_captured_at'),
                                'context_status': ctx.get('context_status'),
                                'context_unavailable_reason': ctx.get('context_unavailable_reason'),
                            },
                        )
                        trade_id = result['trade_id']
                        status = result['status']
                        ticket_id = result['ticket_id']
                    except ValueError as e:
                        msg = str(e)
                        status_code = 409 if ('exceeds sellable' in msg or 'ticket_id required' in msg) else 400
                        self.send_response(status_code)
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({'ok': False, 'error': msg}).encode())
                        return
                    except Exception as e:
                        self.send_response(500)
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())
                        print(f"  [bridge] Ticket-aware sync error: {e}")
                        return

                    if positions_updated:
                        atomic_write_json(DATA_FILE, data)

                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        'ok': True, 'status': status, 'trade_id': trade_id, 'ticket_id': ticket_id,
                    }).encode())
                    _refresh_stock_codes(data)
                    print(f"  [bridge] Synced {status} trade_id={trade_id} ticket_id={ticket_id} → {DATA_FILE}")
                elif tlist:
                    self.send_response(409)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        'ok': False, 'error': 'batch format deprecated; use single entry',
                    }).encode())
                    return
                else:
                    # positions-only sync (no entry)
                    if positions_updated:
                        atomic_write_json(DATA_FILE, data)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': True}).encode())
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
                print(f"  [bridge] Error: {e}")
            finally:
                self._db_close()

        elif self.path == '/api/refresh':
            try:
                import subprocess
                gen_script = ROOT / "scripts" / "gen_dashboard_data.py"
                result = subprocess.run(
                    ["python3", str(gen_script)],
                    capture_output=True, text=True, timeout=120,
                    cwd=str(ROOT)
                )
                self.send_response(200 if result.returncode == 0 else 500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'ok': result.returncode == 0,
                    'output': result.stdout[-200:] if result.stdout else '',
                    'error': result.stderr[-200:] if result.stderr else ''
                }).encode())
                print(f"  [bridge] gen_dashboard_data.py triggered (rc={result.returncode})")
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())
                print(f"  [bridge] refresh error: {e}")

        elif self.path == '/api/llm':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body)
                mode = payload.get('mode', 'auto')   # auto | manual
                question = payload.get('question', None)  # None when "立即研判" has no user question
                userMsg = payload.get('userMsg', None)  # P1-3: 用户消息，供后端写入 conversation

                # 服务端生成时间节点，不再信任前端
                now_ts = datetime.now().strftime('%H:%M:%S')
                node = payload.get('node', now_ts)

                # ── Rate Limit（仅手动模式，线程安全）────────────────────
                if mode == 'manual':
                    now_s = time.time()
                    with _llm_rate_lock:
                        if '_llm_rate' not in CACHE:
                            CACHE['_llm_rate'] = {}
                        recent = [t for t in CACHE['_llm_rate'].get('manual', [])
                                  if now_s - t < 60]
                        if len(recent) >= 10:
                            self.send_response(429)
                            self.send_header('Content-Type', 'application/json')
                            self.end_headers()
                            self.wfile.write(json.dumps({
                                'ok': False,
                                'error_type': 'rate_limit',
                                'error': '请求太频繁，请30秒后再试'
                            }, ensure_ascii=False).encode())
                            print(f"  [bridge] Rate limited: manual mode")
                            return
                        CACHE['_llm_rate']['manual'] = recent + [now_s]

                # ── 快照（后端统一构建）─────────────────────────────────
                snapshot = _build_full_snapshot()

                # ── 对话记忆：加载今日历史，取最近3轮 ──────────────────
                today = datetime.now().strftime('%Y-%m-%d')
                insights = {}
                if LLM_INSIGHTS_FILE.exists():
                    try:
                        with open(LLM_INSIGHTS_FILE) as f:
                            insights = json.load(f)
                    except Exception:
                        pass
                day_data = insights.get(today, {})
                conversation = day_data.get('conversation', [])

                messages = []
                recent = conversation[-6:]  # 最近3轮 = 6条 user+assistant
                for m in recent:
                    if m.get('role') in ('user', 'assistant') and m.get('text', '').strip():
                        messages.append({
                            "role": m['role'],
                            "content": m['text'].strip()
                        })

                # ── Prompt 拼接 ───────────────────────────────────────
                now_dt = datetime.now()
                weekday_cn = ['周一','周二','周三','周四','周五','周六','周日'][now_dt.weekday()]
                time_ctx = f"{now_dt.strftime('%Y-%m-%d')} {weekday_cn} {node}"

                w1_hint = ''
                if '09:' in str(node) or '10:0' in str(node):
                    w1_hint = ('\n\n⚠️ 当前是W1早盘时段(9:30-10:00)。'
                               '请按W1特别关注4项评估：龙头状态、板块合力、候选标的、竞价三件套。'
                               '连板池中标的的操作信号优先输出。')

                if mode == 'manual' and question:
                    prompt = (f"当前时间: {time_ctx}\n"
                              f"用户问题: {question}\n\n"
                              f"全盘数据:\n{json.dumps(snapshot, ensure_ascii=False, indent=2)}\n\n"
                              f"请针对用户问题给出研判。回答要具体，引用实时数据。")
                else:
                    prompt = f"当前时间: {time_ctx}{w1_hint}\n\n全盘数据:\n{json.dumps(snapshot, ensure_ascii=False, indent=2)}"

                messages.append({"role": "user", "content": prompt})
                result = _call_llm_api(messages)

                if not result.get('ok'):
                    err = result.get('error', 'unknown')
                    if 'token' in err.lower() or 'auth' in err.lower() or '401' in str(err):
                        err_type, status = 'auth', 502
                    elif 'timeout' in err.lower() or 'timed out' in err.lower():
                        err_type, status = 'timeout', 504
                    else:
                        err_type, status = 'api_error', 502
                    self.send_response(status)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        'ok': False,
                        'error_type': err_type,
                        'error': err
                    }, ensure_ascii=False).encode())
                    print(f"  [bridge] LLM error [{err_type}]: {str(err)[:100]}")
                    return

                raw_text = result['text']

                # ── 共用处理入口（userMsg 传入单次持久化）──
                today_str = datetime.now().strftime('%Y-%m-%d')
                insight, verified_signals, verified_count, warning_count = _process_llm_result(
                    raw_text, snapshot, today_str, now_ts, mode, userMsg)

                # ── 持久化 → pnl.db ──
                _ensure_db()
                try:
                    from scripts.db import insert_llm
                    insert_llm(datetime.now().strftime('%Y-%m-%d'), now_ts,
                               insight['text'], verified_signals,
                               verified_count, warning_count)
                except Exception as e:
                    print(f"  [bridge] SQLite LLM insert error: {e}")
                finally:
                    self._db_close()

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, **insight}, ensure_ascii=False).encode())
                print(f"  [bridge] LLM [{mode}] {now_ts}: {len(insight['text'])} chars, {verified_count}\u2705/{warning_count}\u26a0\ufe0f")

            except json.JSONDecodeError:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': 'Invalid JSON'}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())
                print(f"  [bridge] LLM exception: {e}")
            finally:
                self._db_close()

        elif self.path == '/api/trades/review':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length)
                if not body:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': False, 'error': 'Missing body'}).encode())
                    return
                payload = json.loads(body)
                trade_id = int(payload.get('trade_id', 0))
                note = str(payload.get('review_note', '') or '')[:2000]
                if trade_id <= 0 or not note:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': False, 'error': 'trade_id and review_note required'}).encode())
                    return
                _ensure_db()
                from scripts.db import update_trade_review_note
                updated = update_trade_review_note(trade_id, note)
                if not updated:
                    self.send_response(404)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': False, 'error': f'trade_id {trade_id} not found'}).encode())
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True}).encode())
                print(f"  [bridge] Review note written for trade {trade_id}")
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())
            finally:
                self._db_close()

        elif self.path == '/api/account/correct':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length)
                if not body:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': False, 'error': 'Missing request body'}).encode())
                    return
                payload = json.loads(body)
                original_id = int(payload.get('original_trade_id', 0))
                if original_id <= 0:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': False, 'error': 'original_trade_id required'}).encode())
                    return
                _ensure_db()
                from scripts.db import insert_correction_trade
                new_id = insert_correction_trade(
                    original_trade_id=original_id,
                    correction_action=payload.get('correction_action'),
                    correction_price=payload.get('correction_price'),
                    correction_qty=payload.get('correction_qty'),
                    note=payload.get('note', 'manual correction'),
                )
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'correction_trade_id': new_id}).encode())
                print(f"  [bridge] Corrected trade {original_id} → new trade {new_id}")
            except json.JSONDecodeError:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': 'Invalid JSON'}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())
                print(f"  [bridge] correct error: {e}")
            finally:
                self._db_close()

        else:
            self.send_response(404)
            self.end_headers()

        # 释放本线程的 SQLite 连接，避免连接随请求线程累积
        self._db_close()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, format, *args):
        if args and hasattr(args[0], 'startswith'):
            if args[0].startswith('GET /api/') or args[0].startswith('POST /api/'):
                print(f"  [{self.log_date_time_string()}] {args[0]}")

# ── 提取为模块级函数以便测试回调生命周期 ──────────────────────────────────

def run_closing_anchor(quotes=None, pnl_history_path=None):
    """收盘锚点回调（15:05）：生成今日收盘锚点并写入 pnl_history.json"""
    from scripts.account_ssot import generate_closing_anchor
    from scripts.db import close_conn
    try:
        closing_quotes = dict(quotes or CACHE.get('live_quotes', {}) or {})
        closing_quotes.update(CACHE.get('live_index', {}) or {})
        result = generate_closing_anchor(closing_quotes,
                                         pnl_history_path=pnl_history_path)
        if result:
            print(f"  [bridge] Closing anchor: {result}")
        else:
            print(f"  [bridge] Closing anchor: skipped (no today anchor)")
    except Exception as e:
        print(f"  [bridge] Closing anchor error: {e}")
    finally:
        close_conn()


def run_morning_health_check():
    """日初健康检查回调（9:35）：检查今日锚点是否存在。
    持仓账户缺 previous_close → 报警/阻断，不静默造 anchor。
    """
    from scripts.db import query_account_baseline, close_conn
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        anchor = query_account_baseline(today)
        if not anchor:
            print(f"  [bridge] BLOCKED: {today} anchor missing — positions not locked. Run closing anchor or create manual_correction.")
        else:
            src = anchor.get("source", "")
            if src == "recovery":
                print(f"  [bridge] WARNING: {today} anchor is recovery (not previous_close)")
            else:
                print(f"  [bridge] Morning health check: anchor OK ({src})")
    finally:
        close_conn()


def trigger_llm_auto():
    """T5 LLM 自动研判回调 — 盘中时段每 14min 触发，浏览器关闭也能运行"""
    now = datetime.now()
    h, m = now.hour, now.minute
    total_min = h * 60 + m
    # 非交易时段跳过（9:25 - 15:05）
    if total_min < 565 or total_min > 905:
        return
    # 速率限制（14min 冷却，900s）
    now_s = time.time()
    with _llm_rate_lock:
        recent = [t for t in CACHE.get('_llm_rate', {}).get('auto', [])
                  if now_s - t < 900]
        if len(recent) >= 100:   # 宽松限制，避免占满手动额度
            return
        CACHE.setdefault('_llm_rate', {})['auto'] = recent + [now_s]
    node = now.strftime('%H:%M:%S')
    weekday_cn = ['周一','周二','周三','周四','周五','周六','周日'][now.weekday()]
    time_ctx = f"{now.strftime('%Y-%m-%d')} {weekday_cn} {node}"
    try:
        snapshot = _build_full_snapshot()

        today_str = now.strftime('%Y-%m-%d')
        insights = {}
        if LLM_INSIGHTS_FILE.exists():
            try:
                with open(LLM_INSIGHTS_FILE) as f:
                    insights = json.load(f)
            except Exception:
                pass
        conversation = insights.get(today_str, {}).get('conversation', [])
        messages = []
        for m in conversation[-6:]:
            if m.get('role') in ('user', 'assistant') and m.get('text', '').strip():
                messages.append({"role": m['role'], "content": m['text'].strip()})

        w1_hint = ''
        if '09:' in node or '10:0' in node:
            w1_hint = ('\n\n⚠️ 当前是W1早盘时段(9:30-10:00)。'
                       '请按W1特别关注4项评估：龙头状态、板块合力、候选标的、竞价三件套。'
                       '连板池中标的的操作信号优先输出。')
        prompt = f"当前时间: {time_ctx}{w1_hint}\n\n全盘数据:\n{json.dumps(snapshot, ensure_ascii=False, indent=2)}"
        messages.append({"role": "user", "content": prompt})
        result = _call_llm_api(messages)
        if not result.get('ok'):
            print(f"  [bridge] LLM auto error: {str(result.get('error',''))[:80]}")
            return
        raw_text = result['text']
        insight, verified_signals, verified_count, warning_count = _process_llm_result(
            raw_text, snapshot, today_str, node, 'auto')
        try:
            _ensure_db()
            from scripts.db import insert_llm
            insert_llm(today_str, node, insight['text'], verified_signals,
                       verified_count, warning_count)
        except Exception as e:
            print(f"  [bridge] SQLite LLM insert error: {e}")
        print(f"  [bridge] LLM [auto-scheduler] {node}: {len(insight['text'])} chars, {verified_count}✅/{warning_count}⚠️")
    except Exception as e:
        print(f"  [bridge] LLM auto-scheduler exception: {e}")
    finally:
        from scripts.db import close_conn
        close_conn()


def _run_cold_bootstrap(bootstrap_fns):
    """Run slow cold-start collectors without blocking HTTP readiness."""
    print(f'[bridge] Cold-start bootstrap: running initial collection...')
    for bootstrap_fn in bootstrap_fns:
        try:
            bootstrap_fn(force=True)
        except Exception as e:
            print(f'  [bridge] bootstrap warning: {e}')


def start_cold_bootstrap(bootstrap_fns):
    """Start cold bootstrap collectors in a daemon thread and return it."""
    thread = Thread(
        target=_run_cold_bootstrap,
        args=(list(bootstrap_fns),),
        name="bridge-cold-bootstrap",
        daemon=True,
    )
    thread.start()
    return thread


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    try:
        # Claim the singleton port before schedulers/bootstrap can mutate live data.
        server = ThreadingHTTPServer(('', port), BridgeHandler)
    except OSError as e:
        print(f'[bridge] Cannot bind http://localhost:{port}: {e}', file=sys.stderr)
        sys.exit(1)

    # === 冷启动：从磁盘恢复采集缓存；账户资产由 account_ssot 单独加载
    _load_cache()

    # === APScheduler 启动 ===
    from scripts.collectors import iwencai_poll, market_data, sentiment_snapshot, quotes
    iwencai_poll.CACHE = CACHE
    market_data.CACHE = CACHE
    sentiment_snapshot.CACHE = CACHE
    quotes.CACHE = CACHE

    # 从 dashboard_data.json 读取自选池代码
    try:
        with open(DATA_FILE) as f:
            dd = json.load(f)
        codes = _refresh_stock_codes(dd)
        quotes.set_stock_codes(codes)
        print(f'[bridge] Stock codes loaded: {len(codes)}')
    except Exception:
        pass

    scheduler = BackgroundScheduler()
    # T1 实时（5s）
    scheduler.add_job(quotes.collect_quotes, 'interval', seconds=5, id='quotes_5s',
                      max_instances=3, misfire_grace_time=10, coalesce=True)
    scheduler.add_job(quotes.collect_index, 'interval', seconds=5, id='index_5s',
                      max_instances=3, misfire_grace_time=10, coalesce=True)
    # T1 半实时（30s）
    scheduler.add_job(quotes.collect_breadth, 'interval', seconds=30, id='breadth_30s',
                      max_instances=1, misfire_grace_time=60, coalesce=True)
    scheduler.add_job(quotes.collect_limit_counts, 'interval', seconds=60, id='limit_counts_60s',
                      max_instances=1, misfire_grace_time=120, coalesce=True)
    scheduler.add_job(quotes.collect_sectors, 'interval', seconds=30, id='sectors_30s',
                      max_instances=1, misfire_grace_time=60, coalesce=True)
    # 缓存落盘（30s，防重启丢数据）
    scheduler.add_job(_dump_cache, 'interval', seconds=30, id='cache_dump_30s',
                      max_instances=1, misfire_grace_time=60)
    # T1 慢周期（300s）
    scheduler.add_job(quotes.log_pnl_snapshot, 'interval', seconds=300, id='pnl_snap_300s',
                      max_instances=1, misfire_grace_time=600)
    # T2 阶段（2min-5min）
    # iwencai 10min 只补收益/晋级/连板等语义指标；情绪值和涨跌停核心计数由 PyTDX breadth 提供
    scheduler.add_job(iwencai_poll.poll_iwencai_sentiment, 'interval', minutes=10, id='iwencai_10min',
                      max_instances=1, misfire_grace_time=300)
    scheduler.add_job(market_data.poll_sector_inflow, 'interval', minutes=5, id='sector_inflow_5min',
                      max_instances=1, misfire_grace_time=600)
    scheduler.add_job(market_data.poll_news, 'interval', minutes=5, id='news_5min',
                      max_instances=1, misfire_grace_time=600)
    scheduler.add_job(quotes.collect_yesterday_compare, 'interval', seconds=30, id='yesterday_compare_30s',
                      max_instances=1, misfire_grace_time=60)
    scheduler.add_job(quotes.collect_northbound, 'interval', seconds=60, id='northbound_60s',
                      max_instances=1, misfire_grace_time=120)
    scheduler.add_job(quotes.collect_kline_15m, 'interval', seconds=60, id='kline_15m_60s',
                      max_instances=1, misfire_grace_time=120)
    scheduler.add_job(quotes.collect_hot_list, 'interval', minutes=5, id='hot_list_5min',
                      max_instances=1, misfire_grace_time=600)
    scheduler.add_job(iwencai_poll.poll_limit_up_detail, 'interval', minutes=5, id='limit_up_detail_5min',
                      max_instances=1, misfire_grace_time=600)
    # T2 定时快照
    # 8个关键节点快照（竞价+30s等iwencai，其余整点）
    for node_h, node_m, node_s, node_id in [
        (9,25,30,'auction'), (10,0,0,'morning'), (10,30,0,'morning2'),
        (11,30,0,'midday'), (13,30,0,'afternoon1'),
        (14,0,0,'afternoon'), (14,30,0,'afternoon2'), (15,0,0,'close')
    ]:
        scheduler.add_job(sentiment_snapshot.take_sentiment_snapshot, 'cron',
                          hour=node_h, minute=node_m, second=node_s,
                          id=f'sentiment_{node_id}', max_instances=1, misfire_grace_time=300)
    # 每30分钟兜底（bridge重启后也能抓到数据）
    scheduler.add_job(sentiment_snapshot.take_sentiment_snapshot, 'cron', minute='0,30', id='sentiment_periodic',
                      max_instances=1, misfire_grace_time=300)
    # 竞价5维快照：9:28（竞价9:25结束，iwencai需~3min处理连板数据，太早拿不到连续涨停天数）
    def run_auction_snapshot():
        from scripts.snapshot_auction import auction_catch_up
        snap, action = auction_catch_up()
        if action == "catch_up":
            print(f"  [bridge] Auction snapshot catch-up: captured at {snap.get('captured_at','?')}")
        elif action == "skip":
            print(f"  [bridge] Auction snapshot already valid, skip")
        elif action == "error":
            print(f"  [bridge] Auction snapshot error: {snap.get('error','unknown')[:100]}")
    scheduler.add_job(run_auction_snapshot, 'cron', hour=9, minute=28, id='auction_0928',
                      max_instances=1, misfire_grace_time=600)
    # 竞价补抓：09:35 二次入口，已有效快照 skip，缺失/无效补抓
    scheduler.add_job(run_auction_snapshot, 'cron', hour=9, minute=35, id='auction_0935_catchup',
                      max_instances=1, misfire_grace_time=600)
    # 收盘数据包（15:02 dump CACHE 全量快照）— 暂停，LLM 方案将替代
    # from scripts.snapshot_close import run_snapshot_close
    # scheduler.add_job(lambda: run_snapshot_close(CACHE, ROOT), 'cron', hour=15, minute=2,
    #                   id='snapshot_close_1502', max_instances=1, misfire_grace_time=300)
    # T4 收盘锚点（15:05：行情已收尾，取最后有效快照）
    scheduler.add_job(run_closing_anchor, 'cron', hour=15, minute=5, id='closing_anchor_1505',
                      max_instances=1, misfire_grace_time=600)

    # T4 基线刷新（盘前 + 盘后）
    def run_gen_baseline():
        import subprocess
        gen_script = ROOT / "scripts" / "gen_dashboard_data.py"
        result = subprocess.run(["python3", str(gen_script)], capture_output=True, text=True, timeout=120, cwd=str(ROOT))
        if result.returncode != 0:
            print(f'  [bridge] gen_dashboard_data.py failed: {result.stderr[-200:]}')
            return False
        return True
    scheduler.add_job(run_gen_baseline, 'cron', hour=8, minute=30, id='gen_baseline_0830',
                      max_instances=1, misfire_grace_time=600)
    scheduler.add_job(run_gen_baseline, 'cron', hour=15, minute=10, id='gen_baseline_1510',
                      max_instances=1, misfire_grace_time=600)

    # T4.5 日初健康检查（9:35：检查今日锚点是否存在）
    scheduler.add_job(run_morning_health_check, 'cron', hour=9, minute=35, id='morning_health_0935',
                      max_instances=1, misfire_grace_time=600)

    # 每14分钟触发一次（留1分钟缓冲，比前端的15min间隔略快以避免漂移）
    scheduler.add_job(trigger_llm_auto, 'interval', seconds=840, id='llm_auto_14min',
                      max_instances=1, misfire_grace_time=60, coalesce=True)

    scheduler.start()
    print(f'[bridge] APScheduler started: {len(scheduler.get_jobs())} jobs registered')

    # 冷启动 gen：每天只跑一次（盘中重启不覆盖 W15 同步的实时持仓/pnl）
    today_str = datetime.now().strftime('%Y-%m-%d')
    need_gen = True
    try:
        if DATA_FILE.exists():
            with open(DATA_FILE) as f:
                dd = json.load(f)
            if _baseline_generated_today(dd.get('meta', {}), today_str):
                need_gen = False
                print(f'[bridge] Gen already ran today, skipping cold-start to preserve live positions')
    except Exception:
        pass
    now_t = datetime.now().time()
    in_trading_session = _time(9, 30) <= now_t <= _time(15, 0)
    if need_gen and in_trading_session:
        print(f'[bridge] Cold-start: stale baseline detected during trading; deferring gen to scheduled close refresh')
    elif need_gen:
        print(f'[bridge] Cold-start: running gen_dashboard_data.py...')
        run_gen_baseline()

    # 冷启动：强制执行一次初始采集填充缓存（不受 is_trading_time 限制）
    # 云端数据源可能慢或限流，不能阻塞 HTTP ready。
    start_cold_bootstrap([
        quotes.collect_limit_counts,
        market_data.poll_sector_inflow,
        iwencai_poll.poll_limit_up_detail,
        iwencai_poll.poll_iwencai_sentiment,
        quotes.collect_quotes,
        quotes.collect_yesterday_compare,
        quotes.collect_hot_list,
        quotes.collect_index,
        quotes.collect_sectors,
        quotes.collect_kline_15m,
        quotes.log_pnl_snapshot,
    ])

    print(f'[bridge] 看板桥接服务启动 → http://localhost:{port}')
    print(f'[bridge] W15 记流水自动同步到 {DATA_FILE}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        scheduler.shutdown(wait=False)
        print('\n[bridge] 已停止')
