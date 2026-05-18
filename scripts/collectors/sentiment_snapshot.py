"""sentiment_snapshot.py — 5节点情绪矩阵 30min 自动快照

每 30 分钟（整点+半点）自动 snapshot 当前情绪指标 → data/sentiment_auto.json。
保留最近 90 天记录（约 1260 条），每季度归档。
"""
import json, os, sys
from pathlib import Path
from datetime import datetime, time as _time_module

ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT = ROOT / "data" / "sentiment_auto.json"
CACHE = {}

NODE_NAMES = {
    (9, 0): "早盘", (9, 30): "早盘", (10, 0): "早盘", (10, 30): "午盘前",
    (11, 0): "午盘前", (11, 30): "午盘",
    (13, 0): "下午", (13, 30): "下午", (14, 0): "尾盘", (14, 30): "尾盘",
    (15, 0): "收盘", (15, 30): "收盘",
}


def _current_node():
    """返回当前对应的情绪节点名"""
    now = datetime.now()
    h = now.hour
    m = now.minute
    # 找最近的半小时节点
    m_rounded = (m // 30) * 30
    return NODE_NAMES.get((h, m_rounded), f"{h:02d}:{m_rounded:02d}")


def take_sentiment_snapshot():
    """采集当前情绪指标快照，追加到 sentiment_auto.json"""
    now = datetime.now()
    # 非交易时段跳过
    if now.weekday() >= 5:
        return
    t = now.time()
    if not (_time_module(9, 25) <= t <= _time_module(15, 5)):
        return
    iwencai = CACHE.get("iwencai", {})
    live_index = CACHE.get("live_index", {})
    breadth = CACHE.get("breadth", {})

    # 从 CACHE 取数据（1.3 后会由 quotes collector 填充更多字段）
    snap = {
        "time": now.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "node": _current_node(),
        # 情绪核心
        "情绪值": iwencai.get("情绪值"),
        "涨停家数": breadth.get("涨停") or live_index.get("涨停"),
        "跌停家数": breadth.get("跌停") or live_index.get("跌停"),
        "涨停收益": iwencai.get("昨日涨停收益"),
        "封板率": iwencai.get("封板率"),
        "炸板率": iwencai.get("炸板率"),
        "晋级率": iwencai.get("晋级率"),
        "最高板": iwencai.get("最高板"),
        "连板风险值": iwencai.get("连板风险值"),
        "赚钱效应": iwencai.get("赚钱效应"),
        "涨停溢价率": iwencai.get("涨停溢价率"),
        # 新增：连板/炸板收益（iwencai Q6/Q7）
        "连板收益": iwencai.get("连板收益"),
        "炸板收益": iwencai.get("炸板收益"),
        "连板股数": iwencai.get("连板股数"),
        # 新增：大盘指数（live_index 5s）
        "上证指数": live_index.get("上证指数"),
        "上证涨幅": live_index.get("上证指数涨幅"),
        "深证涨幅": live_index.get("深证指数涨幅"),
        "创业板涨幅": live_index.get("创业板指涨幅"),
        "成交额": live_index.get("成交额"),
        # 新增：涨跌家数（breadth / live_index）
        "上涨家数": breadth.get("上涨") or live_index.get("上涨家数"),
        "下跌家数": breadth.get("下跌") or live_index.get("下跌家数"),
    }

    # 加载已有快照
    snapshots = []
    if OUTPUT.exists():
        try:
            with open(OUTPUT) as f:
                snapshots = json.load(f)
        except Exception:
            snapshots = []

    snapshots.append(snap)

    # 保留最近 90 天（约 14条/天 × 90 = 1260）
    max_entries = 1260
    if len(snapshots) > max_entries:
        snapshots = snapshots[-max_entries:]

    # 原子写入
    tmp = OUTPUT.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(snapshots, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OUTPUT)
