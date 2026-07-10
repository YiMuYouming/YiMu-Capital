"""ops/common.py — 开/收盘脚本共享工具函数"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run(cmd, *, dry_run=False, check=True, capture_output=False):
    """执行命令。dry_run 模式下只打印不执行。
    返回 subprocess.CompletedProcess 或 None。
    """
    if dry_run:
        print(f"[DRY-RUN] {' '.join(cmd)}")
        return None
    kwargs = {"check": check}
    if capture_output:
        kwargs["capture_output"] = True
        kwargs["text"] = True
    return subprocess.run(cmd, **kwargs)


def read_baseline_summary(path):
    """读取 dashboard_data.json 基线摘要。"""
    path = Path(path)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    meta = data.get("meta", {})
    field_sources = meta.get("field_sources") or {}
    today_operations_source = field_sources.get("今日操作") or {}
    return {
        "generated_at": meta.get("updated") or meta.get("generated_at", "?"),
        "note": meta.get("note", "?"),
        "pools_note": meta.get("pools_note", "?"),
        "pools_note_date": meta.get("pools_note_date", "?"),
        "today_operations_source_date": today_operations_source.get("source_date", "?"),
        "lianban_count": len(data.get("lianban_pool", [])),
        "trend_count": len(data.get("trend_pool", [])),
    }


def sqlite_integrity(path):
    """对 SQLite 文件执行 PRAGMA integrity_check。
    返回 (ok: bool, output: str)。
    """
    path = Path(path)
    if not path.exists():
        return False, "file not found"
    try:
        r = subprocess.run(
            [sys.executable, "-c",
             f"import sqlite3; c=sqlite3.connect('{path}'); "
             f"print(c.execute('PRAGMA integrity_check').fetchone()[0]); c.close()"],
            capture_output=True, text=True, check=True,
        )
        result = r.stdout.strip()
        return result.lower() == "ok", result
    except subprocess.CalledProcessError as e:
        return False, e.stderr.strip() or str(e)


def build_ssh_command(remote, script_lines):
    """构造一条 SSH 远程执行命令。
    remote: "user@host"
    script_lines: list of str
    """
    joined = "; ".join(script_lines)
    return ["ssh", remote, joined]


def require_apply(args):
    """如果 args 没有 --apply，打印使用说明并退出。"""
    if not getattr(args, "apply", False):
        print("这是 dry-run 模式。添加 --apply 执行实际写操作。")
        sys.exit(0)
