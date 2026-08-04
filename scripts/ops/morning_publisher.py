#!/usr/bin/env python3
"""Fail-safe pre-market publisher for the daily open-day baseline.

The LaunchAgent may wake this script on non-trading days or outside the
window.  Those invocations are intentional no-ops.  Only a trading day in
Asia/Shanghai between 08:50 and 09:20 can reach ``open_day.py --apply``.
"""

import argparse
import fcntl
import json
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.db import is_trading_day


PYTHON = "/opt/homebrew/bin/python3"
OPEN_DAY_SCRIPT = PROJECT_ROOT / "scripts" / "ops" / "open_day.py"
REMOTE = "agentuser@43.132.146.234"
CONTEXT_URL = "http://127.0.0.1:8088/api/ai/context"
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
WINDOW_START = time(8, 50)
WINDOW_END = time(9, 20)
LOCK_PATH = Path.home() / "Library" / "Logs" / "yimu-open-day.lock"


@dataclass(frozen=True)
class RunResult:
    status: str
    exit_code: int
    detail: str = ""


def _local_now(now=None):
    if now is None:
        return datetime.now(LOCAL_TZ)
    if now.tzinfo is None:
        return now.replace(tzinfo=LOCAL_TZ)
    return now.astimezone(LOCAL_TZ)


def _in_window(now):
    current = now.timetz().replace(tzinfo=None)
    return WINDOW_START <= current <= WINDOW_END


@contextmanager
def acquire_lock(lock_path=LOCK_PATH):
    """Acquire a process-wide, non-blocking advisory lock."""
    path = Path(lock_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    acquired = False
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            pass
        yield acquired
    finally:
        if acquired:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _context_command():
    return [
        "ssh",
        "-o",
        "ConnectTimeout=10",
        REMOTE,
        f"curl -fsS --max-time 5 {CONTEXT_URL}",
    ]


def _read_context():
    try:
        result = subprocess.run(
            _context_command(),
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, type(exc).__name__
    if result.returncode != 0:
        return None, f"exit={result.returncode}"
    try:
        payload = json.loads(result.stdout or "")
    except (TypeError, json.JSONDecodeError):
        return None, "invalid_json"
    if not isinstance(payload, dict):
        return None, "invalid_payload"
    return payload, ""


def _is_current(context, today):
    rule_state = (context or {}).get("rule_state") or {}
    return (
        (context or {}).get("date") == today
        and rule_state.get("execution_plan_valid") is True
    )


def _apply_open_day():
    command = [
        PYTHON,
        str(OPEN_DAY_SCRIPT),
        "--apply",
        "--restart-cloud",
    ]
    try:
        return subprocess.run(command, cwd=str(PROJECT_ROOT), check=False)
    except (OSError, subprocess.SubprocessError):
        return None


def run_once(now=None, *, lock_path=LOCK_PATH, dry_run=False):
    """Run one guarded morning attempt and return an auditable result."""
    current = _local_now(now)
    today = current.date().isoformat()

    if not is_trading_day(today):
        return RunResult("skip_non_trading_day", 0, today)
    if not _in_window(current):
        return RunResult("skip_outside_window", 0, current.isoformat())

    try:
        with acquire_lock(lock_path) as acquired:
            if not acquired:
                return RunResult("skip_lock", 0)
            if dry_run:
                return RunResult("dry_run", 0, today)

            context, initial_detail = _read_context()
            if _is_current(context, today):
                return RunResult("skip_current", 0, today)

            applied = _apply_open_day()
            if applied is None or applied.returncode != 0:
                detail = initial_detail or (
                    f"exit={applied.returncode}" if applied is not None else "spawn_failed"
                )
                return RunResult("apply_failed", 1, detail)

            final_context, final_detail = _read_context()
            if not _is_current(final_context, today):
                return RunResult("verification_failed", 1, final_detail or "not_current")
            return RunResult("applied", 0, today)
    except OSError as exc:
        return RunResult("lock_failed", 1, type(exc).__name__)


def main(argv=None):
    parser = argparse.ArgumentParser(description="安全的交易日开盘基线发布器")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只检查交易日/时段/锁，不读取远端或执行 apply",
    )
    args = parser.parse_args(argv)
    result = run_once(dry_run=args.dry_run)
    print(f"morning_publisher status={result.status} detail={result.detail}")
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
