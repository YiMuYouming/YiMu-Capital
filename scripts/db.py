#!/usr/bin/env python3
"""db.py — SQLite 数据库管理层（零依赖，Python 内置 sqlite3）

核心表：account_baselines / trade_records / intraday_snapshots / daily_summary / llm_insights
"""
import re
import sqlite3, json, threading, sys
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "pnl.db"

# 交易时段常量
TRADING_HOUR_START = (9, 30)
TRADING_HOUR_END = (15, 0)
TRADING_SLOTS = [(h, m)
    for h in (9, 10, 11, 13, 14)
    for m in (0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55)
    if not (h == 15 and m > 0) and not (h == 9 and m < 30) and not (h == 11 and m >= 30)]

_local = threading.local()

def get_conn():
    """线程本地连接，每个线程独立连接。

    若当前线程已持有连接但 DB_PATH 已变更（如测试隔离），自动关闭旧连接。
    """
    conn = getattr(_local, 'conn', None)
    if conn is not None:
        try:
            actual_path = conn.execute("PRAGMA database_list").fetchone()[2]
            if actual_path != str(DB_PATH):
                conn.close()
                _local.conn = None
        except Exception:
            _local.conn = None
    if getattr(_local, 'conn', None) is None:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        _local.conn = conn
    return conn


def close_conn():
    """显式关闭当前线程的 SQLite 连接，并清空 thread-local 引用。

    在 HTTP 请求结束时调用，避免连接随线程累积。
    WAL 模式下的检查点由下次连接自动恢复。
    """
    conn = getattr(_local, 'conn', None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        finally:
            delattr(_local, 'conn')


def _exec(sql, params=None):
    """便捷执行：连接 → cursor → execute → fetchall（复用连接，不关闭）"""
    conn = get_conn()
    cur = conn.cursor()
    if params:
        cur.execute(sql, params)
    else:
        cur.execute(sql)
    rows = cur.fetchall()
    conn.commit()
    return rows


def _exec_write(sql, params=None):
    conn = get_conn()
    cur = conn.cursor()
    if params: cur.execute(sql, params)
    else: cur.execute(sql)
    conn.commit()


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS intraday_snapshots (
            ts          TEXT PRIMARY KEY,
            date        TEXT NOT NULL,
            pnl_pct     REAL NOT NULL DEFAULT 0,
            nav         REAL NOT NULL DEFAULT 1,
            sh_pct      REAL NOT NULL DEFAULT 0,
            sz_pct      REAL NOT NULL DEFAULT 0,
            cy_pct      REAL NOT NULL DEFAULT 0,
            pos_pct     REAL NOT NULL DEFAULT 0,
            mv          REAL NOT NULL DEFAULT 0,
            total_asset REAL NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_snap_date ON intraday_snapshots(date);

        CREATE TABLE IF NOT EXISTS account_baselines (
            date            TEXT PRIMARY KEY,
            effective_at    TEXT NOT NULL,
            trade_id_cutoff INTEGER NOT NULL DEFAULT 0,
            cash            REAL NOT NULL DEFAULT 0,
            day_start_asset REAL NOT NULL DEFAULT 0,
            total_deposit   REAL NOT NULL DEFAULT 0,
            positions_json  TEXT NOT NULL DEFAULT '[]',
            source          TEXT NOT NULL DEFAULT 'recovery',
            _meta_json      TEXT,
            created_at      TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS daily_summary (
            date        TEXT PRIMARY KEY,
            nav         REAL NOT NULL DEFAULT 1,
            pnl_pct     REAL NOT NULL DEFAULT 0,
            sh_pct      REAL NOT NULL DEFAULT 0,
            sz_pct      REAL NOT NULL DEFAULT 0,
            cy_pct      REAL NOT NULL DEFAULT 0,
            pos_pct     REAL NOT NULL DEFAULT 0,
            deposit     REAL NOT NULL DEFAULT 0,
            max_dd      REAL,
            max_dd_start TEXT,
            max_dd_end   TEXT
        );

        CREATE TABLE IF NOT EXISTS trade_records (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            trade_date  TEXT NOT NULL,
            trade_time  TEXT,
            action      TEXT NOT NULL,
            code        TEXT NOT NULL,
            name        TEXT NOT NULL,
            price       REAL,
            qty         INTEGER,
            window      TEXT,
            reason      TEXT,
            realized_pnl REAL,
            fee         REAL DEFAULT 0,
            reversal_of_id INTEGER,
            is_reversal INTEGER DEFAULT 0
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tr_uniq ON trade_records(trade_date, trade_time, code, action, price, qty);
        CREATE INDEX IF NOT EXISTS idx_tr_date ON trade_records(trade_date);
        CREATE INDEX IF NOT EXISTS idx_tr_code ON trade_records(code);

        CREATE TABLE IF NOT EXISTS llm_insights (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            date        TEXT NOT NULL,
            node        TEXT NOT NULL,
            text        TEXT,
            signals_json TEXT,
            verified    INTEGER DEFAULT 0,
            warnings    INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_llm_date ON llm_insights(date);

        CREATE TABLE IF NOT EXISTS fund_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            event_date  TEXT NOT NULL,
            event_type  TEXT NOT NULL,
            amount      REAL NOT NULL,
            balance_after REAL,
            note        TEXT,
            source      TEXT DEFAULT 'manual'
        );
        CREATE INDEX IF NOT EXISTS idx_fund_date ON fund_events(event_date);

        CREATE TABLE IF NOT EXISTS trade_tickets (
            ticket_id                   TEXT PRIMARY KEY,
            created_at                  TEXT DEFAULT (datetime('now','localtime')),
            updated_at                  TEXT DEFAULT (datetime('now','localtime')),
            trade_date                  TEXT NOT NULL,
            code                        TEXT NOT NULL,
            name                        TEXT,
            action_type                 TEXT NOT NULL,
            ticket_purpose              TEXT NOT NULL DEFAULT 'execution',
            status                      TEXT NOT NULL DEFAULT 'draft',
            window                      TEXT,
            trade_time                  TEXT,
            intent_text                 TEXT,
            rule_state_json             TEXT,
            market_snapshot_json        TEXT,
            account_snapshot_json       TEXT,
            max_qty                     INTEGER,
            max_amount                  REAL,
            stop_line                   REAL,
            expected_r                  REAL,
            missing_data_json           TEXT,
            blocking_rule_ids_json      TEXT,
            triggered_rule_ids_json     TEXT,
            account_day_return_pct      REAL,
            trade_return_pct            REAL,
            realized_pnl_pct            REAL,
            unrealized_pnl_pct          REAL,
            losing_account_days         INTEGER,
            losing_trades_streak        INTEGER,
            sellable_quantity           INTEGER,
            t1_risk_json                TEXT,
            human_override_reason       TEXT,
            funds_evidence_json         TEXT,
            style_score_raw             REAL,
            style_score_adjusted        REAL,
            style_adjustment_reason     TEXT,
            style_adjustment_approver   TEXT,
            style_script_version        TEXT,
            rule_pack_version           TEXT,
            rule_snapshot_hash          TEXT,
            today_execution_card_id     TEXT,
            funds_source_freshness      TEXT,
            funds_query_time            TEXT,
            funds_unit                  TEXT,
            eod_outcome_json            TEXT,
            linked_ticket_id            TEXT,
            close_reason                TEXT,
            review_note                 TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_ticket_date_status ON trade_tickets(trade_date, status);
        CREATE INDEX IF NOT EXISTS idx_ticket_code_date ON trade_tickets(code, trade_date);

        CREATE TABLE IF NOT EXISTS position_lots (
            lot_id              TEXT PRIMARY KEY,
            created_at          TEXT DEFAULT (datetime('now','localtime')),
            code                TEXT NOT NULL,
            name                TEXT,
            source_trade_id     INTEGER,
            source_ticket_id    TEXT,
            buy_date            TEXT NOT NULL,
            original_qty        INTEGER NOT NULL,
            open_qty            INTEGER NOT NULL,
            cost_price          REAL,
            locked_until        TEXT,
            lot_source          TEXT,
            migration_source    TEXT,
            status              TEXT NOT NULL DEFAULT 'open'
        );
        CREATE INDEX IF NOT EXISTS idx_lot_code_status ON position_lots(code, status);
        CREATE INDEX IF NOT EXISTS idx_lot_locked_until ON position_lots(locked_until);

        CREATE TABLE IF NOT EXISTS trade_lot_allocations (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            sell_trade_id   INTEGER NOT NULL,
            lot_id          TEXT NOT NULL,
            qty             INTEGER NOT NULL,
            cost_price      REAL,
            sell_price      REAL,
            realized_pnl    REAL
        );
        CREATE INDEX IF NOT EXISTS idx_alloc_sell_trade ON trade_lot_allocations(sell_trade_id);

        CREATE TABLE IF NOT EXISTS pending_fill_confirmations (
            confirmation_id     TEXT PRIMARY KEY,
            created_at          TEXT DEFAULT (datetime('now','localtime')),
            expires_at          TEXT,
            ticket_id           TEXT NOT NULL,
            input_text          TEXT,
            parsed_entry_json   TEXT,
            preview_token       TEXT,
            preview_hash        TEXT,
            status              TEXT NOT NULL DEFAULT 'pending',
            confirmed_at        TEXT,
            confirmed_by        TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_pending_confirm_status ON pending_fill_confirmations(status, expires_at);

        CREATE TABLE IF NOT EXISTS ticket_conflict_log (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at          TEXT DEFAULT (datetime('now','localtime')),
            trade_date          TEXT NOT NULL,
            ticket_id           TEXT,
            code                TEXT,
            conflict_type       TEXT NOT NULL,
            severity            TEXT,
            expected_json       TEXT,
            actual_json         TEXT,
            resolution_status   TEXT NOT NULL DEFAULT 'open',
            note                TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_ticket_conflict ON ticket_conflict_log(trade_date, code, conflict_type);

        CREATE TABLE IF NOT EXISTS recommendation_observations (
            recommendation_id       TEXT PRIMARY KEY,
            trade_date              TEXT NOT NULL,
            observation_time        TEXT NOT NULL,
            code                    TEXT NOT NULL,
            disposition              TEXT NOT NULL,
            reference_price          REAL,
            rule_ids_json            TEXT NOT NULL DEFAULT '[]',
            blocking_codes_json      TEXT NOT NULL DEFAULT '[]',
            evidence_sha256          TEXT NOT NULL,
            executed_trade_id        INTEGER,
            manual_override_flag    INTEGER NOT NULL DEFAULT 0,
            close_1d                 REAL,
            close_2d                 REAL,
            close_5d                 REAL,
            mfe_1d_pct               REAL,
            mae_1d_pct               REAL,
            realized_r               REAL,
            outcome_status           TEXT NOT NULL DEFAULT 'pending',
            created_at               TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_recommendation_observation_date
            ON recommendation_observations(trade_date, observation_time);
        CREATE INDEX IF NOT EXISTS idx_recommendation_observation_code
            ON recommendation_observations(code, trade_date);
        CREATE TRIGGER IF NOT EXISTS recommendation_observations_no_update
            BEFORE UPDATE ON recommendation_observations
            BEGIN
                SELECT RAISE(ABORT, 'recommendation observations are immutable');
            END;
        CREATE TRIGGER IF NOT EXISTS recommendation_observations_no_delete
            BEFORE DELETE ON recommendation_observations
            BEGIN
                SELECT RAISE(ABORT, 'recommendation observations are immutable');
            END;
    """)
    columns = {row['name'] for row in conn.execute("PRAGMA table_info(account_baselines)").fetchall()}
    if 'trade_id_cutoff' not in columns:
        conn.execute("ALTER TABLE account_baselines ADD COLUMN trade_id_cutoff INTEGER NOT NULL DEFAULT 0")
    if '_meta_json' not in columns:
        conn.execute("ALTER TABLE account_baselines ADD COLUMN _meta_json TEXT")

    trade_cols = {row['name'] for row in conn.execute("PRAGMA table_info(trade_records)").fetchall()}
    for col, col_type in [
        ('reversal_of_id', 'INTEGER'),
        ('is_reversal', 'INTEGER DEFAULT 0'),
        ('rule_state_json', 'TEXT'),
        ('market_snapshot_json', 'TEXT'),
        ('outcome', "TEXT DEFAULT ''"),
        ('review_note', "TEXT DEFAULT ''"),
        ('event_id', 'TEXT'),
        ('context_captured_at', 'TEXT'),
        ('context_status', 'TEXT'),
        ('context_unavailable_reason', 'TEXT'),
        ('ticket_id', 'TEXT'),
        ('trade_group_id', 'TEXT'),
        ('leg_type', 'TEXT'),
        ('sellable_qty_before', 'INTEGER'),
        ('locked_until', 'TEXT'),
        ('input_source', 'TEXT'),
        ('input_text', 'TEXT'),
        ('confirmed_by', 'TEXT'),
        ('audit_note', 'TEXT'),
    ]:
        if col not in trade_cols:
            conn.execute(f"ALTER TABLE trade_records ADD COLUMN {col} {col_type}")
    ticket_cols = {row['name'] for row in conn.execute("PRAGMA table_info(trade_tickets)").fetchall()}
    if 'ticket_purpose' not in ticket_cols:
        conn.execute("ALTER TABLE trade_tickets ADD COLUMN ticket_purpose TEXT NOT NULL DEFAULT 'execution'")
    if 'trade_time' not in ticket_cols:
        conn.execute("ALTER TABLE trade_tickets ADD COLUMN trade_time TEXT")
    # Drop old unconditional unique index; replace with conditional ones
    conn.execute("DROP INDEX IF EXISTS idx_tr_uniq")
    conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_tr_uniq
        ON trade_records(trade_date, trade_time, code, action, price, qty)
        WHERE event_id IS NULL OR event_id = ''""")
    conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_tr_event_id
        ON trade_records(event_id) WHERE event_id IS NOT NULL AND event_id <> ''""")
    conn.commit()


# ===== 账户锚点 =====

def insert_account_baseline(data):
    conn = get_conn()
    cur = conn.cursor()
    _meta = data.get("_meta")
    cur.execute("""INSERT OR IGNORE INTO account_baselines
        (date, effective_at, trade_id_cutoff, cash, day_start_asset, total_deposit, positions_json, source, _meta_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (data['date'], data['effective_at'], data.get('trade_id_cutoff', 0), data.get('cash', 0),
         data.get('day_start_asset', 0), data.get('total_deposit', 0),
         json.dumps(data.get('positions', []), ensure_ascii=False),
         data.get('source', 'recovery'),
         json.dumps(_meta, ensure_ascii=False) if _meta else None))
    inserted = cur.rowcount > 0
    conn.commit()
    return inserted


def query_account_baseline(date_str):
    rows = _exec("SELECT * FROM account_baselines WHERE date = ?", (date_str,))
    if not rows:
        return None
    result = dict(rows[0])
    result['positions'] = json.loads(result.pop('positions_json') or '[]')
    meta_raw = result.pop('_meta_json', None)
    if meta_raw:
        try:
            result['_meta'] = json.loads(meta_raw)
        except (json.JSONDecodeError, TypeError):
            pass
    return result


def query_last_trade_id(date_str):
    rows = _exec("SELECT MAX(id) AS last_id FROM trade_records WHERE trade_date = ?", (date_str,))
    return int(rows[0]['last_id'] or 0) if rows else 0


# ===== 交易票据 =====

TICKET_STATUSES = {
    "draft",
    "blocked",
    "executable",
    "confirmed",
    "partially_filled",
    "filled",
    "cancelled",
    "closed",
    "closed_with_conflict",
    "audit_degraded",
    "manual_review",
    "guarded_experiment",
    "reconciliation_ready",
}

TICKET_PURPOSES = {"execution", "post_trade_reconciliation"}

TICKET_JSON_COLUMNS = {
    "rule_state_json",
    "market_snapshot_json",
    "account_snapshot_json",
    "missing_data_json",
    "blocking_rule_ids_json",
    "triggered_rule_ids_json",
    "t1_risk_json",
    "funds_evidence_json",
    "eod_outcome_json",
}


def _ticket_columns(conn=None):
    conn = conn or get_conn()
    return {row["name"] for row in conn.execute("PRAGMA table_info(trade_tickets)").fetchall()}


def _json_text(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _parse_ticket_row(row):
    if not row:
        return None
    data = dict(row)
    for col in TICKET_JSON_COLUMNS:
        raw = data.get(col)
        if raw:
            try:
                data[col.replace("_json", "")] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
    return data


def _generate_ticket_id(conn, trade_date, code):
    date_key = str(trade_date).replace("-", "")
    code_key = str(code)
    prefix = f"TICKET-{date_key}-{code_key}"
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM trade_tickets WHERE ticket_id LIKE ?",
        (f"{prefix}%",),
    ).fetchone()
    seq = int(row["n"] or 0) + 1
    return f"{prefix}-{seq:04d}"


def create_trade_ticket(data):
    """Create a trade ticket and return its ticket_id."""
    conn = get_conn()
    cols = _ticket_columns(conn)
    payload = dict(data or {})
    status = payload.get("status", "draft")
    if status not in TICKET_STATUSES:
        raise ValueError(f"invalid ticket status: {status}")
    payload["status"] = status
    purpose = payload.get("ticket_purpose", "execution")
    if purpose not in TICKET_PURPOSES:
        raise ValueError(f"invalid ticket purpose: {purpose}")
    payload["ticket_purpose"] = purpose
    payload.setdefault("ticket_id", _generate_ticket_id(conn, payload["trade_date"], payload["code"]))

    insert_cols = []
    values = []
    for col, value in payload.items():
        if col not in cols:
            continue
        insert_cols.append(col)
        values.append(_json_text(value) if col in TICKET_JSON_COLUMNS else value)
    placeholders = ", ".join(["?"] * len(insert_cols))
    conn.execute(
        f"INSERT INTO trade_tickets ({', '.join(insert_cols)}) VALUES ({placeholders})",
        values,
    )
    conn.commit()
    return payload["ticket_id"]


def query_trade_ticket(ticket_id):
    row = get_conn().execute(
        "SELECT * FROM trade_tickets WHERE ticket_id = ?",
        (ticket_id,),
    ).fetchone()
    return _parse_ticket_row(row)


def query_trade_tickets(date_from=None, date_to=None, code=None, status=None, limit=100):
    clauses, params = [], []
    if date_from:
        clauses.append("trade_date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("trade_date <= ?")
        params.append(date_to)
    if code:
        clauses.append("code = ?")
        params.append(code)
    if status:
        clauses.append("status = ?")
        params.append(status)
    sql = "SELECT * FROM trade_tickets"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY trade_date DESC, created_at DESC, ticket_id DESC LIMIT ?"
    params.append(int(limit))
    return [_parse_ticket_row(row) for row in _exec(sql, params)]


def update_trade_ticket_status(ticket_id, status, close_reason=None, review_note=None):
    if status not in TICKET_STATUSES:
        raise ValueError(f"invalid ticket status: {status}")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE trade_tickets
        SET status = ?,
            close_reason = COALESCE(?, close_reason),
            review_note = COALESCE(?, review_note),
            updated_at = datetime('now','localtime')
        WHERE ticket_id = ?
    """, (status, close_reason, review_note, ticket_id))
    conn.commit()
    return cur.rowcount > 0


def link_trade_to_ticket(trade_id, ticket_id, trade_group_id, leg_type,
                         sellable_qty_before=None, locked_until=None):
    conn = get_conn()
    if not conn.execute("SELECT 1 FROM trade_tickets WHERE ticket_id = ?", (ticket_id,)).fetchone():
        return False
    cur = conn.cursor()
    cur.execute("""
        UPDATE trade_records
        SET ticket_id = ?,
            trade_group_id = ?,
            leg_type = ?,
            sellable_qty_before = ?,
            locked_until = ?
        WHERE id = ?
    """, (ticket_id, trade_group_id, leg_type, sellable_qty_before, locked_until, int(trade_id)))
    conn.commit()
    return cur.rowcount > 0


# ===== Position lots / T+1 =====

def _number(value):
    try:
        return float(str(value or 0).replace("股", ""))
    except (TypeError, ValueError):
        return 0.0


def _holiday_dates():
    path = ROOT / "data" / "trading_holidays.json"
    if not path.exists():
        return set()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if isinstance(raw, list):
        return {str(item) for item in raw}
    if isinstance(raw, dict):
        values = raw.get("holidays") or raw.get("dates") or []
        return {str(item) for item in values}
    return set()


def is_trading_day(date_str):
    day = datetime.strptime(str(date_str), "%Y-%m-%d").date()
    return day.weekday() < 5 and day.isoformat() not in _holiday_dates()


def previous_trade_date(date_str):
    day = datetime.strptime(str(date_str), "%Y-%m-%d").date() - timedelta(days=1)
    holidays = _holiday_dates()
    while day.weekday() >= 5 or day.isoformat() in holidays:
        day -= timedelta(days=1)
    return day.isoformat()


def next_trade_date(date_str):
    day = datetime.strptime(str(date_str), "%Y-%m-%d").date() + timedelta(days=1)
    holidays = _holiday_dates()
    while day.weekday() >= 5 or day.isoformat() in holidays:
        day += timedelta(days=1)
    return day.isoformat()


def create_lot_from_buy_trade(trade):
    if int(trade.get("is_reversal") or 0) == 1:
        return None
    action = str(trade.get("action") or "")
    if "买" not in action and "追涨" not in action:
        raise ValueError("create_lot_from_buy_trade requires a buy action")
    trade_id = int(trade.get("id") or trade.get("source_trade_id") or 0)
    if trade_id <= 0:
        raise ValueError("buy trade id is required")
    trade_date = str(trade.get("trade_date") or datetime.now().strftime("%Y-%m-%d"))
    code = str(trade.get("code") or "")
    qty = int(_number(trade.get("qty")))
    if not code or qty <= 0:
        raise ValueError("buy trade requires code and positive qty")
    lot_id = f"trade:{trade_id}"
    conn = get_conn()
    exists = conn.execute("SELECT 1 FROM position_lots WHERE lot_id = ?", (lot_id,)).fetchone()
    if exists:
        return lot_id
    conn.execute("""
        INSERT INTO position_lots
        (lot_id, code, name, source_trade_id, source_ticket_id, buy_date,
         original_qty, open_qty, cost_price, locked_until, lot_source,
         migration_source, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (lot_id, code, trade.get("name"), trade_id, trade.get("ticket_id"),
          trade_date, qty, qty, _number(trade.get("price")),
          next_trade_date(trade_date), "trade_record", None, "open"))
    conn.commit()
    return lot_id


def query_position_lots(code=None, status=None):
    clauses, params = [], []
    if code:
        clauses.append("code = ?")
        params.append(str(code))
    if status:
        clauses.append("status = ?")
        params.append(str(status))
    sql = "SELECT * FROM position_lots"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY buy_date ASC, created_at ASC, lot_id ASC"
    return [dict(row) for row in _exec(sql, params)]


def get_sellable_lots(code, trade_date):
    if not is_trading_day(trade_date):
        return []
    return [dict(row) for row in _exec("""
        SELECT * FROM position_lots
        WHERE code = ? AND status = 'open' AND open_qty > 0 AND locked_until <= ?
        ORDER BY buy_date ASC, created_at ASC, lot_id ASC
    """, (str(code), str(trade_date)))]


def get_sellable_qty(code, trade_date):
    return sum(int(row.get("open_qty") or 0) for row in get_sellable_lots(code, trade_date))


def allocate_sell_to_lots(sell_trade, conn=None):
    if int(sell_trade.get("is_reversal") or 0) == 1:
        return []
    action = str(sell_trade.get("action") or "")
    if "卖" not in action:
        raise ValueError("allocate_sell_to_lots requires a sell action")
    sell_trade_id = int(sell_trade.get("id") or sell_trade.get("sell_trade_id") or 0)
    if sell_trade_id <= 0:
        raise ValueError("sell trade id is required")
    trade_date = str(sell_trade.get("trade_date") or datetime.now().strftime("%Y-%m-%d"))
    code = str(sell_trade.get("code") or "")
    sell_qty = int(_number(sell_trade.get("qty")))
    sell_price = _number(sell_trade.get("price"))
    target_lot_id = str(sell_trade.get("target_lot_id") or "").strip()
    if not code or sell_qty <= 0:
        raise ValueError("sell trade requires code and positive qty")
    if not is_trading_day(trade_date):
        raise ValueError(f"{trade_date} is not a trading day")

    owns_conn = conn is None
    conn = conn or get_conn()
    owns_tx = owns_conn and not conn.in_transaction
    allocations = []
    try:
        if owns_tx:
            conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM trade_lot_allocations WHERE sell_trade_id = ? ORDER BY id",
            (sell_trade_id,),
        ).fetchall()
        if existing:
            if owns_tx:
                conn.commit()
            return [dict(row) for row in existing]
        if target_lot_id:
            lots = [dict(row) for row in conn.execute("""
                SELECT * FROM position_lots
                WHERE lot_id = ? AND code = ? AND status = 'open'
                  AND open_qty > 0 AND locked_until <= ?
            """, (target_lot_id, code, trade_date)).fetchall()]
            if not lots:
                raise ValueError(f"target lot {target_lot_id} is not sellable for {code} on {trade_date}")
        else:
            lots = [dict(row) for row in conn.execute("""
                SELECT * FROM position_lots
                WHERE code = ? AND status = 'open' AND open_qty > 0 AND locked_until <= ?
                ORDER BY buy_date ASC, created_at ASC, lot_id ASC
            """, (code, trade_date)).fetchall()]
        sellable = sum(int(row["open_qty"] or 0) for row in lots)
        if sell_qty > sellable:
            raise ValueError(f"sell qty {sell_qty} exceeds sellable lot qty {sellable} for {code}")

        remaining = sell_qty
        for lot in lots:
            if remaining <= 0:
                break
            lot_qty = int(lot["open_qty"] or 0)
            alloc_qty = min(remaining, lot_qty)
            cost_price = _number(lot.get("cost_price"))
            realized = round((sell_price - cost_price) * alloc_qty, 2) if cost_price else None
            conn.execute("""
                INSERT INTO trade_lot_allocations
                (sell_trade_id, lot_id, qty, cost_price, sell_price, realized_pnl)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (sell_trade_id, lot["lot_id"], alloc_qty, cost_price, sell_price, realized))
            new_open_qty = lot_qty - alloc_qty
            conn.execute(
                "UPDATE position_lots SET open_qty = ?, status = ? WHERE lot_id = ?",
                (new_open_qty, "closed" if new_open_qty == 0 else "open", lot["lot_id"]),
            )
            allocations.append({
                "sell_trade_id": sell_trade_id,
                "lot_id": lot["lot_id"],
                "qty": alloc_qty,
                "cost_price": cost_price,
                "sell_price": sell_price,
                "realized_pnl": realized,
            })
            remaining -= alloc_qty
        if owns_tx:
            conn.commit()
        return allocations
    except Exception:
        if owns_tx:
            conn.rollback()
        raise


def _entry_get(entry, *keys, default=None):
    for key in keys:
        value = entry.get(key)
        if value not in (None, ""):
            return value
    return default


def _sellable_qty_in_tx(conn, code, trade_date):
    if not is_trading_day(trade_date):
        return 0
    row = conn.execute("""
        SELECT COALESCE(SUM(open_qty), 0) AS qty
        FROM position_lots
        WHERE code = ? AND status = 'open' AND open_qty > 0 AND locked_until <= ?
    """, (str(code), str(trade_date))).fetchone()
    return int(row["qty"] or 0) if row else 0


def record_confirmed_fill(entry, rule_state=None, market_snapshot=None, confirmation=None):
    """Atomically record a confirmed fill and apply lot effects."""
    conn = get_conn()
    evt_id = str(_entry_get(entry, "event_id", default="") or "")
    if evt_id:
        existing = conn.execute(
            "SELECT id, ticket_id FROM trade_records WHERE event_id = ?",
            (evt_id,),
        ).fetchone()
        if existing:
            return {
                "trade_id": int(existing["id"]),
                "ticket_id": existing["ticket_id"],
                "status": "idempotent",
            }

    ticket_id = str(_entry_get(entry, "ticket_id") or "")
    if not ticket_id:
        raise ValueError("ticket_id is required for confirmed fill")
    ticket = conn.execute("SELECT * FROM trade_tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
    if not ticket:
        raise ValueError(f"ticket not found: {ticket_id}")
    if str(ticket["status"]) not in {
        "executable", "confirmed", "partially_filled", "audit_degraded", "reconciliation_ready"
    }:
        raise ValueError(f"ticket {ticket_id} cannot accept fills in status {ticket['status']}")

    action = str(_entry_get(entry, "action", "动作") or "")
    code = str(_entry_get(entry, "code", "代码") or "")
    name = str(_entry_get(entry, "name", "标的") or "")
    qty = int(_number(_entry_get(entry, "qty", "数量")))
    price = _number(_entry_get(entry, "price", "价格"))
    trade_date = str(_entry_get(entry, "trade_date", default=ticket["trade_date"]) or ticket["trade_date"])
    trade_time = _entry_get(entry, "trade_time", "时间")
    if not code or qty <= 0 or price <= 0:
        raise ValueError("confirmed fill requires code, positive qty and positive price")

    is_buy = ("买" in action) or ("追涨" in action)
    is_sell = "卖" in action
    if not is_buy and not is_sell:
        raise ValueError(f"unsupported fill action: {action}")

    sellable_qty_before = None
    owns_tx = not conn.in_transaction
    try:
        if owns_tx:
            conn.execute("BEGIN IMMEDIATE")
        if is_sell:
            sellable_qty_before = _sellable_qty_in_tx(conn, code, trade_date)
            if qty > sellable_qty_before:
                raise ValueError(
                    f"sell qty {qty} exceeds sellable_qty_before {sellable_qty_before} for {code}")

        cur = conn.cursor()
        cur.execute("""INSERT INTO trade_records
            (trade_date, trade_time, action, code, name, price, qty, window, reason,
             realized_pnl, fee, reversal_of_id, is_reversal, rule_state_json,
             market_snapshot_json, event_id, context_captured_at, context_status,
             context_unavailable_reason, ticket_id, trade_group_id, leg_type,
             sellable_qty_before, locked_until, input_source, input_text,
             confirmed_by, audit_note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (trade_date, trade_time, action, code, name, price, qty,
             _entry_get(entry, "window", "窗口"),
             _entry_get(entry, "reason", "原因"),
             _entry_get(entry, "realized_pnl"),
             _entry_get(entry, "fee", default=0),
             _entry_get(entry, "reversal_of_id"),
             int(_entry_get(entry, "is_reversal", default=0) or 0),
             json.dumps(rule_state, ensure_ascii=False) if rule_state else None,
             json.dumps(market_snapshot, ensure_ascii=False) if market_snapshot else None,
             evt_id or None,
             (confirmation or {}).get("context_captured_at"),
             (confirmation or {}).get("context_status"),
             (confirmation or {}).get("context_unavailable_reason"),
             ticket_id,
             _entry_get(entry, "trade_group_id"),
             _entry_get(entry, "leg_type"),
             sellable_qty_before,
             _entry_get(entry, "locked_until"),
             _entry_get(entry, "input_source"),
             _entry_get(entry, "input_text"),
             _entry_get(entry, "confirmed_by"),
             _entry_get(entry, "audit_note")))
        trade_id = int(cur.lastrowid)

        if is_buy:
            locked_until = next_trade_date(trade_date)
            conn.execute("""
                INSERT INTO position_lots
                (lot_id, code, name, source_trade_id, source_ticket_id, buy_date,
                 original_qty, open_qty, cost_price, locked_until, lot_source,
                 migration_source, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (f"trade:{trade_id}", code, name, trade_id, ticket_id, trade_date,
                  qty, qty, price, locked_until, "trade_record", None, "open"))
            conn.execute(
                "UPDATE trade_records SET locked_until = ? WHERE id = ?",
                (locked_until, trade_id),
            )
        elif is_sell:
            allocations = allocate_sell_to_lots({
                "id": trade_id,
                "trade_date": trade_date,
                "action": action,
                "code": code,
                "price": price,
                "qty": qty,
                "target_lot_id": _entry_get(entry, "target_lot_id"),
                "is_reversal": _entry_get(entry, "is_reversal", default=0),
            }, conn=conn)
            realized_values = [a.get("realized_pnl") for a in allocations if a.get("realized_pnl") is not None]
            if realized_values:
                conn.execute(
                    "UPDATE trade_records SET realized_pnl = ? WHERE id = ?",
                    (round(sum(_number(v) for v in realized_values), 2), trade_id),
                )

        conn.execute(
            "UPDATE trade_tickets SET status = ?, updated_at = datetime('now','localtime') WHERE ticket_id = ?",
            ("filled", ticket_id),
        )
        if owns_tx:
            conn.commit()
        return {
            "trade_id": trade_id,
            "ticket_id": ticket_id,
            "status": "inserted",
            "sellable_qty_before": sellable_qty_before,
        }
    except sqlite3.IntegrityError:
        err = sys.exc_info()[1]
        if conn.in_transaction:
            conn.rollback()
        if evt_id:
            existing = conn.execute(
                "SELECT id, ticket_id FROM trade_records WHERE event_id = ?",
                (evt_id,),
            ).fetchone()
            if existing:
                return {
                    "trade_id": int(existing["id"]),
                    "ticket_id": existing["ticket_id"],
                    "status": "idempotent",
                }
        if "UNIQUE constraint failed" in str(err):
            return {
                "trade_id": None,
                "ticket_id": ticket_id,
                "status": "duplicate",
            }
        raise
    except Exception:
        if owns_tx:
            conn.rollback()
        raise


# ===== PnL 操作 =====

def insert_snapshot(data):
    _exec_write("""INSERT OR REPLACE INTO intraday_snapshots
        (ts, date, pnl_pct, nav, sh_pct, sz_pct, cy_pct, pos_pct, mv, total_asset)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (data['ts'], data['date'], data['pnl_pct'], data['nav'],
         data['sh_pct'], data['sz_pct'], data['cy_pct'], data['pos_pct'],
         data['mv'], data['total_asset']))


def insert_daily_summary(data):
    _exec_write("""INSERT OR REPLACE INTO daily_summary
        (date, nav, pnl_pct, sh_pct, sz_pct, cy_pct, pos_pct, deposit, max_dd, max_dd_start, max_dd_end)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (data['date'], data['nav'], data['pnl_pct'],
         data.get('sh_pct', 0), data.get('sz_pct', 0), data.get('cy_pct', 0),
         data.get('pos_pct', 0), data.get('deposit', 0),
         data.get('max_dd'), data.get('max_dd_start'), data.get('max_dd_end')))


def query_pnl(range='today', index='sh'):
    idx_map = {'sh': 'sh_pct', 'sz': 'sz_pct', 'cy': 'cy_pct'}
    idx_field = idx_map.get(index, 'sh_pct')
    today = datetime.now().strftime('%Y-%m-%d')
    now_dt = datetime.now()
    before_open = (now_dt.hour, now_dt.minute) < TRADING_HOUR_START

    # today: 走 intraday_snapshots（5分钟粒度），填充完整时段9:30-15:00
    if range == 'today':
        is_fallback = False
        rows = []
        if not is_trading_day(today) or before_open:
            fallback_date = previous_trade_date(today)
            rows = _exec(
                f"SELECT ts, pnl_pct, {idx_field} AS bm_pct, pos_pct, nav FROM intraday_snapshots WHERE date = ? ORDER BY ts",
                (fallback_date,))
            if rows:
                today = fallback_date
                is_fallback = True
        else:
            rows = _exec(
                f"SELECT ts, pnl_pct, {idx_field} AS bm_pct, pos_pct, nav FROM intraday_snapshots WHERE date = ? ORDER BY ts",
                (today,))
        if not rows:
            last_date_row = _exec(
                "SELECT date FROM intraday_snapshots WHERE date < ? ORDER BY date DESC LIMIT 1",
                (today,))
            if last_date_row:
                today = last_date_row[0]['date']
                is_fallback = True
                rows = _exec(
                    f"SELECT ts, pnl_pct, {idx_field} AS bm_pct, pos_pct, nav FROM intraday_snapshots WHERE date = ? ORDER BY ts",
                    (today,))

        # 生成完整时段标签 9:30-15:00（每5分钟），数据填充到对应位置
        full_labels = [f"{h:02d}:{m:02d}" for h, m in TRADING_SLOTS]

        # 行数据按时间索引（对齐到5分钟槽，超过15:00的卡到14:55）
        row_map = {}
        for r in rows:
            ts = r['ts']
            # 兼容无时区和 +08:00 时区的 ts 格式
            if 'T' in ts:
                time_part = ts.split('T')[1]
                time_str = time_part[:5]  # HH:MM
            else:
                time_str = ts[-5:]
            try:
                h, m = int(time_str[:2]), int(time_str[3:5])
                m = (m // 5) * 5  # 对齐到5分钟
                minute_of_day = h * 60 + m
                if 11 * 60 + 30 <= minute_of_day < 13 * 60:
                    h, m = 11, 25  # 午休补写/校正 → 上午最后有效槽
                elif minute_of_day > 14 * 60 + 55:
                    h, m = 14, 55  # 超出收盘时间 → 卡到最后槽
                time_key = f"{h:02d}:{m:02d}"
            except (ValueError, IndexError):
                time_key = time_str
            # 保留最新值（同槽多条取最后一条）
            row_map[time_key] = r

        labels, pnl_vals, bm_vals, pos_vals, nav_vals = [], [], [], [], []
        has_data = False
        for lbl in full_labels:
            labels.append(lbl)
            r = row_map.get(lbl)
            if r:
                has_data = True
                pnl_vals.append(r['pnl_pct'] or 0.0)
                bm_vals.append(r['bm_pct'] or 0.0)
                pos_vals.append(r['pos_pct'] or 0.0)
                nav_vals.append(r['nav'] or 1.0)
            elif not has_data:
                # 有数据之前：填0作为起点基线
                pnl_vals.append(0.0)
                bm_vals.append(0.0)
                pos_vals.append(0.0)
                nav_vals.append(1.0)
            else:
                # 最后一笔数据之后：null = 未发生的未来时间
                pnl_vals.append(None)
                bm_vals.append(None)
                pos_vals.append(None)
                nav_vals.append(None)

        return {
            'type': 'intraday',
            'data_date': today,
            'is_fallback': is_fallback,
            'labels': labels,
            'portfolio': pnl_vals,
            'benchmark': bm_vals,
            'position': pos_vals,
            'nav': nav_vals,
            '_updated': rows[-1]['ts'] if rows else None,
        }

    # 计算 from_date / limit
    now = datetime.now()
    limit = None
    from_date = '2020-01-01'
    if range == 'week':
        limit = 5   # 最近5个交易日
    elif range == 'month':
        limit = 22  # 最近约1个月交易日
    elif range == 'quarter':
        limit = 60  # 近3个月≈60个交易日
    elif range == 'year':
        limit = 250  # 近1年≈250个交易日

    # 图表用 → 累积 TWR；抽屉用(all) → 保持原始日收益
    if range in ('week', 'month', 'quarter', 'year', 'all'):
        rows = _exec(f"""
            SELECT date, pnl_pct, {idx_field} AS bm_pct, pos_pct, nav
            FROM daily_summary WHERE date >= ? ORDER BY date
        """, (from_date,))
        rows_list = [dict(r) for r in rows]

        # Closing-account rollup can persist daily_summary before index fields
        # are finalized.  When daily index values are still zero, recover them
        # from the same day's latest intraday snapshot so week/month benchmark
        # curves do not flatten.
        if rows_list:
            row_dates = [r['date'] for r in rows_list]
            placeholders = ",".join("?" for _ in row_dates)
            intraday_rows = _exec(
                f"""
                SELECT date, {idx_field} AS bm_pct
                FROM intraday_snapshots
                WHERE date IN ({placeholders})
                ORDER BY date, ts
                """,
                tuple(row_dates))
            intraday_bm_by_date = {}
            for r in intraday_rows:
                intraday_bm_by_date[r['date']] = r['bm_pct']
            for r in rows_list:
                bm_from_intraday = intraday_bm_by_date.get(r['date'])
                if bm_from_intraday is None:
                    continue
                if r['date'] == today or float(r.get('bm_pct') or 0.0) == 0.0:
                    r['bm_pct'] = bm_from_intraday or 0.0

        # Daily rollup may be written before market fields are finalized.  For
        # today, prefer the latest intraday snapshot for index/position fields.
        today_rows = _exec(
            f"SELECT pnl_pct, {idx_field} AS bm_pct, pos_pct, nav FROM intraday_snapshots WHERE date = ? ORDER BY ts DESC LIMIT 1",
            (today,))
        if today_rows:
            tr = dict(today_rows[0])
            for r in rows_list:
                if r['date'] == today:
                    r['bm_pct'] = tr['bm_pct'] or 0.0
                    r['pos_pct'] = tr['pos_pct'] or r.get('pos_pct') or 0.0
                    r['nav'] = tr['nav'] or r.get('nav') or 1.0
                    break

        # 追加今天的日内数据（如果今天还没收盘，daily_summary 里没有）
        if range != 'all' and not any(r['date'] == today for r in rows_list):
            if today_rows:
                tr = dict(today_rows[0])
                rows_list.append({
                    'date': today,
                    'pnl_pct': tr['pnl_pct'] or 0.0,
                    'bm_pct': tr['bm_pct'] or 0.0,
                    'pos_pct': tr['pos_pct'] or 0.0,
                    'nav': tr['nav'] or 1.0,
                })

        display_rows = rows_list[-limit:] if limit else rows_list
        labels = [r['date'][-5:] for r in display_rows]
        bm_raw = [r['bm_pct'] for r in display_rows]
        pos_vals = [r['pos_pct'] for r in display_rows]
        nav_vals = [r['nav'] for r in display_rows]

        def nav_returns(rows_for_nav):
            vals = []
            prev_nav = None
            for r in rows_for_nav:
                nav = float(r.get('nav') or 1.0)
                if prev_nav is None or prev_nav <= 0:
                    vals.append(0.0)
                else:
                    vals.append(round((nav / prev_nav - 1) * 100, 4))
                prev_nav = nav
            return vals

        pnl_calc = nav_returns(rows_list)
        pnl_raw = pnl_calc[-len(display_rows):] if display_rows else []

        # 'all' 给抽屉用 → 原始日收益（抽屉自己算 TWR）
        if range == 'all':
            return {
                'type': 'daily',
                'labels': labels,
                'portfolio': pnl_raw,
                'benchmark': bm_raw,
                'position': pos_vals,
                'nav': nav_vals,
                'dates': [r['date'] for r in display_rows],
            }

        # 其他 → 当前周期内累积 TWR 曲线。不要截取全历史累计 NAV，
        # 否则周/月/三月 KPI 会都显示同一个累计收益终值。
        def to_cumulative(vals):
            cum = 1.0
            result = []
            for v in vals:
                cum *= (1 + float(v or 0) / 100)
                result.append(round((cum - 1) * 100, 4))
            return result

        pnl_cumulative = to_cumulative(pnl_raw)
        bm_cumulative = to_cumulative(bm_raw)
        return {
            'type': 'daily',
            'labels': labels,
            'portfolio': pnl_cumulative,
            'benchmark': bm_cumulative,
            'position': pos_vals,
            'nav': nav_vals,
            'dates': [r['date'] for r in display_rows],
    }


def query_pnl_summary():
    rows = _exec("SELECT * FROM daily_summary ORDER BY date DESC LIMIT 1")
    last = rows[0] if rows else None
    count_rows = _exec("SELECT COUNT(*) AS n FROM daily_summary")
    daily_n = count_rows[0]['n'] if count_rows else 0
    today_str = datetime.now().strftime('%Y-%m-%d')
    rows2 = _exec("SELECT COUNT(*) AS n FROM intraday_snapshots WHERE date = ?", (today_str,))
    intra_n = rows2[0]['n'] if rows2 else 0
    snapshot_date = today_str
    snapshot_n = intra_n
    now_dt = datetime.now()
    before_open = (now_dt.hour, now_dt.minute) < TRADING_HOUR_START
    use_previous_snapshot = not is_trading_day(today_str) or before_open
    if use_previous_snapshot:
        prev_date = previous_trade_date(today_str)
        prev_rows = _exec("SELECT COUNT(*) AS n FROM intraday_snapshots WHERE date = ?", (prev_date,))
        prev_n = prev_rows[0]['n'] if prev_rows else 0
        if prev_n > 0:
            snapshot_date = prev_date
            snapshot_n = prev_n
    elif snapshot_n == 0:
        prev_date = previous_trade_date(today_str)
        prev_rows = _exec("SELECT COUNT(*) AS n FROM intraday_snapshots WHERE date = ?", (prev_date,))
        prev_n = prev_rows[0]['n'] if prev_rows else 0
        if prev_n > 0 and before_open:
            snapshot_date = prev_date
            snapshot_n = prev_n
    effective_today_snapshots = intra_n if snapshot_date == today_str and not use_previous_snapshot else 0
    # 盘中有日内快照时，用最新的实时总资产
    today_asset = None
    today_mv = None
    today_pnl_pct = None
    updated = None
    if snapshot_n > 0:
        intra = _exec("SELECT ts, total_asset, mv, pnl_pct FROM intraday_snapshots WHERE date = ? ORDER BY ts DESC LIMIT 2", (snapshot_date,))
        # 取最新一条，但如果 mv 突跳 >50%（如清仓后错误重算），用上一条
        if intra:
            latest = intra[0]
            if len(intra) >= 2 and latest['mv'] and intra[1]['mv']:
                prev_mv = intra[1]['mv'] or 1
                if prev_mv > 0 and abs(latest['mv'] - prev_mv) / prev_mv > 0.5:
                    latest = intra[1]
            today_asset = latest['total_asset']
            today_mv = latest['mv']
            updated = latest['ts']
            today_pnl_pct = latest['pnl_pct']
    day_start_asset = None
    try:
        with open(ROOT / "data" / "pnl_history.json") as f:
            pnl_meta = json.load(f).get("meta", {})
        if pnl_meta.get("day_start_date") == today_str:
            day_start_asset = pnl_meta.get("day_start_asset")
    except Exception:
        pass
    return {
        'last_nav': last['nav'] if last else 1.0,
        'last_date': last['date'] if last else None,
        'daily_count': daily_n,
        'today_snapshots': effective_today_snapshots,
        'total_asset': today_asset if today_asset is not None else (round(last['nav'] * last['deposit'], 1) if last else None),
        'mv': today_mv if today_mv is not None else None,
        'pnl_amount': round(today_asset - day_start_asset, 1) if (today_asset is not None and day_start_asset is not None) else None,
        'pnl_pct': today_pnl_pct,
        'day_start_asset': day_start_asset,
        '_updated': updated or (f"{last['date']}T15:00:00+08:00" if last else None),
    }


# ===== 交易记录 =====

def insert_trade(data):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""INSERT OR IGNORE INTO trade_records (trade_date, trade_time, action, code, name, price, qty, window, reason, realized_pnl, fee, reversal_of_id, is_reversal)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (data.get('trade_date', datetime.now().strftime('%Y-%m-%d')),
         data.get('trade_time'), data['action'], data['code'], data['name'],
         data.get('price'), data.get('qty'), data.get('window'),
         data.get('reason'), data.get('realized_pnl'), data.get('fee', 0),
         data.get('reversal_of_id'), int(data.get('is_reversal', 0))))
    inserted = cur.rowcount > 0
    conn.commit()
    return inserted


def insert_trade_with_context(data, rule_state=None, market_snapshot=None, context_captured_at=None, context_status=None, context_unavailable_reason=None):
    """插入成交并绑定后端可信上下文。event_id 有唯一约束，并发冲突由 DB 处理。

    卖出动作在 BEGIN IMMEDIATE 事务内原子校验可用数量，防止并发超卖。
    返回 (inserted: bool, trade_id: int|None, status: 'inserted'|'idempotent')
    """
    conn = get_conn()
    cur = conn.cursor()
    evt_id = data.get('event_id')
    action = str(data.get('action') or '')
    is_sell = '卖' in action
    start_immediate = is_sell and (not evt_id or evt_id == '')

    try:
        if is_sell:
            # 原子卖出门禁：BEGIN IMMEDIATE + 查库存 + 插入
            if not start_immediate:
                # 仍用 IMMEDIATE 确保库存检查和插入在同一事务
                conn.execute("BEGIN IMMEDIATE")

            sell_code = str(data.get('code') or '')
            sell_qty = int(data.get('qty') or 0)
            trade_date = str(data.get('trade_date') or datetime.now().strftime('%Y-%m-%d'))

            # 查询锚点持仓
            anchor_row = cur.execute(
                "SELECT positions_json FROM account_baselines WHERE date = ?",
                (trade_date,)).fetchone()
            anchor_qty = 0
            if anchor_row:
                positions = json.loads(anchor_row[0] or '[]')
                for p in positions:
                    if str(p.get('代码', '')) == sell_code:
                        anchor_qty = int(p.get('数量', 0) or 0)
                        break

            # 查询当日已成交 net qty（买入+追涨-卖出）
            net_row = cur.execute("""
                SELECT COALESCE(SUM(CASE WHEN action IN ('买入','W1追涨','W2买入')
                                    THEN qty ELSE -qty END), 0) AS net
                FROM trade_records
                WHERE trade_date = ? AND code = ?
            """, (trade_date, sell_code)).fetchone()
            net_traded = int(net_row[0]) if net_row else 0

            available = anchor_qty + net_traded
            if sell_qty > available:
                conn.rollback()
                raise ValueError(
                    f'sell qty {sell_qty} exceeds available {available} for {sell_code}')

        if evt_id and evt_id != '':
            cur.execute("""INSERT INTO trade_records
            (trade_date, trade_time, action, code, name, price, qty, window, reason,
             realized_pnl, fee, reversal_of_id, is_reversal,
             rule_state_json, market_snapshot_json, event_id, context_captured_at,
             context_status, context_unavailable_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (data.get('trade_date', datetime.now().strftime('%Y-%m-%d')),
             data.get('trade_time'), data['action'], data['code'], data['name'],
             data.get('price'), data.get('qty'), data.get('window'),
             data.get('reason'), data.get('realized_pnl'), data.get('fee', 0),
             data.get('reversal_of_id'), int(data.get('is_reversal', 0)),
             json.dumps(rule_state, ensure_ascii=False) if rule_state else None,
             json.dumps(market_snapshot, ensure_ascii=False) if market_snapshot else None,
             str(evt_id), context_captured_at,
             context_status, context_unavailable_reason))
            conn.commit()
            return True, cur.lastrowid, 'inserted'
        else:
            cur.execute("""INSERT OR IGNORE INTO trade_records
            (trade_date, trade_time, action, code, name, price, qty, window, reason,
             realized_pnl, fee, reversal_of_id, is_reversal,
             rule_state_json, market_snapshot_json, context_captured_at,
             context_status, context_unavailable_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (data.get('trade_date', datetime.now().strftime('%Y-%m-%d')),
             data.get('trade_time'), data['action'], data['code'], data['name'],
             data.get('price'), data.get('qty'), data.get('window'),
             data.get('reason'), data.get('realized_pnl'), data.get('fee', 0),
             data.get('reversal_of_id'), int(data.get('is_reversal', 0)),
             json.dumps(rule_state, ensure_ascii=False) if rule_state else None,
             json.dumps(market_snapshot, ensure_ascii=False) if market_snapshot else None,
             context_captured_at,
             context_status, context_unavailable_reason))
            conn.commit()
            inserted = cur.rowcount > 0
            return inserted, (cur.lastrowid if inserted else None), ('inserted' if inserted else 'duplicate')
    except sqlite3.IntegrityError:
        if evt_id and evt_id != '':
            try:
                existing = cur.execute(
                    "SELECT id FROM trade_records WHERE event_id = ?", (str(evt_id),)).fetchone()
                if existing:
                    conn.commit()
                    return False, existing[0], 'idempotent'
            except Exception:
                pass
        raise


def update_trade_outcomes(date_str, outcomes):
    """日结补写 outcome：仅写 outcome 列，不修改原成交事实/纠错链/锚点/资产。
    outcomes: {trade_id: outcome_text, ...}
    同时按 trade_date 约束，拒绝跨日误写。
    """
    conn = get_conn()
    cur = conn.cursor()
    for tid, outcome_text in outcomes.items():
        cur.execute(
            "UPDATE trade_records SET outcome = ? WHERE id = ? AND trade_date = ? AND outcome = ''",
            (str(outcome_text)[:500], int(tid), date_str))
    conn.commit()


def update_trade_review_note(trade_id, note_text):
    """事后写入 review_note（不修改资产/锚点/成交事实）。
    返回 True 表示实际更新到记录，False 表示 trade_id 不存在。
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE trade_records SET review_note = ? WHERE id = ?",
                (str(note_text)[:2000], int(trade_id)))
    conn.commit()
    return cur.rowcount > 0


def query_trade_reviews(date_str):
    """按日期读取逐笔复盘上下文（只读）。"""
    rows = _exec("""SELECT id, created_at, trade_date, trade_time, action, code, name,
        price, qty, window, reason, realized_pnl, fee, reversal_of_id, is_reversal,
        rule_state_json, market_snapshot_json, outcome, review_note,
        context_captured_at, context_status, context_unavailable_reason, ticket_id
        FROM trade_records WHERE trade_date = ? ORDER BY id""", (date_str,))
    results = []
    for r in rows:
        d = dict(r)
        for col in ('rule_state_json', 'market_snapshot_json'):
            raw = d.get(col)
            if raw:
                try:
                    d[col.replace('_json', '')] = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    pass
            d.pop(col, None)
        results.append(d)
    return results


def insert_correction_trade(original_trade_id, correction_action, correction_price, correction_qty, note):
    """冲销/修正一条已有成交：新增一条反向事件并标记 is_reversal=1。"""
    original = _exec("SELECT * FROM trade_records WHERE id = ?", (original_trade_id,))
    if not original:
        raise ValueError(f"Original trade {original_trade_id} not found")
    orig = original[0]
    reversal_action = "卖出" if ("买入" in str(orig["action"])) else "买入"
    if correction_action:
        reversal_action = correction_action
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""INSERT INTO trade_records
        (trade_date, trade_time, action, code, name, price, qty, window, reason, fee, reversal_of_id, is_reversal)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        (datetime.now().strftime('%Y-%m-%d'),
         datetime.now().strftime('%H:%M:%S'),
         reversal_action,
         orig["code"], orig["name"],
         correction_price if correction_price is not None else orig["price"],
         correction_qty if correction_qty is not None else orig["qty"],
         orig["window"],
         f"[纠错] {note} (原id={original_trade_id})",
         orig["fee"],
         original_trade_id))
    conn.commit()
    new_id = cur.lastrowid
    return new_id


def query_trades(date_from=None, date_to=None, limit=50):
    clauses, params = [], []
    if date_from: clauses.append("trade_date >= ?"); params.append(date_from)
    if date_to: clauses.append("trade_date <= ?"); params.append(date_to)
    sql = "SELECT * FROM trade_records"
    if clauses: sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY trade_date DESC, id DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in _exec(sql, params)]


# ===== 推荐观察（只追加、不可变） =====

RECOMMENDATION_OBSERVATION_COLUMNS = (
    'recommendation_id', 'trade_date', 'observation_time', 'code',
    'disposition', 'reference_price', 'rule_ids_json',
    'blocking_codes_json', 'evidence_sha256', 'executed_trade_id',
    'manual_override_flag', 'close_1d', 'close_2d', 'close_5d',
    'mfe_1d_pct', 'mae_1d_pct', 'realized_r', 'outcome_status',
)
_OBSERVATION_SHA256_RE = re.compile(r'^[0-9a-fA-F]{64}$')


def _observation_json_text(value, field_name):
    """Serialize a list/dict JSON field without retaining caller-owned objects."""
    if value is None:
        return '[]'
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f'{field_name} must contain valid JSON') from exc
    else:
        parsed = value
    return json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _normalize_recommendation_observation(data):
    payload = dict(data or {})
    missing = [
        field for field in (
            'recommendation_id', 'trade_date', 'observation_time', 'code',
            'disposition', 'evidence_sha256',
        ) if payload.get(field) in (None, '')
    ]
    if missing:
        raise ValueError(f'missing recommendation observation fields: {", ".join(missing)}')

    evidence_sha256 = str(payload['evidence_sha256']).strip().lower()
    if not _OBSERVATION_SHA256_RE.fullmatch(evidence_sha256):
        raise ValueError('evidence_sha256 must be a 64-character hexadecimal hash')

    rule_ids = payload.get('rule_ids_json', payload.get('rule_ids'))
    blocking_codes = payload.get('blocking_codes_json', payload.get('blocking_codes'))
    manual_override = payload.get('manual_override_flag', False)
    if isinstance(manual_override, str):
        manual_override = manual_override.strip().lower() in {'1', 'true', 'yes', 'y'}
    try:
        executed_trade_id = payload.get('executed_trade_id')
        if executed_trade_id not in (None, ''):
            executed_trade_id = int(executed_trade_id)
        else:
            executed_trade_id = None
    except (TypeError, ValueError) as exc:
        raise ValueError('executed_trade_id must be an integer or null') from exc

    normalized = {
        'recommendation_id': str(payload['recommendation_id']),
        'trade_date': str(payload['trade_date']),
        'observation_time': str(payload['observation_time']),
        'code': str(payload['code']),
        'disposition': str(payload['disposition']),
        'reference_price': payload.get('reference_price'),
        'rule_ids_json': _observation_json_text(rule_ids, 'rule_ids_json'),
        'blocking_codes_json': _observation_json_text(blocking_codes, 'blocking_codes_json'),
        'evidence_sha256': evidence_sha256,
        'executed_trade_id': executed_trade_id,
        'manual_override_flag': 1 if bool(manual_override) else 0,
        'close_1d': payload.get('close_1d'),
        'close_2d': payload.get('close_2d'),
        'close_5d': payload.get('close_5d'),
        'mfe_1d_pct': payload.get('mfe_1d_pct'),
        'mae_1d_pct': payload.get('mae_1d_pct'),
        'realized_r': payload.get('realized_r'),
        'outcome_status': str(payload.get('outcome_status') or 'pending'),
    }
    return normalized


def insert_recommendation_observation(data):
    """Append one recommendation observation; an existing id can never be updated."""
    payload = _normalize_recommendation_observation(data)
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO recommendation_observations
            (recommendation_id, trade_date, observation_time, code, disposition,
             reference_price, rule_ids_json, blocking_codes_json, evidence_sha256,
             executed_trade_id, manual_override_flag, close_1d, close_2d,
             close_5d, mfe_1d_pct, mae_1d_pct, realized_r, outcome_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            tuple(payload[column] for column in RECOMMENDATION_OBSERVATION_COLUMNS),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError as exc:
        existing = conn.execute(
            "SELECT * FROM recommendation_observations WHERE recommendation_id = ?",
            (payload['recommendation_id'],),
        ).fetchone()
        if existing:
            existing_payload = {
                column: existing[column]
                for column in RECOMMENDATION_OBSERVATION_COLUMNS
            }
            if existing_payload == payload:
                conn.commit()
                return False
            raise ValueError(
                f"recommendation observation is immutable: {payload['recommendation_id']}"
            ) from exc
        raise


def create_recommendation_observation(data):
    """Named constructor alias for callers that create a new observation."""
    return insert_recommendation_observation(data)


def _parse_observation_row(row):
    if not row:
        return None
    result = dict(row)
    for column, parsed_name in (
        ('rule_ids_json', 'rule_ids'),
        ('blocking_codes_json', 'blocking_codes'),
    ):
        try:
            result[parsed_name] = json.loads(result[column] or '[]')
        except (TypeError, json.JSONDecodeError):
            result[parsed_name] = []
    return result


def query_recommendation_observations(
    date_from=None, date_to=None, recommendation_id=None, code=None, limit=10000,
):
    """Read immutable recommendation observations without touching trade facts."""
    clauses, params = [], []
    if date_from:
        clauses.append('trade_date >= ?')
        params.append(date_from)
    if date_to:
        clauses.append('trade_date <= ?')
        params.append(date_to)
    if recommendation_id:
        clauses.append('recommendation_id = ?')
        params.append(recommendation_id)
    if code:
        clauses.append('code = ?')
        params.append(code)
    sql = 'SELECT * FROM recommendation_observations'
    if clauses:
        sql += ' WHERE ' + ' AND '.join(clauses)
    sql += ' ORDER BY trade_date ASC, observation_time ASC, recommendation_id ASC LIMIT ?'
    params.append(int(limit))
    return [_parse_observation_row(row) for row in _exec(sql, params)]


# ===== LLM 研判 =====

def insert_llm(node_date, node, text, signals=None, verified=0, warnings=0):
    sig = json.dumps(signals, ensure_ascii=False) if signals else None
    _exec_write("""INSERT INTO llm_insights (date, node, text, signals_json, verified, warnings)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (node_date, node, text, sig, verified, warnings))


def query_llm(date_str=None, limit=20):
    if date_str:
        rows = _exec("SELECT * FROM llm_insights WHERE date = ? ORDER BY created_at DESC LIMIT ?",
                     (date_str, limit))
    else:
        rows = _exec("SELECT * FROM llm_insights ORDER BY date DESC, created_at DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


# ===== 历史导入 =====

def import_daily_history(records):
    conn = get_conn()
    cur = conn.cursor()
    for r in records:
        cur.execute("""INSERT OR REPLACE INTO daily_summary (date, nav, pnl_pct, sh_pct, sz_pct, cy_pct, pos_pct, deposit)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (r['date'], r['nav'], r['pnl_pct'],
             r.get('sh_pct', 0), r.get('sz_pct', 0), r.get('cy_pct', 0),
             r.get('pos_pct', 0), r.get('deposit', 0)))
    conn.commit()


def import_trade_history(trades):
    conn = get_conn()
    cur = conn.cursor()
    for t in trades:
        cur.execute("""INSERT INTO trade_records (trade_date, action, code, name, price, qty, realized_pnl, fee)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (t.get('trade_date', ''), t.get('action', ''), t.get('code', ''),
             t.get('name', ''), t.get('price'), t.get('qty', 0),
             t.get('realized_pnl', 0), t.get('fee', 0)))
    conn.commit()


# ===== 资金事件 =====

FUND_EVENT_TYPES = frozenset(["入金", "出金", "手续费", "红利", "税费", "利息", "其他"])


def insert_fund_event(data):
    """追加一条资金事件记录。返回是否新插入（重复提交返回 False）。"""
    event_type = str(data.get("event_type", ""))
    if event_type not in FUND_EVENT_TYPES:
        raise ValueError(f"Invalid fund event type: {event_type}")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""INSERT INTO fund_events (event_date, event_type, amount, balance_after, note, source)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (data.get("event_date", datetime.now().strftime("%Y-%m-%d")),
         event_type,
         float(data.get("amount", 0)),
         data.get("balance_after"),
         data.get("note"),
         data.get("source", "manual")))
    inserted = cur.rowcount > 0
    conn.commit()
    return inserted


def query_fund_events(date_from=None, date_to=None, limit=100):
    clauses, params = [], []
    if date_from: clauses.append("event_date >= ?"); params.append(date_from)
    if date_to: clauses.append("event_date <= ?"); params.append(date_to)
    sql = "SELECT * FROM fund_events"
    if clauses: sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY event_date ASC, id ASC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in _exec(sql, params)]


def query_cumulative_deposit():
    """查询累计入金总额（所有入金事件 amount 之和）。"""
    rows = _exec("SELECT SUM(amount) AS total FROM fund_events WHERE event_type = '入金'")
    return float(rows[0]["total"] or 0) if rows else 0.0


if __name__ == '__main__':
    init_db()
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r['name'] for r in cur.fetchall()]
    conn.close()
    print(f"✅ 数据库就绪: {DB_PATH}  表: {tables}")
