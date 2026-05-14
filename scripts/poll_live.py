#!/usr/bin/env python3
"""poll_live.py v3.0 — 实时数据轮询 → dashboard_live.json (Layer 2)

v3.0: 底层走 ym_stock_data 统一数据平台，watch_mode 循环保留。
v2.0: PyTDX(个股+指数) + 东方财富(板块) + easyquotation(兜底)

用法:
  python3 poll_live.py                 # 单次运行
  python3 poll_live.py --watch         # 守护模式 (5s个股, 30s板块)
"""

import json, sys, time, subprocess, argparse
from pathlib import Path
from datetime import datetime

# 统一走 ym_stock_data
sys.path.insert(0, str(Path.home() / "Documents/YM_Capital/ym-stock-data"))
from ym_stock_data.consumer.dashboard import build_live

ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_FILE = ROOT_DIR / "data/dashboard_live.json"


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def watch_mode(interval_stocks=5, interval_sectors=30):
    """守护模式：分层轮询写入 dashboard_live.json"""
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    log(f"v3.0 ym_stock_data 守护启动: 个股/指数 {interval_stocks}s, 板块 {interval_sectors}s")

    write_count = 0
    last_sector_update = -999
    auction_done = False

    try:
        while True:
            now = time.time()
            dt = datetime.now()

            # 收盘自动停止
            if dt.hour >= 16 and dt.minute >= 5:
                log(f"收盘停止 ({write_count}次写入)")
                break

            # 9:26 竞价快照
            if not auction_done and (dt.hour > 9 or (dt.hour == 9 and dt.minute >= 26)):
                auction_done = True
                try:
                    auc_script = ROOT_DIR / "scripts" / "snapshot_auction.py"
                    result = subprocess.run(
                        ["python3", str(auc_script)],
                        capture_output=True, text=True, timeout=60
                    )
                    log(f"竞价: {result.stdout.strip()[-100:] if result.stdout else 'OK'}")
                except Exception as e:
                    log(f"竞价失败: {e}")

            # 是否刷新板块 (30s)
            include_sectors = (not auction_done) or (now - last_sector_update >= interval_sectors)

            data = build_live(include_extras=True)

            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            write_count += 1

            if include_sectors:
                last_sector_update = now

            n = len(data.get("live_quotes", {}))
            log(f"写入 #{write_count}: {n}只个股") if write_count <= 5 or write_count % 100 == 0 else None

            time.sleep(interval_stocks)

    except KeyboardInterrupt:
        log(f"手动停止 ({write_count}次写入)")


def main():
    parser = argparse.ArgumentParser(description="实时数据轮询 v3.0 (ym_stock_data)")
    parser.add_argument("--watch", action="store_true", help="守护模式")
    parser.add_argument("--interval", type=int, default=5, help="轮询间隔(秒)")
    parser.add_argument("--sector-interval", type=int, default=30, help="板块刷新间隔(秒)")
    args = parser.parse_args()

    if args.watch:
        watch_mode(args.interval, args.sector_interval)
    else:
        data = build_live(include_extras=True)
        print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
