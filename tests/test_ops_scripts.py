"""test_ops_scripts.py — 开/收盘脚本 RED/GREEN 测试"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

from scripts.ops import common


# ── helpers ──────────────────────────────────────────────

def _make_fixture_baseline(overrides=None):
    """生成 fixture dashboard_data.json 数据"""
    d = {
        "meta": {
            "updated": "2026-05-28T08:00:00+08:00",
            "generated_at": "2026-05-28T08:00:00+08:00",
            "note": "自动生成自 2026_5_27_Wednesday_ReviewNote.md",
            "pools_note": "2026-05-27 收盘自选池",
            "pools_note_date": "2026-05-27",
        },
        "lianban_pool": [{"标的": "华天科技"}],
        "trend_pool": [{"标的": "紫光国微"}, {"标的": "兴森科技"}],
    }
    if overrides:
        d.update(overrides)
    return d


# ── common.py tests ──────────────────────────────────────


class CommonTests(unittest.TestCase):

    def test_read_baseline_summary_returns_none_when_missing(self):
        result = common.read_baseline_summary("/nonexistent/path.json")
        self.assertIsNone(result)

    def test_read_baseline_summary_parses_correctly(self):
        data = _make_fixture_baseline()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False,
                                         encoding="utf-8") as f:
            json.dump(data, f)
            p = f.name
        try:
            summary = common.read_baseline_summary(p)
            self.assertEqual(summary["generated_at"], "2026-05-28T08:00:00+08:00")
            self.assertEqual(summary["note"], "自动生成自 2026_5_27_Wednesday_ReviewNote.md")
            self.assertEqual(summary["pools_note"], "2026-05-27 收盘自选池")
            self.assertEqual(summary["lianban_count"], 1)
            self.assertEqual(summary["trend_count"], 2)
        finally:
            Path(p).unlink(missing_ok=True)

    def test_run_dry_does_not_execute(self):
        with patch("scripts.ops.common.subprocess.run") as mock_run:
            r = common.run(["echo", "hello"], dry_run=True)
        mock_run.assert_not_called()
        self.assertIsNone(r)

    def test_run_apply_calls_subprocess(self):
        with patch("scripts.ops.common.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(["echo"], 0, b"", b"")
            r = common.run(["echo", "hello"], dry_run=False)
        mock_run.assert_called_once_with(["echo", "hello"], check=True)
        self.assertIsNotNone(r)

    def test_require_apply_exits_when_no_apply(self):
        args = MagicMock(apply=False)
        with self.assertRaises(SystemExit) as ctx:
            common.require_apply(args)
        self.assertEqual(ctx.exception.code, 0)

    def test_require_apply_passes_when_apply(self):
        args = MagicMock(apply=True)
        common.require_apply(args)  # should not raise

    def test_sqlite_integrity_handles_missing_file(self):
        ok, msg = common.sqlite_integrity("/nonexistent/path.db")
        self.assertFalse(ok)
        self.assertIn("not found", msg)

    def test_build_ssh_command(self):
        cmd = common.build_ssh_command("user@host", ["echo 1", "echo 2"])
        self.assertEqual(cmd, ["ssh", "user@host", "echo 1; echo 2"])


# ── open_day.py tests ────────────────────────────────────


class OpenDayDryRunTests(unittest.TestCase):

    def setUp(self):
        self.fixture_data = _make_fixture_baseline()
        self.baseline = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(self.fixture_data, self.baseline)
        self.baseline_path = self.baseline.name
        self.baseline.close()

    def tearDown(self):
        Path(self.baseline_path).unlink(missing_ok=True)

    def test_dry_run_does_not_call_gen_or_rsync(self):
        """open_day.py --dry-run 不应调用 gen_dashboard_data 或 rsync"""
        from scripts.ops import open_day
        with patch("scripts.ops.common.subprocess.run") as mock_run:
            with patch("scripts.ops.open_day.argparse.ArgumentParser.parse_args") as mock_args:
                mock_args.return_value = MagicMock(
                    dry_run=True, apply=False, restart_cloud=False,
                    baseline=self.baseline_path,
                )
                open_day.main()
        mock_run.assert_not_called()

    def test_apply_calls_gen_and_rsync(self):
        """open_day.py --apply 应调用 gen 和 rsync"""
        from scripts.ops import open_day
        with patch("scripts.ops.common.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(["true"], 0, "", "")
            with patch("scripts.ops.open_day.argparse.ArgumentParser.parse_args") as mock_args:
                mock_args.return_value = MagicMock(
                    dry_run=False, apply=True, restart_cloud=False,
                    baseline=self.baseline_path,
                )
                open_day.main()
        self.assertGreaterEqual(mock_run.call_count, 2)
        # 验证命令包含 gen/rsync
        all_cmds = [str(c[0][0]) for c in mock_run.call_args_list]
        gen_found = any("gen_dashboard_data" in c for c in all_cmds)
        rsync_found = any("rsync" in c for c in all_cmds)
        self.assertTrue(gen_found, "应调用 gen_dashboard_data.py")
        self.assertTrue(rsync_found, "应调用 rsync")

    def test_restart_cloud_triggers_ssh_restart(self):
        """--apply --restart-cloud 应额外调用 ssh restart"""
        from scripts.ops import open_day
        with patch("scripts.ops.common.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(["true"], 0, "", "")
            with patch("scripts.ops.open_day.argparse.ArgumentParser.parse_args") as mock_args:
                mock_args.return_value = MagicMock(
                    dry_run=False, apply=True, restart_cloud=True,
                    baseline=self.baseline_path,
                )
                open_day.main()
        restart_calls = [
            c for c in mock_run.call_args_list
            if "restart" in str(c)
        ]
        self.assertGreaterEqual(len(restart_calls), 1, "应含 restart 命令")


# ── close_day.py tests ───────────────────────────────────


class CloseDayDryRunTests(unittest.TestCase):

    def test_dry_run_does_not_call_ssh_or_rsync(self):
        """close_day.py --dry-run 不应调用 ssh/rsync 写入"""
        from scripts.ops import close_day
        with patch("scripts.ops.common.subprocess.run") as mock_run:
            with patch("scripts.ops.close_day.argparse.ArgumentParser.parse_args") as mock_args:
                mock_args.return_value = MagicMock(
                    dry_run=True, apply=False,
                    remote_data_dir="/home/agentuser/YiMu-Capital/data",
                    local_data_dir="/tmp",
                )
                close_day.main()
        mock_run.assert_not_called()

    def test_apply_calls_sqlite_backup_sync_and_integrity(self):
        """close_day.py --apply 调用 ssh backup + rsync + integrity，全部 mock"""
        from scripts.ops import close_day

        backup_stdout = "pnl.db.backup-close-20260528-150530\nintegrity_check: ok\n"
        ls_stdout = "data/pnl.db.backup-close-20260528-150530\n"
        integrity_ok = "ok\n"

        call_count = 0
        commands_seen = []

        def fake_run(cmd, **kw):
            nonlocal call_count
            call_count += 1
            cmd_str = str(cmd)
            commands_seen.append(cmd_str)
            if "ls -t" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, ls_stdout, "")
            if "ssh" in cmd_str and "integrity_check" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, backup_stdout, "")
            if "PRAGMA integrity_check" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, integrity_ok, "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch("scripts.ops.common.subprocess.run", side_effect=fake_run):
            with patch("scripts.ops.close_day.argparse.ArgumentParser.parse_args") as mock_args:
                tmpdir = Path(tempfile.mkdtemp())
                real_db = tmpdir / "pnl.db"
                import sqlite3
                con = sqlite3.connect(str(real_db))
                con.execute("CREATE TABLE t (x)")
                con.close()
                mock_args.return_value = MagicMock(
                    dry_run=False, apply=True,
                    remote_data_dir="/home/agentuser/YiMu-Capital/data",
                    local_data_dir=str(tmpdir),
                )
                close_day.main()
        self.assertGreaterEqual(call_count, 1)
        all_cmds = " ".join(commands_seen)
        self.assertIn("ssh", all_cmds, "应调 ssh backup")
        self.assertIn("rsync", all_cmds, "应调 rsync")
        self.assertIn("integrity_check", all_cmds, "应调 integrity check")


# ── entry ─────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main()
