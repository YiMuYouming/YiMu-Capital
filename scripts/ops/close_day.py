#!/usr/bin/env python3
"""close_day.py — 收盘后从云端拉取 SQLite 一致性备份和辅助 JSON。

默认 dry-run。添加 --apply 执行。

Usage:
    python3 scripts/ops/close_day.py --dry-run
    python3 scripts/ops/close_day.py --apply
"""

import argparse
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    from scripts.ops.common import run, sqlite_integrity
    from scripts.ops import backup_live_dashboard_data
    from scripts.ops import generate_review_source_packet as review_source_packet
    from scripts.account_ssot import build_daily_ticket_review
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from scripts.ops.common import run, sqlite_integrity
    from scripts.ops import backup_live_dashboard_data
    from scripts.ops import generate_review_source_packet as review_source_packet
    from scripts.account_ssot import build_daily_ticket_review

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOCAL_DATA_DIR = PROJECT_ROOT / "data"

REMOTE = "agentuser@43.132.146.234"
REMOTE_DATA_DIR = "/home/agentuser/YiMu-Capital/data"
REMOTE_PROJECT = "/home/agentuser/YiMu-Capital"
REMOTE_VENV_PYTHON = f"{REMOTE_PROJECT}/.venv/bin/python"

SYNC_JSON_FILES = [
    "dashboard_data.json",
    "pnl_history.json",
    "sentiment_auto.json",
    "auction_snapshot.json",
    "ymwm_report.json",
    "zt_history.json",
]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="收盘后从云端同步主库和辅助 JSON")
    p.add_argument("--dry-run", action="store_true", default=True,
                   help="只打印不执行（默认）")
    p.add_argument("--apply", action="store_true",
                   help="执行实际写操作")
    p.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"),
                   help="生成票据复盘摘要的日期，默认今天")
    p.add_argument("--remote-data-dir", default=REMOTE_DATA_DIR,
                   help=argparse.SUPPRESS)
    p.add_argument("--local-data-dir", default=str(LOCAL_DATA_DIR),
                   help=argparse.SUPPRESS)
    p.add_argument("--skip-data-backup", action="store_true",
                   help="跳过收盘后的项目专用数据包备份")
    return p.parse_args(argv)


def build_remote_backup_script(remote_data_dir):
    """返回在远端创建 SQLite backup 的 Python 脚本内容。"""
    return (
        'import sqlite3, datetime, pathlib; '
        f'src=pathlib.Path("{remote_data_dir}/pnl.db"); '
        f'dst=pathlib.Path("{remote_data_dir}")/f"pnl.db.backup-close-{{datetime.datetime.now():%Y%m%d-%H%M%S}}"; '
        's=sqlite3.connect(str(src)); t=sqlite3.connect(str(dst)); '
        's.backup(t); t.close(); s.close(); '
        'c=sqlite3.connect(str(dst)); '
        'r=c.execute("PRAGMA integrity_check").fetchone()[0]; c.close(); '
        'print(dst.name); print("integrity_check:", r); '
        'exit(1) if r.lower()!="ok" else None'
    )


def run_project_data_backup(local_data, date_str):
    stamp = f"close-{date_str.replace('-', '')}-{datetime.now().strftime('%H%M%S')}"
    output_dir = Path(local_data) / "backups" / "live-dashboard-data"
    backup_live_dashboard_data.main([
        "--apply",
        "--upload-oss",
        "--data-dir", str(local_data),
        "--output-dir", str(output_dir),
        "--stamp", stamp,
    ])


def run_review_source_packet(local_data, date_str, dry_run):
    packet = review_source_packet.generate_review_source_packet(date_str, data_dir=Path(local_data))
    result = review_source_packet.write_review_source_packet(
        packet,
        Path(local_data),
        apply=not dry_run,
    )
    print(f"  输出路径: {result['path']}")
    print(f"  ai_context: {packet.get('source_status', {}).get('ai_context')}")
    print(f"  tickets: {packet.get('source_status', {}).get('tickets')}")
    print(f"  manual_required: {len(packet.get('manual_required') or [])}")
    print("  ✅ review_source_packet 已写入" if result["written"] else "  [DRY-RUN] 未写入")
    return result


def preview_review_source_packet(local_data, date_str):
    out_path = Path(local_data) / "review_packets" / date_str / "review_source_packet.json"
    print(f"  输出路径: {out_path}")
    print("  [DRY-RUN] 跳过 source collection 和 packet 写入")
    return {"path": str(out_path), "written": False}


def rsync_remote_arg(remote, path):
    return f"{remote}:{shlex.quote(str(path))}"


def list_existing_remote_json_files(remote, remote_data_dir):
    json_names = " ".join(shlex.quote(name) for name in SYNC_JSON_FILES)
    list_cmd = [
        "ssh",
        remote,
        f"cd {shlex.quote(remote_data_dir)} && for f in {json_names}; do [ -f \"$f\" ] && printf '%s\\n' \"$f\"; done",
    ]
    list_result = run(list_cmd, dry_run=False, check=False, capture_output=True)
    if not list_result or list_result.returncode != 0:
        err = list_result.stderr.strip() if list_result and list_result.stderr else "unknown"
        print(f"  ❌ 辅助 JSON 列表获取失败: {err}")
        sys.exit(1)
    return [
        line.strip()
        for line in ((list_result.stdout or "").splitlines() if list_result and list_result.stdout else [])
        if line.strip()
    ]


def main():
    args = parse_args()
    dry_run = not args.apply

    local_data = Path(args.local_data_dir)
    remote_data = args.remote_data_dir
    arg_date = getattr(args, "date", None)
    date_str = arg_date if isinstance(arg_date, str) and arg_date else datetime.now().strftime("%Y-%m-%d")

    print("=" * 60)
    print(f"{'收盘自动化 [DRY-RUN]' if dry_run else '收盘自动化'}")
    print(f"  本地数据目录: {local_data}")
    print(f"  云端数据目录: {REMOTE}:{remote_data}")
    print(f"  远程主机: {REMOTE}")
    print()

    if not dry_run:
        local_data.mkdir(parents=True, exist_ok=True)

    # 1. 云端 SQLite backup
    print("[STEP 1] 云端 SQLite 一致性备份")
    backup_script = build_remote_backup_script(remote_data)
    if dry_run:
        print("  [DRY-RUN] 跳过云端备份")
        print(f"  ssh {REMOTE} '{REMOTE_VENV_PYTHON}' -c '... backup ...'")
    else:
        ssh_cmd = ["ssh", REMOTE,
                    f"cd {REMOTE_PROJECT} && {REMOTE_VENV_PYTHON} -c \"{backup_script}\""]
        r = run(ssh_cmd, dry_run=False, check=False, capture_output=True)
        _out = r.stdout.strip() if r and r.stdout else ""
        if r and "integrity_check: ok" in _out:
            backup_name = _out.split("\n")[0].strip()
            print(f"  ✅ 备份创建: {backup_name}")
        else:
            _err = r.stderr.strip() if r and r.stderr else "unknown"
            print(f"  ❌ 备份失败: {_err}")
            print(f"  stdout: {_out[:200]}")
            sys.exit(1)

    # 2. 拉取 pnl.db
    print()
    print("[STEP 2] 拉取 pnl.db 到本地")

    if dry_run:
        print("  [DRY-RUN] 跳过 rsync")
        print(f"  rsync -avz --backup {REMOTE}:{remote_data}/pnl.db.backup-close-* {local_data}/pnl.db")
    else:
        # 获取最新备份文件名
        ls_cmd = ["ssh", REMOTE, f"ls -t {remote_data}/pnl.db.backup-close-* | head -1"]
        ls_r = run(ls_cmd, dry_run=False, check=False, capture_output=True)
        _ls_out = ls_r.stdout.strip() if ls_r and ls_r.stdout else ""
        if not ls_r or ls_r.returncode != 0 or not _ls_out:
            print("  ❌ 找不到云端备份文件")
            sys.exit(1)
        latest_backup = _ls_out
        rsync_cmd = [
            "rsync", "-avz", "--backup",
            f"{REMOTE}:{latest_backup}",
            f"{local_data}/pnl.db",
        ]
        run(rsync_cmd, dry_run=False)
        print("  ✅ pnl.db 已同步到本地")

    # 3. 同步辅助 JSON
    print()
    print("[STEP 3] 同步辅助 JSON")
    for fname in SYNC_JSON_FILES:
        status = "存在" if (local_data / fname).exists() else "不存在"
        print(f"  {fname}: {status}")

    if not dry_run:
        existing_json = list_existing_remote_json_files(REMOTE, remote_data)
        if existing_json:
            remote_files = [rsync_remote_arg(REMOTE, f"{remote_data}/{f}") for f in existing_json]
            rsync_cmd = [
                "rsync", "-avz", "--backup",
                *remote_files,
                f"{local_data}/",
            ]
            run(rsync_cmd, dry_run=False)
            print("  ✅ 辅助 JSON 同步完成")
        else:
            print("  ⚠️ 云端未找到可同步的辅助 JSON")
    else:
        print("  [DRY-RUN] 跳过 rsync")
        for f in SYNC_JSON_FILES:
            print(f"    {f}")

    # 4. 本地完整性检查
    print()
    print("[STEP 4] 本地 pnl.db 完整性检查")
    local_db = local_data / "pnl.db"
    if dry_run:
        print("  [DRY-RUN] 跳过检查")
        print(f"  python3 -c '... PRAGMA integrity_check ...' {local_db}")
    else:
        ok, msg = sqlite_integrity(local_db)
        if ok:
            print(f"  ✅ integrity_check: {msg}")
        else:
            print(f"  ❌ integrity_check: {msg}")
            sys.exit(1)

    # 5. 生成交易票据复盘摘要
    print()
    print("[STEP 5] 生成交易票据复盘摘要")
    if dry_run:
        print(f"  输出路径: {local_data / 'reviews' / f'ticket_review_{date_str}.md'}")
        print("  [DRY-RUN] 跳过票据复盘摘要生成")
    else:
        summary = build_daily_ticket_review(date_str)
        print(f"  Ticket review summary generated for {date_str}")
        review_dir = local_data / "reviews"
        review_dir.mkdir(parents=True, exist_ok=True)
        out_path = review_dir / f"ticket_review_{date_str}.md"
        out_path.write_text(summary.get("review_markdown", ""), encoding="utf-8")
        print(f"  ✅ Markdown 已写入: {out_path}")

    # 6. 生成 WorkBuddy 复盘事实包
    print()
    print("[STEP 6] 生成 WorkBuddy review_source_packet")
    if dry_run:
        preview_review_source_packet(local_data, date_str)
    else:
        run_review_source_packet(local_data, date_str, dry_run)

    # 7. 项目专用数据包备份
    print()
    print("[STEP 7] 项目专用数据包备份")
    if dry_run:
        print("  [DRY-RUN] 跳过专用数据包备份")
        preview_output_dir = local_data / "backups" / "live-dashboard-data"
        print("  close_day.py --apply 会在数据拉回、完整性检查和 review_source_packet 生成后自动执行专用备份")
        print(f"  备份参数: --data-dir {local_data} --output-dir {preview_output_dir} --upload-oss")
    elif getattr(args, "skip_data_backup", False):
        print("  跳过：--skip-data-backup")
    else:
        run_project_data_backup(local_data, date_str)

    print()
    print("=" * 60)
    print("完成" if not dry_run else "[DRY-RUN] 未执行任何写操作")


if __name__ == "__main__":
    main()
