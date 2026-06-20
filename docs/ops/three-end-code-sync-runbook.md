# 三端一致代码同步流程

适用范围：本地工作区、GitHub 远端、Hermes 生产代码三端对齐。  
不适用范围：`data/*`、SQLite、盘中快照、收益曲线数据；数据按收盘和专用备份流程走。

## 一句话原则

- 本地是唯一代码编辑入口。
- GitHub 是代码 SSOT 和审计记录。
- Hermes 只运行已提交、已推送、已验证的代码。
- 生产目录禁止随手热改；紧急热修也要在本地补 commit，再同步回 Hermes。
- `data/*` 永远不进 git，不用代码同步流程处理。

## 标准流程

### 1. 本地开工前

```bash
cd /Users/yimu/Documents/YM_Capital/live-dashboard
git status --short
git branch --show-current
git fetch origin
```

要求：

- 工作区没有无关脏文件。
- 如有别的 agent 改动，先判断是否同一任务；不要覆盖。
- 新功能用 `codex/<topic>` 分支，不直接在生产目录改代码。

### 2. 本地实现和验证

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest <相关测试> -v
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q scripts tests
git diff --check
```

前端组件至少覆盖：

- 注册表元数据。
- `index.html` 脚本加载。
- 组件空态/降级态。
- 动态文本清洗或转义。

涉及收盘、数据包、Agent facts 时，必须覆盖：

- `tests.test_ops_scripts`
- `tests.test_review_source_packet`
- `tests.test_health_api.AIContextApiTest`

### 3. 本地提交并推送

```bash
git status --short
git add <本次代码文件>
git commit -m "<清晰说明>"
git push -u origin <branch>
```

要求：

- 只提交代码、测试、文档。
- 不提交 `data/*`、备份包、临时快照。
- 推送后 GitHub 分支 commit 等于本地 `git rev-parse HEAD`。

### 4. 部署 Hermes 代码

部署前先确认当前生产状态：

```bash
ssh agentuser@43.132.146.234 'cd /home/agentuser/YiMu-Capital && git status --short && git branch --show-current && git rev-parse --short HEAD'
```

如果生产目录不干净：

- 先做代码快照，至少保留 `git diff`、`git status`、未跟踪文件列表。
- 不用 `git clean` 直接抹掉。
- 能通过 Git stash/备份目录保留现场时，先保留现场，再切到已推送分支。

同步代码：

```bash
ssh agentuser@43.132.146.234 'cd /home/agentuser/YiMu-Capital && git fetch origin && git switch <branch> && git pull --ff-only'
```

如果 Hermes 因历史脏工作区无法切分支，优先处理为“保留现场后切换到 Git 分支”，不要在脏目录继续叠补丁。

### 5. 重启和生产验证

```bash
ssh agentuser@43.132.146.234 'sudo systemctl restart yimu-live-dashboard.service'
ssh agentuser@43.132.146.234 'systemctl is-active yimu-live-dashboard.service && cd /home/agentuser/YiMu-Capital && git status --short && git rev-parse --short HEAD'
curl -s http://localhost:8088/api/health | python3 -m json.tool | head -80
curl -s http://localhost:8088/api/live/quotes | python3 -m json.tool | head -80
```

验收口径：

- 服务 active。
- Hermes 工作区代码干净。
- Hermes HEAD 等于 GitHub 目标分支 HEAD。
- `8088` API 返回 JSON。
- 顶栏若是“降级/阻断”，必须能从 `/api/health` 解释原因；非交易日或收盘后不把它当成代码部署失败。

## 每次收工检查

本地：

```bash
git status --short
git rev-parse --short HEAD
git ls-files data
```

GitHub：

```bash
git ls-remote origin <branch>
```

Hermes：

```bash
ssh agentuser@43.132.146.234 'cd /home/agentuser/YiMu-Capital && git status --short && git rev-parse --short HEAD'
```

三端对齐定义：

- 本地工作区干净。
- GitHub 有同一个 commit。
- Hermes 当前运行目录在同一个 commit，且代码工作区干净。
- 数据同步另看 `close_day.py --apply` 和专用数据包备份，不和代码一致性混在一起。

## 禁止清单

- 禁止在 Hermes 生产目录直接编辑代码后不回补 Git。
- 禁止把截图里的“样子已更新”当作三端一致证据。
- 禁止提交 `data/*` 来同步收益或成交数据。
- 禁止用 `git reset --hard` / `git clean` 处理生产脏目录，除非主人明确批准且已有快照。
- 禁止在 `18088` 录真实交易。
