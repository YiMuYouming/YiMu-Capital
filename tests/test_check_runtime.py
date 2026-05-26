"""test_check_runtime.py — check_runtime 采集器路径检查测试 (HM-G0-R3)

验证：
1. 默认路径时所有 6 个采集器 _load_pipeline_path() 成功
2. 显式无效 YM_DATA_PIPELINE_PATH 时返回非零
"""
import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class CheckRuntimeCollectorPathsTest(unittest.TestCase):
    """验证 _check_collector_paths 实际调用了 _load_pipeline_path()"""

    def test_default_path_all_collectors_pass(self):
        """默认路径（无 YM_DATA_PIPELINE_PATH）时所有采集器通过"""
        env = os.environ.copy()
        env.pop("YM_DATA_PIPELINE_PATH", None)
        result = subprocess.run(
            ["python3", str(ROOT / "scripts/check_runtime.py")],
            capture_output=True, text=True, timeout=30, env=env,
            cwd=str(ROOT),
        )
        output = result.stdout + result.stderr
        # 至少 quotes.py 应通过
        self.assertIn("quotes.py:", output)
        # 不应有 "_load_pipeline_path() 抛 RuntimeError"
        self.assertNotIn("_load_pipeline_path() 抛 RuntimeError", output)

    def test_invalid_env_path_returns_nonzero(self):
        """显式无效 YM_DATA_PIPELINE_PATH 时退出码非零"""
        env = os.environ.copy()
        env["YM_DATA_PIPELINE_PATH"] = "/tmp/does-not-exist-yimucodex"
        result = subprocess.run(
            ["python3", str(ROOT / "scripts/check_runtime.py")],
            capture_output=True, text=True, timeout=30, env=env,
            cwd=str(ROOT),
        )
        self.assertNotEqual(result.returncode, 0,
                            f"无效 YM_DATA_PIPELINE_PATH 应返回非零，got {result.returncode}")
        output = result.stdout + result.stderr
        self.assertIn("_load_pipeline_path() 抛 RuntimeError", output)
        # 应报告至少一个脚本失败
        self.assertIn("quotes.py", output)

    def test_invalid_env_path_exit_code_is_one(self):
        """显式无效 YM_DATA_PIPELINE_PATH 时退出码为 1"""
        env = os.environ.copy()
        env["YM_DATA_PIPELINE_PATH"] = "/tmp/does-not-exist"
        result = subprocess.run(
            ["python3", str(ROOT / "scripts/check_runtime.py")],
            capture_output=True, text=True, timeout=30, env=env,
            cwd=str(ROOT),
        )
        self.assertEqual(result.returncode, 1,
                         f"退出码应为 1，got {result.returncode}")


if __name__ == "__main__":
    unittest.main()
