#!/usr/bin/env python3
"""bridge.py — 看板 ↔ JSON 桥接服务
在看板目录运行: python3 scripts/bridge.py
然后浏览器打开 http://localhost:8080
W15 记流水时自动 POST 到 /api/sync，实时写入 JSON
LLM Hook: POST /api/llm → Anthropic API → 研判文本
"""

import json, os, sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from datetime import datetime, time as _time
from urllib.parse import parse_qs, urlparse

from apscheduler.schedulers.background import BackgroundScheduler

ROOT = Path(__file__).resolve().parent.parent

# 内存缓存（APScheduler 采集线程写入，HTTP handler 读取）
CACHE = {}
DATA_FILE = ROOT / "data/dashboard_data.json"
LLM_INSIGHTS_FILE = ROOT / "data/llm_insights.json"

# SQLite db
try:
    from scripts.db import query_pnl, query_trades, query_pnl_summary
except ImportError:
    _s = str(ROOT)
    if _s not in sys.path: sys.path.insert(0, _s)
    from scripts.db import query_pnl, query_trades, query_pnl_summary

# === LLM System Prompt ===
SYSTEM_PROMPT = """你是洋米盯盘助手，为弈沐哥的A股短线+趋势混合交易提供实时研判。

## 交易规则摘要
- W1(9:30-10:00): 连板追涨 + 趋势强回踩买入(60分钟MA10)
- W2(14:00-14:50): 连板尾盘低吸 + 趋势弱回踩确认
- 核心指标: 60分钟MA10回踩(方向↑,距≤1%) + 缩量(量比<0.8) + 未大跌(>-5%)
- 情绪: <20%冰点, 20-40%低迷, 40-60%主升, 60-80%强势, >80%高潮
- 涨停收益>2%可操作, 赚钱效应好/较好可做
- 单日熔断-3%, 连亏2天空仓

## W1 早盘特别关注
W1时段(9:30-10:00)额外评估以下项目，在研判中优先回答：
1. 连板龙头状态: 检查连板池中各板块龙头是否封板/断板，封板量能是否健康
2. 板块合力: 各板块有多少只标的涨幅>3%，合力是否形成(≥3只)
3. W1候选标的: 华电辽能(3进4)/万控智造(2进3)/韶能股份(1进2)各自条件是否满足
4. 竞价三件套: 情绪是否≥60%? 涨停收益是否>2%? W1标的是否有高开3-7%?

## 输出格式
你必须输出两个部分，用 [TEXT] 和 [SIGNALS] 标记分隔：

[TEXT]
3-5句中文研判。结论优先，简洁直白。W1时段优先回答龙头和合力问题。
[SIGNALS]
每行一个信号，格式: 类型 | 标的 | 方向 | 置信度
类型: BUY(买入信号)/WATCH(关注)/RISK(风险)/INFO(信息)
方向: 多/空/—
置信度: 高/中/低
示例:
BUY | 华电辽能 | 多 | 中
WATCH | CPO板块 | 多 | 高
RISK | 北方华创 | — | 低"""


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


def _call_llm_api(prompt_text):
    """调用 DeepSeek Anthropic-compatible API"""
    cfg = _load_api_config()
    if not cfg.get("token"):
        return {"error": "API token not found in ~/.claude/settings.json"}

    import urllib.request
    url = cfg["base_url"] + "/v1/messages"
    body = json.dumps({
        "model": cfg["model"],
        "max_tokens": 600,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt_text}],
    }).encode()

    req = urllib.request.Request(url, data=body, headers={
        "x-api-key": cfg["token"],
        "Content-Type": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            content = result.get("content", [])
            text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
            return {"ok": True, "text": text}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}

def _add_freshness(data, data_type, fetched_at=None):
    """为 API 响应附加 _freshness 字段（live/delayed/stale/dead）"""
    from datetime import datetime as _dt, time as _time, timedelta as _td
    now = _dt.now()
    if fetched_at:
        age = (now - _dt.fromisoformat(fetched_at)).total_seconds()
    else:
        age = 0

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
        if fetched_at:
            d = _dt.fromisoformat(fetched_at).date()
        else:
            d = today
        if d == today and _time(9, 25) <= t <= _time(10, 0):
            level = 'live'
        elif d == today and t <= _time(15, 0):
            level = 'delayed'
        elif d == today:
            level = 'stale'
        else:
            level = 'dead'
    elif data_type == 'baseline':
        today = _dt.now().date()
        if fetched_at:
            d = _dt.fromisoformat(fetched_at).date()
        else:
            d = today
        diff = (today - d).days
        level = 'live' if diff == 0 else ('delayed' if diff <= 1 else ('stale' if diff <= 2 else 'dead'))
    else:
        rule = freshness_rules.get(data_type, {'live': 300, 'delayed': 3600, 'stale': 86400})
        level = 'live' if age < rule['live'] else ('delayed' if age < rule['delayed'] else ('stale' if age < rule['stale'] else 'dead'))

    if isinstance(data, dict):
        data['_freshness'] = {'level': level, 'type': data_type, 'age_seconds': int(age)}
    return data


class BridgeHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/pnl':
            qs = parse_qs(parsed.query)
            range_val = qs.get('range', ['today'])[0]
            index_val = qs.get('index', ['sh'])[0]
            try:
                result = query_pnl(range_val, index_val)
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
        elif parsed.path == '/api/pnl/summary':
            try:
                result = query_pnl_summary()
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
            result = CACHE.get('iwencai', {})
            result = _add_freshness(result, 'iwencai')
            body = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body)
            return
        elif parsed.path == '/api/live/sectors':
            result = CACHE.get('sector_inflow', {})
            result = _add_freshness(result, 'iwencai')
            body = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body)
            return
        elif parsed.path == '/api/live/news':
            result = CACHE.get('news', {})
            result = _add_freshness(result, 'llm')
            body = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body)
            return
        elif parsed.path == '/api/live/quotes':
            result = {
                'live_index': CACHE.get('live_index', {}),
                'live_quotes': CACHE.get('live_quotes', {}),
                'breadth': CACHE.get('breadth', {}),
                'live_sectors': CACHE.get('live_sectors', {}),
                'hot_list': CACHE.get('hot_list', {}),
                'sector_inflow': CACHE.get('sector_inflow', {}),
            }
            result = _add_freshness(result, 'live_quote')
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
                if DATA_FILE.exists():
                    with open(DATA_FILE) as f:
                        data = json.load(f)
                else:
                    data = {}

                if 'positions' in payload:
                    # merge by 标的: 更新已有或追加新标的，不删除 data 中已有的标的
                    existing = {p.get('标的'): p for p in data.get('positions', [])}
                    for p in payload['positions']:
                        existing[p.get('标的')] = p
                    data['positions'] = list(existing.values())
                if '今日操作' in payload:
                    if 'decision' not in data:
                        data['decision'] = {}
                    data['decision']['今日操作'] = payload['今日操作']
                if 'pnl' in payload:
                    if 'pnl' not in data:
                        data['pnl'] = {}
                    for key in ['总资产', '累计入金']:
                        if key in payload['pnl'] and payload['pnl'][key] is not None:
                            data['pnl'][key] = payload['pnl'][key]

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

                # 原子写入 JSON（tmp + os.replace）
                if not db_error:
                    tmp = DATA_FILE.with_suffix('.tmp')
                    with open(tmp, 'w') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    os.replace(tmp, DATA_FILE)

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
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'ok': True,
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
                node = payload.get('node', '盘中')
                data_snapshot = payload.get('data_snapshot', {})

                # W1时段加专属提示
                w1_hint = ''
                if node and '09:' in str(node) or '10:0' in str(node):
                    w1_hint = '\n\n⚠️ 当前是W1早盘时段(9:30-10:00)。请按W1特别关注4项评估：龙头状态、板块合力、候选标的、竞价三件套。连板池中标的的操作信号优先输出。'
                prompt = f"当前时间: {node}{w1_hint}\n\n全盘数据:\n{json.dumps(data_snapshot, ensure_ascii=False, indent=2)}"
                result = _call_llm_api(prompt)

                if result.get('ok'):
                    raw_text = result['text']

                    # 解析结构化输出 [TEXT]...[SIGNALS]...
                    text_part = raw_text
                    signals_part = ''
                    if '[TEXT]' in raw_text and '[SIGNALS]' in raw_text:
                        parts = raw_text.split('[SIGNALS]')
                        text_part = parts[0].replace('[TEXT]', '').strip()
                        signals_part = parts[1].strip() if len(parts) > 1 else ''

                    # ReAct 验证
                    verified_signals = _verify_signals(signals_part, data_snapshot) if signals_part else []

                    insight = {
                        'timestamp': datetime.now().strftime('%H:%M:%S'),
                        'node': node,
                        'text': text_part,
                        'signals': verified_signals,
                        'verified_count': sum(1 for v in verified_signals if v['status'] == '✅'),
                        'warning_count': sum(1 for v in verified_signals if v['status'] == '⚠️'),
                    }
                    # 持久化写入
                    today = datetime.now().strftime('%Y-%m-%d')
                    insights = {}
                    if LLM_INSIGHTS_FILE.exists():
                        try:
                            with open(LLM_INSIGHTS_FILE) as f:
                                insights = json.load(f)
                        except Exception:
                            pass
                    if today not in insights:
                        insights[today] = {}
                    insights[today][node] = insight
                    LLM_INSIGHTS_FILE.parent.mkdir(parents=True, exist_ok=True)
                    with open(LLM_INSIGHTS_FILE, 'w') as f:
                        json.dump(insights, f, ensure_ascii=False, indent=2)

                    # 同步写入 SQLite
                    try:
                        from scripts.db import insert_llm
                        insert_llm(today, node, text_part, verified_signals,
                                   insight['verified_count'], insight['warning_count'])
                    except Exception as e:
                        print(f"  [bridge] SQLite LLM insert error: {e}")

                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': True, **insight}).encode())
                    print(f"  [bridge] LLM insight: {node} ({len(text_part)} chars, {insight['verified_count']}✓/{insight['warning_count']}⚠)")
                else:
                    self.send_response(502)
                    self.end_headers()
                    self.wfile.write(json.dumps(result).encode())
                    print(f"  [bridge] LLM error: {result.get('error', 'unknown')}")
            except Exception as e:
                self.send_response(500)
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
        codes = list(set(
            [s.get('代码') for s in dd.get('lianban_pool', []) if s.get('代码')] +
            [s.get('代码') for s in dd.get('trend_pool', []) if s.get('代码')] +
            [a.get('代码') for a in dd.get('decision', {}).get('锚定股状态', []) if a.get('代码')]
        ))
        quotes.set_stock_codes(codes)
        print(f'[bridge] Stock codes loaded: {len(codes)}')
    except Exception:
        pass

    scheduler = BackgroundScheduler()
    # T1 实时（5s）
    scheduler.add_job(quotes.collect_quotes, 'interval', seconds=5, id='quotes_5s',
                      max_instances=1, misfire_grace_time=10)
    scheduler.add_job(quotes.collect_index, 'interval', seconds=5, id='index_5s',
                      max_instances=1, misfire_grace_time=10)
    # T1 半实时（30s）
    scheduler.add_job(quotes.collect_breadth, 'interval', seconds=30, id='breadth_30s',
                      max_instances=1, misfire_grace_time=60)
    scheduler.add_job(quotes.collect_sectors, 'interval', seconds=30, id='sectors_30s',
                      max_instances=1, misfire_grace_time=60)
    # T1 慢周期（300s）
    scheduler.add_job(quotes.log_pnl_snapshot, 'interval', seconds=300, id='pnl_snap_300s',
                      max_instances=1, misfire_grace_time=600)
    # T2 阶段（2min-5min）
    scheduler.add_job(iwencai_poll.poll_iwencai_sentiment, 'interval', minutes=2, id='iwencai_2min',
                      max_instances=1, misfire_grace_time=180)
    scheduler.add_job(market_data.poll_sector_inflow, 'interval', minutes=5, id='sector_inflow_5min',
                      max_instances=1, misfire_grace_time=600)
    scheduler.add_job(market_data.poll_news, 'interval', minutes=5, id='news_5min',
                      max_instances=1, misfire_grace_time=600)
    scheduler.add_job(quotes.collect_hot_list, 'interval', minutes=5, id='hot_list_5min',
                      max_instances=1, misfire_grace_time=600)
    # T2 定时快照
    scheduler.add_job(sentiment_snapshot.take_sentiment_snapshot, 'cron', minute='0,30', id='sentiment_snap',
                      max_instances=1, misfire_grace_time=300)
    scheduler.start()
    print(f'[bridge] APScheduler started: 10 jobs registered')

    server = HTTPServer(('', port), BridgeHandler)
    print(f'[bridge] 看板桥接服务启动 → http://localhost:{port}')
    print(f'[bridge] W15 记流水自动同步到 {DATA_FILE}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        scheduler.shutdown(wait=False)
        print('\n[bridge] 已停止')
