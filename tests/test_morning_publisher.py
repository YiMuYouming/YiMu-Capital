import json
import plistlib
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

try:
    from scripts.ops import morning_publisher
except (ImportError, ModuleNotFoundError):
    morning_publisher = None


ROOT = Path(__file__).resolve().parents[1]
PLIST_TEMPLATE = ROOT / "launchd" / "com.yimu.open-day.plist"
INSTALLER = ROOT / "scripts" / "ops" / "install_open_day_launchagent.sh"
SHANGHAI = timezone(timedelta(hours=8))


def _now(hour, minute):
    return datetime(2026, 8, 5, hour, minute, tzinfo=SHANGHAI)


def _context(date, execution_plan_valid):
    return {
        "date": date,
        "rule_state": {"execution_plan_valid": execution_plan_valid},
    }


def _completed(cmd, payload=None, returncode=0):
    stdout = "" if payload is None else json.dumps(payload)
    return subprocess.CompletedProcess(cmd, returncode, stdout, "")


class MorningPublisherTests(unittest.TestCase):
    def setUp(self):
        if morning_publisher is None:
            self.fail("scripts.ops.morning_publisher is not implemented")
        self.tmpdir = tempfile.TemporaryDirectory()
        self.lock_path = Path(self.tmpdir.name) / "morning.lock"

    def tearDown(self):
        self.tmpdir.cleanup()

    def _run(self, now, trading_day=True):
        with patch.object(morning_publisher, "is_trading_day", return_value=trading_day):
            return morning_publisher.run_once(now=now, lock_path=self.lock_path)

    def test_module_exists(self):
        self.assertIsNotNone(morning_publisher)

    def test_non_trading_day_skips_without_remote_or_apply(self):
        with patch("scripts.ops.morning_publisher.subprocess.run") as run:
            result = self._run(_now(8, 55), trading_day=False)

        self.assertEqual("skip_non_trading_day", result.status)
        self.assertEqual(0, result.exit_code)
        run.assert_not_called()

    def test_outside_window_skips_without_remote_or_apply(self):
        for now in (_now(8, 49), _now(9, 21)):
            with self.subTest(now=now), patch(
                "scripts.ops.morning_publisher.subprocess.run"
            ) as run:
                result = self._run(now)

            self.assertEqual("skip_outside_window", result.status)
            self.assertEqual(0, result.exit_code)
            run.assert_not_called()

    def test_window_boundaries_are_inclusive(self):
        for now in (_now(8, 50), _now(9, 20)):
            calls = []

            def fake_run(cmd, **kwargs):
                calls.append((cmd, kwargs))
                return _completed(cmd, _context("2026-08-05", True))

            with self.subTest(now=now), patch(
                "scripts.ops.morning_publisher.subprocess.run", side_effect=fake_run
            ):
                result = self._run(now)

            self.assertEqual("skip_current", result.status)
            self.assertEqual(0, result.exit_code)
            self.assertEqual(1, len(calls))
            self.assertIn("/api/ai/context", calls[0][0][-1])

    def test_current_context_skips_apply_with_zero(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            return _completed(cmd, _context("2026-08-05", True))

        with patch("scripts.ops.morning_publisher.subprocess.run", side_effect=fake_run):
            result = self._run(_now(8, 55))

        self.assertEqual("skip_current", result.status)
        self.assertEqual(0, result.exit_code)
        self.assertEqual(1, len(calls))
        self.assertTrue(calls[0][0][0] == "ssh")
        self.assertNotIn("--apply", " ".join(calls[0][0]))

    def test_stale_context_applies_and_requires_current_readback(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            if cmd[0] == "ssh":
                payload = (
                    _context("2026-08-04", False)
                    if len([c for c, _ in calls if c[0] == "ssh"]) == 1
                    else _context("2026-08-05", True)
                )
                return _completed(cmd, payload)
            return _completed(cmd)

        with patch("scripts.ops.morning_publisher.subprocess.run", side_effect=fake_run):
            result = self._run(_now(8, 55))

        self.assertEqual("applied", result.status)
        self.assertEqual(0, result.exit_code)
        self.assertEqual(3, len(calls))
        self.assertEqual(
            [
                morning_publisher.PYTHON,
                str(morning_publisher.OPEN_DAY_SCRIPT),
                "--apply",
                "--restart-cloud",
            ],
            calls[1][0],
        )
        self.assertEqual(str(ROOT), calls[1][1]["cwd"])

    def test_stale_context_apply_failure_returns_nonzero(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[0] == "ssh":
                return _completed(cmd, _context("2026-08-04", False))
            return _completed(cmd, returncode=7)

        with patch("scripts.ops.morning_publisher.subprocess.run", side_effect=fake_run):
            result = self._run(_now(8, 55))

        self.assertEqual("apply_failed", result.status)
        self.assertEqual(1, result.exit_code)
        self.assertEqual(2, len(calls))

    def test_stale_context_post_apply_readback_failure_returns_nonzero(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[0] == "ssh":
                return _completed(cmd, _context("2026-08-04", False))
            return _completed(cmd)

        with patch("scripts.ops.morning_publisher.subprocess.run", side_effect=fake_run):
            result = self._run(_now(8, 55))

        self.assertEqual("verification_failed", result.status)
        self.assertEqual(1, result.exit_code)
        self.assertEqual(3, len(calls))

    def test_lock_is_non_blocking_and_prevents_remote_work(self):
        with morning_publisher.acquire_lock(self.lock_path) as acquired:
            self.assertTrue(acquired)
            with patch("scripts.ops.morning_publisher.subprocess.run") as run:
                result = self._run(_now(8, 55))

        self.assertEqual("skip_lock", result.status)
        self.assertEqual(0, result.exit_code)
        run.assert_not_called()


class LaunchAgentTests(unittest.TestCase):
    def test_publisher_direct_invocation_is_safe(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "ops" / "morning_publisher.py"), "--dry-run"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("morning_publisher status=", result.stdout)

    def test_plist_has_three_clock_triggers_and_safe_paths(self):
        self.assertTrue(PLIST_TEMPLATE.is_file())
        with PLIST_TEMPLATE.open("rb") as handle:
            plist = plistlib.load(handle)

        self.assertEqual("com.yimu.open-day", plist["Label"])
        self.assertFalse(plist["RunAtLoad"])
        expected_intervals = [
            {"Weekday": weekday, "Hour": hour, "Minute": minute}
            for weekday in range(2, 7)
            for hour, minute in ((8, 55), (9, 5), (9, 15))
        ]
        self.assertEqual(15, len(plist["StartCalendarInterval"]))
        self.assertEqual(
            expected_intervals,
            plist["StartCalendarInterval"],
        )
        self.assertEqual("__PROJECT_ROOT__", plist["WorkingDirectory"])
        self.assertIn("__PROJECT_ROOT__", plist["ProgramArguments"][1])
        self.assertEqual("__HOME__/Library/Logs/yimu-open-day.log", plist["StandardOutPath"])
        self.assertEqual("__HOME__/Library/Logs/yimu-open-day.err.log", plist["StandardErrorPath"])

    def test_installer_materializes_template_and_only_manages_own_label(self):
        self.assertTrue(INSTALLER.is_file())
        source = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("cp", source)
        self.assertIn("plutil -lint", source)
        self.assertIn("launchctl bootstrap", source)
        self.assertIn("launchctl kickstart", source)
        self.assertIn("com.yimu.open-day", source)
        self.assertIn("launchd", source)
        self.assertNotIn("git clean", source)
        self.assertNotIn("rm -rf", source)


if __name__ == "__main__":
    unittest.main()
