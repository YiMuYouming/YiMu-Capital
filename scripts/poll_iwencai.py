#!/usr/bin/env python3
"""poll_iwencai.py — iwencai 盘后复盘查询工具
v2.3: 竞价快照已迁至 snapshot_auction.py，本脚本仅用于盘后复盘查询。

用法:
  python3 poll_iwencai.py --review       # 盘后复盘查询（热榜+龙虎榜+连板生态）
  python3 poll_iwencai.py --review --save # 查询并保存到 data/iwencai_review.json
"""

import json, sys, re
from datetime import datetime
from pathlib import Path

# 统一走 ym_stock_data
sys.path.insert(0, "/Users/YouMing/Documents/YM_Capital/YM-data-pipeline")
from ym_stock_data.sources.iwencai import query as _iwencai_query

ROOT_DIR = Path(__file__).resolve().parent.parent  # live-dashboard/

def run_iwencai(q, extra_args=None):
    """调用 ym_stock_data 问财查询，返回 datas 列表"""
    try:
        raw = _iwencai_query(q)
        if "error" in raw:
            print(f"[warn] iwencai: {raw['error']}", file=sys.stderr)
            return None
        return raw.get("datas", [])
    except Exception as e:
        print(f"[warn] iwencai error: {e}", file=sys.stderr)
        return None

def review_mode(save=False):
    """盘后复盘查询：热榜、龙虎榜、连板生态"""
    print("[poll_iwencai] 盘后复盘查询...", file=sys.stderr)
    queries = {
        "热榜": "今日热榜 人气排行",
        "龙虎榜": "今日龙虎榜 净买入",
        "连板生态": "连板股票 晋级率 最高板 涨停家数",
    }
    results = {}
    for name, query in queries.items():
        result = run_iwencai(query)
        results[name] = result[:500] if result else "查询失败"
        print(f"  [{name}] {'OK' if result else 'FAIL'}", file=sys.stderr)

    if save:
        output = ROOT_DIR / "data/iwencai_review.json"
        with open(output, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"[poll_iwencai] 已保存到 {output}", file=sys.stderr)
    else:
        print(json.dumps(results, ensure_ascii=False, indent=2))


def _parse_iwencai_table(datas):
    """归一化字段名：去掉 [日期] 后缀 (如 涨跌幅[20260514] → 涨跌幅)"""
    if not datas:
        return []
    rows = []
    for item in datas:
        row = {}
        for k, v in item.items():
            clean_key = re.sub(r'\[.*\]', '', k).strip()
            row[clean_key] = v
        rows.append(row)
    return rows


def main():
    import argparse
    parser = argparse.ArgumentParser(description="iwencai 盘后复盘查询工具")
    parser.add_argument("--review", action="store_true", help="盘后复盘查询（热榜+龙虎榜+连板生态）")
    parser.add_argument("--save", action="store_true", help="保存到 data/iwencai_review.json")
    args = parser.parse_args()

    if args.review:
        review_mode(save=args.save)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
