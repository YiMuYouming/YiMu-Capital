# AGENTS.md Slimming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将项目根 `AGENTS.md` 从完整运维手册瘦身为新窗口/新 agent 的决策入口，同时确保现有内容都有落点，不丢失。

**Architecture:** `AGENTS.md` 只保留“必须先知道、会影响决策和安全边界”的规则；完整拓扑、API、故障排查、命令和数据备份细节搬到 README 与 `docs/ops/*`。瘦身后通过链接指向细节文档，避免重复维护。

**Tech Stack:** Markdown 文档、现有 runbook、Git 三端一致流程。

---

## Content Mapping

| 当前 AGENTS 内容 | 保留位置 | 处理方式 |
| --- | --- | --- |
| 生产/预览/诊断地址 | `AGENTS.md` 顶部 | 保留，压缩成 3 行 |
| 代码和数据分流 | `AGENTS.md` 顶部 | 保留为核心硬规则 |
| 生产拓扑 | `README.md` + `docs/ops/2026-05-28-cloud-data-sync-runbook.md` | `AGENTS.md` 只留链接 |
| 核心数据管线 | `README.md` | `AGENTS.md` 只保留 SSOT 结论 |
| 数据备份口径 | `README.md` + `docs/superpowers/plans/2026-06-20-live-dashboard-data-backup.md` | `AGENTS.md` 保留“数据不走 git，收盘用 close_day.py” |
| 健康语义 | `README.md` | `AGENTS.md` 留一句“阻断先查 /api/health” |
| 团队协作边界 | `AGENTS.md` | 保留但压缩表格为短列表 |
| API 端点 | `README.md` | 从 `AGENTS.md` 移除，链接 README |
| 故障排查 | `README.md` + ops runbook | `AGENTS.md` 只保留常见入口链接 |
| 常用运维命令 | `README.md` + ops runbook | `AGENTS.md` 只保留 3 个最高频命令 |
| 禁止操作 | `AGENTS.md` | 保留并去重 |

## Target Shape

瘦身后 `AGENTS.md` 目标 70-90 行，结构如下：

```markdown
# 弈沐资本数据看板 v3.1（稳定性收口）

## 先读这 5 条
- 生产 8088 / 预览 18088 / 诊断 18089
- 代码走 Git：本地 -> GitHub -> Hermes
- 数据走收盘脚本：Hermes -> 本地 -> 备份/复盘
- 真实交易只在 8088
- 细节先看 README 和 docs/ops

## 代码和数据分流
...

## Agent 边界
...

## 必看文档
...

## 最小排障入口
...

## 禁止操作
...
```

## Task 1: Ensure Destination Docs Already Preserve Details

**Files:**
- Read: `/Users/yimu/Documents/YM_Capital/live-dashboard/README.md`
- Read: `/Users/yimu/Documents/YM_Capital/live-dashboard/docs/ops/2026-05-28-cloud-data-sync-runbook.md`
- Read: `/Users/yimu/Documents/YM_Capital/live-dashboard/docs/ops/three-end-code-sync-runbook.md`
- Modify only if missing: same files above

- [ ] **Step 1: Check README contains detailed sections**

Run:

```bash
rg -n "生产拓扑|API 端点|故障排查|数据备份|复盘事实包|代码 vs 数据" README.md
```

Expected: every topic appears at least once.

- [ ] **Step 2: Check ops runbooks contain deployment and data detail**

Run:

```bash
rg -n "8088|18088|close_day.py|git pull --ff-only|Hermes|pnl.db|review_source_packet" docs/ops
```

Expected: command output includes `2026-05-28-cloud-data-sync-runbook.md`, `three-end-code-sync-runbook.md`, and `yangmi-ai-context-runbook.md`.

- [ ] **Step 3: Patch destination docs only if a topic has no destination**

If Step 1 or Step 2 misses a topic, copy the missing detail from `AGENTS.md` into the most relevant destination doc before slimming `AGENTS.md`.

## Task 2: Replace AGENTS.md With Decision-Entry Version

**Files:**
- Modify: `/Users/yimu/Documents/YM_Capital/live-dashboard/AGENTS.md`

- [ ] **Step 1: Replace long sections with compact decision rules**

Keep these exact decisions:

```markdown
## 先读这 5 条

- 生产：`http://localhost:8088`，SSH tunnel 到 Hermes，真实交易只在这里。
- 预览：`http://localhost:18088`，只读代理，只看效果，不录真实交易。
- 诊断：`http://localhost:18089`，可选完整服务，只用于排障。
- 代码走 Git：本地改代码 -> 测试 -> commit -> push -> Hermes `git pull --ff-only` -> 重启验收。
- 数据走收盘脚本：Hermes 生产生成 -> `close_day.py --apply` 拉回本地 -> 复盘事实包 -> 项目专用备份/OSS。
```

- [ ] **Step 2: Preserve the code/data split as hard rule**

Keep this compact block:

```markdown
## 代码和数据分流

### 代码流程
代码 SSOT 是 Git。生产端只运行已提交、已推送的代码。

验证最小集：
```bash
git status --short
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest <相关测试> -v
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q scripts tests
git diff --check
```

部署：
```bash
ssh agentuser@43.132.146.234 'cd /home/agentuser/YiMu-Capital && git pull --ff-only'
ssh agentuser@43.132.146.234 'sudo systemctl restart yimu-live-dashboard.service'
```

### 数据流程
盘中数据 SSOT 是 Hermes，不走 Git。

```bash
python3 scripts/ops/close_day.py --dry-run
python3 scripts/ops/close_day.py --apply
```
```

- [ ] **Step 3: Add document index instead of duplicated details**

Add:

```markdown
## 必看文档

- `README.md`：完整项目结构、API、数据备份、故障排查。
- `docs/ops/three-end-code-sync-runbook.md`：本地/GitHub/Hermes 三端代码一致流程。
- `docs/ops/2026-05-28-cloud-data-sync-runbook.md`：开盘、收盘、云端数据同步 runbook。
- `docs/ops/yangmi-ai-context-runbook.md`：洋米/盯盘 agent 读取 `/api/ai/context` 的规范。
```

- [ ] **Step 4: Preserve agent and safety boundaries**

Keep:

```markdown
## Agent 边界

- 欧米：方案、复杂代码、审查、兜底。
- 洋米：终端执行、部署验证、脚本落地；盯盘前读 `/api/ai/context`。
- 稳米：复盘、文档、流程；复盘前优先读 `data/review_packets/YYYY-MM-DD/review_source_packet.json`。
- 黑米：小范围前端/IDE 快改。
- 紫米：云端运维和异步陪伴。
```

Keep the existing forbidden operations, deduplicated:

```markdown
## 禁止操作

- 禁止 `git reset --hard`、`git clean`，除非主人明确批准且已有备份。
- 禁止对真实 8088 发 POST 测试。
- 禁止在 18088 录真实交易。
- 禁止把 `data/*` 提交到 Git。
- 禁止在云端跑依赖本地 Vault 的 `gen_dashboard_data.py`。
- 禁止用 `pkill -f` 杀进程，用 `kill PID`。
- 禁止在 Hermes 生产目录直接热改代码后不回补 Git。
```

## Task 3: Verify No Content Was Lost

**Files:**
- Read: `/Users/yimu/Documents/YM_Capital/live-dashboard/AGENTS.md`
- Read: destination docs from Task 1

- [ ] **Step 1: Check AGENTS line count**

Run:

```bash
wc -l AGENTS.md
```

Expected: 60-100 lines.

- [ ] **Step 2: Check key terms remain discoverable**

Run:

```bash
rg -n "8088|18088|Git|close_day.py|data/\\*|review_source_packet|/api/ai/context|禁止" AGENTS.md README.md docs/ops
```

Expected: every key term appears in either `AGENTS.md` or a linked destination doc.

- [ ] **Step 3: Check Markdown formatting**

Run:

```bash
git diff --check
```

Expected: no output and exit code 0.

## Task 4: Commit and Sync

**Files:**
- Modify: `/Users/yimu/Documents/YM_Capital/live-dashboard/AGENTS.md`
- Optional modify: destination docs if Task 1 found gaps

- [ ] **Step 1: Stage only docs**

```bash
git status --short
git add AGENTS.md README.md docs/ops/2026-05-28-cloud-data-sync-runbook.md docs/ops/three-end-code-sync-runbook.md
```

- [ ] **Step 2: Commit**

```bash
git commit -m "Slim AGENTS decision entry"
```

- [ ] **Step 3: Push**

```bash
git push
```

- [ ] **Step 4: Hermes pull docs-only change**

```bash
ssh agentuser@43.132.146.234 'cd /home/agentuser/YiMu-Capital && git pull --ff-only && git status --short && git rev-parse --short HEAD'
```

Expected: fast-forward or already up to date, clean working tree. No service restart required for docs-only change.

## Self-Review

- Spec coverage: preserves all existing topics by moving details to README/runbooks and keeping hard decisions in AGENTS.
- Placeholder scan: no TBD/TODO placeholders.
- Risk: if README lacks a topic, Task 1 requires moving that content before slimming AGENTS.
