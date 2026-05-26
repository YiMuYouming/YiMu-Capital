"""market_data.py — 板块主力净流入 + 财联社电报定时采集

- sector_inflow: 每 5min 获取同花顺行业净流入 TOP20，替代被封的东财 push2
- news: 每 5min 获取财联社电报，补充 W20 LLM 研判上下文
"""
import os, sys
from datetime import datetime, time as _time_module
from pathlib import Path

def _load_pipeline_path():
    """从环境变量或默认值解析 ym_stock_data 的路径。

    若用户显式提供 YM_DATA_PIPELINE_PATH 但路径不存在，立即报错。
    """
    env_path = os.environ.get("YM_DATA_PIPELINE_PATH", "")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
        raise RuntimeError(
            f"YM_DATA_PIPELINE_PATH='{env_path}' 不存在。"
            f"请检查路径是否正确，或取消设置该环境变量以使用默认路径。"
            f"默认路径: {Path(__file__).resolve().parent.parent.parent / 'YM-data-pipeline'}"
        )
    # scripts/collectors/market_data.py → parents[4] = YM_Capital/ (4 layers from file to YM_Capital)
    default = Path(__file__).resolve().parent.parent.parent.parent / "YM-data-pipeline"
    return default

_pip_path = None

def _ensure_pipeline():
    """确保 ym_stock_data 在 sys.path 中（延迟导入）"""
    global _pip_path
    if _pip_path is not None:
        return _pip_path
    p = _load_pipeline_path()
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
    _pip_path = p
    return p

def _pipeline_fetch(*args, **kwargs):
    """延迟导入 ym_stock_data.fetch"""
    _ensure_pipeline()
    from ym_stock_data.fetch import fetch as _f
    return _f(*args, **kwargs)

CACHE = {}


def is_trading_time():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return (_time_module(9, 15) <= t <= _time_module(11, 30)) or (_time_module(13, 0) <= t <= _time_module(15, 10))


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
