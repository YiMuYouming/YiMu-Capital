# 云端实盘数据同步运维手册

> 适用对象：洋米、稳米、欧米。  
> 当前主库：hermes 云端 `/home/agentuser/YiMu-Capital/data/pnl.db`。  
> 本地副本：`/Users/yimu/Documents/YM_Capital/live-dashboard/data/pnl.db`。

## 一句话原则

- 代码走 git：`YiMu-Capital` 和 `YM-data-pipeline` 的代码改动必须 commit/push/pull。
- 实盘数据不走 git：`data/*.db`、盘中快照、收益曲线、交易流水用 SQLite backup + rsync/scp。
- 盘中以云端为主：主人浏览器 `localhost:8088` 当前通过 SSH tunnel 看 hermes。
- 收盘后把云端主库拉回本地归档，避免本地 DB 落后。

## 关键机器和路径

| 项 | 值 |
| --- | --- |
| 云端 SSH | `agentuser@43.132.146.234` |
| 云端项目 | `/home/agentuser/YiMu-Capital` |
| 云端 pipeline | `/home/agentuser/YM-data-pipeline` |
| 云端服务 | `yimu-live-dashboard.service` |
| 本地项目 | `/Users/yimu/Documents/YM_Capital/live-dashboard` |
| 本地 tunnel | `ssh -fN -L 8088:127.0.0.1:8088 agentuser@43.132.146.234` |

## 每日收盘同步流程

### 1. 先确认云端服务和 API 正常

```bash
ssh -o ConnectTimeout=30 -o ServerAliveInterval=15 agentuser@43.132.146.234 \
  'systemctl is-active yimu-live-dashboard.service &&
   curl -s http://127.0.0.1:8088/api/pnl/summary'
```

通过条件：

- 服务输出 `active`
- `/api/pnl/summary` 返回 JSON
- `valuation_complete` 为 `true`
- `quote_status` 为 `live` 或收盘后可接受的非缺失状态

### 2. 在云端生成 SQLite 一致性备份

不要直接拉正在写入的 `pnl.db`。先让云端 Python 用 SQLite backup API 复制一份一致性备份。

```bash
ssh agentuser@43.132.146.234 'cd /home/agentuser/YiMu-Capital && .venv/bin/python - <<'"'"'PY'"'"'
import sqlite3
from datetime import datetime
from pathlib import Path

src = Path("data/pnl.db")
dst = Path("data") / f"pnl.db.backup-close-{datetime.now():%Y%m%d-%H%M%S}"

source = sqlite3.connect(str(src))
target = sqlite3.connect(str(dst))
try:
    source.backup(target)
finally:
    target.close()
    source.close()

check = sqlite3.connect(str(dst))
try:
    result = check.execute("PRAGMA integrity_check").fetchone()[0]
finally:
    check.close()

print(dst)
print("integrity_check:", result)
if result.lower() != "ok":
    raise SystemExit(1)
PY'
```

记下输出的备份路径，例如：

```text
data/pnl.db.backup-close-20260528-150530
integrity_check: ok
```

### 3. 拉回本地

把上一步输出的备份文件替换到命令里的 `REMOTE_BACKUP`。

```bash
REMOTE_BACKUP="data/pnl.db.backup-close-YYYYMMDD-HHMMSS"
LOCAL_ROOT="/Users/yimu/Documents/YM_Capital/live-dashboard"

rsync -avz --backup \
  "agentuser@43.132.146.234:/home/agentuser/YiMu-Capital/${REMOTE_BACKUP}" \
  "${LOCAL_ROOT}/data/pnl.db"
```

说明：

- `--backup` 会给被覆盖的本地 `pnl.db` 留备份。
- 这一步是“云端主库覆盖本地副本”，不要反向同步。

### 4. 同步辅助 JSON

这些不是主账本，但影响本地看板和复盘体验。

```bash
LOCAL_ROOT="/Users/yimu/Documents/YM_Capital/live-dashboard"

rsync -avz --ignore-missing-args --backup \
  agentuser@43.132.146.234:/home/agentuser/YiMu-Capital/data/dashboard_data.json \
  agentuser@43.132.146.234:/home/agentuser/YiMu-Capital/data/pnl_history.json \
  agentuser@43.132.146.234:/home/agentuser/YiMu-Capital/data/sentiment_auto.json \
  agentuser@43.132.146.234:/home/agentuser/YiMu-Capital/data/auction_snapshot.json \
  agentuser@43.132.146.234:/home/agentuser/YiMu-Capital/data/ymwm_report.json \
  "${LOCAL_ROOT}/data/"
```

### 5. 本地验收

```bash
cd /Users/yimu/Documents/YM_Capital/live-dashboard
python3 - <<'PY'
import sqlite3
db = "data/pnl.db"
con = sqlite3.connect(db)
try:
    print("integrity_check:", con.execute("PRAGMA integrity_check").fetchone()[0])
    print("snapshots:", con.execute("SELECT count(*) FROM intraday_snapshots").fetchone()[0])
    print("trades:", con.execute("SELECT count(*) FROM trade_records").fetchone()[0])
finally:
    con.close()
PY
```

通过条件：

- `integrity_check: ok`
- `intraday_snapshots` 和 `trade_records` 能正常查询

## 盘中发现数据 bug 的处理流程

### 成交流水录错

1. 先确认当前浏览器是否看云端：

```bash
lsof -nP -iTCP:8088 -sTCP:LISTEN
```

如果监听进程是 `ssh -L 8088:127.0.0.1:8088 agentuser@43.132.146.234`，说明页面写入云端。

2. 优先在页面用系统已有“纠错/反向流水”能力处理。
3. 不要手改 SQLite。
4. 修完后查：

```bash
ssh agentuser@43.132.146.234 \
  'curl -s http://127.0.0.1:8088/api/account/state &&
   curl -s http://127.0.0.1:8088/api/pnl/summary'
```

### 日初基准价缺失

典型症状：W15 显示“基线不可用”。

处理方式：只用受控脚本 `scripts/repair_day_start_price.py`，先 dry-run，再 apply。必须使用已核验价格，不能用成本价替代。

```bash
cd /Users/yimu/Documents/YM_Capital/live-dashboard

python3 scripts/repair_day_start_price.py \
  --date YYYY-MM-DD \
  --code CODE \
  --price PRICE \
  --source "verified source description" \
  --reason "why this repair is needed"
```

dry-run 通过后，本地 apply：

```bash
python3 scripts/repair_day_start_price.py \
  --date YYYY-MM-DD \
  --code CODE \
  --price PRICE \
  --source "verified source description" \
  --reason "why this repair is needed" \
  --apply
```

云端也要 apply：

```bash
ssh agentuser@43.132.146.234 'cd /home/agentuser/YiMu-Capital && .venv/bin/python scripts/repair_day_start_price.py \
  --date YYYY-MM-DD \
  --code CODE \
  --price PRICE \
  --source "verified source description" \
  --reason "why this repair is needed" \
  --apply && sudo systemctl restart yimu-live-dashboard.service'
```

验收：

```bash
ssh agentuser@43.132.146.234 \
  'curl -s http://127.0.0.1:8088/api/pnl/summary'
```

看 `closed_positions` 或 `positions` 中对应股票的 `realized_today_pnl` / `today_pnl` 不再为 `null`。

## 代码 bug 的处理流程

代码 bug 不直接改云端文件。流程：

1. 本地改代码。
2. 本地跑相关测试。
3. commit。
4. push 到 GitHub。
5. 云端 pull。
6. 重启服务。
7. 查 API 验收。

示例：

```bash
cd /Users/yimu/Documents/YM_Capital/live-dashboard
python3 -m unittest tests.test_account_ssot -v
git add PATHS
git commit -m "fix: short description"
git push origin main

ssh agentuser@43.132.146.234 'set -e
cd /home/agentuser/YiMu-Capital
git pull --ff-only origin main
sudo systemctl restart yimu-live-dashboard.service
systemctl is-active yimu-live-dashboard.service
curl -s http://127.0.0.1:8088/api/health'
```

如果 bug 在 `YM-data-pipeline`：

```bash
cd /Users/yimu/Documents/YM_Capital/YM-data-pipeline
python3 -m unittest discover tests -v
git add PATHS
git commit -m "fix: short description"
git push origin main

ssh agentuser@43.132.146.234 'set -e
cd /home/agentuser/YM-data-pipeline
git pull --ff-only origin main
cd /home/agentuser/YiMu-Capital
.venv/bin/pip install -e /home/agentuser/YM-data-pipeline
sudo systemctl restart yimu-live-dashboard.service
curl -s http://127.0.0.1:8088/api/health'
```

## 不要做的事

- 不要把 `data/pnl.db` 提交到 git。
- 不要用成本价伪造 `day_start_price`。
- 不要盘中把本地旧 DB 覆盖到云端。
- 不要直接 `scp` 正在写入的 SQLite 主库，除非先停服务或使用 SQLite backup。
- 不要在真实 8088 上做压力测试、批量 POST 或实验性修复。

## 当前已知云端差异

- hermes 无法稳定使用 PyTDX，服务已配置 `YIMU_DISABLE_PYTDX=1`。
- 云端实时行情走腾讯 fallback，足够支撑持仓估值和 PnL 曲线。
- PyTDX 专属细项可能弱于本地，包括部分均线、量比、K 线细节。
- 云端 AI 配置若缺 token，`llm_config` 会显示 `missing`，不影响 PnL 采集。

## 交付回报模板

```text
状态：DONE / BLOCKED
执行人：洋米 / 稳米 / 欧米
时间：

做了什么：
- 

关键命令：
- 

验证结果：
- systemctl:
- /api/health:
- /api/pnl/summary:
- SQLite integrity_check:

是否触碰真实数据：
- 是/否
- 触碰文件：
- 备份路径：

剩余风险：
- 
```
