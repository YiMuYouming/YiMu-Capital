#!/usr/bin/env python3
"""bridge.py — 看板 ↔ JSON 桥接服务
在看板目录运行: python3 scripts/bridge.py
然后浏览器打开 http://localhost:8080
W15 记流水时自动 POST 到 /api/sync，实时写入 JSON
LLM Hook: POST /api/llm → Anthropic API → 研判文本
"""

import json, os, sys, time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
from pathlib import Path
from datetime import datetime, time as _time
from urllib.parse import parse_qs, urlparse
from threading import Lock

from apscheduler.schedulers.background import BackgroundScheduler

ROOT = Path(__file__).resolve().parent.parent

try:
    from scripts.file_utils import atomic_write_json
except ImportError:
    _s = str(ROOT)
    if _s not in sys.path: sys.path.insert(0, _s)
    from scripts.file_utils import atomic_write_json

# 内存缓存（APScheduler 采集线程写入，HTTP handler 读取）
CACHE = {}
CACHE_FILE = ROOT / "data" / "cache_dump.json"
DATA_FILE = ROOT / "data/dashboard_data.json"
LLM_INSIGHTS_FILE = ROOT / "data/llm_insights.json"

_llm_rate_lock = Lock()


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


def _collect_stock_codes(data):
    """Collect all instruments that must stay subscribed to live quotes."""
    return list(set(
        [s.get('代码') for s in data.get('lianban_pool', []) if s.get('代码')] +
        [s.get('代码') for s in data.get('trend_pool', []) if s.get('代码')] +
        [a.get('代码') for a in data.get('decision', {}).get('锚定股状态', []) if a.get('代码')] +
        [p.get('代码') for p in data.get('positions', []) if p.get('代码')]
    ))


def _trade_cash_effect(op):
    """Return the cash movement for one executed trade."""
    amount = round(float(op.get('价格', 0) or 0) * float(op.get('数量', 0) or 0), 2)
    action = str(op.get('动作', ''))
    if '卖出' in action:
        return amount
    if '买入' in action or '追涨' in action:
        return -amount
    return 0


def _payload_overwrites_account(payload):
    """Asset state is server-owned; legacy browser PnL writes are forbidden."""
    return isinstance(payload, dict) and 'pnl' in payload

# SQLite db
try:
    from scripts.db import init_db, query_pnl, query_trades, query_pnl_summary
    from scripts.account_ssot import load_current_account_state
    init_db()
except ImportError:
    _s = str(ROOT)
    if _s not in sys.path: sys.path.insert(0, _s)
    from scripts.db import init_db, query_pnl, query_trades, query_pnl_summary
    from scripts.account_ssot import load_current_account_state
    init_db()


def _merge_pnl_summary(snapshot_summary, account_state):
    """Keep chart metadata, but source all live asset values from account SSOT."""
    result = dict(snapshot_summary or {})
    for key in [
        'cash', 'positions', 'trades', 'mv', 'total_asset', 'day_start_asset',
        'pnl_amount', 'pnl_pct', 'pos_pct', 'total_deposit',
        'valuation_complete', 'anchor', '_updated',
    ]:
        if key in account_state:
            result[key] = account_state[key]
    return result


def _current_pnl_summary():
    legacy = query_pnl_summary()
    state = load_current_account_state(CACHE.get('live_quotes', {}))
    return _merge_pnl_summary(legacy, state)

# === LLM System Prompt ===
SYSTEM_PROMPT_HEADER = """你是弈沐盯盘助手，严格遵循弈沐交易规则做研判。
每次研判你会收到: ①交易规则(LLM_RULES) ②项目约定(CLAUDE) ③全盘实时数据。
结论优先，引用具体数据点。操作建议必须对照规则逐条验证。"""

OUTPUT_FORMAT = """## 输出格式
[TEXT]
3-5句中文研判。结论优先，简洁直白。W1时段优先回答龙头和合力问题。
[SIGNALS]
每行一个信号，格式: 类型 | 标的 | 方向 | 置信度
类型: BUY/WATCH/RISK/INFO 方向: 多/空/— 置信度: 高/中/低"""


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


def _verify_signals(signals_raw, snapshot):
    """ReAct 验证：交叉检查 LLM 输出的信号是否与数据一致"""
    verified = []
    for line in signals_raw.strip().split('\n'):
        line = line.strip()
        if not line or '|' not in line:
            continue
        parts = [p.strip() for p in line.split('|')]
        if len(parts) < 4:
            continue
        sig_type, target, direction, confidence = parts[0], parts[1], parts[2], parts[3]

        check = {'signal': line, 'type': sig_type, 'target': target, 'status': '✅', 'note': ''}

        # 验证规则（基于数据快照交叉检查）
        try:
            if sig_type == 'BUY':
                # 检查该标的是否真的在趋势自选里，且满足 W2 回踩条件
                trend_stocks = snapshot.get('趋势自选', [])
                found = None
                for s in trend_stocks:
                    if target in str(s.get('name', '')):
                        found = s
                        break
                if found:
                    dist_str = str(found.get('dist_to_ma10_60m', '—'))
                    vol_str = str(found.get('volRatio', '1'))
                    if '—' in dist_str:
                        check['status'] = '⚠️'
                        check['note'] = 'MA10数据缺失，无法验证回踩距离'
                    else:
                        dist = float(dist_str.replace('%', ''))
                        vol = float(vol_str)
                        conditions_met = 0
                        if -1 <= dist <= 0.5:
                            conditions_met += 1
                        else:
                            check['note'] = f'距MA10 {dist}% (需-1%~0.5%)'
                        if vol < 0.8:
                            conditions_met += 1
                        else:
                            check['note'] = (check['note'] + ' ' if check['note'] else '') + f'量比{vol}(需<0.8)'
                        if conditions_met < 2:
                            check['status'] = '⚠️'
                            if not check['note']:
                                check['note'] = '回踩条件不足'
                        elif conditions_met == 2:
                            check['note'] = '满足回踩+缩量' + ((' ' + check['note']) if check['note'] else '')
                else:
                    check['status'] = '⚠️'
                    check['note'] = '标的未在趋势自选池中'

            elif sig_type == 'RISK':
                # 检查风控指标
                positions = snapshot.get('持仓', [])
                for p in positions:
                    if target in str(p.get('name', '')):
                        pnl = float(str(p.get('pnl_pct', '0')).replace('%', ''))
                        if pnl < -3:
                            check['note'] = f'浮亏{pnl}%，接近熔断线'
                        elif pnl < 0:
                            check['note'] = f'浮亏{pnl}%，正常范围内'
                        else:
                            check['note'] = f'浮盈，无风险'
                        break

            elif sig_type == 'INFO':
                # 信息类信号，仅检查数据是否存在
                sectors = snapshot.get('sectors', [])
                found_sec = any(target in str(s.get('name', '')) for s in sectors)
                if not found_sec:
                    check['status'] = '⚠️'
                    check['note'] = '板块未在数据中'

        except Exception as e:
            check['status'] = '⚠️'
            check['note'] = f'验证异常: {str(e)[:50]}'

        verified.append(check)

    return verified


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


# ===== 快照构建（供 LLM 和调试端点使用） =====

def _load_dashboard_data():
    """读取 dashboard_data.json，带缓存避免重复读盘"""
    try:
        if DATA_FILE.exists():
            with open(DATA_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


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
        lianban_pool.append({
            '标的': s.get('标的', '—'),
            '代码': code,
            '板块': s.get('板块', '—'),
            '角色': s.get('角色', '—'),
            '涨幅': pnl_str,
            '量比': q.get('量比', s.get('量比', '—')),
            'MA10_60m': q.get('MA10_60m', '—'),
        })

    # ── 4. 趋势池（基线 + 实时涨幅/量比） ──────────────────────
    trend_pool = []
    for s in (dd.get('trend_pool') or []):
        code = str(s.get('代码', ''))
        q = live_quotes.get(code, {})
        trend_pool.append({
            '标的': s.get('标的', '—'),
            '代码': code,
            '板块': s.get('板块', '—'),
            '角色': s.get('角色', '—'),
            '涨幅': q.get('涨幅', '—'),
            '量比': q.get('量比', s.get('量比', '—')),
            'MA10_60m': q.get('MA10_60m', '—'),
        })

    # ── 5. 持仓（基线 + 实时现价/浮盈） ──────────────────────
    positions = []
    for p in (dd.get('positions') or []):
        code = str(p.get('代码', ''))
        q = live_quotes.get(code, {})
        cost = p.get('成本', 0)
        price = q.get('最新价') or p.get('现价') or 0
        qty_str = str(p.get('数量', '0'))
        try:
            qty = int(''.join(filter(str.isdigit, qty_str)))
        except Exception:
            qty = 0
        pnl_pct = ((price - cost) / cost * 100) if cost and price else 0
        positions.append({
            '标的': p.get('标的', '—'),
            '代码': code,
            '成本': cost,
            '现价': price,
            '数量': qty,
            '浮盈%': round(pnl_pct, 2),
            '状态': p.get('状态', '—'),
        })

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
    risk_snap = {
        '连亏天数':    risk.get('连亏天数', 0),
        '周累计回撤':  risk.get('周累计回撤', 0),
        '月累计回撤':  risk.get('月累计回撤', 0),
        '仓位':        round(total_mv / total_asset * 100, 2) if total_asset else 0,
        '总资产':      total_asset,
    }

    return {
        '指数': index_snap,
        '情绪': sentiment_snap,
        '连板池': lianban_pool,
        '趋势池': trend_pool,
        '持仓': positions,
        '板块': sectors,
        '涨停梯队TOP5': hot_rank,
        '风控': risk_snap,
    }


class BridgeHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _serve_cached(self, key, data_type):
        result = CACHE.get(key, {})
        fetched_at = result.get('_updated') if isinstance(result, dict) else None
        result = _add_freshness(result, data_type, fetched_at)
        body = json.dumps(result, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/debug/snapshot':
            snap = _build_full_snapshot()
            body = json.dumps(snap, ensure_ascii=False, indent=2).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body)
            return
        elif parsed.path == '/api/baseline':
            try:
                if DATA_FILE.exists():
                    with open(DATA_FILE) as f:
                        result = json.load(f)
                else:
                    result = {}
                meta = result.get('meta', {}) if isinstance(result, dict) else {}
                result = _add_freshness(result, 'baseline', meta.get('updated') or meta.get('date'))
                body = json.dumps(result, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
            return
        elif parsed.path == '/api/pnl':
            qs = parse_qs(parsed.query)
            range_val = qs.get('range', ['today'])[0]
            index_val = qs.get('index', ['sh'])[0]
            try:
                result = query_pnl(range_val, index_val)
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
            return
        elif parsed.path == '/api/pnl/summary':
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
            return
        elif parsed.path == '/api/account/state':
            try:
                result = load_current_account_state(CACHE.get('live_quotes', {}))
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
            return
        elif parsed.path == '/api/account/correct':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length)
                payload = json.loads(body)
                original_id = int(payload.get('original_trade_id', 0))
                if original_id <= 0:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': False, 'error': 'original_trade_id required'}).encode())
                    return
                from scripts.db import insert_correction_trade
                new_id = insert_correction_trade(
                    original_trade_id=original_id,
                    correction_action=payload.get('action'),
                    correction_price=payload.get('price'),
                    correction_qty=payload.get('qty'),
                    note=payload.get('note', 'manual correction'),
                )
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'correction_trade_id': new_id}).encode())
                print(f"  [bridge] Corrected trade {original_id} → new trade {new_id}")
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())
            return
        elif parsed.path == '/api/trades':
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
            result = {
                'live_index': CACHE.get('live_index', {}),
                'live_quotes': CACHE.get('live_quotes', {}),
                'breadth': CACHE.get('breadth', {}),
                'live_sectors': CACHE.get('live_sectors', {}),
                'hot_list': CACHE.get('hot_list', {}),
                'sector_inflow': CACHE.get('sector_inflow', {}),
                'northbound': CACHE.get('northbound', {}),
                'iwencai': CACHE.get('iwencai', {}),
                '上证15min': CACHE.get('上证15min', []),
                '深证15min': CACHE.get('深证15min', []),
                '创业15min': CACHE.get('创业15min', []),
            }
            result = _add_freshness(result, 'live_quote', CACHE.get('live_quotes', {}).get('_updated'))
            body = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body)
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
                    result = {
                        'live_index': CACHE.get('live_index', {}),
                        'live_quotes': CACHE.get('live_quotes', {}),
                        'breadth': CACHE.get('breadth', {}),
                        'live_sectors': CACHE.get('live_sectors', {}),
                        'hot_list': CACHE.get('hot_list', {}),
                        'sector_inflow': CACHE.get('sector_inflow', {}),
                        'northbound': CACHE.get('northbound', {}),
                        'iwencai': CACHE.get('iwencai', {}),
                        '上证15min': CACHE.get('上证15min', []),
                        '深证15min': CACHE.get('深证15min', []),
                        '创业15min': CACHE.get('创业15min', []),
                    }
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
        if self.path == '/api/sync':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body)
                if _payload_overwrites_account(payload):
                    self.send_response(409)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        'ok': False,
                        'error': 'account asset fields are server-owned; submit trade events only',
                    }).encode())
                    return
                if DATA_FILE.exists():
                    with open(DATA_FILE) as f:
                        data = json.load(f)
                else:
                    data = {}

                # Lock the pre-command account state before applying a new event.
                if payload.get('今日操作'):
                    load_current_account_state(CACHE.get('live_quotes', {}))

                if 'positions' in payload:
                    # merge by 标的: 更新已有或追加新标的，不删除 data 中已有的标的
                    existing = {p.get('标的'): p for p in data.get('positions', [])}
                    for p in payload['positions']:
                        existing[p.get('标的')] = p
                    data['positions'] = list(existing.values())
                    CACHE['_stock_codes'] = _collect_stock_codes(data)
                if '今日操作' in payload:
                    if 'decision' not in data:
                        data['decision'] = {}
                    data['decision']['今日操作'] = payload['今日操作']
                # 同步写入 SQLite 交易记录（先写 DB，成功后再原子写 JSON）
                db_error = None
                try:
                    from scripts.db import insert_trade
                    tdate = payload.get('_trade_date', datetime.now().strftime('%Y-%m-%d'))
                    for op in (payload.get('今日操作') or []):
                        insert_trade({
                            'trade_date': tdate,
                            'trade_time': op.get('时间'),
                            'action': op.get('动作'),
                            'code': op.get('代码', ''),
                            'name': op.get('标的', ''),
                            'price': op.get('价格'),
                            'qty': op.get('数量'),
                            'window': op.get('窗口'),
                            'reason': op.get('原因'),
                        })
                except Exception as e:
                    db_error = str(e)
                    print(f"  [bridge] SQLite trade insert error: {e}")

                # 进程安全原子写入 JSON（filelock + atomic_write）
                if not db_error:
                    atomic_write_json(DATA_FILE, data)

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True}).encode())
                print(f"  [bridge] Synced {len(body)} bytes → {DATA_FILE}")
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
                print(f"  [bridge] Error: {e}")

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

                # ── 解析 [TEXT] / [SIGNALS] 结构 ───────────────────────
                text_part = raw_text
                signals_part = ''
                if '[TEXT]' in raw_text and '[SIGNALS]' in raw_text:
                    parts = raw_text.split('[SIGNALS]')
                    text_part = parts[0].replace('[TEXT]', '').strip()
                    signals_part = parts[1].strip() if len(parts) > 1 else ''
                elif not raw_text.strip():
                    text_part = '(模型返回为空，请重试)'

                # ── ReAct 验证 ─────────────────────────────────────────
                verified_signals = []
                if signals_part:
                    try:
                        verified_signals = _verify_signals(signals_part, snapshot)
                    except Exception as e:
                        print(f"  [bridge] signal verify error: {e}")

                verified_count = sum(1 for v in verified_signals if v.get('status') == '\u2705')
                warning_count = sum(1 for v in verified_signals if v.get('status') == '\u26a0\ufe0f')

                insight = {
                    'timestamp': now_ts,
                    'node': node,
                    'mode': mode,
                    'text': text_part,
                    'signals': verified_signals,
                    'verified_count': verified_count,
                    'warning_count': warning_count,
                }

                # ── 持久化 → llm_insights.json（v2 conversation 格式，复用上方的 insights） ──
                if today not in insights:
                    insights[today] = {'meta': {}, 'conversation': []}

                meta = insights[today].setdefault('meta', {})
                if 'started_at' not in meta:
                    meta['started_at'] = now_ts
                meta['last_assistant_ts'] = now_ts
                if mode == 'auto':
                    meta['auto_trigger_count'] = meta.get('auto_trigger_count', 0) + 1
                else:
                    meta['manual_question_count'] = meta.get('manual_question_count', 0) + 1

                # P1-3: 先写用户消息，再写 AI 回复，保证刷新后对话完整
                if userMsg and isinstance(userMsg, dict) and userMsg.get('text'):
                    insights[today]['conversation'].append({
                        'role': 'user',
                        'ts': userMsg.get('ts', now_ts),
                        'text': userMsg.get('text', ''),
                        'auto': False,
                    })

                insights[today]['conversation'].append({
                    'role': 'assistant',
                    'ts': now_ts,
                    'text': text_part,
                    'signals': verified_signals,
                    'auto': mode == 'auto',
                })

                LLM_INSIGHTS_FILE.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_json(LLM_INSIGHTS_FILE, insights)

                # ── 持久化 → pnl.db ────────────────────────────────────
                try:
                    from scripts.db import insert_llm
                    insert_llm(today, node, text_part, verified_signals,
                               verified_count, warning_count)
                except Exception as e:
                    print(f"  [bridge] SQLite LLM insert error: {e}")

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, **insight}, ensure_ascii=False).encode())
                print(f"  [bridge] LLM [{mode}] {node}: {len(text_part)} chars, {verified_count}\u2705/{warning_count}\u26a0\ufe0f")

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

        else:
            self.send_response(404)
            self.end_headers()

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
        codes = _collect_stock_codes(dd)
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
    scheduler.add_job(quotes.collect_sectors, 'interval', seconds=30, id='sectors_30s',
                      max_instances=1, misfire_grace_time=60, coalesce=True)
    # 缓存落盘（30s，防重启丢数据）
    scheduler.add_job(_dump_cache, 'interval', seconds=30, id='cache_dump_30s',
                      max_instances=1, misfire_grace_time=60)
    # T1 慢周期（300s）
    scheduler.add_job(quotes.log_pnl_snapshot, 'interval', seconds=300, id='pnl_snap_300s',
                      max_instances=1, misfire_grace_time=600)
    # T2 阶段（2min-5min）
    # iwencai 10min轮询（仅涨停收益/连板收益/炸板收益，PyTDX不可替代）
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
        import subprocess
        snap_script = ROOT / "scripts" / "snapshot_auction.py"
        subprocess.run(["python3", str(snap_script)], capture_output=True, timeout=120, cwd=str(ROOT))
    scheduler.add_job(run_auction_snapshot, 'cron', hour=9, minute=28, id='auction_0928',
                      max_instances=1, misfire_grace_time=600)
    # 收盘数据包（15:02 dump CACHE 全量快照）— 暂停，LLM 方案将替代
    # from scripts.snapshot_close import run_snapshot_close
    # scheduler.add_job(lambda: run_snapshot_close(CACHE, ROOT), 'cron', hour=15, minute=2,
    #                   id='snapshot_close_1502', max_instances=1, misfire_grace_time=300)
    # T4 收盘锚点（15:05：行情已收尾，取最后有效快照）
    def run_closing_anchor():
        from scripts.account_ssot import generate_closing_anchor
        try:
            result = generate_closing_anchor(CACHE.get('live_quotes', {}))
            if result:
                print(f"  [bridge] Closing anchor: {result}")
            else:
                print(f"  [bridge] Closing anchor: skipped (no today anchor)")
        except Exception as e:
            print(f"  [bridge] Closing anchor error: {e}")

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
    def run_morning_health_check():
        from scripts.db import query_account_baseline
        today = datetime.now().strftime("%Y-%m-%d")
        anchor = query_account_baseline(today)
        if not anchor:
            print(f"  [bridge] ⚠️  MISSING TODAY ANCHOR for {today} — open positions/assets NOT yet locked")
            # 尝试从 pnl_history 补建
            try:
                from scripts.account_ssot import ensure_today_anchor, load_current_account_state
                from pathlib import Path
                dashboard_path = ROOT / "data" / "dashboard_data.json"
                history_path = ROOT / "data" / "pnl_history.json"
                if dashboard_path.exists() and history_path.exists():
                    state = load_current_account_state(CACHE.get('live_quotes', {}))
                    print(f"  [bridge] Auto-recovery anchor created: cash={state.get('cash')}, total_asset={state.get('total_asset')}")
            except Exception as e:
                print(f"  [bridge] Auto-recovery failed: {e}")
        else:
            print(f"  [bridge] Morning health check: anchor OK ({anchor.get('source')})")

    scheduler.add_job(run_morning_health_check, 'cron', hour=9, minute=35, id='morning_health_0935',
                      max_instances=1, misfire_grace_time=600)

    # T5 LLM 自动研判（15min，盘中时段，浏览器关闭也能运行）
    def trigger_llm_auto():
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
        # 直接调用内部 LLM 流程（复用 POST /api/llm 的逻辑，不走 HTTP）
        node = now.strftime('%H:%M:%S')
        weekday_cn = ['周一','周二','周三','周四','周五','周六','周日'][now.weekday()]
        time_ctx = f"{now.strftime('%Y-%m-%d')} {weekday_cn} {node}"
        try:
            snapshot = _build_full_snapshot()

            # ── 对话记忆：加载今日历史 ──
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
            text_part = raw_text
            signals_part = ''
            if '[TEXT]' in raw_text and '[SIGNALS]' in raw_text:
                parts = raw_text.split('[SIGNALS]')
                text_part = parts[0].replace('[TEXT]', '').strip()
                signals_part = parts[1].strip() if len(parts) > 1 else ''
            if not raw_text.strip():
                text_part = '(模型返回为空，请重试)'
            verified_signals = []
            if signals_part:
                try:
                    verified_signals = _verify_signals(signals_part, snapshot)
                except Exception as e:
                    print(f"  [bridge] signal verify error: {e}")
            verified_count = sum(1 for v in verified_signals if v.get('status') == '\u2705')
            warning_count = sum(1 for v in verified_signals if v.get('status') == '\u26a0\ufe0f')
            insight = {
                'timestamp': node,
                'node': node,
                'mode': 'auto',
                'text': text_part,
                'signals': verified_signals,
                'verified_count': verified_count,
                'warning_count': warning_count,
            }
            # 持久化（复用上方已加载的 insights）
            if today_str not in insights:
                insights[today_str] = {'meta': {}, 'conversation': []}
            meta = insights[today_str].setdefault('meta', {})
            if 'started_at' not in meta:
                meta['started_at'] = node
            meta['last_assistant_ts'] = node
            meta['auto_trigger_count'] = meta.get('auto_trigger_count', 0) + 1
            insights[today_str]['conversation'].append({
                'role': 'assistant',
                'ts': node,
                'text': text_part,
                'signals': verified_signals,
                'auto': True,
            })
            LLM_INSIGHTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(LLM_INSIGHTS_FILE, insights)
            try:
                from scripts.db import insert_llm
                insert_llm(today_str, node, text_part, verified_signals,
                           verified_count, warning_count)
            except Exception as e:
                print(f"  [bridge] SQLite LLM insert error: {e}")
            print(f"  [bridge] LLM [auto-scheduler] {node}: {len(text_part)} chars, {verified_count}\u2705/{warning_count}\u26a0\ufe0f")
        except Exception as e:
            print(f"  [bridge] LLM auto-scheduler exception: {e}")

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
            if dd.get('meta', {}).get('date') == today_str:
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
    print(f'[bridge] Cold-start bootstrap: running initial collection...')
    for bootstrap_fn in [quotes.collect_index, quotes.collect_quotes, quotes.collect_sectors, iwencai_poll.poll_iwencai_sentiment, quotes.collect_yesterday_compare, quotes.collect_kline_15m, quotes.log_pnl_snapshot, quotes.collect_hot_list]:
        try:
            bootstrap_fn(force=True)
        except Exception as e:
            print(f'  [bridge] bootstrap warning: {e}')

    print(f'[bridge] 看板桥接服务启动 → http://localhost:{port}')
    print(f'[bridge] W15 记流水自动同步到 {DATA_FILE}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        scheduler.shutdown(wait=False)
        print('\n[bridge] 已停止')
