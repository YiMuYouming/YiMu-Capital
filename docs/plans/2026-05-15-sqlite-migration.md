# SQLite 架构迁移 · 实施计划

**目标：** 将所有时序数据从 JSON/localStorage 迁移到统一 SQLite 数据库，一次性建好 schema，以后只扩表不动架构。

**日期：** 2026-05-15

---

## 架构总览

```
                     ┌─────────────────────┐
                     │     pnl.db (SQLite)  │
                     │                     │
    poll_live.py ───→│  intraday_snapshots  │←─── W22 pnl-curve.js
      (每60s)        │  daily_summary       │     (GET /api/pnl)
                     │  trade_records       │←─── W15 + W17
    bridge.py ──────→│  llm_insights        │←─── W20 llm-monitor
    POST /api/sync   │                     │
    POST /api/llm    └─────────────────────┘

    dashboard_data.json  (保留) → gen_dashboard_data.py → store.js Layer 1
    dashboard_live.json  (保留) → poll_live.py → store.js Layer 2
    localStorage         (保留) → W16 报数字段 (19 键值对)
```

## 数据库 Schema（4 表）

```sql
-- 表1: P&L 日内快照（poll_live.py 每60s写入）
CREATE TABLE IF NOT EXISTS intraday_snapshots (
    ts          TEXT PRIMARY KEY,        -- '2026-05-15T10:30:00'
    date        TEXT NOT NULL,           -- '2026-05-15'
    pnl_pct     REAL NOT NULL DEFAULT 0, -- 账户浮动盈亏%
    nav         REAL NOT NULL DEFAULT 1, -- TWR净值
    sh_pct      REAL NOT NULL DEFAULT 0, -- 上证涨幅%
    sz_pct      REAL NOT NULL DEFAULT 0, -- 深证涨幅%
    cy_pct      REAL NOT NULL DEFAULT 0, -- 创业涨幅%
    pos_pct     REAL NOT NULL DEFAULT 0, -- 仓位%
    mv          REAL NOT NULL DEFAULT 0, -- 持仓市值
    total_asset REAL NOT NULL DEFAULT 0  -- 总资产
);
CREATE INDEX IF NOT EXISTS idx_snap_date ON intraday_snapshots(date);

-- 表2: 日终汇总（poll_live.py 收盘写入）
CREATE TABLE IF NOT EXISTS daily_summary (
    date        TEXT PRIMARY KEY,        -- '2026-05-15'
    nav         REAL NOT NULL DEFAULT 1,
    pnl_pct     REAL NOT NULL DEFAULT 0,
    sh_pct      REAL NOT NULL DEFAULT 0,
    sz_pct      REAL NOT NULL DEFAULT 0,
    cy_pct      REAL NOT NULL DEFAULT 0,
    pos_pct     REAL NOT NULL DEFAULT 0,
    deposit     REAL NOT NULL DEFAULT 0, -- 当日入金
    max_dd      REAL,                    -- 日内最大回撤
    max_dd_start TEXT,                   -- 回撤起始时间
    max_dd_end   TEXT                    -- 回撤结束时间
);

-- 表3: 交易流水（W15 记流水 + W17 今日操作）
CREATE TABLE IF NOT EXISTS trade_records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT DEFAULT (datetime('now','localtime')),
    trade_date  TEXT NOT NULL,
    trade_time  TEXT,                    -- '09:35'
    action      TEXT NOT NULL,           -- '买入'/'卖出'/'W1追涨'/'W2买入'
    code        TEXT NOT NULL,
    name        TEXT NOT NULL,
    price       REAL,
    qty         INTEGER,
    window      TEXT,                    -- 'W1'/'W2'
    reason      TEXT,
    realized_pnl REAL,                   -- 实现盈亏（卖出时计算）
    fee         REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_trade_date ON trade_records(trade_date);
CREATE INDEX IF NOT EXISTS idx_trade_code ON trade_records(code);

-- 表4: LLM 研判
CREATE TABLE IF NOT EXISTS llm_insights (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT DEFAULT (datetime('now','localtime')),
    date        TEXT NOT NULL,
    node        TEXT NOT NULL,           -- '竞价'/'早盘'/'午盘'/'尾盘'/'收盘'
    text        TEXT,
    signals_json TEXT,                   -- JSON 数组字符串
    verified    INTEGER DEFAULT 0,
    warnings    INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_llm_date ON llm_insights(date);
```

---

## 实施任务（7 步，按依赖排序）

### 任务 1: 创建 SQLite 数据库 + 初始化模块

**文件：** 新建 `scripts/db.py`

**内容：** 数据库管理模块，封装所有 SQLite 操作。

```python
# scripts/db.py — SQLite 数据库管理层
import sqlite3, json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "pnl.db"

def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS intraday_snapshots (...);
        CREATE TABLE IF NOT EXISTS daily_summary (...);
        CREATE TABLE IF NOT EXISTS trade_records (...);
        CREATE TABLE IF NOT EXISTS llm_insights (...);
        -- indexes (见上面 schema)
    """)
    conn.commit()
    conn.close()

# P&L 操作
def insert_snapshot(data): ...
def insert_daily_summary(data): ...
def query_pnl(range, index='sh'): ...

# 交易操作
def insert_trade(data): ...
def query_trades(date_from=None, date_to=None): ...
def get_latest_trades(limit=50): ...

# LLM 操作
def insert_llm_insight(date, node, text, signals, verified, warnings): ...
def query_llm_by_date(date): ...
```

**验证：** `python3 -c "from scripts.db import init_db; init_db()"` → pnl.db 生成 4 张表。

---

### 任务 2: 迁移 poll_live.py → SQLite

**文件：** 修改 `scripts/poll_live.py:1182-1294` + 新增 `is_trading_time()`

**改动：**
1. 导入 `from scripts.db import insert_snapshot, insert_daily_summary`
2. `is_trading_time()` 函数（Mon-Fri, 9:30-15:00）
3. `log_pnl_snapshot()` → 调用 `insert_snapshot()`
4. 收盘时（15:00 过后首次检测）→ 调用 `rollup_to_daily()` → `insert_daily_summary()`
5. 删除写入 `pnl_history.json` 的逻辑

**验证：** poll_live.py --watch 运行 → 检查 pnl.db 有 intraday_snapshots 记录。

---

### 任务 3: 扩展 bridge.py → SQLite API

**文件：** 修改 `scripts/bridge.py`

**新增路由：**

```python
# GET /api/pnl?range=today|week|month|quarter|year&index=sh
def do_GET(self):
    if self.path.startswith('/api/pnl'):
        # 解析参数，调用 db.query_pnl()，返回 JSON
        pass
    elif self.path.startswith('/api/trades'):
        # 返回最近的交易记录
        pass
    else:
        super().do_GET()

# POST /api/sync 扩展：pnl 数据写 SQLite
# POST /api/llm 扩展：研判写 SQLite
```

**SQL 查询示例（range=today）：**

```sql
SELECT ts, pnl_pct, sh_pct, sz_pct, cy_pct, pos_pct, nav
FROM intraday_snapshots
WHERE date = '2026-05-15'
ORDER BY ts;
```

**return 格式（保持与现有 W22 兼容）：**

```json
{
  "type": "intraday",
  "labels": ["09:35", "09:40", ...],
  "portfolio": [0.00, 0.10, ...],
  "benchmark": [-0.05, -0.03, ...],
  "position": [42.0, 42.0, ...],
  "nav": [1.000, 1.001, ...]
}
```

**验证：** `curl http://localhost:8088/api/pnl?range=today` → 返回 JSON。

---

### 任务 4: 迁移 store.js + W22 pnl-curve.js → 走 API

**文件：**
- 修改 `store.js`：移除 `pnlData`/`fetchPNL`/`getPNL`
- 修改 `widgets/pnl-curve.js`：`render()` 中调用 `fetch('/api/pnl?range=' + period + '&index=' + index)` 替代 `DataStore.getPNL()`

**改动量：** store.js ~15 行删除，pnl-curve.js ~30 行修改。

**验证：** 浏览器打开看板 → W22 组件显示曲线（数据从 SQLite → bridge API）。

---

### 任务 5: 迁移 W15 + W17 交易流水 → SQLite

**文件：**
- 修改 `widgets/positions.js`：`_bridgeSync()` 改为 POST `/api/trades`（含完整交易记录字段）
- 修改 `widgets/today-ops.js`：同上
- 修改 `bridge.py`：`POST /api/trades` 写入 `trade_records` 表

**改动量：** 各 ~15 行修改。

**验证：** W15 记一笔流水 → 检查 pnl.db trade_records 有记录。

---

### 任务 6: 迁移 W20 LLM 研判 → SQLite

**文件：**
- 修改 `scripts/bridge.py`：`POST /api/llm` 改为调用 `db.insert_llm_insight()`
- 修改 `widgets/llm-monitor.js`：fetch llm_insights 从 JSON 改为 `/api/llm-insights?date=`
- 删除 `data/llm_insights.json`（可选保留作备份）

**改动量：** bridge.py ~5 行修改，llm-monitor.js ~10 行修改。

---

### 任务 7: 历史数据导入 + 清理

**文件：**
- 修改 `import_xlsx_pnl.py`：改为调用 `db.insert_daily_summary()`
- 运行导入脚本，将 Excel 交易历史写入 `trade_records`
- 删除 `data/pnl_history.json`（备份后删除）

**验证：** 导入后 `daily_summary` 表有 22 条历史记录，`trade_records` 表有 31 条。

---

## 文件变更总览

| 文件 | 动作 | 说明 |
|------|------|------|
| `scripts/db.py` | **新建** | SQLite 数据库管理模块 |
| `data/pnl.db` | **新建** | SQLite 数据库文件 |
| `scripts/poll_live.py` | 修改 | 写入 SQLite + 交易日门控 + 收盘 rollup |
| `scripts/bridge.py` | 修改 | 新增 GET /api/pnl, GET /api/trades, GET /api/llm-insights; POST 写 SQLite |
| `store.js` | 修改 | 移除 pnlData/fetchPNL 层 |
| `widgets/pnl-curve.js` | 修改 | fetch API 替代 DataStore.getPNL() |
| `widgets/positions.js` | 修改 | _bridgeSync 写 SQLite |
| `widgets/today-ops.js` | 修改 | 同上 |
| `widgets/llm-monitor.js` | 修改 | fetch API 替代直接读 JSON |
| `scripts/import_xlsx_pnl.py` | 修改 | 写 SQLite 替代 JSON |
| `data/pnl_history.json` | **删除** | 被 SQLite 替代 |
| `data/llm_insights.json` | **删除** | 被 SQLite 替代 |

---

## 非功能需求

- **不新增 Python 依赖**（sqlite3 内置）
- **不新增 JS 依赖**
- **file:// 协议兼容**：API 模式需要 bridge 运行；file:// 模式下 W22 降级显示「需要 bridge 服务」
- **向后兼容**：dashboard_data.json / dashboard_live.json / embedded-data.js 不变
