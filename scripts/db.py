#!/usr/bin/env python3
"""db.py — SQLite 数据库管理层（零依赖，Python 内置 sqlite3）

四张表：intraday_snapshots / daily_summary / trade_records / llm_insights
"""
import sqlite3, json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "pnl.db"


def _exec(sql, params=None):
    """便捷执行：连接 → cursor → execute → fetchall → 关闭"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if params:
        cur.execute(sql, params)
    else:
        cur.execute(sql)
    rows = cur.fetchall()
    conn.commit()
    conn.close()
    return rows


def _exec_write(sql, params=None):
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    if params: cur.execute(sql, params)
    else: cur.execute(sql)
    conn.commit()
    conn.close()


def init_db():
    conn = sqlite3.connect(str(DB_PATH))
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
            fee         REAL DEFAULT 0
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
    """)
    conn.commit()
    conn.close()


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

    # today: 走 intraday_snapshots（5分钟粒度），唯一保留的日内路径
    if range == 'today':
        rows = _exec(
            f"SELECT ts, pnl_pct, {idx_field} AS bm_pct, pos_pct, nav FROM intraday_snapshots WHERE date = ? ORDER BY ts",
            (today,))
        return {
            'type': 'intraday',
            'labels': [r['ts'][-8:-3] if 'T' in r['ts'] else r['ts'] for r in rows],
            'portfolio': [r['pnl_pct'] for r in rows],
            'benchmark': [r['bm_pct'] for r in rows],
            'position': [r['pos_pct'] for r in rows],
            'nav': [r['nav'] for r in rows],
        }

    # 计算 from_date
    now = datetime.now()
    day_of_week = now.weekday()
    if range == 'week':
        d = now.day - day_of_week
        from_date = now.replace(day=max(d, 1)).strftime('%Y-%m-%d')
    elif range == 'month':
        from_date = now.strftime('%Y-%m-01')
    elif range == 'quarter':
        m = ((now.month - 1) // 3) * 3 + 1
        from_date = f"{now.year}-{m:02d}-01"
    elif range == 'year':
        from_date = f"{now.year}-01-01"
    else:
        from_date = '2020-01-01'

    # week/month/quarter/year/all — 统一走 daily_summary（日频数据）
    # 前端拿到后自己做 TWR 连乘，避免 intraday_snapshots 的单日累积值歧义
    rows = _exec(f"""
        SELECT date, pnl_pct, {idx_field} AS bm_pct, pos_pct, nav
        FROM daily_summary WHERE date >= ? ORDER BY date
    """, (from_date,))
    rows_list = [dict(r) for r in rows]
    return {
        'type': 'daily',
        'labels': [r['date'][-5:] for r in rows_list],
        'portfolio': [r['pnl_pct'] for r in rows_list],
        'benchmark': [r['bm_pct'] for r in rows_list],
        'position': [r['pos_pct'] for r in rows_list],
        'nav': [r['nav'] for r in rows_list],
        'dates': [r['date'] for r in rows_list],
    }


def query_pnl_summary():
    rows = _exec("SELECT * FROM daily_summary ORDER BY date DESC LIMIT 1")
    last = rows[0] if rows else None
    count_rows = _exec("SELECT COUNT(*) AS n FROM daily_summary")
    daily_n = count_rows[0]['n'] if count_rows else 0
    rows2 = _exec("SELECT COUNT(*) AS n FROM intraday_snapshots WHERE date = ?",
                  (datetime.now().strftime('%Y-%m-%d'),))
    intra_n = rows2[0]['n'] if rows2 else 0
    return {
        'last_nav': last['nav'] if last else 1.0,
        'last_date': last['date'] if last else None,
        'daily_count': daily_n,
        'today_snapshots': intra_n,
    }


# ===== 交易记录 =====

def insert_trade(data):
    _exec_write("""INSERT OR IGNORE INTO trade_records (trade_date, trade_time, action, code, name, price, qty, window, reason, realized_pnl, fee)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (data.get('trade_date', datetime.now().strftime('%Y-%m-%d')),
         data.get('trade_time'), data['action'], data['code'], data['name'],
         data.get('price'), data.get('qty'), data.get('window'),
         data.get('reason'), data.get('realized_pnl'), data.get('fee', 0)))


def query_trades(date_from=None, date_to=None, limit=50):
    clauses, params = [], []
    if date_from: clauses.append("trade_date >= ?"); params.append(date_from)
    if date_to: clauses.append("trade_date <= ?"); params.append(date_to)
    sql = "SELECT * FROM trade_records"
    if clauses: sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY trade_date DESC, id DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in _exec(sql, params)]


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
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    for r in records:
        cur.execute("""INSERT OR REPLACE INTO daily_summary (date, nav, pnl_pct, sh_pct, sz_pct, cy_pct, pos_pct, deposit)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (r['date'], r['nav'], r['pnl_pct'],
             r.get('sh_pct', 0), r.get('sz_pct', 0), r.get('cy_pct', 0),
             r.get('pos_pct', 0), r.get('deposit', 0)))
    conn.commit()
    conn.close()


def import_trade_history(trades):
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    for t in trades:
        cur.execute("""INSERT INTO trade_records (trade_date, action, code, name, price, qty, realized_pnl, fee)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (t.get('trade_date', ''), t.get('action', ''), t.get('code', ''),
             t.get('name', ''), t.get('price'), t.get('qty', 0),
             t.get('realized_pnl', 0), t.get('fee', 0)))
    conn.commit()
    conn.close()


if __name__ == '__main__':
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r['name'] for r in cur.fetchall()]
    conn.close()
    print(f"✅ 数据库就绪: {DB_PATH}  表: {tables}")
