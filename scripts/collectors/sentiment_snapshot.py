"""sentiment_snapshot.py — 5节点情绪矩阵 30min 自动快照

每 30 分钟（整点+半点）自动 snapshot 当前情绪指标 → data/sentiment_auto.json。
保留最近 90 天记录（约 1260 条），每季度归档。
"""
import json, os, sys
from pathlib import Path
from datetime import datetime, time as _time_module

from scripts.file_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT = ROOT / "data" / "sentiment_auto.json"
CACHE = {}

NODE_NAMES = {
    (9, 25): "竞价",
    (10, 0): "早盘", (10, 30): "早盘2",
    (11, 0): "午盘前", (11, 30): "午盘",
    (13, 0): "午盘", (13, 30): "尾盘1",
    (14, 0): "尾盘", (14, 30): "尾盘2",
    (15, 0): "收盘",
}


def _current_node():
    """返回当前对应的情绪节点名"""
    now = datetime.now()
    h = now.hour
    m = now.minute
    # 找最近的半小时节点
    m_rounded = (m // 30) * 30
    return NODE_NAMES.get((h, m_rounded), f"{h:02d}:{m_rounded:02d}")


def take_sentiment_snapshot(force=False):
    """采集当前情绪指标快照，追加到 sentiment_auto.json
    时间控制由 APScheduler cron 负责，函数内仅跳过周末"""
    now = datetime.now()
    if not force and now.weekday() >= 5:
        return
    iwencai = CACHE.get("iwencai", {})
    live_index = CACHE.get("live_index", {})
    breadth = CACHE.get("breadth", {})

    # baseline 兜底：iwencai 轮询关闭时用 dashboard_data.json 的 sentiment/market
    baseline = {}
    try:
        dd_file = Path(__file__).resolve().parent.parent.parent / "data" / "dashboard_data.json"
        if dd_file.exists():
            with open(dd_file) as f:
                dd = json.load(f)
            baseline = {**(dd.get("sentiment", {})), **(dd.get("market", {}))}
    except Exception:
        pass
    def _v(key, alt_key=None):
        v = iwencai.get(key)
        if v is not None: return v
        v = baseline.get(key)
        if v is not None: return v
        return baseline.get(alt_key) if alt_key else None

    # 情绪值：T3 实时计算（涨跌家数比），与 store.js 逻辑一致
    up = live_index.get("上涨家数", 0) or 0
    dn = live_index.get("下跌家数", 0) or 0
    emotion_val = round(up / (up + dn) * 100, 1) if (up + dn) > 0 else None

    # 炸板率：从封板率反推
    fbr = _v("封板率")
    zbr = round(1 - fbr, 4) if fbr is not None else None

    # 从 CACHE 取数据，None 时回退 baseline
    snap = {
        "time": now.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "node": _current_node(),
        # 情绪核心
        "情绪值": emotion_val,
        "涨停家数": _v("涨停家数") or (breadth.get("涨停") if breadth else None),
        "跌停家数": _v("跌停家数") or (breadth.get("跌停") if breadth else None),
        "涨停收益": _v("昨日涨停收益"),
        "封板率": fbr,
        "炸板率": zbr,
        "晋级率": _v("晋级率"),
        "最高板": _v("最高板"),
        "连板风险值": _v("连板风险值"),
        "赚钱效应": _v("赚钱效应"),
        "涨停溢价率": _v("涨停溢价率"),
        # 连板/炸板收益（baseline 存 昨日连板收益/昨日炸板收益）
        "连板收益": _v("连板收益", "昨日连板收益"),
        "炸板收益": _v("炸板收益", "昨日炸板收益"),
        "连板股数": _v("连板股数"),
        # 大盘指数（live_index 5s）
        "上证指数": live_index.get("上证指数"),
        "上证涨幅": live_index.get("上证指数涨幅"),
        "深证涨幅": live_index.get("深证指数涨幅"),
        "创业板涨幅": live_index.get("创业板指涨幅"),
        "成交额": live_index.get("成交额"),
        # 涨跌家数
        "上涨家数": up or None,
        "下跌家数": dn or None,
    }

    # 加载已有快照（按日期分组: {"2026-05-18": [{...}, ...]}）
    date_key = now.strftime("%Y-%m-%d")
    all_snapshots = {}
    if OUTPUT.exists():
        try:
            with open(OUTPUT) as f:
                all_snapshots = json.load(f)
        except Exception:
            all_snapshots = {}

    # 兼容旧格式（list → dict 自动迁移）
    if isinstance(all_snapshots, list):
        all_snapshots = {}
    day_snapshots = all_snapshots.get(date_key, [])
    day_snapshots.append(snap)
    all_snapshots[date_key] = day_snapshots

    # 保留最近 90 天
    max_days = 90
    if len(all_snapshots) > max_days:
        sorted_keys = sorted(all_snapshots.keys())
        keep_keys = sorted_keys[-max_days:]
        all_snapshots = {k: all_snapshots[k] for k in keep_keys}

    atomic_write_json(OUTPUT, all_snapshots)
