#!/usr/bin/env python3
"""db.py — SQLite 数据库管理层（零依赖，Python 内置 sqlite3）

四张表：intraday_snapshots / daily_summary / trade_records / llm_insights
"""
import sqlite3, json, threading
from pathlib import Path
from datetime import datetime

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
    """线程本地连接，每个线程独立连接"""
    conn = getattr(_local, 'conn', None)
    if conn is None:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        _local.conn = conn
    return conn


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

    # today: 走 intraday_snapshots（5分钟粒度），填充完整时段9:30-15:00
    if range == 'today':
        rows = _exec(
            f"SELECT ts, pnl_pct, {idx_field} AS bm_pct, pos_pct, nav FROM intraday_snapshots WHERE date = ? ORDER BY ts",
            (today,))
        if not rows:
            last_date_row = _exec(
                "SELECT date FROM intraday_snapshots ORDER BY date DESC LIMIT 1")
            if last_date_row:
                today = last_date_row[0]['date']
                rows = _exec(
                    f"SELECT ts, pnl_pct, {idx_field} AS bm_pct, pos_pct, nav FROM intraday_snapshots WHERE date = ? ORDER BY ts",
                    (today,))

        # 生成完整时段标签 9:30-15:00（每5分钟），数据填充到对应位置
        full_labels = [f"{h:02d}:{m:02d}" for h, m in TRADING_SLOTS]

        # 行数据按时间索引（对齐到5分钟槽，超过15:00的卡到14:55）
        row_map = {}
        for r in rows:
            ts = r['ts']
            time_str = ts[-8:-3] if 'T' in ts else ts[-5:]
            try:
                h, m = int(time_str[:2]), int(time_str[3:5])
                m = (m // 5) * 5  # 对齐到5分钟
                if h * 60 + m > 14 * 60 + 55:
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
            'labels': labels,
            'portfolio': pnl_vals,
            'benchmark': bm_vals,
            'position': pos_vals,
            'nav': nav_vals,
        }

    # 计算 from_date / limit
    now = datetime.now()
    limit = None
    if range == 'week':
        limit = 5   # 最近5个交易日
    elif range == 'month':
        limit = 22  # 最近约1个月交易日
    elif range == 'quarter':
        limit = 60  # 近3个月≈60个交易日
    elif range == 'year':
        limit = 250  # 近1年≈250个交易日
    else:
        from_date = '2020-01-01'

    # 图表用 → 累积 TWR；抽屉用(all) → 保持原始日收益
    if range in ('week', 'month', 'quarter', 'year', 'all'):
        if limit:
            rows = _exec(f"""
                SELECT date, pnl_pct, {idx_field} AS bm_pct, pos_pct, nav
                FROM daily_summary ORDER BY date DESC LIMIT ?
            """, (limit,))
            rows = list(reversed(rows))  # 倒回日期升序
        else:
            rows = _exec(f"""
                SELECT date, pnl_pct, {idx_field} AS bm_pct, pos_pct, nav
                FROM daily_summary WHERE date >= ? ORDER BY date
            """, (from_date,))
        rows_list = [dict(r) for r in rows]

        # 追加今天的日内数据（如果今天还没收盘，daily_summary 里没有）
        if range != 'all' and not any(r['date'] == today for r in rows_list):
            today_rows = _exec(
                f"SELECT pnl_pct, {idx_field} AS bm_pct, pos_pct, nav FROM intraday_snapshots WHERE date = ? ORDER BY ts DESC LIMIT 1",
                (today,))
            if today_rows:
                tr = dict(today_rows[0])
                rows_list.append({
                    'date': today,
                    'pnl_pct': tr['pnl_pct'] or 0.0,
                    'bm_pct': tr['bm_pct'] or 0.0,
                    'pos_pct': tr['pos_pct'] or 0.0,
                    'nav': tr['nav'] or 1.0,
                })

        # 维持 rolling 窗口大小（追加今天后去掉最早的）
        if limit and len(rows_list) > limit:
            rows_list = rows_list[-limit:]

        labels = [r['date'][-5:] for r in rows_list]
        pnl_raw = [r['pnl_pct'] for r in rows_list]
        bm_raw = [r['bm_pct'] for r in rows_list]
        pos_vals = [r['pos_pct'] for r in rows_list]
        nav_vals = [r['nav'] for r in rows_list]

        # 'all' 给抽屉用 → 原始日收益（抽屉自己算 TWR）
        if range == 'all':
            return {
                'type': 'daily',
                'labels': labels,
                'portfolio': pnl_raw,
                'benchmark': bm_raw,
                'position': pos_vals,
                'nav': nav_vals,
                'dates': [r['date'] for r in rows_list],
            }

        # 其他 → 累积 TWR 曲线
        def to_cumulative(vals):
            cum = 1.0
            result = []
            for v in vals:
                cum *= (1 + float(v or 0) / 100)
                result.append(round((cum - 1) * 100, 4))
            return result

        return {
            'type': 'daily',
            'labels': labels,
            'portfolio': to_cumulative(pnl_raw),
            'benchmark': to_cumulative(bm_raw),
            'position': pos_vals,
            'nav': nav_vals,
            'dates': [r['date'] for r in rows_list],
    }


def query_pnl_summary():
    rows = _exec("SELECT * FROM daily_summary ORDER BY date DESC LIMIT 1")
    last = rows[0] if rows else None
    count_rows = _exec("SELECT COUNT(*) AS n FROM daily_summary")
    daily_n = count_rows[0]['n'] if count_rows else 0
    today_str = datetime.now().strftime('%Y-%m-%d')
    rows2 = _exec("SELECT COUNT(*) AS n FROM intraday_snapshots WHERE date = ?", (today_str,))
    intra_n = rows2[0]['n'] if rows2 else 0
    # 盘中有日内快照时，用最新的实时总资产
    today_asset = None
    today_mv = None
    if intra_n > 0:
        intra = _exec("SELECT ts, total_asset, mv FROM intraday_snapshots WHERE date = ? ORDER BY ts DESC LIMIT 2", (today_str,))
        # 取最新一条，但如果 mv 突跳 >50%（如清仓后错误重算），用上一条
        if intra:
            latest = intra[0]
            if len(intra) >= 2 and latest['mv'] and intra[1]['mv']:
                prev_mv = intra[1]['mv'] or 1
                if prev_mv > 0 and abs(latest['mv'] - prev_mv) / prev_mv > 0.5:
                    latest = intra[1]
            today_asset = latest['total_asset']
            today_mv = latest['mv']
    return {
        'last_nav': last['nav'] if last else 1.0,
        'last_date': last['date'] if last else None,
        'daily_count': daily_n,
        'today_snapshots': intra_n,
        'total_asset': today_asset if today_asset else (round(last['nav'] * last['deposit'], 1) if last else None),
        'mv': today_mv if today_mv else None,
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


if __name__ == '__main__':
    init_db()
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r['name'] for r in cur.fetchall()]
    conn.close()
    print(f"✅ 数据库就绪: {DB_PATH}  表: {tables}")
