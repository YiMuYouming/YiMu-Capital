"""iwencai_poll.py — T2 情绪数据定时轮询（每 2min）

通过 pywencai 网页抓取（零 API 额度消耗），采集情绪指标写入 bridge CACHE。
非交易时段自动跳过。

数据源: pywencai (同花顺问财网页版)
"""
import sys, json, warnings
from datetime import datetime, time
from pathlib import Path

# pywencai venv
_VENV = "/Users/YouMing/WorkBuddy/Tools/iwencai-venv/lib/python3.14/site-packages"
if _VENV not in sys.path:
    sys.path.insert(0, _VENV)

import pandas as pd
import pywencai

warnings.filterwarnings("ignore")

CACHE = {}


def _native(val):
    """numpy/int64 → Python native type"""
    if val is None:
        return None
    try:
        import numpy as np
        if isinstance(val, (np.integer,)): return int(val)
        if isinstance(val, (np.floating,)): return float(val)
        if isinstance(val, np.ndarray): return val.tolist()
    except ImportError:
        pass
    if isinstance(val, float) and (val != val):  # NaN
        return None
    return val


def is_trading_time():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return (time(9, 25) <= t <= time(11, 30)) or (time(13, 0) <= t <= time(15, 10))


def _q(query_str, limit=50):
    """pywencai 查询 → DataFrame（失败返回空）"""
    try:
        df = pywencai.get(query=query_str, loop_first=True)
        if df is None or df.empty:
            return pd.DataFrame()
        return df
    except Exception:
        return pd.DataFrame()


def _col(df, keyword):
    """找包含关键字的列名"""
    for c in df.columns:
        if keyword in str(c):
            return c
    return None


def _num(series):
    """转数值"""
    return pd.to_numeric(series, errors="coerce")


def _avg_pct(df, col_keyword):
    """从 DataFrame 中提取涨跌幅列并算均值"""
    c = _col(df, col_keyword)
    if c is None:
        return None
    vals = _num(df[c]).dropna()
    if len(vals) == 0:
        return None
    return round(float(vals.mean()), 2)


def _max_board(df):
    """提取最高板 + 次高板"""
    c = _col(df, "连续涨停天数")
    if c is None:
        return None, None
    vals = _num(df[c]).dropna()
    vals = vals[vals >= 2].astype(int)
    if len(vals) == 0:
        return None, None
    uniq = sorted(vals.unique(), reverse=True)
    return uniq[0], uniq[1] if len(uniq) >= 2 else None


def poll_iwencai_sentiment(force=False):
    if not force and not is_trading_time():
        return

    results = {}
    try:
        # === 涨停收益 + 赚钱效应 ===
        df = _q("昨日涨停 今日涨跌幅 非st", limit=100)
        avg = _avg_pct(df, "涨跌幅")
        if avg is not None:
            results["昨日涨停收益"] = avg
            c = _col(df, "涨跌幅")
            vals = _num(df[c]).dropna()
            green = (vals > 0).sum()
            results["涨停溢价率"] = round(green / len(vals) * 100, 1) if len(vals) else None
            results["赚钱效应"] = "好" if avg > 2 else ("差" if avg < 0 else "一般")

        # === 连板收益 ===
        avg = _avg_pct(_q("昨日连续涨停天数>=2 今日涨跌幅 非st", limit=30), "涨跌幅")
        if avg is not None:
            results["连板收益"] = avg

        # === 炸板收益 ===
        avg = _avg_pct(_q("昨日炸板 今日涨跌幅 非st", limit=30), "涨跌幅")
        if avg is not None:
            results["炸板收益"] = avg

        # === 最高板 + 次高板 + 晋级率 + 连板股列表 ===
        df = _q("连续涨停天数>=2 非st 连续涨停天数 所属行业 封板时间 换手率", limit=50)
        max_b, sub_b = _max_board(df)
        if max_b is not None:
            results["最高板"] = max_b
        if sub_b is not None:
            results["次高板"] = sub_b

        # 连板股数
        results["连板股数"] = len(df) if not df.empty else None

        # 晋级率 = 连板股数 / 昨日涨停股数
        zt_df = _q("昨日涨停 非st", limit=200)
        yest_zt = len(zt_df) if not zt_df.empty else 0
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
                ldf = _q(layer_q, limit=100)
                c = _col(ldf, "涨跌幅")
                if c is not None:
                    vals = _num(ldf[c]).dropna()
                    if len(vals) > 0:
                        up = (vals > 0).sum()
                        results[layer_key] = round(up / len(vals), 4)
            except Exception:
                pass

        # === 连板股列表 ===
        if not df.empty:
            lb_stocks = []
            name_c = _col(df, "股票简称")
            code_c = _col(df, "股票代码")
            days_c = _col(df, "连续涨停天数")
            sector_c = _col(df, "所属行业")
            ft_c = _col(df, "封板时间")
            hs_c = _col(df, "换手率")
            for _, row in df.iterrows():
                code = str(row.get(code_c, "")) if code_c else ""
                code = code.split(".")[0] if "." in code else code
                name = str(row.get(name_c, "")) if name_c else ""
                days = row.get(days_c) if days_c else 0
                sector = str(row.get(sector_c, "")) if sector_c else ""
                ft = str(row.get(ft_c, "")) if ft_c else ""
                hs = row.get(hs_c)
                if code and days:
                    lb_stocks.append({
                        "代码": code,
                        "名称": name,
                        "连板数": int(float(days)),
                        "板块": sector,
                        "封板时间": ft,
                        "换手率": round(float(hs), 2) if hs and str(hs) != "nan" else None,
                    })
            if lb_stocks:
                results["连板股列表"] = lb_stocks

        # === 封板率 + 炸板率 ===
        # 封板率 = 最终涨停数 / 今日涨停触及总数
        # 跌停家数
        zt_touch_df = _q("今日触及涨停 非st", limit=200)
        zt_close_df = _q("今日涨停 非st", limit=200)
        dt_df = _q("今日跌停 非st", limit=200)
        touch_cnt = len(zt_touch_df) if not zt_touch_df.empty else 0
        close_cnt = len(zt_close_df) if not zt_close_df.empty else 0
        dt_cnt = len(dt_df) if not dt_df.empty else 0
        if touch_cnt > 0:
            results["封板率"] = round(close_cnt / touch_cnt, 4)
            results["炸板率"] = round((touch_cnt - close_cnt) / touch_cnt, 4)
        results["跌停家数"] = dt_cnt

        # === 连板风险值 ===
        jj = results.get("晋级率")
        if jj is not None:
            results["连板风险值"] = round(max(0, min(1, 1.0 - jj * 1.8)), 2)

        if results:
            # numpy → native 转换
            for k in list(results.keys()):
                results[k] = _native(results[k])
            # 连板股列表特殊处理
            if "连板股列表" in results:
                for s in results["连板股列表"]:
                    for sk in s:
                        s[sk] = _native(s[sk])
            results["_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
            CACHE["iwencai"] = results
    except Exception as e:
        print(f"  [iwencai_poll] error: {e}", file=sys.stderr)
