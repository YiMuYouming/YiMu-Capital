"""quotes.py — T1 实时行情采集器（替代 poll_live 内联 PyTDX）

使用 YM-data-pipeline fetch() 统一接口，不再直接调 PyTDX/easyquotation。
bridge.py APScheduler 调度：5s/30s/300s 三档频率。
"""
import sys, json, threading
from pathlib import Path
from datetime import datetime, time as _time_module

sys.path.insert(0, "/Users/YouMing/Documents/YM_Capital/YM-data-pipeline")
from ym_stock_data.fetch import fetch as _pipeline_fetch

CACHE = {}
_tdx_lock = threading.Lock()  # PyTDX 共用连接保护锁


def is_trading_time():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return (_time_module(9, 15) <= t <= _time_module(11, 30)) or (_time_module(13, 0) <= t <= _time_module(15, 10))


def collect_quotes(force=False):
    """5s: 个股行情（从 CACHE 中的 codes 列表获取）"""
    if not force and not is_trading_time():
        return
    codes = CACHE.get("_stock_codes", [])
    if not codes:
        return
    try:
        with _tdx_lock:
            r = _pipeline_fetch("quotes", codes=codes)
        if r:
            if isinstance(r, dict): r.pop('_meta', None)
            CACHE["live_quotes"] = r
            CACHE["live_quotes"]["_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    except Exception as e:
        print(f"  [quotes] collect_quotes error: {e}", file=sys.stderr)


def collect_index(force=False):
    """5s: 三大指数 + 涨跌家数 + 成交额"""
    if not force and not is_trading_time():
        return
    try:
        with _tdx_lock:
            r = _pipeline_fetch("index")
        if r:
            if isinstance(r, dict): r.pop('_meta', None)
            CACHE["live_index"] = r
            CACHE["live_index"]["_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    except Exception as e:
        print(f"  [quotes] collect_index error: {e}", file=sys.stderr)


def collect_yesterday_compare(force=False):
    """30s: 成交额较昨日同时段对比"""
    if not force and not is_trading_time():
        return
    try:
        from datetime import datetime as _dt
        now = _dt.now()
        # 已交易分钟数（从9:30算起）
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        minutes_traded = max(1, min(240, (now - market_open).total_seconds() / 60))
        slot_count = int(minutes_traded / 15) + 1  # 多少个15分钟槽

        # 从 PyTDX 获取昨日15分钟K线
        api = _get_tdx_api()
        if not api:
            return

        result = {}
        for name, (mkt, code) in [("上证", (1, "000001")), ("深证", (0, "399001"))]:
            try:
                bars = api.get_index_bars(1, mkt, code, 0, 60)
                if not bars:
                    continue
                today_str = now.strftime("%Y-%m-%d")
                current_min = now.hour * 60 + now.minute

                # 找到昨天日期
                from datetime import timedelta
                yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

                yesterday_amt = 0
                for b in bars:
                    dt = str(b.get("datetime", ""))
                    if yesterday not in dt:
                        continue
                    # 解析时间，只取到当前时刻对应的时段
                    try:
                        bar_time = dt.split(" ")[-1] if " " in dt else dt[-5:]
                        h, m = bar_time.split(":")[0], bar_time.split(":")[1]
                        bar_min = int(h) * 60 + int(m)
                        if bar_min <= current_min:
                            yesterday_amt += b.get("amount", 0)
                    except (ValueError, IndexError):
                        continue
                yesterday_amt_yi = yesterday_amt / 1e8

                # 从 live_index 取今日累计
                li = CACHE.get("live_index", {})
                today_amt_str = li.get(f"{name}指数成交额", "")
                if today_amt_str:
                    try:
                        today_amt_yi = float(str(today_amt_str).replace("亿", "").replace("万亿", "e4"))
                    except ValueError:
                        today_amt_yi = 0
                else:
                    today_amt_yi = 0

                if yesterday_amt_yi > 0:
                    diff = today_amt_yi - yesterday_amt_yi
                    pct = round(diff / yesterday_amt_yi * 100, 1)
                    result[f"{name}昨成交额"] = f"{yesterday_amt_yi:.2f}亿"
                    result[f"{name}成交额差"] = f"{diff:+.2f}亿"
                    result[f"{name}成交额差百分比"] = f"{pct:+.1f}%"
            except Exception:
                continue

        if result:
            # 合并到 live_index
            li = CACHE.get("live_index", {})
            li.update(result)
            CACHE["live_index"] = li
    except Exception as e:
        print(f"  [quotes] collect_yesterday_compare error: {e}", file=sys.stderr)


def _get_tdx_api():
    try:
        from ym_stock_data.sources.pytdx import _get_api
        return _get_api()
    except Exception:
        return None


def collect_breadth(force=False):
    """30s: 全市场涨跌分布（10档 + 涨停跌停数）"""
    if not force and not is_trading_time():
        return
    try:
        with _tdx_lock:
            r = _pipeline_fetch("breadth")
        if r:
            if isinstance(r, dict): r.pop('_meta', None)
            CACHE["breadth"] = r
            CACHE["breadth"]["_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    except Exception as e:
        print(f"  [quotes] collect_breadth error: {e}", file=sys.stderr)


def collect_sectors(force=False):
    """30s: 板块涨跌幅/MA5/20/方向"""
    if not force and not is_trading_time():
        return
    # 从 pools 或 sectors 缓存取板块名列表
    names = _get_sector_names()
    if not names:
        return
    try:
        with _tdx_lock:
            r = _pipeline_fetch("sector_index", names=names)
        if r:
            if isinstance(r, dict):
                r.pop('_meta', None)
                r.pop('error', None)
            CACHE["live_sectors"] = r
            CACHE["live_sectors"]["_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    except Exception as e:
        print(f"  [quotes] collect_sectors error: {e}", file=sys.stderr)


def _get_sector_names():
    """从 pools.json 和 sectors 缓存拼板块名列表"""
    names = set()
    # 从 pools CACHE
    pools = CACHE.get("pools", {})
    for s in pools.get("sectors", []):
        if s.get("板块"):
            names.add(s["板块"])
    # 从 dashboard_data.json 兜底
    if not names:
        try:
            import json
            ROOT = Path(__file__).resolve().parent.parent.parent
            with open(ROOT / "data" / "dashboard_data.json") as f:
                dd = json.load(f)
            for s in dd.get("sectors", []):
                if s.get("板块"):
                    names.add(s["板块"])
        except Exception:
            pass
    return sorted(names) if names else []


def collect_northbound(force=False):
    """60s: 北向资金实时累计净买入"""
    if not force and not is_trading_time():
        return
    try:
        r = _pipeline_fetch("northbound")
        if r:
            if isinstance(r, dict):
                r.pop('_meta', None)
                r.pop('error', None)
            CACHE["northbound"] = r
            CACHE["northbound"]["_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    except Exception as e:
        print(f"  [quotes] collect_northbound error: {e}", file=sys.stderr)


def collect_hot_list(force=False):
    """5min: 同花顺热榜 + 题材归因"""
    if not force and not is_trading_time():
        return
    try:
        r = _pipeline_fetch("ths_hot")
        if r:
            CACHE["hot_list"] = {"data": r, "_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")}
    except Exception as e:
        print(f"  [quotes] collect_hot_list error: {e}", file=sys.stderr)


def collect_kline_15m(force=False):
    """60s: 三大指数15分钟量价（同比昨日）"""
    if not force and not is_trading_time():
        return
    try:
        with _tdx_lock:
            r = _pipeline_fetch("kline_15m")
        if r and isinstance(r, dict):
            r.pop('_meta', None)
            if '上证15min' in r: CACHE['上证15min'] = r['上证15min']
            if '深证15min' in r: CACHE['深证15min'] = r['深证15min']
            if '创业15min' in r: CACHE['创业15min'] = r['创业15min']
    except Exception as e:
        print(f"  [quotes] collect_kline_15m error: {e}", file=sys.stderr)


def log_pnl_snapshot():
    """300s: P&L 快照写入 pnl.db（独立计算，不依赖前端组件）"""
    if not is_trading_time():
        return
    try:
        from scripts.db import get_conn, init_db
        init_db()
        conn = get_conn()
        cur = conn.cursor()
        now = datetime.now()
        ROOT = Path(__file__).resolve().parent.parent.parent

        # 1. 指数涨跌（来自 PyTDX 实时采集）
        live_idx = CACHE.get("live_index") or {}
        sh_pct_str = live_idx.get("上证指数涨幅", "0") or "0"
        sz_pct_str = live_idx.get("深证指数涨幅", "0") or "0"
        cy_pct_str = live_idx.get("创业板指涨幅", "0") or "0"
        sh_pct = float(str(sh_pct_str).replace("%","").replace("+","")) if sh_pct_str else 0
        sz_pct = float(str(sz_pct_str).replace("%","").replace("+","")) if sz_pct_str else 0
        cy_pct = float(str(cy_pct_str).replace("%","").replace("+","")) if cy_pct_str else 0

        # 2. 从持仓+实时价计算总资产和仓位
        mv = 0  # 持仓市值
        pos_pct = 0
        total_asset = 0
        nav = 1.0
        total_deposit = 0
        pnl_pct = 0

        try:
            # 读持仓（dashboard_data.json + pools.json）
            data_file = ROOT / "data" / "dashboard_data.json"
            positions = []
            if data_file.exists():
                with open(data_file) as f:
                    dd = json.load(f)
                positions = [p for p in dd.get("positions", []) if (p.get('状态','') or '').find('清') < 0]

            # 读实时报价算市值
            live_q = CACHE.get("live_quotes", {})
            for p in positions:
                code = str(p.get("代码", ""))
                qty = float(str(p.get("数量", "0")).replace("股", "")) if p.get("数量") else 0
                if not code or qty <= 0:
                    continue
                q = live_q.get(code, {})
                price = float(q.get("最新价", 0)) if q else 0
                if price <= 0:
                    price = float(p.get("现价", 0)) if p.get("现价") else 0
                mv += round(price * qty)

            # 读可用资金（优先 CACHE pnl，其次 pnl_history.json）
            available = 0
            pnl = CACHE.get("pnl") or {}
            available = float(pnl.get("可用资金", 0) or 0)

            # 读累计入金（优先 CACHE pnl，其次 dashboard_data.json，最后 pnl_history.json）
            pnl_hist_file = ROOT / "data" / "pnl_history.json"
            total_deposit = float(pnl.get("累计入金", 0) or 0)
            if not total_deposit:
                if pnl_hist_file.exists():
                    with open(pnl_hist_file) as f:
                        ph = json.load(f)
                    total_deposit = ph.get("meta", {}).get("total_deposit", 0) or 0
            if not available:
                # 从历史记录推算可用资金
                if pnl_hist_file.exists():
                    with open(pnl_hist_file) as f:
                        ph = json.load(f)
                    last_asset = ph.get("meta", {}).get("last_total_asset", 0) or 0
                    if last_asset > 0:
                        available = max(0, last_asset - mv)

            total_asset = mv + available
            if total_asset > 0 and total_deposit > 0:
                nav = round(total_asset / total_deposit, 6)
                pos_pct = round(mv / total_asset * 100, 2)

            # 当日盈亏：当日首笔快照锁定 day_start_asset，后续不再变
            day_start_asset = 0
            today_str = now.strftime("%Y-%m-%d")
            if pnl_hist_file.exists():
                with open(pnl_hist_file) as f:
                    ph = json.load(f)
                meta = ph.get("meta", {})
                day_start_asset = meta.get("day_start_asset", 0) or 0
                day_start_date = meta.get("day_start_date", "")
                # 新的一天 / 首笔快照 → 锁定起始资产
                if day_start_date != today_str and total_asset > 0:
                    day_start_asset = total_asset
                    ph["meta"]["day_start_asset"] = day_start_asset
                    ph["meta"]["day_start_date"] = today_str
                    tmp = pnl_hist_file.with_suffix('.tmp')
                    with open(tmp, 'w') as f:
                        json.dump(ph, f, ensure_ascii=False)
                    import os as _os
                    _os.replace(tmp, pnl_hist_file)

            if day_start_asset > 0:
                pnl_pct = round((total_asset - day_start_asset) / day_start_asset * 100, 2)

            # 收盘时更新 last_total_asset（供第二天起始资产）和 last_twr_nav
            if total_asset > 0 and now.hour >= 15:
                try:
                    if pnl_hist_file.exists():
                        with open(pnl_hist_file) as f:
                            ph_data = json.load(f)
                    else:
                        ph_data = {}
                    ph_data["meta"] = ph_data.get("meta", {})
                    ph_data["meta"]["last_total_asset"] = total_asset
                    ph_data["meta"]["last_twr_nav"] = nav
                    ph_data["meta"]["last_updated"] = now.strftime("%Y-%m-%dT%H:%M:%S")
                    tmp = pnl_hist_file.with_suffix('.tmp')
                    with open(tmp, 'w') as f:
                        json.dump(ph_data, f, ensure_ascii=False)
                    import os as _os
                    _os.replace(tmp, pnl_hist_file)
                except Exception:
                    pass
        except Exception:
            pass

        cur.execute("""INSERT OR REPLACE INTO intraday_snapshots
            (ts, date, pnl_pct, nav, sh_pct, sz_pct, cy_pct, pos_pct, mv, total_asset)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (now.strftime("%Y-%m-%dT%H:%M:%S"), now.strftime("%Y-%m-%d"),
             pnl_pct, nav, sh_pct, sz_pct, cy_pct, pos_pct, mv, total_asset))
        conn.commit()
    except Exception as e:
        print(f"  [quotes] log_pnl_snapshot error: {e}", file=sys.stderr)


def set_stock_codes(codes):
    """设置需要查询的股票代码列表"""
    CACHE["_stock_codes"] = codes
