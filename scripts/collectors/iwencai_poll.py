"""iwencai_poll.py — T2 情绪数据定时轮询（每 2min）

通过 ym_stock_data 统一接口 → OpenAPI 优先，额度耗尽自动降级 pywencai。
非交易时段自动跳过。
"""
import sys, json
from datetime import datetime, time

sys.path.insert(0, "/Users/YouMing/Documents/YM_Capital/YM-data-pipeline")
from ym_stock_data.sources.iwencai import query as _iwencai_query

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
        if touch_cnt > 0:
            results["封板率"] = round(close_cnt / touch_cnt, 4)
            results["炸板率"] = round((touch_cnt - close_cnt) / touch_cnt, 4)
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
