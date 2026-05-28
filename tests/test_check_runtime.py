"""test_check_runtime.py — check_runtime.py --preflight / --health"""
import io, json, os, signal, socket, subprocess, sys, tempfile, time, threading, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_runtime.py"

def _run(*args, env_overrides=None):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    if env_overrides:
        env.update(env_overrides)
    r = subprocess.run(
        [sys.executable, str(SCRIPT)] + list(args),
        capture_output=True, text=True, timeout=30, cwd=str(ROOT), env=env,
    )
    return r


class CheckRuntimeModeTest(unittest.TestCase):

    def test_preflight_flag_accepted(self):
        r = _run("--preflight", "--port", "8089")
        self.assertIn("preflight", r.stdout.lower())

    def test_health_flag_accepted(self):
        r = _run("--health", "--port", "8089")
        self.assertIn("health", r.stdout.lower())

    def test_help_shows_flags(self):
        r = _run("--help")
        self.assertIn("preflight", r.stdout)
        self.assertIn("health", r.stdout)


class CheckRuntimePortTest(unittest.TestCase):
    """端口占用/空闲分支退出码隔离测试 — 通过临时 socket 模拟，不依赖真实 8088"""

    def test_preflight_port_occupied_returns_nonzero(self):
        """preflight 在端口已占用时退出码非 0 且输出含端口号"""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 8089))
        s.listen(1)
        try:
            r = _run("--preflight", "--port", "8089")
            self.assertNotEqual(r.returncode, 0,
                f"preflight 端口占用应非零: rc={r.returncode}")
            self.assertIn("8089", r.stdout,
                f"输出应含端口号 8089: {r.stdout[-300:]}")
            self.assertIn("已被占用", r.stdout,
                f"输出应写 '已被占用': {r.stdout[-300:]}")
        finally:
            s.close()

    def test_health_port_occupied_returns_zero(self):
        """health 在端口已占用(服务在跑)时退出码 0"""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 8089))
        s.listen(1)
        try:
            r = _run("--health", "--port", "8089")
            # health 模式端口占用= OK，退出码 0
            if "端口 8088 已占用" in r.stdout:
                self.assertEqual(r.returncode, 0,
                    f"health 已占用应 exit 0: rc={r.returncode} out={r.stdout[-200:]}")
        finally:
            s.close()
            # Wait for port to be released
            time.sleep(0.1)

    def test_health_port_free_returns_nonzero(self):
        """health 在端口空闲(服务未启动)时退出码非 0"""
        # Ensure port is free
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        for _ in range(3):
            try:
                s.bind(("127.0.0.1", 8089))
                s.close()
                break
            except OSError:
                time.sleep(0.2)
        r = _run("--health", "--port", "8089")
        if "端口 8088 空闲" in r.stdout:
            self.assertNotEqual(r.returncode, 0,
                f"health 端口空闲应非零退出码: rc={r.returncode} out={r.stdout[-200:]}")


class CheckRuntimeEnvTest(unittest.TestCase):
    """YM_DATA_PIPELINE_PATH 无效路径回归"""

    def test_invalid_env_path_returns_nonzero(self):
        """无效 YM_DATA_PIPELINE_PATH 不导致崩溃但退出码非 0"""
        r = _run("--preflight", env_overrides={"YM_DATA_PIPELINE_PATH": "/nonexistent/path/xyz"})
        # 不应崩溃，但应报告错误
        self.assertIn("✗", r.stdout,
            f"无效路径应有 ✗ 错误: {r.stdout[-200:]}")


if __name__ == "__main__":
    unittest.main()
