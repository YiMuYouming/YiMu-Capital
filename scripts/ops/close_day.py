#!/usr/bin/env python3
"""close_day.py — 收盘后从云端拉取 SQLite 一致性备份和辅助 JSON。

默认 dry-run。添加 --apply 执行。

Usage:
    python3 scripts/ops/close_day.py --dry-run
    python3 scripts/ops/close_day.py --apply
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    from scripts.ops.common import run, sqlite_integrity
    from scripts.account_ssot import build_daily_ticket_review
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from scripts.ops.common import run, sqlite_integrity
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
        remote_files = [f"{REMOTE}:{remote_data}/{f}" for f in SYNC_JSON_FILES]
        rsync_cmd = [
            "rsync", "-avz", "--ignore-missing-args", "--backup",
            *remote_files,
            f"{local_data}/",
        ]
        run(rsync_cmd, dry_run=False)
        print("  ✅ 辅助 JSON 同步完成")
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
    summary = build_daily_ticket_review(date_str)
    print(f"  Ticket review summary generated for {date_str}")
    if dry_run:
        print("  [DRY-RUN] 跳过 Markdown 写入")
    else:
        review_dir = local_data / "reviews"
        review_dir.mkdir(parents=True, exist_ok=True)
        out_path = review_dir / f"ticket_review_{date_str}.md"
        out_path.write_text(summary.get("review_markdown", ""), encoding="utf-8")
        print(f"  ✅ Markdown 已写入: {out_path}")

    print()
    print("=" * 60)
    print("完成" if not dry_run else "[DRY-RUN] 未执行任何写操作")


if __name__ == "__main__":
    main()
