"""pnl_calc.py — P&L 计算公共模块（NAV 链 / 回撤 / 日收益率）

供 import_xlsx_pnl.py / backfill_history.py / backfill_intraday.py 复用，
消除三份代码中的 P&L 计算重复。
"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "pnl.db"


def calc_nav_chain(daily_returns, base_nav=1.0):
    """从日收益率列表计算 NAV 链（连乘）

    daily_returns: [0.5, -0.3, 1.2, ...] (百分比)
    base_nav: 起始 NAV
    返回: [base_nav, nav_day1, nav_day2, ...]
    """
    navs = [base_nav]
    nav = base_nav
    for r in daily_returns:
        nav = nav * (1 + r / 100)
        navs.append(round(nav, 6))
    return navs


def calc_max_drawdown(navs):
    """从 NAV 链计算最大回撤（百分比）"""
    if not navs or len(navs) < 2:
        return 0, None, None
    peak = navs[0]
    max_dd = 0
    dd_start = dd_end = None
    for i, nav in enumerate(navs):
        if nav > peak:
            peak = nav
        dd = (peak - nav) / peak * 100
        if dd > max_dd:
            max_dd = dd
            dd_start = i - 1 if i > 0 else 0
            dd_end = i
    return round(max_dd, 2), dd_start, dd_end


def get_prev_nav(date_str):
    """从 daily_summary 获取指定日期前一日的收盘 NAV"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cur = conn.cursor()
        cur.execute("SELECT nav FROM daily_summary WHERE date < ? ORDER BY date DESC LIMIT 1", (date_str,))
        row = cur.fetchone()
        conn.close()
        return row[0] if row else 1.0
    except Exception:
        return 1.0


def daily_return_from_snapshots(date_str):
    """从 intraday_snapshots 计算某日的日收益率（首末快照 NAV 差）"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cur = conn.cursor()
        cur.execute(
            "SELECT nav FROM intraday_snapshots WHERE date = ? ORDER BY ts ASC LIMIT 1", (date_str,))
        first = cur.fetchone()
        cur.execute(
            "SELECT nav FROM intraday_snapshots WHERE date = ? ORDER BY ts DESC LIMIT 1", (date_str,))
        last = cur.fetchone()
        conn.close()
        if first and last and first[0] > 0:
            return round((last[0] - first[0]) / first[0] * 100, 4)
    except Exception:
        pass
    return 0.0
