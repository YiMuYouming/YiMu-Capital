# 弈沐资本数据看板 v3.1（稳定性收口）

## 先读这 5 条

- 生产：`http://localhost:8088`，SSH tunnel 到 Hermes，真实交易只在这里。
- 预览：`http://localhost:18088`，只读代理，只看效果，不录真实交易。
- 诊断：`http://localhost:18089`，可选完整服务，只用于排障。
- 代码走 Git：本地改代码 -> 测试 -> commit -> push -> Hermes `git pull --ff-only` -> 重启验收。
- 开盘 baseline 每个交易日前必须刷新：本地 `open_day.py --apply --restart-cloud` 生成 `dashboard_data.json`/`pools.json` 并同步 Hermes；锚定股、连板池、趋势池不靠代码 push 自动更新。
- 数据走收盘脚本：Hermes 生产生成 -> `close_day.py --apply` 拉回本地 -> 复盘事实包 -> 项目专用备份/OSS。

## 代码和数据分流

### 代码流程

代码 SSOT 是 Git。生产端只运行已提交、已推送的代码；Hermes 生产目录不要直接叠补丁。

本地验证最小集：

```bash
git status --short
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest <相关测试> -v
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q scripts tests
git diff --check
```

部署到 Hermes：

```bash
ssh agentuser@43.132.146.234 'cd /home/agentuser/YiMu-Capital && git pull --ff-only'
ssh agentuser@43.132.146.234 'sudo systemctl restart yimu-live-dashboard.service'
```

验收：本地、GitHub、Hermes 三端 commit 一致，Hermes `git status --short` 干净，`8088` API 可用。

### 数据流程

盘中数据 SSOT 是 Hermes，不走 Git。成交、收益曲线、快照、运行 JSON 都不要 `git add`。代码三端同步不等于每日 baseline 已同步；若 W18 锚定股、W12/W13 池子或 baseline 日期像旧数据，先查 `/api/baseline.meta.note` 和 `meta.pools_note_date`，再跑开盘同步。

```bash
python3 scripts/ops/open_day.py --dry-run
python3 scripts/ops/open_day.py --apply --restart-cloud
python3 scripts/ops/close_day.py --dry-run
python3 scripts/ops/close_day.py --apply
```

`open_day.py --apply --restart-cloud` 会从本地 Vault 复盘笔记生成 `data/dashboard_data.json` / `data/pools.json`，rsync 到 Hermes，并重启 8088。开盘验收至少确认 `/api/health.baseline=ok`、`/api/baseline.meta.note` 是当日 ReviewNote、`decision.锚定股状态` 与昨日确定的锚定股一致。

`close_day.py --apply` 会在 Hermes 创建 SQLite 一致性备份，拉回本地 `pnl.db` 和关键 JSON，生成
`data/review_packets/YYYY-MM-DD/review_source_packet.json`，再生成项目专用数据包并上传 OSS。

## Agent 协作倾向

这不是硬分工，主人可以随时调整；当前只是默认倾向：

- 欧米：方案、复杂代码、审查、兜底。
- 洋米：终端执行、部署验证、脚本落地；盯盘/交易动作先走 `docs/ops/yangmi-ai-context-runbook.md`，按 Rule 2.0 读取 `AGENT_QUICKSTART.md` / `compiled/rules.v1.json` / 规则门边界，再读 `/api/ai/context`。
- 稳米：复盘、文档、流程；复盘前优先读 `data/review_packets/YYYY-MM-DD/review_source_packet.json`。
- 黑米：小范围前端/IDE 快改。
- 紫米：云端运维、异步陪伴、轻量查询。

跨 agent 派任务、领任务、检查结果、验收结果时，先按全局规则进入 `/Users/yimu/agent-board`。

## 必看文档

- `README.md`：完整项目结构、打开方式、API、数据备份、故障排查。
- `docs/ops/three-end-code-sync-runbook.md`：本地/GitHub/Hermes 三端代码一致流程。
- `docs/ops/2026-05-28-cloud-data-sync-runbook.md`：开盘、收盘、云端数据同步 runbook。
- `docs/ops/yangmi-ai-context-runbook.md`：洋米/盯盘 agent 读取 Rule 2.0 快速入口和 `/api/ai/context` 的规范。
- `docs/audit/2026-06-20-dashboard-3-closeout.md`：Dashboard 3.0 Phase 3 收口基线。

## 最小排障入口

```bash
curl -s localhost:8088/api/health | python3 -m json.tool
curl -s localhost:8088/api/pnl/summary | python3 -m json.tool
curl -s localhost:8088/api/ai/context | python3 -m json.tool
```

- 顶栏"阻断"先查 `/api/health`，不要只看截图下结论。
- 顶栏"降级"不是"阻断"，交易入口以 `/api/health.trade_entry_allowed` 为准。
- 冰点 W1 黄灯只表示极化主线强回踩进入人工复核；`manual_review_allowed=true` 不能当作 `buy_allowed=true`，也不能生成 executable ticket。
- 洋米读不到事实包先查 `/api/ai/context`，失败再查 `/api/health`。
- 盘中票据队列优先读 `/api/ai/context.tickets`；如果直接 GET `/api/trade/tickets`，必须传 `?date=YYYY-MM-DD`，避免把历史票据误当今日票据。无 date 时服务端只默认返回当天。
- 8088/18088 混淆、交易录入、数据同步问题先看 `docs/ops/2026-05-28-cloud-data-sync-runbook.md`。

## 禁止操作

- 禁止 `git reset --hard`、`git clean`，除非主人明确批准且已有备份。
- 禁止对真实 8088 发 POST 测试。
- 禁止在 18088 录真实交易。
- 禁止把 `data/*` 提交到 Git。
- 禁止在云端跑依赖本地 Vault 的 `gen_dashboard_data.py`。
- 禁止用 `pkill -f` 杀进程，用 `kill PID`。
- 禁止在 Hermes 生产目录直接热改代码后不回补 Git。
