#!/usr/bin/env python3
"""open_day.py — 开盘前本地生成今日基线并同步上云。

默认 dry-run。添加 --apply 执行。
--restart-cloud 额外重启云端服务。

Usage:
    python3 scripts/ops/open_day.py --dry-run
    python3 scripts/ops/open_day.py --apply
    python3 scripts/ops/open_day.py --apply --restart-cloud
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

# 支持直接 python3 scripts/ops/open_day.py 运行
try:
    from scripts.ops.common import run, read_baseline_summary, require_apply
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from scripts.ops.common import run, read_baseline_summary, require_apply

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
GEN_SCRIPT = PROJECT_ROOT / "scripts/gen_dashboard_data.py"
DATA_DIR = PROJECT_ROOT / "data"
BASELINE_PATH = DATA_DIR / "dashboard_data.json"

REMOTE = "agentuser@43.132.146.234"
REMOTE_DATA_DIR = "/home/agentuser/YiMu-Capital/data"


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="开盘前生成基线并同步上云")
    p.add_argument("--dry-run", action="store_true", default=True,
                   help="只打印不执行（默认）")
    p.add_argument("--apply", action="store_true",
                   help="执行实际写操作")
    p.add_argument("--restart-cloud", action="store_true",
                   help="同步后重启云端服务")
    p.add_argument("--baseline", default=str(BASELINE_PATH),
                   help=argparse.SUPPRESS)
    return p.parse_args(argv)


def print_baseline_summary(path):
    summary = read_baseline_summary(path)
    if summary is None:
        print("  基线文件不存在")
        return
    print(f"  生成/更新时间: {summary['generated_at']}")
    print(f"  来源: {summary['note']}")
    print(f"  自选池来源: {summary['pools_note']} ({summary['pools_note_date']})")
    print(f"  今日操作来源日期: {summary['today_operations_source_date']}")
    print(f"  连板池: {summary['lianban_count']} 只")
    print(f"  趋势池: {summary['trend_count']} 只")


def main():
    args = parse_args()
    dry_run = not args.apply  # 无 --apply 时默认 dry-run

    print("=" * 60)
    print(f"{'开盘自动化 [DRY-RUN]' if dry_run else '开盘自动化'}")
    print(f"  本地项目: {PROJECT_ROOT}")
    print(f"  云端路径: {REMOTE}:{REMOTE_DATA_DIR}")
    print(f"  远程主机: {REMOTE}")
    print()

    # 1. 检查 gen 脚本存在
    if not GEN_SCRIPT.exists():
        print(f"[ERROR] gen_dashboard_data.py 不存在: {GEN_SCRIPT}")
        sys.exit(1)
    print(f"[STEP 1] 生成基线: {GEN_SCRIPT.name}")

    if dry_run:
        print("  [DRY-RUN] 跳过生成")
        print("  命令: python3", GEN_SCRIPT)
    else:
        r = run([sys.executable, str(GEN_SCRIPT)], dry_run=False)
        if r and r.returncode != 0:
            print(f"[ERROR] 基线生成失败 (exit={r.returncode})")
            sys.exit(1)
        print("  ✅ 基线生成完成")

    # 2. 基线摘要
    print()
    print(f"[STEP 2] 基线摘要: {BASELINE_PATH.name}")
    if dry_run and not BASELINE_PATH.exists():
        print("  [DRY-RUN] 基线文件尚未生成（跳过）")
    else:
        print_baseline_summary(args.baseline)

    # 3. 同步到云端
    print()
    print("[STEP 3] 同步到云端")
    sync_files = ["dashboard_data.json", "pools.json"]
    for fname in sync_files:
        local = DATA_DIR / fname
        status = "存在" if local.exists() else "不存在"
        print(f"  {fname}: {status}")
    print(f"  目标: {REMOTE}:{REMOTE_DATA_DIR}/")

    if not dry_run:
        rsync_cmd = [
            "rsync", "-avz", "--backup",
            str(DATA_DIR / "dashboard_data.json"),
            str(DATA_DIR / "pools.json"),
            f"{REMOTE}:{REMOTE_DATA_DIR}/",
        ]
        run(rsync_cmd, dry_run=False)
        print("  ✅ 同步完成")
    else:
        print("  [DRY-RUN] 跳过 rsync")
        print(f"  rsync -avz --backup dashboard_data.json pools.json {REMOTE}:{REMOTE_DATA_DIR}/")

    # 4. 可选重启云端
    if args.restart_cloud:
        print()
        print("[STEP 4] 重启云端服务")
        if not dry_run:
            restart_cmd = [
                "ssh", REMOTE,
                "sudo systemctl restart yimu-live-dashboard.service",
            ]
            run(restart_cmd, dry_run=False)
            print("  ✅ 服务已重启")
        else:
            print("  [DRY-RUN] 跳过重启")
            print(f"  ssh {REMOTE} 'sudo systemctl restart yimu-live-dashboard.service'")

    # 5. 验收（仅 apply 模式）
    if not dry_run:
        print()
        print("[STEP 5] 只读验收")
        for url_path in ["/api/baseline", "/api/account/state", "/api/pnl/summary"]:
            curl_cmd = ["curl", "-s", "--max-time", "5",
                        f"http://127.0.0.1:8088{url_path}"]
            r = run(curl_cmd, dry_run=False, check=False, capture_output=True)
            if r and r.returncode == 0 and r.stdout.strip():
                snippet = r.stdout.strip()[:120]
                print(f"  ✅ {url_path}: {snippet}...")
            else:
                print(f"  ⚠️  {url_path}: 无响应")
    else:
        print()
        print("[STEP 5] 验收命令（apply 后执行）:")
        for url_path in ["/api/baseline", "/api/account/state", "/api/pnl/summary"]:
            print(f"  curl -s http://127.0.0.1:8088{url_path} | python3 -m json.tool | head -20")

    print()
    print("=" * 60)
    print("完成" if not dry_run else "[DRY-RUN] 未执行任何写操作")


if __name__ == "__main__":
    main()
