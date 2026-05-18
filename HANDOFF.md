# live-dashboard 数据架构重构 — 执行 Handoff

> 创建：2026-05-18 | 交接方：洋米（Claude Code Mac本地）
> 接收方：稳米/黑米/新Claude Code窗口
> 状态：**计划完成，等待执行。Phase 0 可立即开工。**

---

## 一、这是什么

弈沐资本 live-dashboard 数据架构重构项目。经过 5 份审计报告交叉验证（洋米架构审计+稳米管线审计+代码审计+管线实测+黑米独立审计v2），已产出完整实施计划。现在需要开新窗口逐 Phase 执行。

## 二、关键文件（按重要性）

| # | 文件 | 说明 |
|---|------|------|
| 1 | `docs/plans/2026-05-18-data-architecture-refactor.md` | **主计划**（Markdown），1050行，全部任务定义 |
| 2 | `~/Desktop/live-dashboard-architecture-plan-20260518.html` | **阅读版**（HTML），浏览器打开，一目了然 |
| 3 | `docs/plans/2026-05-18-data-automation-tiers.md` | 自动化分层调研（T1-T4详细字段分级） |
| 4 | `DATA_ARCHITECTURE_AUDIT.md` | 洋米架构审计原始报告 |
| 5 | `审计报告-1-20260518.md` | 稳米管线审计原始报告 |
| 6 | `审计报告-2-20260518.md` | 代码审计原始报告 |
| 7 | `CLAUDE.md` | 项目上下文（启动命令/架构/组件状态） |

## 三、当前运行状态

```
✅ bridge.py 运行中（PID 见 lsof -i :8088）
✅ poll_live.py 运行中（PID 12660）
✅ dashboard_live.json 5s实时更新中
✅ auction_snapshot.json 今天已抓取
⚠️ 所有改动需重启 bridge 后生效
⚠️ poll_live.py 将在 Phase 1.3 被 APScheduler 替代
```

## 四、Phase 0 执行指南（立即开工）

### 开工前置

在改任何代码之前，先确认这 6 条：

1. `pools.json` schema 的 key 名必须和 `store.js` merge()/getSSOT() 的引用完全一致
2. `baseline.json` vs `pools.json` 边界 — baseline不含池子，pools不重复market/sentiment
3. 三源自选池优先级：pools.json > auction_snapshot.json > localStorage
4. YM-data-pipeline：**集成**，poll_live改用fetch()替代内联PyTDX
5. gen_dashboard_data.py角色：数据生产者→数据校验者
6. codes格式对齐：fetch("quotes",codes=["002979"])与pools.json代码字段对齐

### 任务 0.1：清理死代码和备份残留
- **文件**：`scripts/poll_iwencai.py`（删~120行死函数）、18个.bak文件
- **命令**：`grep -rn "def watch_mode\|def fetch_live_index\|def fetch_live_quotes\|def fetch_live_sectors\|def build_live_data" scripts/poll_iwencai.py`
- **验证**：`python3 scripts/poll_iwencai.py --auction` 正常运行；`wc -l` 从~500→~380

### 任务 0.2：情绪值三源竞态修复
- **文件**：`store.js` merge()情绪值部分、`widgets/input-panel.js`
- **逻辑**：T3涨跌家数比(主源) → T2 iwencai(校验) → T4手工覆盖(需勾选checkbox)
- **验证**：看板情绪值随涨跌家数自动变化 → 勾选手动覆盖 → 锁定 → 取消 → 恢复自动

### 任务 0.3：pools.json SSOT解耦
- **文件**：新建`data/pools.json`、改`gen_dashboard_data.py`、`snapshot_auction.py`
- **核心**：gen新增parse_appendix_a()解析"附录A：次日盘前速查"；T1/T2字段不再从frontmatter首次写入
- **验证**：pools.json不含蒙娜丽莎（在不碰列表）

### 任务 0.4：原子写入+bridge双写事务化
- **文件**：`gen_dashboard_data.py`(tmp+os.replace)、`bridge.py`(SQLite事务+JSON原子写)
- **验证**：并发`gen & bridge sync &`不出现文件损坏

### 任务 0.5：db.py连接复用
- **文件**：`scripts/db.py` — 模块级get_conn()
- **验证**：`python3 -c "from scripts.db import get_conn; assert get_conn() is get_conn()"` → True

### 任务 0.6：竞价管线合并
- **文件**：`snapshot_auction.py`合并_judge_auction()、`poll_iwencai.py`移除auction_mode()
- **验证**：snapshot_auction输出含高潮保护字段 → poll_iwencai --auction已移除

### 任务 0.7：数据新鲜度标记
- **文件**：`bridge.py`(_add_freshness)、`store.js`(merge保留)、`widget-base.js`(灰显)
- **验证**：`curl /api/pnl`含`_freshness`字段

## 五、工作方式

- **每个任务一个 commit**，commit message 写"Phase 0.N: 做了什么"
- **改前备份**：`cp file file.bak_$(date +%Y%m%d_%H%M)`
- **改完验证**：跑任务定义的验证命令，通过才 commit
- **不顺手改无关代码**：只动任务指定的文件和行
- **bridge 重启**：改完 bridge.py 后 `kill <PID>` 再启动（或直接 `python3 scripts/bridge.py 8088 &`）
- **store.js / widget 改完**：浏览器硬刷新（Cmd+Shift+R）

## 六、常见坑

1. **bridge.py 进程不会自动重载** — 改 Python 代码后必须重启 bridge 进程
2. **store.js merge() 改完要清 localStorage** — 旧缓存可能导致字段冲突
3. **pools.json key 名大小写** — `lianban_pool` vs `lianban_pool` 不一致会导致 W06/W12 读不到数据
4. **gen_dashboard_data.py 依赖复盘笔记路径** — 确保 Vault 路径存在：`~/Documents/YouMingVault/10_⚡Now/01_💰弈沐资本/复盘笔记/`
5. **style_detect.py 调用可能超时** — gen脚本里的subprocess超时120s，如果style_detect挂了gen也挂
6. **file:// 降级路径不能断** — 所有 store.js adapter 改动必须保留 `if (location.protocol === 'file:')` 分支
7. **poll_live.py 还在跑** — Phase 0不改poll_live，Phase 1.3才迁移。Phase 0期间poll_live继续运行

## 七、需要我做什么

1. **新窗口打开**：`cd ~/Documents/YM_Capital/live-dashboard`，读 `HANDOFF.md`
2. **读计划**：打开 `~/Desktop/live-dashboard-architecture-plan-20260518.html` 浏览器看
3. **从 Phase 0 任务 0.1 开始**：逐个执行，每个任务改→验→commit
4. **遇到问题**：回来这个窗口问我，我能看到完整上下文
5. **每完成一个 Phase**：跑 `git log --oneline -5` 确认 commits，回来汇报进度

## 八、禁止事项

- 不引入新依赖（FastAPI/Flask/Celery/Redis/DuckDB/InfluxDB）
- 不删除 file://降级路径
- 不改组件渲染逻辑（22 Widget接口不变）
- bridge.py改造后不超过1000行
- 文档型数据不迁SQLite
