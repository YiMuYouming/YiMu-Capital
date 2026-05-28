# 云端实盘闭环运维手册

> 适用对象：洋米、稳米、欧米、紫米。  
> 当前主库：hermes 云端 `/home/agentuser/YiMu-Capital/data/pnl.db`。  
> 本地副本：`/Users/yimu/Documents/YM_Capital/live-dashboard/data/pnl.db`。
> 当前日期基线：2026-05-28 跑通云端生产 + 本地预览 + 收盘回流闭环。

## 一句话原则

- 代码走 git：`YiMu-Capital` 和 `YM-data-pipeline` 的代码改动必须 commit/push/pull。
- 实盘数据不走 git：`data/*.db`、盘中快照、收益曲线、交易流水用 SQLite backup + rsync/scp。
- 盘中以云端为主：主人浏览器 `localhost:8088` 当前通过 SSH tunnel 看 hermes。
- 本地只做预览：`localhost:18088` 用本地代码看效果，但 API 和数据读云端，写操作被代理拦截。
- 收盘后把云端主库拉回本地归档，避免本地 DB 落后。
- 复盘笔记在本地：云端没有主人本地 Vault，不能独立生成明日基线；生成后要把 JSON 同步上云。

## 关键机器和路径

| 项 | 值 |
| --- | --- |
| 云端 SSH | `agentuser@43.132.146.234` |
| 云端项目 | `/home/agentuser/YiMu-Capital` |
| 云端 pipeline | `/home/agentuser/YM-data-pipeline` |
| 云端服务 | `yimu-live-dashboard.service` |
| 本地项目 | `/Users/yimu/Documents/YM_Capital/live-dashboard` |
| 本地 tunnel | `ssh -fN -L 8088:127.0.0.1:8088 agentuser@43.132.146.234` |
| 本地预览 | `http://localhost:18088` |

## 当前生产形态

### 云端生产 8088

`http://localhost:8088` 是主人盘中使用的生产看板。它不是本地服务，而是 SSH tunnel 转发到 hermes：

```bash
ssh -fN -L 8088:127.0.0.1:8088 agentuser@43.132.146.234
```

生产写入范围：

- W15 成交录入、纠错、账户状态写到云端 `data/pnl.db`。
- PnL 曲线、盘中快照、情绪节点由云端 APScheduler 持续生成。
- 主人电脑休眠、浏览器关闭后，云端服务仍会继续跑。

云端限制：

- hermes 香港节点不能稳定使用 PyTDX 裸 TCP，因此生产服务默认禁用 PyTDX。
- 云端没有主人本地复盘笔记 Vault，不能自己跑完整 `gen_dashboard_data.py`。
- 云端实时行情使用 Eastmoney/Tencent/iwencai/hot_list 等 fallback。足够保证账户曲线和关键节点不断，但部分精细字段会降级。

### 本地预览 18088

`http://localhost:18088` 用于改组件和看样式。它加载本地文件，但 `/api/*` 和关键 `/data/*.json` 读云端生产数据。

规则：

- 可以用它验证前端改动。
- 不在这里录真实交易。
- 代理会拦截 `POST`、`PUT`、`DELETE`，避免误写云端。
- 改完确认无误后，走 git 推送，再部署到云端 8088。

### 可选本地完整服务

需要本地 PyTDX 对照时，可以另起端口，例如：

```bash
cd /Users/yimu/Documents/YM_Capital/live-dashboard
python3 scripts/bridge.py 18089
```

这只用于诊断，不作为生产账本。除非明确决定切回本地生产，否则不要在本地完整服务里录真实交易。

## 每日开盘前流程

推荐使用自动化脚本（默认 dry-run，加 `--apply` 才执行）：

```bash
cd /Users/yimu/Documents/YM_Capital/live-dashboard
python3 scripts/ops/open_day.py --dry-run     # 预览步骤
python3 scripts/ops/open_day.py --apply        # 执行生成+同步
python3 scripts/ops/open_day.py --apply --restart-cloud  # 同步后重启云端
```

### 1. 本地生成今日基线（手动备选）

复盘笔记是 SSOT。交易日 D 的 W12 连板池、W13 趋势池来自 D-1 晚上的复盘笔记；交易日 D 当晚写的复盘笔记用于 D+1。

```bash
cd /Users/yimu/Documents/YM_Capital/live-dashboard
python3 scripts/gen_dashboard_data.py
```

验收重点：

- `data/dashboard_data.json` 生成成功。
- `meta.pools_note_date` 指向上一交易日复盘笔记。
- W12/W13 自选池和上一交易日复盘笔记附件一致。

可用命令：

```bash
python3 - <<'PY'
import json
from pathlib import Path

data = json.loads(Path("data/dashboard_data.json").read_text())
meta = data.get("meta", {})
print("generated_at:", meta.get("generated_at"))
print("pools_note:", meta.get("pools_note"))
print("pools_note_date:", meta.get("pools_note_date"))
print("lianban:", len(data.get("lianban_pool", [])))
print("trend:", len(data.get("trend_pool", [])))
PY
```

### 2. 同步今日基线上云（手动备选）

```bash
cd /Users/yimu/Documents/YM_Capital/live-dashboard
rsync -avz --backup \
  data/dashboard_data.json \
  data/pools.json \
  agentuser@43.132.146.234:/home/agentuser/YiMu-Capital/data/
```

云端重新载入：

```bash
ssh agentuser@43.132.146.234 'sudo systemctl restart yimu-live-dashboard.service'
```

### 3. 开盘前验收

```bash
ssh agentuser@43.132.146.234 'set -e
curl -s http://127.0.0.1:8088/api/baseline | python3 -m json.tool | head -80
curl -s http://127.0.0.1:8088/api/account/state
curl -s http://127.0.0.1:8088/api/pnl/summary'
```

通过条件：

- API 返回 JSON，不是空文件或错误页。
- 持仓和现金与主人确认口径一致。
- PnL summary 有日初锚点。
- W12/W13 池子来自上一交易日复盘笔记。

## 盘中操作流程

### 主人做买卖

1. 浏览器使用 `http://localhost:8088`。
2. 在 W15/W17 的既有入口录入成交。
3. 录完立即验收云端账户：

```bash
ssh agentuser@43.132.146.234 'set -e
curl -s http://127.0.0.1:8088/api/account/state
curl -s "http://127.0.0.1:8088/api/trades/review?date=$(date +%F)"
curl -s http://127.0.0.1:8088/api/pnl/summary'
```

不要在 18088 或本地完整服务里录真实交易，除非当天已经明确切换生产账本。

### 主人要外出或电脑休眠

只要 hermes 服务还 active，云端会继续：

- 记录 PnL 曲线。
- 生成盘中快照。
- 采集 iwencai/hot_list 等数据。
- 保留成交和账户状态。

主人本地电脑关机只会影响：

- 本地预览 18088。
- 本地 PyTDX 对照。
- 本地复盘笔记生成。

### 盘中改组件

1. 本地改代码。
2. 打开 `http://localhost:18088` 看效果。
3. 本地验证通过后 commit/push。
4. 云端 pull 或 code-only checkout。
5. 重启 `yimu-live-dashboard.service`。
6. 用 8088 验收生产效果。

## 云端数据源降级说明

云端目前不能把 PyTDX 作为唯一实时源。生产口径如下：

| 数据 | 云端来源 | 状态 |
| --- | --- | --- |
| 持仓、现金、交易流水 | `pnl.db` SSOT | 生产主口径 |
| PnL 曲线 | 云端 snapshots + 账户 SSOT | 生产主口径 |
| 指数和全市场成交额 | Eastmoney/Tencent fallback | 可用 |
| 涨跌家数 | fallback breadth | 可用，但不是完整 10 档分布 |
| 涨停榜 | hot_list collector | 可用，重启后需等首轮采集 |
| 情绪指标 | iwencai collector | 可用，重启后需等首轮采集 |
| 15minK/部分 PyTDX 字段 | PyTDX | 云端降级或不可用 |

W04 当前展示规则：

- 成交额对比显示 `昨日 +x%` 或 `昨日 -x%`，不再展示容易误解的差额。
- 云端只有 up/down 时，只显示 `涨 N / 跌 M`，不显示一排 0 档位。
- 涨跌停缺数据时显示 `—/—`，不再显示误导性的 `0/6`。
- 昨日收盘基线的指数卡片始终保留；缺值显示 `—`。

如果以后需要完整 PyTDX 体验，优先方案是独立国内行情中转或国内云节点。不要让主人本机作为长期生产中转，否则主人电脑休眠后仍会断。

## 每日收盘同步流程

推荐使用自动化脚本（默认 dry-run，加 `--apply` 才执行）：

```bash
cd /Users/yimu/Documents/YM_Capital/live-dashboard
python3 scripts/ops/close_day.py --dry-run     # 预览步骤
python3 scripts/ops/close_day.py --apply        # 执行备份+同步
```

### 1. 先确认云端服务和 API 正常（手动备选）

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

如果云端因为本地运行数据或临时改动导致 `git pull --ff-only` 失败，不要 `git reset --hard`。先看差异：

```bash
ssh agentuser@43.132.146.234 'cd /home/agentuser/YiMu-Capital && git status --short'
```

仅代码热修可以用 code-only checkout：

```bash
ssh agentuser@43.132.146.234 'set -e
cd /home/agentuser/YiMu-Capital
git fetch origin main
git checkout origin/main -- widgets/market-overview.js
sudo systemctl restart yimu-live-dashboard.service
curl -s http://127.0.0.1:8088/api/health'
```

把 `widgets/market-overview.js` 换成实际改动文件。不要把 `data/*` 放进这个命令。

## 常用验收命令

### 生产服务

```bash
ssh agentuser@43.132.146.234 'set -e
systemctl is-active yimu-live-dashboard.service
curl -s http://127.0.0.1:8088/api/health'
```

### 账户和收益曲线

```bash
ssh agentuser@43.132.146.234 'set -e
curl -s http://127.0.0.1:8088/api/account/state
curl -s http://127.0.0.1:8088/api/pnl/summary
curl -s "http://127.0.0.1:8088/api/pnl?range=today&index=sh" | python3 -m json.tool | head -80'
```

### W04 市场全景

```bash
ssh agentuser@43.132.146.234 'curl -s http://127.0.0.1:8088/api/live/quotes > /tmp/quotes.json && python3 - <<'"'"'PY'"'"'
import json
q = json.load(open("/tmp/quotes.json"))
li = q.get("live_index", {})
print("成交额:", li.get("成交额"))
print("昨日成交额:", li.get("yesterday_compare", {}).get("amount"))
print("breadth:", li.get("breadth"))
print("hot_list total:", q.get("hot_list", {}).get("total"))
print("iwencai:", q.get("iwencai", {}))
PY'
```

判断：

- `成交额` 有值时，W04 顶部成交额卡片应显示。
- `yesterday_compare.amount` 有值时，应显示 `昨日 ±x%`。
- `breadth.up/down` 有值时，红绿条应显示涨跌家数。
- `hot_list` 或 `iwencai` 刚重启为空时，页面显示 `—` 是正常降级。

## 跨 Agent 交接模板

给任何一个米派看板任务时，尽量复制下面模板，避免上下文丢失：

```text
目标：
- （要修什么/查什么）

生产入口：
- 主人看 http://localhost:8088，这是 SSH tunnel 到 hermes 云端。
- 本地预览 http://localhost:18088 只看本地代码效果，不录真实交易。

路径：
- 本地：/Users/yimu/Documents/YM_Capital/live-dashboard
- 云端：agentuser@43.132.146.234:/home/agentuser/YiMu-Capital
- 服务：yimu-live-dashboard.service

硬规则：
- 代码走 git。
- data/*.db、dashboard_data.json、pools.json、盘中快照不走 git。
- 不要 git reset --hard。
- 不要在 18088 录真实交易。

验收：
- curl /api/health
- curl /api/account/state
- curl /api/pnl/summary
- 涉及 W04 时查 /api/live/quotes

交付：
- 说明改了哪些文件。
- 说明是否碰了云端服务。
- 说明是否碰了真实 data。
- 给出验证命令和结果。
```

## 不要做的事

- 不要把 `data/pnl.db` 提交到 git。
- 不要把 `data/dashboard_data.json`、`data/pools.json` 当作代码部署文件提交，除非任务明确要求版本化样例。
- 不要在云端直接跑依赖本地 Vault 的 `gen_dashboard_data.py`，云端没有复盘笔记源。
- 不要把主人本机 PyTDX 中转当成长期生产依赖。
- 不要为了让 `git pull` 成功而重置云端工作区，尤其不能误删云端运行数据。
- 不要把 18088 当生产入口。
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
