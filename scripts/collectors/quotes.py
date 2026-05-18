"""quotes.py — T1 实时行情采集器（替代 poll_live 内联 PyTDX）

使用 YM-data-pipeline fetch() 统一接口，不再直接调 PyTDX/easyquotation。
bridge.py APScheduler 调度：5s/30s/300s 三档频率。
"""
import sys, json
from pathlib import Path
from datetime import datetime, time as _time_module

sys.path.insert(0, "/Users/YouMing/Documents/YM_Capital/YM-data-pipeline")
from ym_stock_data.fetch import fetch as _pipeline_fetch

CACHE = {}


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
        r = _pipeline_fetch("index")
        if r:
            if isinstance(r, dict): r.pop('_meta', None)
            CACHE["live_index"] = r
            CACHE["live_index"]["_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    except Exception as e:
        print(f"  [quotes] collect_index error: {e}", file=sys.stderr)


def collect_breadth(force=False):
    """30s: 全市场涨跌分布（10档 + 涨停跌停数）"""
    if not force and not is_trading_time():
        return
    try:
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
        live_idx = CACHE.get("live_index") or {}
        sh_pct = live_idx.get("上证指数涨幅", 0) or 0
        sz_pct = live_idx.get("深证指数涨幅", 0) or 0
        cy_pct = live_idx.get("创业板指涨幅", 0) or 0

        # NAV: 从 pnl_history.json 读取 last_twr_nav + total_deposit，按持仓市值计算
        nav = 1.0
        total_asset = 0
        pnl_pct = 0
        pos_pct = 0
        mv = 0
        try:
            ROOT = Path(__file__).resolve().parent.parent.parent
            pnl_hist_file = ROOT / "data" / "pnl_history.json"
            if pnl_hist_file.exists():
                with open(pnl_hist_file) as f:
                    ph = json.load(f)
                meta = ph.get("meta", {})
                last_nav = meta.get("last_twr_nav", 1.0)
                total_deposit = meta.get("total_deposit", 0)
                # 从 CACHE 读取当前持仓市值：W16 总资产或 live_quotes 算市值
                import json as _json
                pnl = CACHE.get("pnl") or {}
                total_asset = pnl.get("总资产", 0) or 0
                if total_asset > 0 and total_deposit > 0:
                    nav = round(total_asset / total_deposit, 6)
                elif last_nav and last_nav != 1.0:
                    nav = last_nav
                # 仓位百分比：有持仓 > 0 则根据总资产和可用资金算
                available = pnl.get("可用资金", 0) or 0
                if total_asset > 0 and available >= 0:
                    pos_pct = round((total_asset - available) / total_asset * 100, 2) if total_asset > 0 else 0
            # 读取 dashboard_data.json 的 risk 域获取当日盈亏
            data_file = ROOT / "data" / "dashboard_data.json"
            if data_file.exists():
                with open(data_file) as f:
                    dd = _json.load(f)
                risk = dd.get("risk", {})
                pnl_pct_val = risk.get("当日盈亏", 0)
                if isinstance(pnl_pct_val, (int, float)) and pnl_pct_val != 0:
                    pnl_pct = float(pnl_pct_val)
        except Exception:
            pass

        cur.execute("""INSERT OR REPLACE INTO intraday_snapshots
            (ts, date, pnl_pct, nav, sh_pct, sz_pct, cy_pct, pos_pct, mv, total_asset)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (now.strftime("%Y-%m-%dT%H:%M:%S"), now.strftime("%Y-%m-%d"),
             pnl_pct, nav, sh_pct, sz_pct, cy_pct, pos_pct, mv, total_asset))
        conn.commit()
    except Exception as e:
        print(f"  [quotes] log_pnl_snapshot error: {e}", file=sys.stderr)


def set_stock_codes(codes):
    """设置需要查询的股票代码列表"""
    CACHE["_stock_codes"] = codes
