"""iwencai_poll.py — T2 情绪数据定时轮询（每 2min）

从 iwencai 采集情绪指标，写入 bridge 内存缓存 CACHE['iwencai']。
非交易时段自动跳过以节省 API 配额。

查询策略（实测验证）:
  - 封板率/炸板率: "封板率 炸板率" → 1 row aggregate
  - 晋级率/连板股数: "涨停晋级率 连板股数" → 1 row aggregate
  - 最高板: 从 "连板股票 最高板" 个股中取 max
  - 赚钱效应: "昨日涨停今日表现" → 计算平均涨幅
"""
import sys, json, re
from datetime import datetime, time
from pathlib import Path

sys.path.insert(0, "/Users/YouMing/Documents/YM_Capital/YM-data-pipeline")
from ym_stock_data.sources.iwencai import query as _iwencai_query

# bridge.py 设置
CACHE = {}


def is_trading_time():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return (time(9, 25) <= t <= time(11, 30)) or (time(13, 0) <= t <= time(15, 2))


def _clean(val):
    """清洗值：去 % 转 float"""
    if val is None:
        return None
    s = str(val).replace('%', '').strip()
    try:
        return float(s)
    except ValueError:
        return val


def _find_key(row, keyword):
    for k in row:
        if keyword in str(k):
            return k
    return None


def _get_val(row, keyword, clean=False):
    """从 iwencai row 中取值，自动匹配带日期后缀的 key"""
    k = _find_key(row, keyword)
    if k and k in row:
        v = row[k]
        return _clean(v) if clean else v
    if keyword in row:
        v = row[keyword]
        return _clean(v) if clean else v
    return None


def poll_iwencai_sentiment():
    if not is_trading_time():
        return

    results = {}
    try:
        # Q1: 封板率 + 炸板率
        r1 = _iwencai_query("封板率 炸板率", limit=5)
        for row in r1.get("datas", []):
            fb = _get_val(row, "封板率", clean=True)
            zb = _get_val(row, "炸板率", clean=True)
            if fb is not None: results["封板率"] = fb
            if zb is not None: results["炸板率"] = zb
            break

        # Q2: 晋级率 + 连板股数 + 最高板
        r2 = _iwencai_query("涨停晋级率 连板股数", limit=5)
        for row in r2.get("datas", []):
            jj = _get_val(row, "晋级率", clean=True)
            lb_count = _get_val(row, "连板股数")
            if jj is not None: results["晋级率"] = jj
            if lb_count is not None: results["连板股数"] = lb_count
            break

        # Q3: 最高板 — 从连板个股中取 max
        r3 = _iwencai_query("连板股票 最高板", limit=20)
        max_board = 0
        for row in r3.get("datas", []):
            days = _get_val(row, "连续涨停天数", clean=True)
            if days is not None and isinstance(days, (int, float)) and days > max_board:
                max_board = int(days)
            # 也检查 最高板 字段
            gb = _get_val(row, "最高板", clean=True)
            if gb is not None and isinstance(gb, (int, float)) and gb > max_board:
                max_board = int(gb)
        if max_board > 0:
            results["最高板"] = max_board

        # Q4: 涨停收益/赚钱效应 — 从昨日涨停今日表现计算
        r4 = _iwencai_query("昨日涨停 今日涨跌幅", limit=30)
        zt_pcts = []
        for row in r4.get("datas", []):
            pct = _get_val(row, "涨跌幅", clean=True)
            if pct is not None and isinstance(pct, (int, float)):
                zt_pcts.append(pct)
        if zt_pcts:
            avg_zt = round(sum(zt_pcts) / len(zt_pcts), 2)
            results["昨日涨停收益"] = avg_zt
            green_count = sum(1 for p in zt_pcts if p > 0)
            results["涨停溢价率"] = round(green_count / len(zt_pcts) * 100, 1)
            # 赚钱效应：均涨幅 >2% 为好，<0 为差
            results["赚钱效应"] = "好" if avg_zt > 2 else ("差" if avg_zt < 0 else "一般")

        # Q5: 连板风险值 — 从晋级率反推（1 - 晋级率，晋级率越低风险越高）
        jj_now = results.get("晋级率")
        if jj_now is not None and isinstance(jj_now, (int, float)):
            rate = jj_now if jj_now <= 1 else jj_now / 100  # iwencai 返回小数（0-1）
            results["连板风险值"] = round(1.0 - rate, 2)

        if results:
            results["_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
            CACHE["iwencai"] = results
    except Exception as e:
        print(f"  [iwencai_poll] error: {e}", file=sys.stderr)
