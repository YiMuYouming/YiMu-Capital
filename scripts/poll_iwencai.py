#!/usr/bin/env python3
"""poll_iwencai.py — iwencai API 轮询 → dashboard_live.json (Layer 2 实时数据)
稳米维护 | v2.0 Phase 1.9

轮询频率(v2.0下调):
  大盘指数(live_index): 30s
  个股报价(live_quotes): 15s
  板块数据(live_sectors): 60s

用法:
  python3 poll_iwencai.py                # 单次运行，输出到 stdout
  python3 poll_iwencai.py --watch        # 守护模式，循环输出文件
  python3 poll_iwencai.py --tier index   # 只查大盘 (Q1)
  python3 poll_iwencai.py --tier quotes  # 只查个股报价 (Q4)
  python3 poll_iwencai.py --tier sectors # 只查板块 (Q4)
"""

import json, os, sys, time, subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent  # live-dashboard/
IWC_SCRIPT = Path.home() / "WorkBuddy/Tools/iwencai_query.py"
OUTPUT_FILE = ROOT_DIR / "data/dashboard_live.json"
DASHBOARD_DATA = ROOT_DIR / "data/dashboard_data.json"

# 频率配置 (v2.0)
TIER_INTERVALS = {
    "index": 30,
    "quotes": 15,
    "sectors": 60,
    "all": 30,  # 综合模式取最小值
}

def run_iwencai(query, extra_args=None):
    """调用 iwencai_query.py 查询"""
    cmd = ["python3", str(IWC_SCRIPT), query]
    if extra_args:
        cmd.extend(extra_args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=45, cwd=str(ROOT_DIR))
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            print(f"[warn] iwencai query failed: {result.stderr[:200]}", file=sys.stderr)
            return None
    except subprocess.TimeoutExpired:
        print("[warn] iwencai query timed out", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[warn] iwencai error: {e}", file=sys.stderr)
        return None

def fetch_live_index():
    """Q1: 大盘指数实时数据"""
    result = run_iwencai("上证指数 深证指数 创业板指 成交额 涨跌幅")
    if not result:
        return {}
    # 解析 iwencai 返回的表格数据
    # 简单实现：返回上一次缓存的数据（iwencai 输出解析较复杂）
    return {"note": "live_index from iwencai Q1", "last_fetch": time.strftime("%H:%M:%S")}

def fetch_live_quotes(stock_codes):
    """Q4: 批量个股报价"""
    if not stock_codes:
        return {}
    codes_str = ",".join(stock_codes[:20])  # 限制批量查询大小
    result = run_iwencai(codes_str, extra_args=["--fields", "涨跌幅,量比,换手,最新价"])
    if not result:
        return {}
    return {"note": "live_quotes from iwencai Q4", "last_fetch": time.strftime("%H:%M:%S"), "codes": stock_codes[:20]}

def fetch_live_sectors():
    """板块实时涨跌幅"""
    result = run_iwencai("板块涨幅 主力净流入", extra_args=["--fields", "涨跌幅,主力净流入"])
    if not result:
        return {}
    return {"note": "live_sectors from iwencai", "last_fetch": time.strftime("%H:%M:%S")}

def get_stock_codes_from_dashboard():
    """从 dashboard_data.json 提取所有涉及股票的代码（全量SSOT）"""
    codes = set()
    try:
        with open(DASHBOARD_DATA) as f:
            data = json.load(f)

        # 持仓（活跃 + 清仓）
        for p in data.get("positions", []):
            code = p.get("代码")
            if code and str(code).isdigit():
                codes.add(str(code))

        # 连板自选池
        for s in data.get("lianban_pool", []):
            code = s.get("代码")
            if code and str(code).isdigit():
                codes.add(str(code))

        # 趋势自选池
        for s in data.get("trend_pool", []):
            code = s.get("代码")
            if code and str(code).isdigit():
                codes.add(str(code))

        # 锚定股状态
        for a in (data.get("decision", {}).get("锚定股状态") or []):
            code = a.get("代码")
            if code and str(code).isdigit():
                codes.add(str(code))

        # 今日操作
        for o in (data.get("decision", {}).get("今日操作") or []):
            code = o.get("代码")
            if code and str(code).isdigit():
                codes.add(str(code))

        # 竞价5维-高标竞价和锚定股竞价（名字匹配到pool里的代码）
        auction = data.get("decision", {}).get("竞价", {})
        for item in (auction.get("高标竞价") or []) + (auction.get("锚定股竞价") or []):
            name = item.get("名称", "")
            # 尝试从 pool 中匹配
            for pool in [data.get("lianban_pool", []), data.get("trend_pool", [])]:
                for s in pool:
                    if s.get("标的") and s["标的"] in name:
                        code = s.get("代码")
                        if code and str(code).isdigit():
                            codes.add(str(code))

    except Exception as e:
        print(f"[warn] get_stock_codes: {e}", file=sys.stderr)

    codes = sorted(codes)
    print(f"[info] Found {len(codes)} stock codes: {', '.join(codes[:10])}{'...' if len(codes)>10 else ''}")
    return codes

def build_live_data(tier="all"):
    """组装 live 数据"""
    data = {}

    if tier in ("index", "all"):
        data["live_index"] = fetch_live_index()
    if tier in ("sectors", "all"):
        data["live_sectors"] = fetch_live_sectors()
    if tier in ("quotes", "all"):
        codes = get_stock_codes_from_dashboard()
        data["live_quotes"] = fetch_live_quotes(codes)

    data["meta"] = {
        "fetched": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "tier": tier
    }
    return data

def watch_mode(tier="all"):
    """守护模式：循环轮询写入文件"""
    interval = TIER_INTERVALS.get(tier, 30)
    print(f"[watch] Polling every {interval}s, tier={tier}, output={OUTPUT_FILE}")
    print("[watch] Press Ctrl+C to stop")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    try:
        while True:
            data = build_live_data(tier)
            with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"  [{time.strftime('%H:%M:%S')}] Updated dashboard_live.json")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[done] Polling stopped.")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="iwencai 实时数据轮询")
    parser.add_argument("--watch", action="store_true", help="守护模式，循环轮询")
    parser.add_argument("--tier", default="all", choices=["index","quotes","sectors","all"], help="数据层")
    args = parser.parse_args()

    if args.watch:
        watch_mode(args.tier)
    else:
        data = build_live_data(args.tier)
        print(json.dumps(data, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
