# 弈沐资本数据看板 v3.1（稳定性收口）

> Agent 协作入口。生产：`http://localhost:8088`（SSH tunnel → hermes）。
> 预览：`http://localhost:18088`（只读代理）。
> 诊断：`http://localhost:18089`（可选完整服务）。

## 最重要工作流：代码和数据分流

任何新窗口、新 agent、盘中排障或部署前，先按这个判断：

### 代码流程（本地 → GitHub → Hermes）

代码的 SSOT 是 Git。生产端只运行已提交、已推送的代码。

```bash
# 1. 本地改代码并验证
git status --short
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest <相关测试> -v
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q scripts tests
git diff --check

# 2. 本地提交并推送
git add <本次代码文件>
git commit -m "<说明>"
git push

# 3. Hermes 生产端拉代码并重启
ssh agentuser@43.132.146.234 'cd /home/agentuser/YiMu-Capital && git pull --ff-only'
ssh agentuser@43.132.146.234 'sudo systemctl restart yimu-live-dashboard.service'
```

验收：本地、GitHub、Hermes 三端 commit 一致，Hermes `git status --short` 干净，`8088` API 可用。

### 数据流程（Hermes → 本地 → 备份/复盘）

盘中数据的 SSOT 是 Hermes 生产端，不走 Git。成交、收益曲线、快照、运行 JSON 都不要 `git add`。

```bash
# 收盘后把生产数据拉回本地，并生成复盘事实包和项目专用备份
python3 scripts/ops/close_day.py --dry-run
python3 scripts/ops/close_day.py --apply
```

这个脚本会在 Hermes 创建 SQLite 一致性备份，拉回本地 `pnl.db` 和关键 JSON，生成
`data/review_packets/YYYY-MM-DD/review_source_packet.json`，再生成项目专用数据包并上传 OSS。

### 绝对不要混用

- 不用 Git 同步 `data/*`。
- 不用 `close_day.py` 同步代码。
- 不在 Hermes 生产目录直接热改代码；紧急热修也必须回补本地 commit/push。
- 本地预览 `18088` 只看效果，不录真实交易；真实交易只在 `8088`。

## 生产拓扑

```
浏览器 localhost:8088
      ↓ SSH tunnel (-L 8088:127.0.0.1:8088)
hermes 43.132.146.234
   └─ systemd: yimu-live-dashboard.service
      └─ bridge.py 8088 (云端, PyTDX dead 已知限制)
         ├─ 持仓估值/W22 → 腾讯 HTTP fallback
         ├─ 情绪节点 → iwencai
         ├─ 热榜/涨停梯队 → hot_list
         └─ 竞价 → snapshot_auction 9:28
```

## 核心数据管线（v3.1 实际口径）

```
复盘笔记(SSOT, D-1) → gen_dashboard_data.py → dashboard_data.json(每日基线)
Tencent/EM fallback → bridge CACHE → /api/live/quotes + live_index (PyTDX 云端降级)
iwencai pywencai → CACHE["iwencai"] → 情绪指标
同花顺 hot_list → CACHE["hot_list"] → 涨停梯队
account_baselines + trade_records + live quote → /api/account/state (账户 SSOT)
dashboard facts + health + tickets + freshness → /api/ai/context (Agent 只读事实包)
snapshot_auction 9:28 → auction_snapshot.json (竞价5维)
open_day.py/close_day.py → 开盘生成基线+rsync上云 / 收盘SQLite备份+拉回+review_source_packet+项目数据包备份
git commit → 代码留痕；需要部署云端时按确认后的 git/rsync 代码同步流程执行；data/* 不走 git
```

三端一致代码流程见 `docs/ops/three-end-code-sync-runbook.md`。本地是唯一代码编辑入口，GitHub 是代码 SSOT，Hermes 只运行已提交并推送的代码；生产热改必须回补 Git 后才算完成。

## 数据备份口径

- **Git 是代码留痕，不是数据备份**：禁止提交 `data/*`、`data/*.db*`、运行 JSON 和备份包。
- **Hermes 是生产源，不当作备份层**：`/home/agentuser/YiMu-Capital/data/pnl.db` 是 8088 实际读写的主数据；它在云端，但生产源损坏/误写时也会同步损坏。
- **全量 OSS 是灾备层**：WorkBuddy 的全量备份适合整机/目录级恢复，但 live-dashboard 的日常专用数据包不挂入 WorkBuddy 全量流程，避免通用备份和交易恢复包混在一起。
- **专用数据备份是快速恢复层**：需要恢复收益曲线/成交数据时，优先使用 `backup_live_dashboard_data.py` 生成的 tar.gz，里面包含一致性 `pnl.db`、关键 JSON 和 `manifest.json`。
- **收盘自动备份**：`python3 scripts/ops/close_day.py --apply` 在收盘同步和本地完整性检查后，自动生成本项目专用数据包并上传 OSS；紧急跳过用 `--skip-data-backup`。
- **复盘事实包**：同一次 `close_day.py --apply` 会先生成 `data/review_packets/YYYY-MM-DD/review_source_packet.json`，供稳米 `daily-review` / `auto-review-fill` 读取。它是证据输入，不是 Vault 复盘 SSOT，不进 git。

```bash
python3 scripts/ops/close_day.py --dry-run
python3 scripts/ops/close_day.py --apply
```

默认路径：
- 本地：`data/backups/live-dashboard-data/live-dashboard-data-<stamp>.tar.gz`
- OSS：`oss://ym-mac/yimu-capital/live-dashboard-data/`

## 健康语义

| 顶栏标签 | 含义 |
|---------|------|
| 正常 | 无 critical 无 degraded，交易录入可用 |
| 降级 | 有 degraded（iwencai 过期/基准缺失等非关键问题），交易录入可用 |
| 阻断 | critical 故障（行情 dead/账户 error/锚点缺失），交易录入关闭 |
| 无响应 | API 不可达（云端服务或 SSH tunnel 中断） |

## 团队协作边界

| 角色 | 职责 | 代码 | 数据 |
|------|------|------|------|
| 洋米（执行） | 后端+复杂前端实现、终端落地 | 代码 | 只读 |
| 欧米（主控） | 方案设计、派单、审查、兜底 | 审查所有 PR | 只读 |
| 稳米（操作） | 文档/流程/运维/复盘笔记 | 文档+runbook | 可读复盘笔记 |
| 黑米（前端） | UI/交互 | 前端小范围 | 只读 |
| 紫米（运维） | 云端部署/SSH/服务 | 运维脚本 | 只读 |

- 代码任务优先交洋米实现、欧米审查。
- 洋米盯盘/排障回答前，先按 `ai-rule-system/RULE_GATE.md` 和 `docs/trade-ticket-workflow.md` 确认规则/票据边界，再 `GET /api/ai/context` 读取统一事实包；字段解释见 `docs/ops/yangmi-ai-context-runbook.md`。
- 稳米复盘前优先读取 `data/review_packets/YYYY-MM-DD/review_source_packet.json`；若缺失或 stale/dead/untrusted，写入缺失/复核清单，继续按 daily-review + auto-review-fill 旧路径补数据。
- 文档/流程任务可交稳米。
- agent-board 是跨 agent 派单和验收入口。
- 遇到 8088/18088 混淆、交易录入、数据同步问题先看 runbook。

## 关键架构决策

- **账户 SSOT**：锚点+成交流水+实时行情统一派生，2026-05-27 验收通过
- **健康门禁**：`/api/health` + 顶栏三态，非关键降级不误关交易入口
- **云端非 PyTDX 依赖**：行情走 Tencent/EM fallback，PyTDX 仅本地可选
- **gen 防覆盖**：每天只跑一次，盘中 bridge 重启不覆盖 W15 实时持仓
- **开/收盘脚本**：默认 dry-run，显式 `--apply` 才写云端

## API 端点

| 端点 | 方法 | 说明 | 频率 |
|------|------|------|------|
| `/api/health` | GET | 服务与关键数据健康状态（含 account_basis） | 实时 |
| `/api/account/state` | GET | 账户 SSOT 派生状态 | 实时 |
| `/api/account/audit` | GET | 账户基准审计（日初价/清仓缺口） | 实时 |
| `/api/pnl/summary` | GET | PnL 摘要（含 valuation_complete） | 实时 |
| `/api/pnl?range=today&index=sh` | GET | PnL 曲线 | 5min/日结 |
| `/api/live/quotes` | GET | 实时行情（含 iwencai/北向/热榜） | 5s |
| `/api/ai/context` | GET | Agent 只读事实包（健康/新鲜度/风险/票据/人审动作） | 按需 |
| `/api/baseline` | GET | dashboard_data.json | 60s |
| `/api/sync` | POST | W15 单笔成交录入 | 随录 |
| `/api/trades/review?date=YYYY-MM-DD` | GET | W23 逐笔复盘 | 按需 |
| `/api/llm` | POST | AI 研判 | 15min/manual |

## 故障排查

| 症状 | 排查 |
|------|------|
| 看板白屏 | `curl localhost:8088/api/pnl/summary` |
| 顶栏显示"阻断" | `curl localhost:8088/api/health` 查 critical_ok / trade_entry_allowed |
| 顶栏显示"无响应" | 检查 SSH tunnel: `lsof -i :8088 \| grep ssh`；检查 hermes 服务: `systemctl is-active yimu-live-dashboard.service` |
| 洋米读不到事实包 | `curl -s localhost:8088/api/ai/context \| python3 -m json.tool`；失败再查 `/api/health` |
| 情绪数据空 | iwencai 采集在跑吗？`/api/live/quotes` 有 iwencai 字段吗？ |
| W15 显示"基准不可用" | 核查隔夜标的是否缺 `_meta.day_start_prices` |
| 竞价面板无数据 | 9:28 过了吗？auction_snapshot.json mtime 今天？ |
| LLM 不触发 | `~/.claude/settings.json` 有 ANTHROPIC_BASE_URL 和 token 吗？ |
| PyTDX 字段缺失 | 已知限制（hermes 香港节点不稳定），走 Tencent fallback |
| 成交录不进去 | 是否在 18088 上操作？本地预览只读，请用 8088 |

## 常用运维命令

```bash
# SSH tunnel（如中断）
ssh -fN -L 8088:127.0.0.1:8088 agentuser@43.132.146.234

# 云端服务
ssh agentuser@43.132.146.234 'systemctl status yimu-live-dashboard.service --no-pager'
ssh agentuser@43.132.146.234 'sudo systemctl restart yimu-live-dashboard.service'

# 开盘
python3 scripts/ops/open_day.py --dry-run
python3 scripts/ops/open_day.py --apply --restart-cloud

# 收盘
python3 scripts/ops/close_day.py --dry-run
python3 scripts/ops/close_day.py --apply

# 收盘事实包检查
python3 -m json.tool data/review_packets/$(date +%F)/review_source_packet.json | head -80

# 本地预览（18088）
python3 scripts/ops/local_dev_proxy.py --port 18088
```

## 禁止操作

- 禁止 `git reset --hard`、`git clean`
- 禁止对真实 8088 发 POST 测试
- 禁止在 18088 录真实交易
- 禁止把 `data/*` 提交到 git
- 禁止在云端跑依赖本地 Vault 的 `gen_dashboard_data.py`
- 禁止用 `pkill -f` 杀进程（用 `kill PID`）
- 禁止在 Hermes 生产目录直接热改代码后不回补 Git
