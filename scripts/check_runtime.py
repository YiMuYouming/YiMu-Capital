#!/usr/bin/env python3
"""check_runtime.py — 运行环境健康检查

检查内容：
  1. Python 包是否可导入
  2. 必要数据文件是否可读
  3. SQLite PRAGMA integrity_check
  4. 目标端口（8088）是否被占用
  5. LLM API 配置是否存在（只报告 token 存在性，绝不输出 token 值）

退出码：0=全部正常，非0=有缺失项
"""

import ast
import json
import os
import sqlite3
import subprocess
import sys
import socket
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

EXIT_CODE = 0
TARGET_PORT = 8088


def _err(msg):
    global EXIT_CODE
    print(f"  ✗ {msg}")
    EXIT_CODE = 1


def _ok(msg):
    print(f"  ✓ {msg}")


def _check(name, fn):
    print(f"\n[{name}]")
    try:
        fn()
    except Exception as e:
        _err(f"检查异常: {e}")


# ── 1. Python 包 ──────────────────────────────────────────────────────────────
def _check_packages():
    required = {
        "apscheduler": "apscheduler",
        "filelock": "filelock",
    }
    missing = []
    for label, module in required.items():
        try:
            __import__(module)
            _ok(f"{label} 可导入")
        except ImportError:
            _err(f"{label} 缺失 — 运行: pip install {module}")
            missing.append(label)

    # pytest 暂非必须（测试套件使用 unittest）
    try:
        __import__("pytest")
        _ok("pytest 可导入")
    except ImportError:
        _ok("pytest 未安装（测试套件使用 unittest）")

    # ym_stock_data — 检查两种安装方式
    ym_ok = False
    try:
        sys.path.insert(0, str(ROOT))
        import ym_stock_data
        _ok("ym_stock_data 可导入")
        ym_ok = True
    except ImportError:
        # 检查 YM_DATA_PIPELINE_PATH 环境变量
        env_path = os.environ.get("YM_DATA_PIPELINE_PATH", "")
        if env_path and Path(env_path).exists():
            try:
                sys.path.insert(0, env_path)
                import ym_stock_data
                _ok(f"ym_stock_data 通过 YM_DATA_PIPELINE_PATH 可导入 ({env_path})")
                ym_ok = True
            except ImportError:
                _err(f"ym_stock_data 导入失败（YM_DATA_PIPELINE_PATH={env_path}）")
        else:
            if not env_path:
                _err(
                    "ym_stock_data 未安装 — "
                    "cd ~/Documents/YM_Capital/YM-data-pipeline && pip install -e ."
                )
            else:
                _err(
                    f"ym_stock_data 导入失败（YM_DATA_PIPELINE_PATH='{env_path}' 不存在）"
                )


# ── 2. 数据文件可读性 ────────────────────────────────────────────────────────
def _check_data_files():
    required_files = [
        DATA_DIR / "dashboard_data.json",
        DATA_DIR / "pnl_history.json",
    ]
    optional_files = [
        DATA_DIR / "pnl.db",
        DATA_DIR / "auction_snapshot.json",
        DATA_DIR / "sentiment_auto.json",
    ]
    for f in required_files:
        if f.exists():
            try:
                with open(f, encoding="utf-8") as fh:
                    fh.read(10)
                _ok(f"{f.name} 可读")
            except Exception as e:
                _err(f"{f.name} 存在但读取失败: {e}")
        else:
            _err(f"{f.name} 不存在（运行 gen_dashboard_data.py）")

    for f in optional_files:
        if f.exists():
            # .db 文件是二进制 SQLite，跳过文本读，由 PRAGMA integrity_check 验证
            if f.suffix in ('.db', '.db-wal', '.db-shm'):
                _ok(f"{f.name} 存在（SQLite，二进制格式，由 PRAGMA 验证）")
            else:
                try:
                    with open(f, encoding="utf-8") as fh:
                        fh.read(10)
                    _ok(f"{f.name} 可读（可选）")
                except Exception as e:
                    _err(f"{f.name} 存在但读取失败: {e}")


# ── 3. SQLite PRAGMA integrity_check ─────────────────────────────────────────
def _check_sqlite():
    db_file = DATA_DIR / "pnl.db"
    if not db_file.exists():
        _err(f"pnl.db 不存在 — 跳过 SQLite 检查")
        return

    try:
        conn = sqlite3.connect(str(db_file))
        cur = conn.cursor()
        result = cur.execute("PRAGMA integrity_check").fetchone()[0]
        journal = cur.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        if result == "ok":
            _ok(f"pnl.db integrity_check=ok, journal_mode={journal}")
        else:
            _err(f"pnl.db integrity_check={result}（预期 ok）")
    except Exception as e:
        _err(f"pnl.db 检查失败: {e}")


# ── 4. 端口占用 ──────────────────────────────────────────────────────────────
def _check_port():
    port = TARGET_PORT
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    try:
        result = sock.connect_ex(("127.0.0.1", port))
        sock.close()
        if result == 0:
            _err(f"端口 {port} 已被占用（8088 正在运行）")
        else:
            _ok(f"端口 {port} 空闲")
    except Exception as e:
        _err(f"端口 {port} 检查异常: {e}")


# ── 5. LLM API 配置 ──────────────────────────────────────────────────────────
def _check_llm_config():
    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        _err(f"~/.claude/settings.json 不存在 — LLM 研判不可用")
        return

    try:
        with open(settings_path) as f:
            s = json.load(f)
        env = s.get("env", {})

        base_url = bool(env.get("ANTHROPIC_BASE_URL", "").strip())
        token_exists = bool(env.get("ANTHROPIC_AUTH_TOKEN", "").strip())
        model = env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL", "")

        if base_url:
            _ok("ANTHROPIC_BASE_URL 已配置")
        else:
            _err("ANTHROPIC_BASE_URL 为空")

        if token_exists:
            _ok("ANTHROPIC_AUTH_TOKEN 存在（已脱敏）")
        else:
            _err("ANTHROPIC_AUTH_TOKEN 为空或不存在")

        if model:
            _ok(f"LLM 模型: {model}")
        else:
            _err("ANTHROPIC_DEFAULT_HAIKU_MODEL 未配置")
    except Exception as e:
        _err(f"~/.claude/settings.json 读取失败: {e}")


# ── 6. ym_stock_data 采集器路径检查 ────────────────────────────────────────
def _check_collector_paths():
    """使用 importlib 实际加载每个采集脚本的 _load_pipeline_path()，
    验证返回路径存在且 ym_stock_data 可导入。"""
    import importlib.util

    collector_modules = {
        "quotes.py":           "scripts.collectors.quotes",
        "iwencai_poll.py":    "scripts.collectors.iwencai_poll",
        "market_data.py":      "scripts.collectors.market_data",
        "snapshot_auction.py": "scripts.snapshot_auction",
        "style_detect.py":     "scripts.style_detect",
        "poll_iwencai.py":   "scripts.poll_iwencai",
    }

    for name, module_path in collector_modules.items():
        try:
            mod = importlib.import_module(module_path)
        except Exception as e:
            _err(f"{name}: importlib 加载失败 ({e})")
            continue

        load_fn = getattr(mod, "_load_pipeline_path", None)
        if load_fn is None:
            _err(f"{name}: 缺少 _load_pipeline_path() 函数")
            continue

        try:
            resolved = load_fn()
        except RuntimeError as e:
            _err(f"{name}: _load_pipeline_path() 抛 RuntimeError — {e}")
            continue
        except Exception as e:
            _err(f"{name}: _load_pipeline_path() 异常 — {e}")
            continue

        if not resolved or not resolved.exists():
            _err(f"{name}: _load_pipeline_path() 返回路径不存在 ({resolved})")
            continue

        # 验证从解析路径可导入 ym_stock_data
        old_path = sys.path[:]
        sys.path.insert(0, str(resolved))
        try:
            import ym_stock_data
            _ok(f"{name}: {resolved}")
        except ImportError:
            _err(f"{name}: 路径 {resolved} 存在但 ym_stock_data 不可导入")
        finally:
            sys.path[:] = old_path


def main():
    import argparse
    parser = argparse.ArgumentParser(description="live-dashboard 运行环境检查")
    parser.add_argument("--preflight", action="store_true", help="启动前完整检查（含端口冲突检测）")
    parser.add_argument("--health", action="store_true", help="只读健康检查（端口占用视为正常，服务在跑即可）")
    parser.add_argument("--port", type=int, default=8088, help="检查的目标端口（默认 8088）")
    args = parser.parse_args()
    global TARGET_PORT
    TARGET_PORT = args.port

    # 默认 preflight
    mode = "preflight"
    if args.health:
        mode = "health"

    label = "启动前检查" if mode == "preflight" else "运行中健康检查"
    print("=" * 60)
    print(f"弈沐资本数据看板 — {label} ({mode})")
    print("=" * 60)

    if mode == "health":
        global _check_port
        def _check_port_health():
            port = TARGET_PORT
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            try:
                result = sock.connect_ex(("127.0.0.1", port))
                sock.close()
                if result == 0:
                    _ok(f"端口 {port} 已占用（服务运行中 ✓）")
                else:
                    _err(f"端口 {port} 空闲（服务未启动）")
            except Exception as e:
                _err(f"端口 {port} 检查异常: {e}")
        _check_port_fn = _check_port_health
    else:
        _check_port_fn = _check_port

    checks = [
        ("Python 包", _check_packages),
        ("数据文件", _check_data_files),
        ("SQLite 数据库", _check_sqlite),
        ("端口 8088", _check_port_fn),
        ("LLM API 配置", _check_llm_config),
        ("采集器路径", _check_collector_paths),
    ]

    for name, fn in checks:
        _check(name, fn)

    print("\n" + "=" * 60)
    if EXIT_CODE == 0:
        print("✅ 全部检查通过")
    else:
        print("⚠️  有缺失项（见上方 ✗ 行）")
    print("=" * 60)

    sys.exit(EXIT_CODE)


if __name__ == "__main__":
    main()
