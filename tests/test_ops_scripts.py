"""test_ops_scripts.py — 开/收盘脚本 RED/GREEN 测试"""

import json
import io
import sqlite3
import subprocess
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
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


class BackupRollbackTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.data_dir = self.tmpdir / "data"
        self.data_dir.mkdir()
        (self.data_dir / "pnl.db").write_text("db-v1", encoding="utf-8")
        (self.data_dir / "pnl.db-wal").write_text("wal-v1", encoding="utf-8")
        (self.data_dir / "pnl.db-shm").write_text("shm-v1", encoding="utf-8")

    def test_backup_dry_run_writes_nothing(self):
        from scripts.ops import backup_pnl_db
        out = io.StringIO()
        with redirect_stdout(out):
            backup_pnl_db.main(["--dry-run", "--data-dir", str(self.data_dir), "--stamp", "20260604-160000"])
        self.assertFalse((self.data_dir / "backups").exists())
        self.assertIn("[DRY-RUN]", out.getvalue())

    def test_backup_apply_copies_db_wal_shm_and_prints_restore(self):
        from scripts.ops import backup_pnl_db
        out = io.StringIO()
        with redirect_stdout(out):
            backup_pnl_db.main(["--apply", "--data-dir", str(self.data_dir), "--stamp", "20260604-160000"])
        backup_dir = self.data_dir / "backups" / "20260604-160000"
        self.assertEqual((backup_dir / "pnl.db").read_text(encoding="utf-8"), "db-v1")
        self.assertEqual((backup_dir / "pnl.db-wal").read_text(encoding="utf-8"), "wal-v1")
        self.assertEqual((backup_dir / "pnl.db-shm").read_text(encoding="utf-8"), "shm-v1")
        self.assertIn("rollback_ticket_migration.py --backup", out.getvalue())

    def test_rollback_dry_run_does_not_overwrite(self):
        from scripts.ops import rollback_ticket_migration
        backup_dir = self.data_dir / "backups" / "20260604-160000"
        backup_dir.mkdir(parents=True)
        (backup_dir / "pnl.db").write_text("db-backup", encoding="utf-8")
        out = io.StringIO()
        with redirect_stdout(out):
            rollback_ticket_migration.main(["--dry-run", "--data-dir", str(self.data_dir), "--backup", str(backup_dir)])
        self.assertEqual((self.data_dir / "pnl.db").read_text(encoding="utf-8"), "db-v1")
        self.assertIn("[DRY-RUN]", out.getvalue())

    def test_rollback_apply_restores_backup_files(self):
        from scripts.ops import rollback_ticket_migration
        backup_dir = self.data_dir / "backups" / "20260604-160000"
        backup_dir.mkdir(parents=True)
        (backup_dir / "pnl.db").write_text("db-backup", encoding="utf-8")
        (backup_dir / "pnl.db-wal").write_text("wal-backup", encoding="utf-8")
        rollback_ticket_migration.main(["--apply", "--data-dir", str(self.data_dir), "--backup", str(backup_dir)])
        self.assertEqual((self.data_dir / "pnl.db").read_text(encoding="utf-8"), "db-backup")
        self.assertEqual((self.data_dir / "pnl.db-wal").read_text(encoding="utf-8"), "wal-backup")

    def test_rollback_apply_drops_ticket_migration_tables_from_restored_db(self):
        from scripts.ops import rollback_ticket_migration
        backup_dir = self.data_dir / "backups" / "20260604-160000"
        backup_dir.mkdir(parents=True)
        backup_db = backup_dir / "pnl.db"
        conn = sqlite3.connect(backup_db)
        try:
            conn.execute("CREATE TABLE trade_records (id INTEGER PRIMARY KEY, name TEXT)")
            conn.execute("CREATE TABLE trade_tickets (ticket_id TEXT PRIMARY KEY)")
            conn.execute("CREATE TABLE position_lots (lot_id TEXT PRIMARY KEY)")
            conn.execute("CREATE TABLE trade_lot_allocations (id INTEGER PRIMARY KEY)")
            conn.execute("CREATE TABLE pending_fill_confirmations (confirmation_id TEXT PRIMARY KEY)")
            conn.execute("CREATE TABLE ticket_conflict_log (id INTEGER PRIMARY KEY)")
            conn.commit()
        finally:
            conn.close()

        rollback_ticket_migration.main(["--apply", "--data-dir", str(self.data_dir), "--backup", str(backup_dir)])

        conn = sqlite3.connect(self.data_dir / "pnl.db")
        try:
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
        finally:
            conn.close()
        self.assertIn("trade_records", tables)
        self.assertNotIn("trade_tickets", tables)
        self.assertNotIn("position_lots", tables)
        self.assertNotIn("trade_lot_allocations", tables)
        self.assertNotIn("pending_fill_confirmations", tables)
        self.assertNotIn("ticket_conflict_log", tables)

    def test_rollback_requires_pnl_db_in_backup(self):
        from scripts.ops import rollback_ticket_migration
        backup_dir = self.data_dir / "backups" / "bad"
        backup_dir.mkdir(parents=True)
        with self.assertRaises(SystemExit):
            rollback_ticket_migration.main(["--apply", "--data-dir", str(self.data_dir), "--backup", str(backup_dir)])


class BackupLiveDashboardDataTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.data_dir = self.tmpdir / "data"
        self.data_dir.mkdir()
        conn = sqlite3.connect(self.data_dir / "pnl.db")
        try:
            conn.execute("CREATE TABLE daily_summary (date TEXT PRIMARY KEY, nav REAL)")
            conn.execute("INSERT INTO daily_summary VALUES (?, ?)", ("2026-06-19", 1.0043))
            conn.commit()
        finally:
            conn.close()
        (self.data_dir / "dashboard_data.json").write_text(
            json.dumps({"meta": {"updated": "2026-06-19T15:10:00+08:00"}}),
            encoding="utf-8",
        )
        (self.data_dir / "sentiment_auto.json").write_text('{"sentiment":39}', encoding="utf-8")

    def test_live_data_backup_dry_run_writes_nothing(self):
        from scripts.ops import backup_live_dashboard_data
        out = io.StringIO()
        with redirect_stdout(out):
            backup_live_dashboard_data.main([
                "--dry-run",
                "--data-dir", str(self.data_dir),
                "--output-dir", str(self.data_dir / "backups" / "live-dashboard-data"),
                "--stamp", "20260620-120000",
            ])
        self.assertFalse((self.data_dir / "backups").exists())
        self.assertIn("[DRY-RUN]", out.getvalue())

    def test_live_data_backup_apply_creates_archive_with_manifest_and_consistent_db(self):
        from scripts.ops import backup_live_dashboard_data
        out_dir = self.data_dir / "backups" / "live-dashboard-data"
        backup_live_dashboard_data.main([
            "--apply",
            "--data-dir", str(self.data_dir),
            "--output-dir", str(out_dir),
            "--stamp", "20260620-120000",
        ])
        archive = out_dir / "live-dashboard-data-20260620-120000.tar.gz"
        self.assertTrue(archive.exists())
        with tarfile.open(archive, "r:gz") as tar:
            names = set(tar.getnames())
            self.assertIn("manifest.json", names)
            self.assertIn("pnl.db", names)
            self.assertIn("dashboard_data.json", names)
            self.assertIn("sentiment_auto.json", names)
            manifest = json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))
            db_bytes = tar.extractfile("pnl.db").read()
        self.assertEqual(manifest["archive_name"], archive.name)
        self.assertIn("pnl.db", manifest["files"])
        restored_db = self.tmpdir / "restored-pnl.db"
        restored_db.write_bytes(db_bytes)
        conn = sqlite3.connect(restored_db)
        try:
            row = conn.execute("SELECT nav FROM daily_summary WHERE date='2026-06-19'").fetchone()
        finally:
            conn.close()
        self.assertEqual(row[0], 1.0043)

    def test_live_data_backup_upload_oss_invokes_configured_uploader(self):
        from scripts.ops import backup_live_dashboard_data
        out_dir = self.data_dir / "backups" / "live-dashboard-data"
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "ok\n", "")

        with patch("scripts.ops.common.subprocess.run", side_effect=fake_run):
            backup_live_dashboard_data.main([
                "--apply",
                "--upload-oss",
                "--data-dir", str(self.data_dir),
                "--output-dir", str(out_dir),
                "--stamp", "20260620-120000",
                "--oss-python", "/tmp/python",
                "--oss-uploader", "/tmp/oss_upload.py",
                "--oss-prefix", "yimu-capital/live-dashboard-data",
            ])

        joined = " ".join(" ".join(cmd) for cmd in calls)
        self.assertIn("/tmp/python", joined)
        self.assertIn("/tmp/oss_upload.py", joined)
        self.assertIn("live-dashboard-data-20260620-120000.tar.gz", joined)
        self.assertIn("yimu-capital/live-dashboard-data", joined)

    def test_live_data_backup_can_pull_cloud_before_archive(self):
        from scripts.ops import backup_live_dashboard_data
        out_dir = self.data_dir / "backups" / "live-dashboard-data"
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            cmd_str = " ".join(cmd)
            if "ls -t" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "/remote/data/pnl.db.backup-live-data-20260620-120000\n", "")
            if "ssh" in cmd_str and "integrity_check" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "pnl.db.backup-live-data-20260620-120000\nintegrity_check: ok\n", "")
            if "for f in" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "dashboard_data.json\n", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch("scripts.ops.common.subprocess.run", side_effect=fake_run):
            backup_live_dashboard_data.main([
                "--apply",
                "--pull-cloud-first",
                "--data-dir", str(self.data_dir),
                "--output-dir", str(out_dir),
                "--stamp", "20260620-120000",
                "--remote", "agentuser@example",
                "--remote-data-dir", "/remote/data",
                "--remote-project", "/remote/project",
                "--remote-python", "/remote/project/.venv/bin/python",
            ])

        archive = out_dir / "live-dashboard-data-20260620-120000.tar.gz"
        self.assertTrue(archive.exists())
        joined = " ".join(" ".join(cmd) for cmd in calls)
        self.assertIn("ssh agentuser@example", joined)
        self.assertIn("pnl.db.backup-live-data-", joined)
        self.assertNotIn("'/remote/data/pnl.db.backup-live-data-*'", joined)
        self.assertIn("rsync", joined)
        self.assertIn("dashboard_data.json", joined)
        self.assertNotIn("--ignore-missing-args", joined)

    def test_live_data_backup_cloud_backup_failure_stops_before_archive_and_upload(self):
        from scripts.ops import backup_live_dashboard_data
        out_dir = self.data_dir / "backups" / "live-dashboard-data"
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            cmd_str = " ".join(cmd)
            if "ssh" in cmd_str and "integrity_check" in cmd_str:
                return subprocess.CompletedProcess(cmd, 1, "bad.db\nintegrity_check: malformed\n", "remote failed")
            raise AssertionError(f"unexpected command after failed backup: {cmd}")

        with patch("scripts.ops.common.subprocess.run", side_effect=fake_run):
            with self.assertRaises(RuntimeError):
                backup_live_dashboard_data.main([
                    "--apply",
                    "--pull-cloud-first",
                    "--upload-oss",
                    "--data-dir", str(self.data_dir),
                    "--output-dir", str(out_dir),
                    "--stamp", "20260620-120000",
                ])

        self.assertFalse((out_dir / "live-dashboard-data-20260620-120000.tar.gz").exists())
        joined = " ".join(" ".join(cmd) for cmd in calls)
        self.assertNotIn("oss_upload.py", joined)

    def test_live_data_backup_json_listing_failure_stops_before_archive(self):
        from scripts.ops import backup_live_dashboard_data
        out_dir = self.data_dir / "backups" / "live-dashboard-data"

        def fake_run(cmd, **kw):
            cmd_str = " ".join(cmd)
            if "ls -t" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "/remote/data/pnl.db.backup-live-data-20260620-120000\n", "")
            if "ssh" in cmd_str and "integrity_check" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "pnl.db.backup-live-data-20260620-120000\nintegrity_check: ok\n", "")
            if cmd and cmd[0] == "rsync":
                return subprocess.CompletedProcess(cmd, 0, "", "")
            if "for f in" in cmd_str:
                return subprocess.CompletedProcess(cmd, 255, "", "permission denied")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch("scripts.ops.common.subprocess.run", side_effect=fake_run):
            with self.assertRaises(RuntimeError):
                backup_live_dashboard_data.main([
                    "--apply",
                    "--pull-cloud-first",
                    "--data-dir", str(self.data_dir),
                    "--output-dir", str(out_dir),
                    "--stamp", "20260620-120000",
                ])

        self.assertFalse((out_dir / "live-dashboard-data-20260620-120000.tar.gz").exists())


class TicketUpgradeReadinessTests(unittest.TestCase):

    def test_ticket_upgrade_readiness_passes_with_widget_and_ticket_api(self):
        from scripts.ops import check_ticket_upgrade_ready

        calls = []

        class Resp:
            def __init__(self, body, status=200, content_type="text/html"):
                self.body = body.encode("utf-8")
                self.status = status
                self.headers = {"Content-Type": content_type}
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return self.body

        def fake_urlopen(req, timeout=5):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            calls.append((url, getattr(req, "method", "GET")))
            if url.endswith("/"):
                return Resp('<script src="widgets/trade-tickets.js?v=1"></script><button>W24</button>')
            if url.endswith("/widgets/trade-tickets.js"):
                return Resp("function _prepareTicket(){} data-tt-prepare data-tt-confirm /api/trade/fills/confirm")
            if url.endswith("/api/trade/tickets"):
                return Resp('{"tickets":[]}', content_type="application/json")
            raise AssertionError(url)

        result = check_ticket_upgrade_ready.check("http://127.0.0.1:8088", opener=fake_urlopen)

        self.assertTrue(result["ok"], result)
        self.assertTrue(all(method == "GET" for _, method in calls))

    def test_ticket_upgrade_readiness_fails_old_cloud_without_ticket_api(self):
        from scripts.ops import check_ticket_upgrade_ready

        class Resp:
            def __init__(self, body, status=200, content_type="text/html"):
                self.body = body.encode("utf-8")
                self.status = status
                self.headers = {"Content-Type": content_type}
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return self.body

        def fake_urlopen(req, timeout=5):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if url.endswith("/"):
                return Resp("<html>old dashboard</html>")
            if url.endswith("/widgets/trade-tickets.js"):
                return Resp("<h1>404</h1>", status=404)
            if url.endswith("/api/trade/tickets"):
                return Resp("<html>404</html>", status=404)
            raise AssertionError(url)

        result = check_ticket_upgrade_ready.check("http://127.0.0.1:8088", opener=fake_urlopen)

        self.assertFalse(result["ok"], result)
        names = [item["name"] for item in result["checks"] if not item["ok"]]
        self.assertIn("index_w24_resource", names)
        self.assertIn("trade_tickets_api_json", names)


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

    def test_apply_health_check_captures_curl_output(self):
        """apply 只读验收必须捕获 curl stdout，避免 stdout=None 崩溃"""
        from scripts.ops import open_day

        def fake_run(cmd, **kw):
            if cmd and cmd[0] == "curl":
                if kw.get("capture_output") and kw.get("text"):
                    return subprocess.CompletedProcess(cmd, 0, '{"ok": true}', "")
                return subprocess.CompletedProcess(cmd, 0, None, None)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch("scripts.ops.common.subprocess.run", side_effect=fake_run) as mock_run:
            with patch("scripts.ops.open_day.argparse.ArgumentParser.parse_args") as mock_args:
                mock_args.return_value = MagicMock(
                    dry_run=False, apply=True, restart_cloud=False,
                    baseline=self.baseline_path,
                )
                open_day.main()

        curl_calls = [
            c for c in mock_run.call_args_list
            if c.args and c.args[0] and c.args[0][0] == "curl"
        ]
        self.assertEqual(len(curl_calls), 3)
        for c in curl_calls:
            self.assertTrue(c.kwargs.get("capture_output"))
            self.assertTrue(c.kwargs.get("text"))


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

    def test_dry_run_prints_ticket_review_summary(self):
        from scripts.ops import close_day
        with patch("scripts.ops.common.subprocess.run"):
            with patch("scripts.ops.close_day.build_daily_ticket_review", create=True) as mock_review:
                mock_review.return_value = {"review_markdown": "# review"}
                with patch("scripts.ops.close_day.argparse.ArgumentParser.parse_args") as mock_args:
                    mock_args.return_value = MagicMock(
                        dry_run=True, apply=False, date="2026-06-03",
                        remote_data_dir="/home/agentuser/YiMu-Capital/data",
                        local_data_dir="/tmp",
                    )
                    out = io.StringIO()
                    with redirect_stdout(out):
                        close_day.main()
        self.assertIn("Ticket review summary generated for 2026-06-03", out.getvalue())

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

    def test_apply_writes_ticket_review_markdown(self):
        from scripts.ops import close_day
        tmpdir = Path(tempfile.mkdtemp())
        real_db = tmpdir / "pnl.db"
        import sqlite3
        con = sqlite3.connect(str(real_db))
        con.execute("CREATE TABLE t (x)")
        con.close()

        def fake_run(cmd, **kw):
            cmd_str = str(cmd)
            if "ls -t" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "data/pnl.db.backup-close-20260603-150530\n", "")
            if "ssh" in cmd_str and "integrity_check" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "pnl.db.backup-close-20260603-150530\nintegrity_check: ok\n", "")
            if "PRAGMA integrity_check" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "ok\n", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch("scripts.ops.common.subprocess.run", side_effect=fake_run):
            with patch("scripts.ops.close_day.build_daily_ticket_review", create=True) as mock_review:
                mock_review.return_value = {"review_markdown": "# ticket review\n\n3 tickets"}
                with patch("scripts.ops.close_day.argparse.ArgumentParser.parse_args") as mock_args:
                    mock_args.return_value = MagicMock(
                        dry_run=False, apply=True, date="2026-06-03",
                        remote_data_dir="/home/agentuser/YiMu-Capital/data",
                        local_data_dir=str(tmpdir),
                    )
                    close_day.main()

        out = tmpdir / "reviews" / "ticket_review_2026-06-03.md"
        self.assertTrue(out.exists())
        self.assertIn("3 tickets", out.read_text(encoding="utf-8"))


# ── entry ─────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main()
