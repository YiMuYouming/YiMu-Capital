"""snapshot_close.py — 收盘数据包（15:02 触发，dump bridge CACHE 全量快照）

输出: data/close_snapshot_{date}.json
包含: live_index / live_quotes / breadth / live_sectors / iwencai / sector_inflow /
       northbound / hot_list / news
"""
import json, os
from pathlib import Path
from datetime import datetime


def run_snapshot_close(CACHE, ROOT=None):
    """收盘时 dump CACHE 全量快照到磁盘"""
    if ROOT is None:
        ROOT = Path(__file__).resolve().parent.parent
    data_dir = ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    output = data_dir / f"close_snapshot_{date_str}.json"

    snapshot = {
        "fetched": now.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "date": date_str,
        # T1 实时
        "live_index": _safe_copy(CACHE.get("live_index")),
        "live_quotes": _safe_copy(CACHE.get("live_quotes")),
        "breadth": _safe_copy(CACHE.get("breadth")),
        "live_sectors": _safe_copy(CACHE.get("live_sectors")),
        # T2 阶段
        "iwencai": _safe_copy(CACHE.get("iwencai")),
        "sector_inflow": _safe_copy(CACHE.get("sector_inflow")),
        "northbound": _safe_copy(CACHE.get("northbound")),
        "hot_list": _safe_copy(CACHE.get("hot_list")),
        "news": _safe_copy(CACHE.get("news")),
    }

    # 原子写入
    tmp = output.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, output)

    size = output.stat().st_size
    print(f"  [snapshot_close] Written {size} bytes → {output}")
    return str(output)


def _safe_copy(obj):
    """浅拷贝，过滤不可序列化对象"""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return {k: v for k, v in obj.items() if not k.startswith("_") or k in ("_updated",)}
    return obj
