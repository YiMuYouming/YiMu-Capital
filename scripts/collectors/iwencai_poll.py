"""iwencai_poll.py — T2 情绪数据定时轮询（每 2min）

通过 ym_stock_data 统一接口 → OpenAPI 优先，额度耗尽自动降级 pywencai。
非交易时段自动跳过。
"""
import os, sys, json
from datetime import datetime, time
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
    # scripts/collectors/*.py → parents[4] = YM_Capital/ (4 layers from file to YM_Capital)
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

def _iwencai_query(*args, **kwargs):
    """延迟导入 iwencai 模块"""
    _ensure_pipeline()
    from ym_stock_data.sources.iwencai import query as _q
    return _q(*args, **kwargs)

CACHE = {}


def is_trading_time():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return (time(9, 25) <= t <= time(11, 30)) or (time(13, 0) <= t <= time(15, 10))


def _clean(v):
    if v is None: return None
    try: return float(str(v).replace("%", "").strip())
    except: return v


def _find_key(row, keyword):
    for k in row:
        if keyword in str(k): return k
    return None


def _val(row, keyword, clean=False):
    k = _find_key(row, keyword)
    v = row.get(k) if k else row.get(keyword)
    return _clean(v) if clean and v is not None else v


def _avg_pct(datas, col_keyword):
    """从 dict list 中提取涨跌幅列并算均值"""
    vals = []
    for row in datas:
        v = _val(row, col_keyword, clean=True)
        if isinstance(v, (int, float)):
            vals.append(v)
    return round(sum(vals) / len(vals), 2) if vals else None


def _max_board(datas):
    """提取最高板 + 次高板"""
    boards = []
    for row in datas:
        d = _val(row, "连续涨停天数", clean=True)
        if isinstance(d, (int, float)) and d >= 2:
            boards.append(int(d))
    if not boards:
        return None, None
    uniq = sorted(set(boards), reverse=True)
    return uniq[0], uniq[1] if len(uniq) >= 2 else None


def poll_iwencai_sentiment(force=False):
    if not force and not is_trading_time():
        return

    results = {}
    try:
        # === 涨停收益 + 赚钱效应 ===
        r = _iwencai_query("昨日涨停 今日涨跌幅 非st", limit=100)
        datas = r.get("datas", [])
        avg = _avg_pct(datas, "涨跌幅")
        if avg is not None:
            results["昨日涨停收益"] = avg
            vals = []
            for row in datas:
                v = _val(row, "涨跌幅", clean=True)
                if isinstance(v, (int, float)): vals.append(v)
            if vals:
                green = sum(1 for v in vals if v > 0)
                results["涨停溢价率"] = round(green / len(vals) * 100, 1)
                results["赚钱效应"] = "好" if avg > 2 else ("差" if avg < 0 else "一般")

        # === 连板收益 ===
        r = _iwencai_query("昨日连续涨停天数>=2 今日涨跌幅 非st", limit=30)
        avg = _avg_pct(r.get("datas", []), "涨跌幅")
        if avg is not None:
            results["连板收益"] = avg

        # === 炸板收益 ===
        r = _iwencai_query("昨日炸板 今日涨跌幅 非st", limit=30)
        avg = _avg_pct(r.get("datas", []), "涨跌幅")
        if avg is not None:
            results["炸板收益"] = avg

        # === 最高板 + 次高板 + 连板股列表 ===
        r = _iwencai_query("连续涨停天数>=2 非st 连续涨停天数 所属行业 封板时间 换手率", limit=50)
        datas = r.get("datas", [])
        max_b, sub_b = _max_board(datas)
        if max_b is not None: results["最高板"] = max_b
        if sub_b is not None: results["次高板"] = sub_b
        results["连板股数"] = len(datas) if datas else None

        # 晋级率 = 连板股数 / 昨日涨停股数
        r = _iwencai_query("昨日涨停 非st", limit=200)
        yest_zt = len(r.get("datas", []))
        if yest_zt > 0 and results.get("连板股数") is not None:
            rate = results["连板股数"] / yest_zt
            results["晋级率"] = round(rate, 4) if rate <= 1 else round(rate / 100, 4)

        # 分层晋级率
        for layer_q, layer_key in [
            ("昨日首板 今日涨跌幅 非st", "一进二晋级率"),
            ("昨日二板 今日涨跌幅 非st", "二进三晋级率"),
            ("昨日三板 今日涨跌幅 非st", "三进四晋级率"),
        ]:
            try:
                r = _iwencai_query(layer_q, limit=100)
                vals = []
                for row in r.get("datas", []):
                    v = _val(row, "涨跌幅", clean=True)
                    if isinstance(v, (int, float)): vals.append(v)
                if vals:
                    up = sum(1 for v in vals if v > 0)
                    results[layer_key] = round(up / len(vals), 4)
            except Exception:
                pass

        # === 连板股列表 ===
        lb_stocks = []
        for row in datas:
            code = str(_val(row, "股票代码") or "")
            code = code.split(".")[0] if "." in code else code
            name = str(_val(row, "股票简称") or "")
            days = _val(row, "连续涨停天数", clean=True)
            sector = str(_val(row, "所属行业") or "")
            ft = str(_val(row, "封板时间") or "")
            hs = _val(row, "换手率", clean=True)
            if code and days:
                lb_stocks.append({
                    "代码": code,
                    "名称": name,
                    "连板数": int(days),
                    "板块": sector,
                    "封板时间": ft,
                    "换手率": round(float(hs), 2) if hs else None,
                })
        if lb_stocks:
            results["连板股列表"] = lb_stocks

        # === 封板率 + 炸板率 + 跌停家数 ===
        r = _iwencai_query("今日触及涨停 非st", limit=200)
        touch_cnt = len(r.get("datas", []))
        r = _iwencai_query("今日涨停 非st", limit=200)
        close_cnt = len(r.get("datas", []))
        r = _iwencai_query("今日跌停 非st", limit=200)
        dt_cnt = len(r.get("datas", []))
        if touch_cnt > 0 or close_cnt > 0:
            base = max(touch_cnt, close_cnt)
            results["封板率"] = round(min(close_cnt / base, 1.0), 4) if base > 0 else 0
            results["炸板率"] = round(max((touch_cnt - close_cnt) / base, 0), 4)
        results["涨停家数"] = close_cnt
        results["跌停家数"] = dt_cnt

        # === 连板风险值 ===
        jj = results.get("晋级率")
        if jj is not None:
            results["连板风险值"] = round(max(0, min(1, 1.0 - jj * 1.8)), 2)

        if results:
            results["_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
            CACHE["iwencai"] = results
    except Exception as e:
        print(f"  [iwencai_poll] error: {e}", file=sys.stderr)
