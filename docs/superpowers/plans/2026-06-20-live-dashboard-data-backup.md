# Live Dashboard Data Backup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated backup path for live-dashboard runtime data that keeps one local archive and can upload the same archive to OSS.

**Architecture:** Git remains code-only. The new ops script can first create a SQLite backup on hermes and pull production data into local `data/`, then creates a SQLite online backup of `data/pnl.db`, copies selected JSON runtime files into a temporary staging directory, writes a manifest with file hashes, compresses the staging directory to `data/backups/live-dashboard-data/live-dashboard-data-<stamp>.tar.gz`, and optionally uploads that archive using the existing WorkBuddy OSS uploader.

**Tech Stack:** Python stdlib (`sqlite3`, `tarfile`, `hashlib`, `tempfile`, `subprocess`), existing `scripts.ops.common.run`, existing WorkBuddy `oss_upload.py`.

---

### Task 1: Dedicated Backup Script

**Files:**
- Create: `scripts/ops/backup_live_dashboard_data.py`
- Modify: `tests/test_ops_scripts.py`
- Modify: `README.md`

- [x] **Step 1: Write failing tests**

Add tests that prove:
- `--dry-run` writes nothing.
- `--apply` creates a tar.gz archive containing `manifest.json`, `pnl.db`, and available JSON files.
- `--apply --upload-oss` invokes the configured uploader with the created archive and OSS prefix.

- [x] **Step 2: Run tests and verify failure**

Run: `python3 -m unittest tests.test_ops_scripts.BackupLiveDashboardDataTests`

Observed: initial import failure because `scripts.ops.backup_live_dashboard_data` did not exist; later red tests also caught JSON listing failure behavior before the fix.

- [x] **Step 3: Implement script**

Create `backup_live_dashboard_data.py` with:
- `--dry-run` default behavior.
- `--apply` to write local archive.
- `--upload-oss` to upload the archive after successful local creation.
- `--pull-cloud-first` to refresh local data from hermes before archiving.
- SQLite online backup for `pnl.db`.
- Manifest with timestamp, source data dir, archive contents, file size, and SHA-256.

- [x] **Step 4: Verify tests pass**

Run: `python3 -m unittest tests.test_ops_scripts.BackupLiveDashboardDataTests`

Expected: all tests pass.

- [x] **Step 5: Update README**

Document:
- Git is code-only.
- Dedicated local + OSS data backup command.
- Restore is manual: download/extract archive, stop service, replace `data/pnl.db` and selected JSON, restart.

- [x] **Step 6: Full focused verification**

Run:
- `python3 -m unittest tests.test_ops_scripts`
- `python3 scripts/ops/backup_live_dashboard_data.py --dry-run`
- `python3 scripts/ops/backup_live_dashboard_data.py --apply --pull-cloud-first --stamp verify-YYYYMMDD-HHMMSS`

- [ ] **Step 7: Commit**

Commit only plan, script, tests, and README.
