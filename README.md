# 弈沐资本数据看板 v3.1（稳定性收口）

## 打开方式

生产服务在 hermes 云端，本机通过 SSH tunnel 访问。

| 地址 | 用途 | 说明 |
|------|------|------|
| `http://localhost:8088` | 云端生产 | SSH tunnel → hermes `yimu-live-dashboard.service` |
| `http://localhost:18088` | 本地预览 | 只读代理，改组件看效果，不录真实交易 |
| `http://localhost:18089` | 本地诊断 | 可选完整服务，不默认录真实交易 |
| `file://index.html` | 离线查看 | 无实时 API，无成交录入 |

## 生产拓扑

```text
浏览器 localhost:8088
      ↓ SSH tunnel (-L 8088:127.0.0.1:8088)
hermes 43.132.146.234
   └─ systemd: yimu-live-dashboard.service
      └─ bridge.py 8088
         ├─ 实时行情/市场广度/涨跌停核心计数 → PyTDX（失败才走 Tencent/EM）
         ├─ 情绪值 → PyTDX 广度；收益/晋级/连板明细 → iwencai 语义增强
         ├─ 热榜/涨停梯队/W26 → hot_list + limit_up_detail
         └─ 竞价 → snapshot_auction 9:28
```

核心数据管线：

```text
复盘笔记(SSOT, D-1) → gen_dashboard_data.py → dashboard_data.json(每日基线)
PyTDX → bridge CACHE → /api/live/quotes + live_index + breadth
iwencai/pywencai → CACHE["iwencai"] → 仅补收益、晋级、连板等语义指标
hot_list + limit_up_detail → 涨停梯队 + W26 主攻方向
Codex 涨跌停日报 → data/limitboard_reports/latest.json → /api/live/quotes.limitboard_report → W21 盘后补充
account_baselines + trade_records + live quote → /api/account/state (账户 SSOT)
dashboard facts + health + tickets + freshness → /api/ai/context (Agent 只读事实包)
open_day.py/close_day.py → 开盘生成基线+rsync上云 / 收盘SQLite备份+拉回+review_source_packet+项目数据包备份
```

## 开盘前

每日开盘前必须刷新 baseline；这不是代码 push 的一部分。锚定股、连板池、趋势池来自复盘笔记生成的 `dashboard_data.json` / `pools.json`，不跑 `open_day.py` 就会继续显示旧数据。

推荐使用自动化脚本（默认 dry-run）：

```bash
cd ~/Documents/YM_Capital/live-dashboard
python3 scripts/ops/open_day.py --dry-run         # 预览步骤
python3 scripts/ops/open_day.py --apply            # 生成基线 + rsync 上云
python3 scripts/ops/open_day.py --apply --restart-cloud  # 同步后重启云端
```

### 自动晨间发布

仓库提供可审计的 macOS LaunchAgent 模板
`launchd/com.yimu.open-day.plist` 和安装器
`scripts/ops/install_open_day_launchagent.sh`。安装后每个工作日 08:55、09:05、09:15
各唤醒一次（plist 为 `Weekday=2..6` 的 15 个组合）；`scripts/ops/morning_publisher.py` 使用 Asia/Shanghai 和
`scripts.db.is_trading_day` 做交易日及 08:50–09:20 门禁，周末、节假日和其他时段
均 fail-safe skip。进入窗口后先 SSH 只读 GET `/api/ai/context`；今日
`rule_state.execution_plan_valid=true` 时返回 0，不重复发布，否则调用既有
`/opt/homebrew/bin/python3 scripts/ops/open_day.py --apply --restart-cloud`，再做同样的
日期/计划有效性回读。日志写入 `~/Library/Logs/yimu-open-day.log` 和
`~/Library/Logs/yimu-open-day.err.log`，锁文件在同一 Logs 目录，不写入仓库状态文件。

安装只管理 `com.yimu.open-day` 自有标签，不删除其他 LaunchAgent；安装器会先
`plutil -lint`，再 `launchctl bootstrap/kickstart`。脚本自身的交易日/时段门保证安装时
的立即唤醒不会在窗口外执行 production apply。

```bash
./scripts/ops/install_open_day_launchagent.sh
launchctl print "gui/$(id -u)/com.yimu.open-day"
```

手动备选：`python3 scripts/gen_dashboard_data.py` → `rsync` → `systemctl restart`。

开盘验收至少确认（日期绑定字段不允许从历史 ReviewNote 静默回填；只有 W12/W13 池子通过 `pools_note_date` 有意读取上一交易日终稿）：

```bash
curl -s http://127.0.0.1:8088/api/health | python3 -m json.tool
python3 - <<'PY'
import json
from urllib.request import urlopen

data = json.load(urlopen("http://127.0.0.1:8088/api/baseline", timeout=10))
print(data.get("meta", {}).get("note"))
print((data.get("meta", {}).get("field_sources") or {}).get("今日操作"))
print([x.get("标的") for x in (data.get("decision", {}).get("锚定股状态") or [])])
PY
```

## 收盘后

```bash
cd ~/Documents/YM_Capital/live-dashboard
python3 scripts/ops/close_day.py --dry-run   # 预览步骤
python3 scripts/ops/close_day.py --apply     # 云端备份 + 拉回本地 + review_source_packet + 项目专用数据包备份
```

需要生成涨跌停盘后日报并接入 W21 时，调用 Codex Skill
`$a-share-limitboard-report`。它从 8088 的 `limit_up_detail`、`limit_counts`、
`iwencai` 与 `hot_list` 生成 HTML，并写入独立的
`data/limitboard_reports/latest.json`。W21 始终优先使用盘中确认明细；日报只作盘后
汇总与历史补充，数量冲突时显式显示口径差异，不覆盖实时事实。

## 盘中

- **真实成交**只在 `http://localhost:8088`（云端生产）录入。
- **组件调试**在 `http://localhost:18088`（本地预览）看效果，只读不录。
- **监控**：顶栏健康标签表示 `正常 / 降级 / 阻断 / 无响应`。
- **数据源**：生产优先 PyTDX；实时情绪值、涨跌家数和涨跌停核心计数不调用问财。问财只补收益、晋级、连板等语义指标，失败时不覆盖 PyTDX 核心事实。

### 健康语义

| 顶栏标签 | 含义 |
|---------|------|
| 正常 | 无 critical 无 degraded，交易录入可用 |
| 降级 | 有 degraded（iwencai 过期/基准缺失等非关键问题），交易录入可用 |
| 阻断 | critical 故障（行情 dead/账户 error/锚点缺失），交易录入关闭 |
| 无响应 | API 不可达（云端服务或 SSH tunnel 中断） |

交易入口以 `/api/ai/context.decision_gate.allowed` 为唯一最终口径；`/api/health` 只说明服务健康与 freshness，不能授予交易权限。AI context 缺失时按阻断处理。不要把“降级”误判成“阻断”。

票据分两类：`ticket_purpose=execution` 才是执行票，并在成交 preview/confirm 两次重新校验当前 `decision_gate`；`ticket_purpose=post_trade_reconciliation` 只记录已发生的券商成交，状态是 `reconciliation_ready`，在 W24 单列为“成交补录”，永远不显示为“可执行”，且只能由弈沐确认。

## 代码 vs 数据

- **代码走 git**：本地先 `git commit`；需要部署云端时，再按确认后的 git/rsync 代码同步流程执行。
- **数据不走 git**：`data/pnl.db`、`data/dashboard_data.json`、盘中快照。
- **数据走项目专用备份**：`close_day.py --apply` 收盘后自动在本项目 `data/backups/live-dashboard-data/` 生成一致性 tar.gz，并上传 OSS。
  ```bash
  python3 scripts/ops/close_day.py --apply
  ```
- **收工前**：
  ```bash
  git status --short          # 确认代码干净
  git diff -- data/           # 确认数据未混入
  ```

### 数据备份与恢复

备份分三层，不重复承担同一个职责：

- **Hermes 生产数据**：`/home/agentuser/YiMu-Capital/data/` 是 8088 的主数据源，不能当成备份。生产误写、损坏、误删时，Hermes 会一起受影响。
- **WorkBuddy 全量 OSS**：适合整机/目录级灾备，范围大、恢复慢；live-dashboard 的日常数据包不挂在 WorkBuddy 全量流程里，避免和通用备份混在一起。
- **live-dashboard 专用数据包**：适合快速恢复收益曲线、成交记录和关键运行 JSON，是日常优先使用的数据恢复入口。

日常收盘只需要执行 `python3 scripts/ops/close_day.py --apply`。脚本会先在 hermes 创建 SQLite
一致性备份并拉回本地，再同步存在的运行 JSON，生成 WorkBuddy 复盘事实包，
最后自动调用项目专用数据包备份。
备份包会写到 `data/backups/live-dashboard-data/live-dashboard-data-<stamp>.tar.gz`，
同一个压缩包会上传到
`oss://ym-mac/yimu-capital/live-dashboard-data/`。

### 复盘事实包

Dashboard 3.0 到 Phase 3 收口后，收盘流程会生成：

```text
data/review_packets/YYYY-MM-DD/review_source_packet.json
```

这个文件给 Market Watch `market-watch-review` 和复盘自动填充流程读取，用于账户、PnL、持仓、成交、票据闭环、健康/新鲜度和 AI context 风险事实。它不进 git，也不是最终复盘 SSOT；最终日复盘与次日计划仍以 Vault 复盘笔记为准，W12/W13 仍读 Vault 复盘附录。

紧急情况下可用 `python3 scripts/ops/close_day.py --apply --skip-data-backup` 跳过最后的数据包备份。
需要临时补一份当前生产数据包时，再手动运行：

```bash
python3 scripts/ops/backup_live_dashboard_data.py --apply --pull-cloud-first --upload-oss
```

恢复时不要走 git。先停服务，解压备份包，把 `pnl.db` 和需要恢复的 JSON 放回
`data/`，再执行 SQLite `PRAGMA integrity_check`，最后重启服务。

## 依赖

- Python 3.11+，依赖见 `requirements.txt`
- 数据管道：`YM-data-pipeline`（`pip install -e`）
- 前端：GridStack.js v12（CDN），无 Node.js 依赖

## 运行环境检查

```bash
python3 scripts/check_runtime.py --health      # 运行中健康检查
python3 scripts/check_runtime.py --preflight   # 启动前检查
```

## API 端点

| 端点 | 方法 | 说明 | 频率 |
|------|------|------|------|
| `/api/health` | GET | 服务与关键数据健康状态（含 account_basis） | 实时 |
| `/api/account/state` | GET | 账户 SSOT 派生状态 | 实时 |
| `/api/account/audit` | GET | 账户基准审计（日初价/清仓缺口） | 实时 |
| `/api/pnl/summary` | GET | PnL 摘要（含 valuation_complete） | 实时 |
| `/api/pnl?range=today&index=sh` | GET | PnL 曲线 | 5min/日结 |
| `/api/live/quotes` | GET | 实时行情（含 iwencai、北向、热榜、W26 主攻方向） | 5s |
| `/api/ai/context` | GET | Agent 只读事实包（含唯一最终门禁 `decision_gate.v1`、健康/新鲜度/风险/票据/人审动作）；盘中票据优先读 `tickets` 字段 | 按需 |
| `/api/baseline` | GET | dashboard_data.json | 60s |
| `/api/sync` | POST | W15 单笔成交录入 | 随录 |
| `/api/trades/review?date=YYYY-MM-DD` | GET | W23 逐笔复盘 | 按需 |
| `/api/trade/tickets?date=YYYY-MM-DD` | GET | 只读票据列表；脚本/Agent 直接读取必须显式传当日日期，裸请求仅默认 today | 按需 |
| `/api/llm` | POST | AI 研判 | 15min/manual |

## 故障排查

| 症状 | 排查 |
|------|------|
| 看板白屏 | `curl localhost:8088/api/pnl/summary` |
| 顶栏显示"阻断" | `curl localhost:8088/api/ai/context` 查 `decision_gate`，再用 `/api/health` 拆解健康原因 |
| 顶栏显示"无响应" | 检查 SSH tunnel: `lsof -i :8088 \| grep ssh`；检查 hermes 服务: `systemctl is-active yimu-live-dashboard.service` |
| 洋米读不到事实包 | `curl -s localhost:8088/api/ai/context \| python3 -m json.tool`；失败再查 `/api/health` |
| 情绪数据空 | `/api/live/quotes` 是否有 `iwencai` 字段，iwencai collector 是否在跑 |
| W15 显示"基准不可用" | 核查隔夜标的是否缺 `_meta.day_start_prices` |
| 竞价面板无数据 | 9:28 过了吗？`auction_snapshot.json` mtime 今天？ |
| LLM 不触发 | `~/.claude/settings.json` 有 `ANTHROPIC_BASE_URL` 和 token 吗？ |
| PyTDX 字段缺失 | 已知限制（hermes 香港节点不稳定），走 Tencent/EM fallback |
| 成交录不进去 | 是否在 18088 上操作？本地预览只读，请用 8088 |

## 项目结构

```
live-dashboard/
├── index.html              # GridStack 画板
├── store.js                # DataStore 三层合并
├── widget-base.js          # 组件基类
├── widget-registry.js      # 26 组件注册表
├── widgets/                # W01-W26 组件
├── scripts/
│   ├── bridge.py           # HTTP 桥接 + APScheduler
│   ├── ops/                # 开/收盘自动化脚本
│   │   ├── open_day.py
│   │   ├── close_day.py
│   │   └── local_dev_proxy.py  # 18088 只读代理
│   ├── gen_dashboard_data.py
│   └── db.py
├── css/theme.css           # 全局主题
├── data/                   # 运行数据（不走 git）
└── docs/                   # 审计/计划/操作手册
```

## 文档入口

- `docs/ops/2026-05-28-cloud-data-sync-runbook.md` — 完整运维手册
- `docs/ops/three-end-code-sync-runbook.md` — 本地/GitHub/Hermes 三端一致代码流程
- `docs/audit/2026-05-28-v3.1-completion-baseline.md` — V3.1 完成基线
- `docs/audit/2026-06-20-dashboard-3-closeout.md` — Dashboard 3.0 Phase 3 收口基线
- `AGENTS.md` — 团队协作与任务派发

## 快捷键

| 键 | 功能 |
|----|------|
| R | 全局刷新 |
| P | 报数面板 |
| Ctrl+S | 保存布局 |
| Ctrl+Z | 撤销删除 |
| A | 打开组件面板 |
