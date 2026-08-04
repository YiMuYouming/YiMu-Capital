"""test_ops_scripts.py — 开/收盘脚本 RED/GREEN 测试"""

import json
import io
import shlex
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
        data = _make_fixture_baseline({
            "meta": {
                **_make_fixture_baseline()["meta"],
                "field_sources": {
                    "今日操作": {
                        "source_note": "2026_5_28_Thursday_ReviewNote.md",
                        "source_date": "2026-05-28",
                        "fallback": False,
                    }
                },
            }
        })
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
            self.assertEqual("2026-05-28", summary["today_operations_source_date"])
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


class CloseDayReviewSourcePacketTests(unittest.TestCase):

    def test_review_source_packet_dry_run_builds_but_does_not_write(self):
        from scripts.ops import close_day
        data_dir = Path(tempfile.mkdtemp())
        packet = {"schema_version": "review_source_packet.v1", "date": "2026-06-19"}
        with patch("scripts.ops.close_day.review_source_packet.generate_review_source_packet",
                   return_value=packet) as mock_generate, \
             patch("scripts.ops.close_day.review_source_packet.write_review_source_packet",
                   return_value={"path": str(data_dir / "review_packets/2026-06-19/review_source_packet.json"),
                                 "written": False}) as mock_write:
            result = close_day.run_review_source_packet(data_dir, "2026-06-19", dry_run=True)

        mock_generate.assert_called_once_with("2026-06-19", data_dir=data_dir)
        mock_write.assert_called_once_with(packet, data_dir, apply=False)
        self.assertFalse(result["written"])

    def test_review_source_packet_apply_writes_packet(self):
        from scripts.ops import close_day
        data_dir = Path(tempfile.mkdtemp())
        packet = {"schema_version": "review_source_packet.v1", "date": "2026-06-19"}
        with patch("scripts.ops.close_day.review_source_packet.generate_review_source_packet",
                   return_value=packet), \
             patch("scripts.ops.close_day.review_source_packet.write_review_source_packet",
                   return_value={"path": str(data_dir / "review_packets/2026-06-19/review_source_packet.json"),
                                 "written": True}) as mock_write:
            result = close_day.run_review_source_packet(data_dir, "2026-06-19", dry_run=False)

        mock_write.assert_called_once_with(packet, data_dir, apply=True)
        self.assertTrue(result["written"])


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
            if "/api/trade/tickets?date=" in url:
                return Resp('{"tickets":[],"data_date":"%s","date_source":"query_param"}' % url.rsplit("date=", 1)[-1], content_type="application/json")
            raise AssertionError(url)

        result = check_ticket_upgrade_ready.check("http://127.0.0.1:8088", opener=fake_urlopen)

        self.assertTrue(result["ok"], result)
        self.assertTrue(all(method == "GET" for _, method in calls))
        self.assertTrue(any("/api/trade/tickets?date=" in url for url, _ in calls), calls)

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
            if "/api/trade/tickets?date=" in url:
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
            with patch("scripts.ops.open_day._remote_validate", return_value={"ok": True}), \
                 patch("scripts.ops.open_day._api_readback", return_value={"ok": True}):
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

    def test_apply_publishes_rule_bundle_plan_card_and_baseline_as_staged_artifacts(self):
        """apply 的 rsync 必须包含规则包、日计划、兼容卡和 baseline。"""
        from scripts.ops import open_day

        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch("scripts.ops.open_day.run", side_effect=fake_run), \
             patch("scripts.ops.open_day._remote_validate", create=True, return_value={"ok": True}), \
             patch("scripts.ops.open_day._api_readback", create=True, return_value={"ok": True}), \
             patch("scripts.ops.open_day._atomic_rename", create=True):
            with patch("scripts.ops.open_day.argparse.ArgumentParser.parse_args") as mock_args:
                mock_args.return_value = MagicMock(
                    dry_run=False, apply=True, restart_cloud=False,
                    baseline=self.baseline_path,
                )
                open_day.main()

        rsync = [cmd for cmd in calls if cmd and cmd[0] == "rsync"]
        joined = " ".join(" ".join(cmd) for cmd in rsync)
        self.assertIn("rule_bundle_manifest.json", joined)
        self.assertIn("daily_plan.json", joined)
        self.assertIn("today_execution_card.json", joined)
        self.assertIn("dashboard_data.json", joined)

    def test_apply_stops_before_restart_when_remote_hash_readback_differs(self):
        """远端 hash/date 回读失败时不得执行 systemctl restart。"""
        from scripts.ops import open_day

        executed_commands = []

        def fake_run(cmd, **kwargs):
            executed_commands.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch("scripts.ops.open_day.run", side_effect=fake_run), \
             patch(
                 "scripts.ops.open_day._remote_validate",
                 create=True,
                 return_value={"ok": False, "reason": "REMOTE_HASH_MISMATCH"},
             ), \
             patch("scripts.ops.open_day._api_readback", create=True, return_value={"ok": True}), \
             patch("scripts.ops.open_day._atomic_rename", create=True):
            with patch("scripts.ops.open_day.argparse.ArgumentParser.parse_args") as mock_args:
                mock_args.return_value = MagicMock(
                    dry_run=False, apply=True, restart_cloud=True,
                    baseline=self.baseline_path,
                )
                with self.assertRaises(SystemExit) as ctx:
                    open_day.main()

        self.assertNotEqual(0, ctx.exception.code)
        self.assertNotIn(
            "systemctl restart",
            " ".join(" ".join(cmd) for cmd in executed_commands),
        )

    def test_remote_validate_requires_hashes_dates_and_card_contract(self):
        from scripts.ops import open_day

        stage = "/home/agentuser/YiMu-Capital/.open-day-staging-test"
        expected = {
            "compiled/rules.v1.json": "a" * 64,
            "daily-runtime/rule_bundle_manifest.json": "b" * 64,
            "daily-runtime/daily_plan.json": "c" * 64,
            "daily-runtime/today_execution_card.json": "d" * 64,
            "data/dashboard_data.json": "e" * 64,
            "data/pools.json": "f" * 64,
        }
        output = "\n".join([
            f"{expected['compiled/rules.v1.json']}  {stage}/rules/compiled/rules.v1.json",
            f"{expected['daily-runtime/rule_bundle_manifest.json']}  {stage}/rules/daily-runtime/rule_bundle_manifest.json",
            f"{expected['daily-runtime/daily_plan.json']}  {stage}/rules/daily-runtime/daily_plan.json",
            f"{expected['daily-runtime/today_execution_card.json']}  {stage}/rules/daily-runtime/today_execution_card.json",
            f"{expected['data/dashboard_data.json']}  {stage}/dashboard/data/dashboard_data.json",
            f"{expected['data/pools.json']}  {stage}/dashboard/data/pools.json",
            "PLAN_DATE 2026-08-04",
            "CARD_DATE 2026-08-04",
            "CARD_ID EXEC-20260804-20260804T010000+0000",
            "SNAPSHOT_HASH sha256:" + "1" * 64,
            "RECOMMENDATION_SCHEMA recommendation_state.v1",
        ])
        metadata = {
            "trade_date": "2026-08-04",
            "card_id": "EXEC-20260804-20260804T010000+0000",
            "snapshot_hash": "sha256:" + "1" * 64,
            "recommendation_schema": "recommendation_state.v1",
        }
        with patch(
            "scripts.ops.open_day.run",
            return_value=subprocess.CompletedProcess(["ssh"], 0, output, ""),
        ):
            result = open_day._remote_validate(stage, expected, metadata)

        self.assertTrue(result["ok"], result)

    def test_restart_cloud_triggers_ssh_restart(self):
        """--apply --restart-cloud 应额外调用 ssh restart"""
        from scripts.ops import open_day
        with patch("scripts.ops.common.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(["true"], 0, "", "")
            with patch("scripts.ops.open_day._remote_validate", return_value={"ok": True}), \
                 patch("scripts.ops.open_day._api_readback", return_value={"ok": True}):
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

        metadata = open_day._publication_metadata()

        def fake_run(cmd, **kw):
            if cmd and cmd[0] == "curl":
                if kw.get("capture_output") and kw.get("text"):
                    if "api/baseline" in cmd[-1]:
                        payload = {"meta": {"date": metadata["trade_date"]}}
                    else:
                        payload = {
                            "date": metadata["trade_date"],
                            "rule_state": {
                                "today_execution_card_id": metadata["card_id"],
                                "rule_snapshot_hash": metadata["snapshot_hash"],
                            },
                            "recommendation_state": {
                                "schema_version": metadata["recommendation_schema"],
                            },
                        }
                    return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
                return subprocess.CompletedProcess(cmd, 0, None, None)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch("scripts.ops.common.subprocess.run", side_effect=fake_run) as mock_run:
            with patch("scripts.ops.open_day._remote_validate", return_value={"ok": True}), \
                 patch("scripts.ops.open_day.argparse.ArgumentParser.parse_args") as mock_args:
                mock_args.return_value = MagicMock(
                    dry_run=False, apply=True, restart_cloud=False,
                    baseline=self.baseline_path,
                )
                open_day.main()

        curl_calls = [
            c for c in mock_run.call_args_list
            if c.args and c.args[0] and c.args[0][0] == "curl"
        ]
        self.assertEqual(len(curl_calls), 2)
        for c in curl_calls:
            self.assertTrue(c.kwargs.get("capture_output"))
            self.assertTrue(c.kwargs.get("text"))


# ── close_day.py tests ───────────────────────────────────


class CloseDayDryRunTests(unittest.TestCase):
    def test_remote_backup_command_quotes_embedded_python_script(self):
        from scripts.ops import close_day

        cmd = close_day.build_remote_backup_command("/tmp/data dir/with'quote")

        self.assertEqual(cmd[:2], ["ssh", close_day.REMOTE])
        parsed = shlex.split(cmd[2])
        self.assertEqual(parsed[0], "cd")
        self.assertEqual(parsed[1], close_day.REMOTE_PROJECT)
        self.assertEqual(parsed[2], "&&")
        self.assertEqual(parsed[3], close_day.REMOTE_VENV_PYTHON)
        self.assertEqual(parsed[4], "-c")
        self.assertIn("/tmp/data dir/with'quote", parsed[5])

    def test_dry_run_does_not_call_ssh_or_rsync(self):
        """close_day.py --dry-run 不应调用 ssh/rsync 写入"""
        from scripts.ops import close_day
        with patch("scripts.ops.common.subprocess.run") as mock_run:
            with patch("scripts.ops.close_day.run_review_source_packet") as mock_packet:
                with patch("scripts.ops.close_day.argparse.ArgumentParser.parse_args") as mock_args:
                    mock_args.return_value = MagicMock(
                        dry_run=True, apply=False,
                        remote_data_dir="/home/agentuser/YiMu-Capital/data",
                        local_data_dir="/tmp",
                    )
                    close_day.main()
        mock_packet.assert_not_called()
        mock_run.assert_not_called()

    def test_main_orders_ticket_review_packet_then_project_backup(self):
        from scripts.ops import close_day
        tmpdir = Path(tempfile.mkdtemp())
        real_db = tmpdir / "pnl.db"
        import sqlite3
        con = sqlite3.connect(str(real_db))
        con.execute("CREATE TABLE t (x)")
        con.close()
        events = []

        def fake_run(cmd, **kw):
            cmd_str = str(cmd)
            if "for f in dashboard_data.json" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "", "")
            if "ls -t" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "data/pnl.db.backup-close-20260603-150530\n", "")
            if "ssh" in cmd_str and "integrity_check" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "pnl.db.backup-close-20260603-150530\nintegrity_check: ok\n", "")
            if "PRAGMA integrity_check" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "ok\n", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        def fake_ticket_review(date_str):
            events.append("ticket")
            return {"review_markdown": "# ticket review"}

        def fake_packet(local_data, date_str, dry_run):
            events.append("packet")
            return {"path": str(Path(local_data) / "review_packets" / date_str / "review_source_packet.json"),
                    "written": True}

        def fake_backup(local_data, date_str):
            events.append("backup")

        with patch("scripts.ops.common.subprocess.run", side_effect=fake_run):
            with patch("scripts.ops.close_day.build_daily_ticket_review", side_effect=fake_ticket_review):
                with patch("scripts.ops.close_day.run_review_source_packet", side_effect=fake_packet):
                    with patch("scripts.ops.close_day.run_project_data_backup", side_effect=fake_backup):
                        with patch("scripts.ops.close_day.argparse.ArgumentParser.parse_args") as mock_args:
                            mock_args.return_value = MagicMock(
                                dry_run=False, apply=True, date="2026-06-03",
                                remote_data_dir="/home/agentuser/YiMu-Capital/data",
                                local_data_dir=str(tmpdir),
                                skip_data_backup=False,
                            )
                            close_day.main()

        self.assertEqual(events, ["ticket", "packet", "backup"])

    def test_main_does_not_hit_real_ai_context_in_close_day_tests(self):
        from scripts.ops import close_day
        with patch("scripts.ops.common.subprocess.run"):
            with patch("scripts.ops.close_day.run_review_source_packet") as mock_packet:
                with patch("scripts.ops.close_day.fetch_ai_context", create=True) as mock_fetch:
                    with patch("scripts.ops.close_day.argparse.ArgumentParser.parse_args") as mock_args:
                        mock_args.return_value = MagicMock(
                            dry_run=True, apply=False,
                            remote_data_dir="/home/agentuser/YiMu-Capital/data",
                            local_data_dir="/tmp",
                        )
                        close_day.main()
        mock_packet.assert_not_called()
        mock_fetch.assert_not_called()

    def test_dry_run_previews_ticket_review_without_opening_db(self):
        from scripts.ops import close_day
        with patch("scripts.ops.common.subprocess.run"):
            with patch("scripts.ops.close_day.build_daily_ticket_review", create=True) as mock_review:
                with patch("scripts.ops.close_day.backup_live_dashboard_data.main") as mock_backup:
                    with patch("scripts.ops.close_day.run_review_source_packet"):
                        with patch("scripts.ops.close_day.argparse.ArgumentParser.parse_args") as mock_args:
                            mock_args.return_value = MagicMock(
                                dry_run=True, apply=False, date="2026-06-03",
                                remote_data_dir="/home/agentuser/YiMu-Capital/data",
                                local_data_dir="/tmp",
                                skip_data_backup=False,
                            )
                            out = io.StringIO()
                            with redirect_stdout(out):
                                close_day.main()
        self.assertIn("[DRY-RUN] 跳过票据复盘摘要生成", out.getvalue())
        mock_review.assert_not_called()
        mock_backup.assert_not_called()

    def test_dry_run_previews_review_source_packet_without_collecting_sources(self):
        from scripts.ops import close_day
        missing_data_dir = Path(tempfile.mkdtemp()) / "missing-data"
        with patch("scripts.ops.common.subprocess.run"):
            with patch("scripts.ops.close_day.build_daily_ticket_review", create=True) as mock_review:
                with patch("scripts.ops.close_day.run_review_source_packet") as mock_packet:
                    with patch("scripts.ops.close_day.argparse.ArgumentParser.parse_args") as mock_args:
                        mock_args.return_value = MagicMock(
                            dry_run=True, apply=False, date="2026-06-03",
                            remote_data_dir="/home/agentuser/YiMu-Capital/data",
                            local_data_dir=str(missing_data_dir),
                            skip_data_backup=False,
                        )
                        out = io.StringIO()
                        with redirect_stdout(out):
                            close_day.main()

        self.assertIn("review_packets/2026-06-03/review_source_packet.json", out.getvalue())
        mock_review.assert_not_called()
        mock_packet.assert_not_called()

    def test_apply_runs_project_data_backup_after_close_sync(self):
        from scripts.ops import close_day
        tmpdir = Path(tempfile.mkdtemp())
        real_db = tmpdir / "pnl.db"
        import sqlite3
        con = sqlite3.connect(str(real_db))
        con.execute("CREATE TABLE t (x)")
        con.close()

        def fake_run(cmd, **kw):
            cmd_str = str(cmd)
            if "for f in dashboard_data.json" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "dashboard_data.json\npnl_history.json\n", "")
            if "ls -t" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "data/pnl.db.backup-close-20260603-150530\n", "")
            if "ssh" in cmd_str and "integrity_check" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "pnl.db.backup-close-20260603-150530\nintegrity_check: ok\n", "")
            if "PRAGMA integrity_check" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "ok\n", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch("scripts.ops.common.subprocess.run", side_effect=fake_run):
            with patch("scripts.ops.close_day.build_daily_ticket_review", create=True) as mock_review:
                mock_review.return_value = {"review_markdown": "# ticket review"}
                with patch("scripts.ops.close_day.backup_live_dashboard_data.main") as mock_backup:
                    with patch("scripts.ops.close_day.run_review_source_packet"):
                        with patch("scripts.ops.close_day.argparse.ArgumentParser.parse_args") as mock_args:
                            mock_args.return_value = MagicMock(
                                dry_run=False, apply=True, date="2026-06-03",
                                remote_data_dir="/home/agentuser/YiMu-Capital/data",
                                local_data_dir=str(tmpdir),
                                skip_data_backup=False,
                            )
                            close_day.main()

        mock_backup.assert_called_once()
        backup_args = mock_backup.call_args.args[0]
        self.assertIn("--apply", backup_args)
        self.assertIn("--upload-oss", backup_args)
        self.assertNotIn("--pull-cloud-first", backup_args)
        self.assertIn("--data-dir", backup_args)
        self.assertIn(str(tmpdir), backup_args)
        self.assertIn("--output-dir", backup_args)
        self.assertIn(str(tmpdir / "backups" / "live-dashboard-data"), backup_args)

    def test_apply_creates_local_data_dir_before_rsync(self):
        from scripts.ops import close_day
        missing_data_dir = Path(tempfile.mkdtemp()) / "missing-data"
        commands_seen = []

        def fake_run(cmd, **kw):
            cmd_str = str(cmd)
            commands_seen.append(cmd_str)
            if "for f in dashboard_data.json" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "", "")
            if "ls -t" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "data/pnl.db.backup-close-20260603-150530\n", "")
            if "ssh" in cmd_str and "integrity_check" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "pnl.db.backup-close-20260603-150530\nintegrity_check: ok\n", "")
            if "rsync" in cmd_str:
                self.assertTrue(missing_data_dir.exists())
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch("scripts.ops.common.subprocess.run", side_effect=fake_run):
            with patch("scripts.ops.close_day.sqlite_integrity", return_value=(True, "ok")):
                with patch("scripts.ops.close_day.build_daily_ticket_review", create=True) as mock_review:
                    mock_review.return_value = {"review_markdown": "# ticket review"}
                    with patch("scripts.ops.close_day.run_review_source_packet"):
                        with patch("scripts.ops.close_day.argparse.ArgumentParser.parse_args") as mock_args:
                            mock_args.return_value = MagicMock(
                                dry_run=False, apply=True, date="2026-06-03",
                                remote_data_dir="/home/agentuser/YiMu-Capital/data",
                                local_data_dir=str(missing_data_dir),
                                skip_data_backup=True,
                            )
                            close_day.main()

        self.assertTrue(missing_data_dir.exists())
        self.assertIn("rsync", " ".join(commands_seen))

    def test_apply_can_skip_project_data_backup(self):
        from scripts.ops import close_day
        tmpdir = Path(tempfile.mkdtemp())
        real_db = tmpdir / "pnl.db"
        import sqlite3
        con = sqlite3.connect(str(real_db))
        con.execute("CREATE TABLE t (x)")
        con.close()

        def fake_run(cmd, **kw):
            cmd_str = str(cmd)
            if "for f in dashboard_data.json" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "dashboard_data.json\npnl_history.json\n", "")
            if "ls -t" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "data/pnl.db.backup-close-20260603-150530\n", "")
            if "ssh" in cmd_str and "integrity_check" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "pnl.db.backup-close-20260603-150530\nintegrity_check: ok\n", "")
            if "PRAGMA integrity_check" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "ok\n", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch("scripts.ops.common.subprocess.run", side_effect=fake_run):
            with patch("scripts.ops.close_day.build_daily_ticket_review", create=True) as mock_review:
                mock_review.return_value = {"review_markdown": "# ticket review"}
                with patch("scripts.ops.close_day.backup_live_dashboard_data.main") as mock_backup:
                    with patch("scripts.ops.close_day.run_review_source_packet"):
                        with patch("scripts.ops.close_day.argparse.ArgumentParser.parse_args") as mock_args:
                            mock_args.return_value = MagicMock(
                                dry_run=False, apply=True, date="2026-06-03",
                                remote_data_dir="/home/agentuser/YiMu-Capital/data",
                                local_data_dir=str(tmpdir),
                                skip_data_backup=True,
                            )
                            close_day.main()

        mock_backup.assert_not_called()

    def test_apply_skips_json_rsync_when_remote_has_no_json(self):
        from scripts.ops import close_day
        tmpdir = Path(tempfile.mkdtemp())
        real_db = tmpdir / "pnl.db"
        import sqlite3
        con = sqlite3.connect(str(real_db))
        con.execute("CREATE TABLE t (x)")
        con.close()

        commands_seen = []

        def fake_run(cmd, **kw):
            cmd_str = str(cmd)
            commands_seen.append(cmd_str)
            if "for f in dashboard_data.json" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "", "")
            if "ls -t" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "data/pnl.db.backup-close-20260603-150530\n", "")
            if "ssh" in cmd_str and "integrity_check" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "pnl.db.backup-close-20260603-150530\nintegrity_check: ok\n", "")
            if "PRAGMA integrity_check" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "ok\n", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch("scripts.ops.common.subprocess.run", side_effect=fake_run):
            with patch("scripts.ops.close_day.build_daily_ticket_review", create=True) as mock_review:
                mock_review.return_value = {"review_markdown": "# ticket review"}
                with patch("scripts.ops.close_day.run_review_source_packet"):
                    with patch("scripts.ops.close_day.argparse.ArgumentParser.parse_args") as mock_args:
                        mock_args.return_value = MagicMock(
                            dry_run=False, apply=True, date="2026-06-03",
                            remote_data_dir="/home/agentuser/YiMu-Capital/data",
                            local_data_dir=str(tmpdir),
                            skip_data_backup=True,
                        )
                        out = io.StringIO()
                        with redirect_stdout(out):
                            close_day.main()

        self.assertIn("云端未找到可同步的辅助 JSON", out.getvalue())
        all_cmds = " ".join(commands_seen)
        self.assertNotIn("/dashboard_data.json", all_cmds)
        self.assertNotIn("/pnl_history.json", all_cmds)

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
            if "for f in dashboard_data.json" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "dashboard_data.json\npnl_history.json\n", "")
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
                    skip_data_backup=True,
                )
                with patch("scripts.ops.close_day.build_daily_ticket_review", create=True) as mock_review:
                    mock_review.return_value = {"review_markdown": "# ticket review"}
                    with patch("scripts.ops.close_day.run_review_source_packet"):
                        close_day.main()
        self.assertGreaterEqual(call_count, 1)
        all_cmds = " ".join(commands_seen)
        self.assertIn("ssh", all_cmds, "应调 ssh backup")
        self.assertIn("rsync", all_cmds, "应调 rsync")
        self.assertIn("integrity_check", all_cmds, "应调 integrity check")
        self.assertNotIn("--ignore-missing-args", all_cmds)

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
            if "for f in dashboard_data.json" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, "dashboard_data.json\npnl_history.json\n", "")
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
                with patch("scripts.ops.close_day.run_review_source_packet"):
                    with patch("scripts.ops.close_day.argparse.ArgumentParser.parse_args") as mock_args:
                        mock_args.return_value = MagicMock(
                            dry_run=False, apply=True, date="2026-06-03",
                            remote_data_dir="/home/agentuser/YiMu-Capital/data",
                            local_data_dir=str(tmpdir),
                            skip_data_backup=True,
                        )
                        close_day.main()

        out = tmpdir / "reviews" / "ticket_review_2026-06-03.md"
        self.assertTrue(out.exists())
        self.assertIn("3 tickets", out.read_text(encoding="utf-8"))


# ── entry ─────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main()
