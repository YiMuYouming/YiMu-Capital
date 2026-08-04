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
import hashlib
import json
import shlex
import subprocess
import sys
from datetime import datetime, timezone
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
AI_RULE_ROOT = Path("/Users/yimu/Documents/YM_Capital/ai-rule-system")
RULE_COMPILE_SCRIPT = AI_RULE_ROOT / "tools/compile_rules.py"
RULE_MANIFEST_SCRIPT = AI_RULE_ROOT / "tools/gen_rule_bundle_manifest.py"
RULE_CARD_SCRIPT = AI_RULE_ROOT / "tools/gen_today_execution_card.py"
RULE_ARTIFACTS = (
    ("compiled/rules.v1.json", AI_RULE_ROOT / "compiled/rules.v1.json"),
    ("daily-runtime/rule_bundle_manifest.json", AI_RULE_ROOT / "daily-runtime/rule_bundle_manifest.json"),
    ("daily-runtime/daily_plan.json", AI_RULE_ROOT / "daily-runtime/daily_plan.json"),
    ("daily-runtime/today_execution_card.json", AI_RULE_ROOT / "daily-runtime/today_execution_card.json"),
)
BASELINE_ARTIFACTS = (
    ("data/dashboard_data.json", DATA_DIR / "dashboard_data.json"),
    ("data/pools.json", DATA_DIR / "pools.json"),
)

REMOTE = "agentuser@43.132.146.234"
REMOTE_PROJECT = "/home/agentuser/YiMu-Capital"
REMOTE_DATA_DIR = f"{REMOTE_PROJECT}/data"
REMOTE_AI_RULE_ROOT = "/home/agentuser/ai-rule-system"
REMOTE_STAGE_PREFIX = f"{REMOTE_PROJECT}/.open-day-staging"


def _sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _artifact_hashes():
    artifacts = {}
    for relative, path in (*RULE_ARTIFACTS, *BASELINE_ARTIFACTS):
        if not path.is_file():
            raise FileNotFoundError(f"publication artifact missing: {path}")
        artifacts[relative] = _sha256_file(path)
    return artifacts


def _publication_metadata():
    try:
        plan = json.loads((AI_RULE_ROOT / "daily-runtime/daily_plan.json").read_text(encoding="utf-8"))
        card = json.loads((AI_RULE_ROOT / "daily-runtime/today_execution_card.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"publication metadata unreadable: {exc}") from exc
    expected_date = plan.get("valid_for_trade_date") or card.get("next_trade_date")
    card_id = card.get("today_execution_card_id")
    snapshot_hash = card.get("rule_snapshot_hash")
    if not expected_date or not card_id or not snapshot_hash:
        raise RuntimeError("publication metadata missing date/card id/snapshot hash")
    return {
        "trade_date": expected_date,
        "card_id": card_id,
        "snapshot_hash": snapshot_hash,
        "recommendation_schema": "recommendation_state.v1",
    }


def _rule_preflight_commands():
    python = sys.executable
    return [
        [python, str(RULE_COMPILE_SCRIPT), "--check"],
        [python, str(RULE_MANIFEST_SCRIPT), "--review", "latest"],
        [python, str(RULE_CARD_SCRIPT), "--review", "latest"],
        [python, str(RULE_MANIFEST_SCRIPT), "--check"],
        [python, str(RULE_CARD_SCRIPT), "--check", str(AI_RULE_ROOT / "daily-runtime/today_execution_card.json")],
    ]


def _run_rule_preflight(dry_run):
    for command in _rule_preflight_commands():
        result = run(command, dry_run=dry_run, check=False, capture_output=not dry_run)
        if not dry_run and result is not None and result.returncode != 0:
            raise RuntimeError(f"rule preflight failed: {' '.join(command)}")


def _stage_name():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{REMOTE_STAGE_PREFIX}-{stamp}"


def _rsync_stage_commands(stage_root):
    rule_sources = [str(AI_RULE_ROOT / "./" / relative) for relative, _ in RULE_ARTIFACTS]
    baseline_sources = [str(PROJECT_ROOT / "./" / relative) for relative, _ in BASELINE_ARTIFACTS]
    return [
        ["rsync", "-avz", "--backup", "--relative", *rule_sources,
         f"{REMOTE}:{stage_root}/rules/"],
        ["rsync", "-avz", "--backup", "--relative", *baseline_sources,
         f"{REMOTE}:{stage_root}/dashboard/"],
    ]


def _remote_validate(stage_root, expected_hashes, metadata):
    remote_paths = [
        (f"rules/{relative}", f"{stage_root}/rules/{relative}")
        for relative, _ in RULE_ARTIFACTS
    ] + [
        (relative, f"{stage_root}/dashboard/{relative}")
        for relative, _ in BASELINE_ARTIFACTS
    ]
    hash_lines = " ".join(shlex.quote(path) for _, path in remote_paths)
    plan_path = f"{stage_root}/rules/daily-runtime/daily_plan.json"
    card_path = f"{stage_root}/rules/daily-runtime/today_execution_card.json"
    script = (
        f"set -eu; sha256sum {hash_lines}; "
        "python3 -c "
        + shlex.quote(
            "import json; "
            f"p=json.load(open({plan_path!r})); "
            f"c=json.load(open({card_path!r})); "
            "print('PLAN_DATE '+str(p.get('valid_for_trade_date',''))); "
            "print('CARD_DATE '+str(c.get('next_trade_date',''))); "
            "print('CARD_ID '+str(c.get('today_execution_card_id',''))); "
            "print('SNAPSHOT_HASH '+str(c.get('rule_snapshot_hash',''))); "
            "print('RECOMMENDATION_SCHEMA recommendation_state.v1')"
        )
    )
    result = run(["ssh", REMOTE, script], dry_run=False, check=False, capture_output=True)
    if result is None or result.returncode != 0:
        return {"ok": False, "reason": "REMOTE_READBACK_FAILED"}
    output = result.stdout or ""
    if isinstance(output, bytes):
        output = output.decode("utf-8", errors="replace")
    actual_hashes = {}
    for line in str(output).splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or len(parts[0]) != 64:
            continue
        remote_path = parts[1].lstrip("*")
        relative = remote_path.split(f"{stage_root}/", 1)[-1]
        actual_hashes[relative] = parts[0]
    for relative, expected in expected_hashes.items():
        remote_key = (
            f"rules/{relative}"
            if relative in {item[0] for item in RULE_ARTIFACTS}
            else f"dashboard/{relative}"
        )
        if actual_hashes.get(remote_key) != expected:
            return {
                "ok": False,
                "reason": "REMOTE_HASH_MISMATCH",
                "path": relative,
                "expected": expected,
                "actual": actual_hashes.get(remote_key),
            }
    markers = {}
    for line in str(output).splitlines():
        if " " in line:
            key, value = line.split(" ", 1)
            if key in {"PLAN_DATE", "CARD_DATE", "CARD_ID", "SNAPSHOT_HASH", "RECOMMENDATION_SCHEMA"}:
                markers[key] = value.strip()
    expected_markers = {
        "PLAN_DATE": metadata["trade_date"],
        "CARD_DATE": metadata["trade_date"],
        "CARD_ID": metadata["card_id"],
        "SNAPSHOT_HASH": metadata["snapshot_hash"],
        "RECOMMENDATION_SCHEMA": metadata["recommendation_schema"],
    }
    for key, expected in expected_markers.items():
        if markers.get(key) != expected:
            return {"ok": False, "reason": "REMOTE_DATE_OR_CONTRACT_MISMATCH", "field": key}
    return {"ok": True, "hashes": actual_hashes, "markers": markers}


def _atomic_rename(stage_root):
    commands = [
        f"set -eu; mkdir -p {shlex.quote(REMOTE_AI_RULE_ROOT + '/compiled')} "
        f"{shlex.quote(REMOTE_AI_RULE_ROOT + '/daily-runtime')} "
        f"{shlex.quote(REMOTE_DATA_DIR)}; "
        f"mv {shlex.quote(stage_root + '/rules/compiled/rules.v1.json')} "
        f"{shlex.quote(REMOTE_AI_RULE_ROOT + '/compiled/rules.v1.json')}; "
        f"mv {shlex.quote(stage_root + '/rules/daily-runtime/rule_bundle_manifest.json')} "
        f"{shlex.quote(REMOTE_AI_RULE_ROOT + '/daily-runtime/rule_bundle_manifest.json')}; "
        f"mv {shlex.quote(stage_root + '/rules/daily-runtime/daily_plan.json')} "
        f"{shlex.quote(REMOTE_AI_RULE_ROOT + '/daily-runtime/daily_plan.json')}; "
        f"mv {shlex.quote(stage_root + '/rules/daily-runtime/today_execution_card.json')} "
        f"{shlex.quote(REMOTE_AI_RULE_ROOT + '/daily-runtime/today_execution_card.json')}; "
        f"mv {shlex.quote(stage_root + '/dashboard/data/dashboard_data.json')} "
        f"{shlex.quote(REMOTE_DATA_DIR + '/dashboard_data.json')}; "
        f"mv {shlex.quote(stage_root + '/dashboard/data/pools.json')} "
        f"{shlex.quote(REMOTE_DATA_DIR + '/pools.json')}"
    ]
    return run(["ssh", REMOTE, commands[0]], dry_run=False, check=True)


def _api_readback(metadata):
    endpoints = {
        "baseline": "/api/baseline",
        "context": "/api/ai/context",
    }
    payloads = {}
    for name, path in endpoints.items():
        result = run(
            ["curl", "-s", "--max-time", "5", f"http://127.0.0.1:8088{path}"],
            dry_run=False,
            check=False,
            capture_output=True,
        )
        if result is None or result.returncode != 0:
            return {"ok": False, "reason": f"API_READBACK_FAILED:{name}"}
        output = result.stdout or ""
        try:
            payloads[name] = json.loads(output)
        except (TypeError, json.JSONDecodeError):
            return {"ok": False, "reason": f"API_READBACK_JSON_INVALID:{name}"}
    baseline = payloads["baseline"]
    context = payloads["context"]
    baseline_date = ((baseline.get("meta") or {}).get("date") or baseline.get("date"))
    rule_state = context.get("rule_state") or {}
    if baseline_date != metadata["trade_date"]:
        return {"ok": False, "reason": "API_BASELINE_DATE_MISMATCH", "actual": baseline_date}
    if context.get("date") not in {None, metadata["trade_date"]}:
        return {"ok": False, "reason": "API_CONTEXT_DATE_MISMATCH", "actual": context.get("date")}
    if rule_state.get("today_execution_card_id") != metadata["card_id"]:
        return {"ok": False, "reason": "API_CARD_ID_MISMATCH"}
    if rule_state.get("rule_snapshot_hash") != metadata["snapshot_hash"]:
        return {"ok": False, "reason": "API_SNAPSHOT_HASH_MISMATCH"}
    if (context.get("recommendation_state") or {}).get("schema_version") != metadata["recommendation_schema"]:
        return {"ok": False, "reason": "API_RECOMMENDATION_SCHEMA_MISMATCH"}
    return {"ok": True, "payloads": payloads}


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
    stage_root = _stage_name()

    print("=" * 60)
    print(f"{'开盘自动化 [DRY-RUN]' if dry_run else '开盘自动化'}")
    print(f"  本地项目: {PROJECT_ROOT}")
    print(f"  云端规则包: {REMOTE}:{REMOTE_AI_RULE_ROOT}")
    print(f"  云端数据: {REMOTE}:{REMOTE_DATA_DIR}")
    print(f"  远程主机: {REMOTE}")
    print()

    # 1. 规则包和日计划预检
    print("[STEP 1] 规则包/日计划预检")
    try:
        _run_rule_preflight(dry_run)
    except (OSError, RuntimeError) as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)
    if dry_run:
        print("  [DRY-RUN] 规则包预检命令已列出")
    else:
        print("  ✅ 规则包与日计划预检完成")

    # 2. 检查 baseline 生成脚本并生成
    if not GEN_SCRIPT.exists():
        print(f"[ERROR] gen_dashboard_data.py 不存在: {GEN_SCRIPT}")
        sys.exit(1)
    print(f"[STEP 2] 生成基线: {GEN_SCRIPT.name}")

    if dry_run:
        print("  [DRY-RUN] 跳过生成")
        print("  命令: python3", GEN_SCRIPT)
    else:
        r = run([sys.executable, str(GEN_SCRIPT)], dry_run=False, check=False)
        if r and r.returncode != 0:
            print(f"[ERROR] 基线生成失败 (exit={r.returncode})")
            sys.exit(1)
        print("  ✅ 基线生成完成")

    # 3. 基线摘要
    print()
    print(f"[STEP 3] 基线摘要: {BASELINE_PATH.name}")
    if dry_run and not BASELINE_PATH.exists():
        print("  [DRY-RUN] 基线文件尚未生成（跳过）")
    else:
        print_baseline_summary(args.baseline)

    # 4. staged rsync，hash/date readback，再原子 rename
    print()
    print("[STEP 4] staged 发布与远端 hash/date 回读")
    for relative, path in (*RULE_ARTIFACTS, *BASELINE_ARTIFACTS):
        print(f"  {relative}: {'存在' if path.is_file() else '不存在'}")
    print(f"  临时目录: {REMOTE}:{stage_root}")

    if dry_run:
        for command in _rsync_stage_commands(stage_root):
            print("  [DRY-RUN]", shlex.join(command))
        print("  [DRY-RUN] remote sha256/date/API readback and atomic rename skipped")
    else:
        try:
            expected_hashes = _artifact_hashes()
            metadata = _publication_metadata()
        except (OSError, RuntimeError) as exc:
            print(f"[ERROR] 发布 artifact 不完整: {exc}")
            sys.exit(1)
        for command in _rsync_stage_commands(stage_root):
            result = run(command, dry_run=False, check=False)
            if result is not None and result.returncode != 0:
                print(f"[ERROR] staged rsync 失败 (exit={result.returncode})")
                sys.exit(1)
        validation = _remote_validate(stage_root, expected_hashes, metadata)
        if not validation.get("ok"):
            print(f"[ERROR] 远端 staged readback 失败: {validation}")
            sys.exit(1)
        print("  ✅ 远端 hash/date/contract 回读通过")
        _atomic_rename(stage_root)
        print("  ✅ 规则包与 baseline 已原子切换")

    # 5. 可选重启云端（仅在远端 readback + atomic rename 后）
    if args.restart_cloud:
        print()
        print("[STEP 5] 重启云端服务")
        if not dry_run:
            restart_cmd = [
                "ssh", REMOTE,
                "sudo systemctl restart yimu-live-dashboard.service",
            ]
            result = run(restart_cmd, dry_run=False, check=False)
            if result is not None and result.returncode != 0:
                print(f"[ERROR] 服务重启失败 (exit={result.returncode})")
                sys.exit(1)
            print("  ✅ 服务已重启")
        else:
            print("  [DRY-RUN] 跳过重启")
            print(f"  ssh {REMOTE} 'sudo systemctl restart yimu-live-dashboard.service'")

    # 6. 只读 API 验收（仅 apply 模式）
    if not dry_run:
        readback = _api_readback(metadata)
        if not readback.get("ok"):
            print(f"[ERROR] API 只读回读失败: {readback}")
            sys.exit(1)
        print("  ✅ GET /api/baseline 与 GET /api/ai/context 回读通过")
    else:
        print()
        print("[STEP 6] 验收命令（apply 后执行）:")
        for url_path in ["/api/baseline", "/api/ai/context"]:
            print(f"  curl -s http://127.0.0.1:8088{url_path} | python3 -m json.tool | head -40")

    print()
    print("=" * 60)
    print("完成" if not dry_run else "[DRY-RUN] 未执行任何写操作")


if __name__ == "__main__":
    main()
