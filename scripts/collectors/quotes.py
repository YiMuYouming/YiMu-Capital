"""quotes.py — T1 实时行情采集器（替代 poll_live 内联 PyTDX）

使用 YM-data-pipeline fetch() 统一接口，不再直接调 PyTDX/easyquotation。
bridge.py APScheduler 调度：5s/30s/300s 三档频率。
"""
import sys
from datetime import datetime, time as _time_module

sys.path.insert(0, "/Users/YouMing/Documents/YM_Capital/YM-data-pipeline")
from ym_stock_data.fetch import fetch as _pipeline_fetch

CACHE = {}


def is_trading_time():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return (_time_module(9, 15) <= t <= _time_module(11, 30)) or (_time_module(13, 0) <= t <= _time_module(15, 2))


def collect_quotes():
    """5s: 个股行情（从 CACHE 中的 codes 列表获取）"""
    if not is_trading_time():
        return
    codes = CACHE.get("_stock_codes", [])
    if not codes:
        return
    try:
        r = _pipeline_fetch("quotes", codes=codes)
        if r:
            if isinstance(r, dict): r.pop('_meta', None)
            CACHE["live_quotes"] = r
            CACHE["live_quotes"]["_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    except Exception as e:
        print(f"  [quotes] collect_quotes error: {e}", file=sys.stderr)


def collect_index():
    """5s: 三大指数 + 涨跌家数 + 成交额"""
    if not is_trading_time():
        return
    try:
        r = _pipeline_fetch("index")
        if r:
            if isinstance(r, dict): r.pop('_meta', None)
            CACHE["live_index"] = r
            CACHE["live_index"]["_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    except Exception as e:
        print(f"  [quotes] collect_index error: {e}", file=sys.stderr)


def collect_breadth():
    """30s: 全市场涨跌分布（10档 + 涨停跌停数）"""
    if not is_trading_time():
        return
    try:
        r = _pipeline_fetch("breadth")
        if r:
            if isinstance(r, dict): r.pop('_meta', None)
            CACHE["breadth"] = r
            CACHE["breadth"]["_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    except Exception as e:
        print(f"  [quotes] collect_breadth error: {e}", file=sys.stderr)


def collect_sectors():
    """30s: 板块涨跌幅/MA5/20/方向"""
    if not is_trading_time():
        return
    # 从 pools 或 sectors 缓存取板块名列表
    names = _get_sector_names()
    if not names:
        return
    try:
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


def collect_northbound():
    """60s: 北向资金实时累计净买入"""
    if not is_trading_time():
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


def collect_hot_list():
    """5min: 同花顺热榜 + 题材归因"""
    if not is_trading_time():
        return
    try:
        r = _pipeline_fetch("ths_hot")
        if r:
            CACHE["hot_list"] = {"data": r, "_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")}
    except Exception as e:
        print(f"  [quotes] collect_hot_list error: {e}", file=sys.stderr)


def log_pnl_snapshot():
    """300s: P&L 快照写入 pnl.db"""
    if not is_trading_time():
        return
    try:
        from scripts.db import get_conn, init_db
        init_db()
        conn = get_conn()
        cur = conn.cursor()
        now = datetime.now()
        live_idx = (CACHE.get("live_index") or {}).get("data", {})
        sh_pct = live_idx.get("上证指数涨幅", 0)
        sz_pct = live_idx.get("深证指数涨幅", 0)
        cy_pct = live_idx.get("创业板指涨幅", 0)
        cur.execute("""INSERT OR REPLACE INTO intraday_snapshots
            (ts, date, pnl_pct, nav, sh_pct, sz_pct, cy_pct, pos_pct, mv, total_asset)
            VALUES (?, ?, 0, 1.0, ?, ?, ?, 0, 0, 0)""",
            (now.strftime("%Y-%m-%dT%H:%M:%S"), now.strftime("%Y-%m-%d"), sh_pct, sz_pct, cy_pct))
        conn.commit()
    except Exception as e:
        print(f"  [quotes] log_pnl_snapshot error: {e}", file=sys.stderr)


def set_stock_codes(codes):
    """设置需要查询的股票代码列表"""
    CACHE["_stock_codes"] = codes
