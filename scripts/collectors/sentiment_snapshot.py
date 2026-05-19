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
    # 5个关键节点 + 中间映射
    (9, 0): "早盘", (9, 25): "竞价", (9, 30): "早盘",
    (10, 0): "早盘", (10, 30): "早盘",
    (11, 0): "午盘", (11, 30): "午盘",
    (13, 0): "午盘", (13, 30): "尾盘",
    (14, 0): "尾盘", (14, 30): "尾盘",
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


def take_sentiment_snapshot(force=False):
    """采集当前情绪指标快照，追加到 sentiment_auto.json
    时间控制由 APScheduler cron 负责，函数内仅跳过周末"""
    now = datetime.now()
    if not force and now.weekday() >= 5:
        return
    iwencai = CACHE.get("iwencai", {})
    live_index = CACHE.get("live_index", {})
    breadth = CACHE.get("breadth", {})

    # 情绪值：T3 实时计算（涨跌家数比），与 store.js 逻辑一致
    up = live_index.get("上涨家数", 0) or 0
    dn = live_index.get("下跌家数", 0) or 0
    emotion_val = round(up / (up + dn) * 100, 1) if (up + dn) > 0 else None

    # 炸板率：从封板率反推（iwencai 返回的炸板率字段定义与复盘口径不一致，约 72% vs 真实 ~30%）
    fbr = iwencai.get("封板率")
    zbr = round(1 - fbr, 4) if fbr is not None else None

    # 从 CACHE 取数据
    snap = {
        "time": now.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "node": _current_node(),
        # 情绪核心
        "情绪值": emotion_val,
        "涨停家数": iwencai.get("涨停家数") if iwencai.get("涨停家数") else (breadth.get("涨停") if breadth else None),
        "跌停家数": iwencai.get("跌停家数") if iwencai.get("跌停家数") else (breadth.get("跌停") if breadth else None),
        "涨停收益": iwencai.get("昨日涨停收益"),
        "封板率": fbr,
        "炸板率": zbr,
        "晋级率": iwencai.get("晋级率"),
        "最高板": iwencai.get("最高板"),
        "连板风险值": iwencai.get("连板风险值"),
        "赚钱效应": iwencai.get("赚钱效应"),
        "涨停溢价率": iwencai.get("涨停溢价率"),
        # 连板/炸板收益（iwencai Q6/Q7）
        "连板收益": iwencai.get("连板收益"),
        "炸板收益": iwencai.get("炸板收益"),
        "连板股数": iwencai.get("连板股数"),
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

    # 原子写入
    tmp = OUTPUT.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(all_snapshots, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OUTPUT)
