"""market_data.py — 板块主力净流入 + 财联社电报定时采集

- sector_inflow: 每 5min 获取同花顺行业净流入 TOP20，替代被封的东财 push2
- news: 每 5min 获取财联社电报，补充 W20 LLM 研判上下文
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
    return (_time_module(9, 15) <= t <= _time_module(11, 30)) or (_time_module(13, 0) <= t <= _time_module(15, 5))


def poll_sector_inflow():
    """每 5min 获取同花顺行业净流入 TOP20"""
    if not is_trading_time():
        return
    try:
        r = _pipeline_fetch("sector_inflow", top_n=20)
        if r and r.get("top"):
            CACHE["sector_inflow"] = {
                "data": r["top"],
                "_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
            }
    except Exception as e:
        print(f"  [market_data] sector_inflow error: {e}", file=sys.stderr)


def poll_news():
    """每 5min 获取财联社电报（供 W20 LLM 研判上下文）"""
    if not is_trading_time():
        return
    try:
        r = _pipeline_fetch("news", limit=20)
        if r and r.get("items"):
            CACHE["news"] = {
                "data": r["items"],
                "_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
            }
    except Exception as e:
        print(f"  [market_data] news error: {e}", file=sys.stderr)
