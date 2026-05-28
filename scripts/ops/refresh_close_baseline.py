#!/usr/bin/env python3
"""refresh_close_baseline.py — 用本地收盘行情修正 dashboard_data.json。

云端香港节点不能依赖 PyTDX。收盘复盘要用本地可取到的最终行情，修正
market/sentiment 基线后再同步上云。
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

try:
    from scripts.file_utils import atomic_write_json
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from scripts.file_utils import atomic_write_json

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_FILE = PROJECT_ROOT / "data" / "dashboard_data.json"
DEFAULT_PIPELINE = PROJECT_ROOT.parent / "YM-data-pipeline"


def _parse_pct(value):
    if value in (None, "", "—"):
        return None
    try:
        return round(float(str(value).replace("%", "").replace("+", "").strip()), 2)
    except (TypeError, ValueError):
        return None


def _parse_amount_wanyi(value):
    if value in (None, "", "—"):
        return None
    s = str(value).strip()
    try:
        if "万亿" in s:
            return round(float(s.replace("万亿", "")), 2)
        if s.endswith("亿"):
            return round(float(s[:-1]) / 10000, 2)
        n = float(s)
    except (TypeError, ValueError):
        return None
    return round(n / 10000, 2) if n >= 10000 else round(n, 2)


def _pct100(value):
    if value is None:
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return value
    return round(n * 100, 2) if abs(n) <= 1 else round(n, 2)


def _emotion_zone(value):
    if value < 20:
        return "冰点"
    if value < 40:
        return "低迷"
    if value < 60:
        return "主升"
    if value < 80:
        return "强势"
    return "高潮"


def apply_close_baseline(data, index_data, sentiment_data, updated_at):
    """返回修正后的 dashboard_data dict，不修改输入对象。"""
    out = json.loads(json.dumps(data, ensure_ascii=False))
    market = out.setdefault("market", {})
    sentiment = out.setdefault("sentiment", {})
    meta = out.setdefault("meta", {})

    up = index_data.get("上涨家数")
    down = index_data.get("下跌家数")
    emotion = None
    if isinstance(up, (int, float)) and isinstance(down, (int, float)) and up + down > 0:
        emotion = round(up / (up + down) * 100, 1)

    market.update({
        "上证指数": index_data.get("上证指数"),
        "上证涨幅": _parse_pct(index_data.get("上证指数涨幅")),
        "深证指数": index_data.get("深证指数"),
        "深证涨幅": _parse_pct(index_data.get("深证指数涨幅")),
        "深证成交额": _parse_amount_wanyi(index_data.get("深证指数成交额")),
        "创业指数": index_data.get("创业指数"),
        "创业涨幅": _parse_pct(index_data.get("创业指数涨幅")),
        "创业成交额": _parse_amount_wanyi(index_data.get("创业指数成交额")),
        "市场量能": _parse_amount_wanyi(index_data.get("成交额")),
        "涨跌比": f"{int(up)}/{int(down)}" if up is not None and down is not None else market.get("涨跌比"),
        "涨停家数": sentiment_data.get("涨停家数", market.get("涨停家数")),
        "跌停家数": sentiment_data.get("跌停家数", market.get("跌停家数")),
        "炸板率": _pct100(sentiment_data.get("炸板率")),
        "封板率": _pct100(sentiment_data.get("封板率")),
    })
    market["_close_source"] = "local_pipeline_close_refresh"
    market["_close_updated"] = updated_at

    if emotion is not None:
        sentiment["情绪值"] = emotion
        sentiment["情绪区间"] = _emotion_zone(emotion)
        sentiment["竞价情绪值"] = emotion
    for dst, src in [
        ("赚钱效应", "赚钱效应"),
        ("昨日涨停收益", "昨日涨停收益"),
        ("昨日炸板收益", "炸板收益"),
        ("连板收益", "连板收益"),
        ("连板风险值", "连板风险值"),
        ("晋级率", "晋级率"),
        ("一进二晋级率", "一进二晋级率"),
        ("二进三晋级率", "二进三晋级率"),
        ("三进四晋级率", "三进四晋级率"),
        ("最高板", "最高板"),
        ("次高板", "次高板"),
        ("连板梯队", "连板股列表"),
    ]:
        if src in sentiment_data and sentiment_data[src] is not None:
            val = sentiment_data[src]
            if dst.endswith("晋级率"):
                val = _pct100(val)
            sentiment[dst] = val
    sentiment["_close_source"] = "local_pipeline_close_refresh"
    sentiment["_close_updated"] = updated_at

    meta["updated"] = updated_at
    meta["close_refreshed_at"] = updated_at
    meta["close_source"] = "scripts/ops/refresh_close_baseline.py"
    return out


def fetch_close_inputs(pipeline_path):
    if str(pipeline_path) not in sys.path:
        sys.path.insert(0, str(pipeline_path))
    from ym_stock_data import fetch
    from scripts.collectors import iwencai_poll

    index_data = fetch("index")
    if not index_data.get("上证指数") or not index_data.get("深证指数") or not index_data.get("创业指数"):
        raise RuntimeError(f"index 数据不完整: {index_data}")

    iwencai_poll.poll_iwencai_sentiment(force=True)
    sentiment_data = iwencai_poll.CACHE.get("iwencai") or {}
    if not sentiment_data.get("涨停家数") or sentiment_data.get("跌停家数") is None:
        raise RuntimeError(f"iwencai 情绪数据不完整: {sentiment_data}")
    return index_data, sentiment_data


def main(argv=None):
    p = argparse.ArgumentParser(description="用本地收盘行情修正 dashboard_data.json")
    p.add_argument("--apply", action="store_true", help="实际写入；默认只预览")
    p.add_argument("--data-file", default=str(DATA_FILE), help=argparse.SUPPRESS)
    p.add_argument("--pipeline", default=str(DEFAULT_PIPELINE), help=argparse.SUPPRESS)
    args = p.parse_args(argv)

    data_file = Path(args.data_file)
    pipeline = Path(args.pipeline)
    data = json.loads(data_file.read_text(encoding="utf-8"))
    index_data, sentiment_data = fetch_close_inputs(pipeline)
    updated_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    refreshed = apply_close_baseline(data, index_data, sentiment_data, updated_at)

    summary = {
        "上证": [refreshed["market"].get("上证指数"), refreshed["market"].get("上证涨幅")],
        "深证": [index_data.get("深证指数"), index_data.get("深证指数涨幅")],
        "创业": [index_data.get("创业指数"), index_data.get("创业指数涨幅")],
        "成交额": refreshed["market"].get("市场量能"),
        "涨跌比": refreshed["market"].get("涨跌比"),
        "涨跌停": [refreshed["market"].get("涨停家数"), refreshed["market"].get("跌停家数")],
        "情绪值": refreshed["sentiment"].get("情绪值"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.apply:
        atomic_write_json(data_file, refreshed)
        print(f"✅ 已写入 {data_file}")
    else:
        print("[DRY-RUN] 未写入；加 --apply 执行")


if __name__ == "__main__":
    main()
