#!/usr/bin/env python3
"""Create a dedicated local archive for live-dashboard runtime data.

Data stays out of git. Use --upload-oss to copy the same archive to OSS through
the existing OSS uploader utility; this does not join the WorkBuddy full backup.
"""

import argparse
import hashlib
import json
import shlex
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

try:
    from scripts.ops import common
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from scripts.ops import common


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_OUTPUT_DIR = DEFAULT_DATA_DIR / "backups" / "live-dashboard-data"
DEFAULT_OSS_PYTHON = Path.home() / "WorkBuddy" / "Tools" / "data-venv" / "bin" / "python"
DEFAULT_OSS_UPLOADER = Path.home() / "WorkBuddy" / "Tools" / "oss_upload.py"
DEFAULT_OSS_PREFIX = "yimu-capital/live-dashboard-data"
DEFAULT_REMOTE = "agentuser@43.132.146.234"
DEFAULT_REMOTE_PROJECT = "/home/agentuser/YiMu-Capital"
DEFAULT_REMOTE_DATA_DIR = f"{DEFAULT_REMOTE_PROJECT}/data"
DEFAULT_REMOTE_PYTHON = f"{DEFAULT_REMOTE_PROJECT}/.venv/bin/python"

JSON_FILES = [
    "dashboard_data.json",
    "pnl_history.json",
    "sentiment_auto.json",
    "auction_snapshot.json",
    "ymwm_report.json",
    "zt_history.json",
    "pools.json",
    "llm_insights.json",
]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Backup live-dashboard data locally and optionally to OSS")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="只打印不执行（默认）")
    parser.add_argument("--apply", action="store_true",
                        help="执行实际备份")
    parser.add_argument("--upload-oss", action="store_true",
                        help="本地备份成功后上传同一个 tar.gz 到 OSS")
    parser.add_argument("--pull-cloud-first", action="store_true",
                        help="先从云端生产数据目录创建一致性备份并拉回本地")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR),
                        help="数据目录，默认 data/")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR),
                        help="本地备份输出目录")
    parser.add_argument("--stamp", default=None,
                        help="备份时间戳，默认当前时间 YYYYMMDD-HHMMSS")
    parser.add_argument("--oss-python", default=str(DEFAULT_OSS_PYTHON),
                        help="运行 OSS uploader 的 Python")
    parser.add_argument("--oss-uploader", default=str(DEFAULT_OSS_UPLOADER),
                        help="OSS 上传脚本路径（复用上传工具，不接入 WorkBuddy 全量备份）")
    parser.add_argument("--oss-prefix", default=DEFAULT_OSS_PREFIX,
                        help="OSS 目标前缀")
    parser.add_argument("--remote", default=DEFAULT_REMOTE,
                        help="云端 SSH 目标")
    parser.add_argument("--remote-project", default=DEFAULT_REMOTE_PROJECT,
                        help="云端项目目录")
    parser.add_argument("--remote-data-dir", default=DEFAULT_REMOTE_DATA_DIR,
                        help="云端数据目录")
    parser.add_argument("--remote-python", default=DEFAULT_REMOTE_PYTHON,
                        help="云端 Python 路径")
    return parser.parse_args(argv)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sqlite_online_backup(src_path, dst_path):
    src = sqlite3.connect(str(src_path))
    dst = sqlite3.connect(str(dst_path))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    conn = sqlite3.connect(str(dst_path))
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()
    if str(result).lower() != "ok":
        raise RuntimeError(f"SQLite backup integrity_check failed: {result}")


def build_manifest(staging_dir, archive_name, data_dir, stamp):
    files = {}
    for path in sorted(staging_dir.iterdir()):
        if not path.is_file() or path.name == "manifest.json":
            continue
        files[path.name] = {
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    return {
        "kind": "live-dashboard-data-backup",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "stamp": stamp,
        "source_data_dir": str(data_dir),
        "archive_name": archive_name,
        "files": files,
    }


def create_archive(data_dir, output_dir, stamp):
    data_dir = Path(data_dir)
    output_dir = Path(output_dir)
    db_path = data_dir / "pnl.db"
    if not db_path.exists():
        raise FileNotFoundError(f"missing required database: {db_path}")

    archive_name = f"live-dashboard-data-{stamp}.tar.gz"
    archive_path = output_dir / archive_name

    with tempfile.TemporaryDirectory(prefix="live-dashboard-data-") as tmp:
        staging = Path(tmp) / "payload"
        staging.mkdir()
        sqlite_online_backup(db_path, staging / "pnl.db")
        for name in JSON_FILES:
            src = data_dir / name
            if src.exists():
                shutil.copy2(src, staging / name)

        manifest = build_manifest(staging, archive_name, data_dir, stamp)
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, "w:gz") as tar:
            for path in sorted(staging.iterdir()):
                tar.add(path, arcname=path.name)

    return archive_path


def build_remote_backup_script(remote_data_dir, stamp):
    src_expr = json.dumps(f"{remote_data_dir}/pnl.db")
    dst_expr = json.dumps(f"{remote_data_dir}/pnl.db.backup-live-data-{stamp}")
    return (
        "import sqlite3, pathlib; "
        f"src=pathlib.Path({src_expr}); "
        f"dst=pathlib.Path({dst_expr}); "
        "s=sqlite3.connect(str(src)); t=sqlite3.connect(str(dst)); "
        "s.backup(t); t.close(); s.close(); "
        "c=sqlite3.connect(str(dst)); "
        'r=c.execute("PRAGMA integrity_check").fetchone()[0]; c.close(); '
        'print(dst.name); print("integrity_check:", r); '
        'exit(1) if str(r).lower()!="ok" else None'
    )


def rsync_remote_arg(remote, path):
    return f"{remote}:{shlex.quote(str(path))}"


def pull_cloud_data_first(args, stamp, dry_run=False):
    data_dir = Path(args.data_dir)
    remote_data = args.remote_data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    print("  ☁️ 先同步云端生产数据")

    backup_script = build_remote_backup_script(remote_data, stamp)
    ssh_cmd = [
        "ssh",
        args.remote,
        f"cd {shlex.quote(args.remote_project)} && {shlex.quote(args.remote_python)} -c {shlex.quote(backup_script)}",
    ]
    if dry_run:
        common.run(ssh_cmd, dry_run=True)
        print(f"  [DRY-RUN] rsync {args.remote}:{remote_data}/pnl.db.backup-live-data-{stamp} {data_dir}/pnl.db")
        return

    backup_result = common.run(ssh_cmd, dry_run=False, check=False, capture_output=True)
    backup_out = backup_result.stdout.strip() if backup_result and backup_result.stdout else ""
    if not backup_result or backup_result.returncode != 0 or "integrity_check: ok" not in backup_out:
        err = backup_result.stderr.strip() if backup_result and backup_result.stderr else "unknown"
        raise RuntimeError(f"cloud SQLite backup failed: {err}; stdout={backup_out[:200]}")

    backup_glob = f"{shlex.quote(remote_data)}/pnl.db.backup-live-data-*"
    ls_cmd = ["ssh", args.remote, f"ls -t {backup_glob} | head -1"]
    ls_result = common.run(ls_cmd, dry_run=False, check=False, capture_output=True)
    latest = ls_result.stdout.strip() if ls_result and ls_result.stdout else ""
    if not ls_result or ls_result.returncode != 0 or not latest:
        raise RuntimeError("cloud SQLite backup exists but latest backup path was not found")

    common.run([
        "rsync", "-avz", "--backup",
        rsync_remote_arg(args.remote, latest),
        f"{data_dir / 'pnl.db'}",
    ], dry_run=False)

    json_names = " ".join(shlex.quote(name) for name in JSON_FILES)
    list_cmd = [
        "ssh",
        args.remote,
        f"cd {shlex.quote(remote_data)} && for f in {json_names}; do [ -f \"$f\" ] && printf '%s\\n' \"$f\"; done",
    ]
    list_result = common.run(list_cmd, dry_run=False, check=False, capture_output=True)
    if not list_result or list_result.returncode != 0:
        err = list_result.stderr.strip() if list_result and list_result.stderr else "unknown"
        raise RuntimeError(f"cloud JSON listing failed: {err}")
    existing_json = [
        line.strip()
        for line in ((list_result.stdout or "").splitlines() if list_result and list_result.stdout else [])
        if line.strip()
    ]
    if existing_json:
        remote_files = [rsync_remote_arg(args.remote, f"{remote_data}/{name}") for name in existing_json]
        common.run([
            "rsync", "-avz", "--backup",
            *remote_files,
            f"{data_dir}/",
        ], dry_run=False)


def upload_to_oss(archive_path, oss_python, oss_uploader, oss_prefix, dry_run=False):
    cmd = [str(oss_python), str(oss_uploader), str(archive_path), str(oss_prefix)]
    return common.run(cmd, dry_run=dry_run, check=True, capture_output=False)


def main(argv=None):
    args = parse_args(argv)
    dry_run = not args.apply
    stamp = args.stamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    archive_name = f"live-dashboard-data-{stamp}.tar.gz"
    archive_path = output_dir / archive_name

    print("=" * 60)
    print(f"{'Live Dashboard 数据备份 [DRY-RUN]' if dry_run else 'Live Dashboard 数据备份'}")
    print(f"  数据目录: {data_dir}")
    print(f"  本地备份: {archive_path}")
    print(f"  OSS 上传: {'yes' if args.upload_oss else 'no'}")

    if args.pull_cloud_first:
        pull_cloud_data_first(args, stamp, dry_run=dry_run)

    if dry_run:
        print("  [DRY-RUN] 跳过本地 tar.gz 写入")
        print(f"  将包含: pnl.db + {', '.join(JSON_FILES)}（存在才打包）")
        if args.upload_oss:
            upload_to_oss(archive_path, args.oss_python, args.oss_uploader, args.oss_prefix, dry_run=True)
        print("=" * 60)
        return archive_path

    archive_path = create_archive(data_dir, output_dir, stamp)
    size = archive_path.stat().st_size
    print(f"  ✅ 本地备份完成: {archive_path} ({size / 1024 / 1024:.2f} MB)")

    if args.upload_oss:
        print(f"  ☁️ 上传 OSS: oss://ym-mac/{args.oss_prefix}/{archive_path.name}")
        upload_to_oss(archive_path, args.oss_python, args.oss_uploader, args.oss_prefix, dry_run=False)
        print("  ✅ OSS 上传完成")

    print("=" * 60)
    print("完成")
    return archive_path


if __name__ == "__main__":
    main()
