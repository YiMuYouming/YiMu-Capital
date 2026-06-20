# 弈沐资本数据看板 v3.1（稳定性收口）

## 打开方式

生产服务在 hermes 云端，本机通过 SSH tunnel 访问。

| 地址 | 用途 | 说明 |
|------|------|------|
| `http://localhost:8088` | 云端生产 | SSH tunnel → hermes `yimu-live-dashboard.service` |
| `http://localhost:18088` | 本地预览 | 只读代理，改组件看效果，不录真实交易 |
| `http://localhost:18089` | 本地诊断 | 可选完整服务，不默认录真实交易 |
| `file://index.html` | 离线查看 | 无实时 API，无成交录入 |

## 开盘前

推荐使用自动化脚本（默认 dry-run）：

```bash
cd ~/Documents/YM_Capital/live-dashboard
python3 scripts/ops/open_day.py --dry-run         # 预览步骤
python3 scripts/ops/open_day.py --apply            # 生成基线 + rsync 上云
python3 scripts/ops/open_day.py --apply --restart-cloud  # 同步后重启云端
```

手动备选：`python3 scripts/gen_dashboard_data.py` → `rsync` → `systemctl restart`。

## 收盘后

```bash
cd ~/Documents/YM_Capital/live-dashboard
python3 scripts/ops/close_day.py --dry-run   # 预览步骤
python3 scripts/ops/close_day.py --apply     # 云端备份 + 拉回本地
```

## 盘中

- **真实成交**只在 `http://localhost:8088`（云端生产）录入。
- **组件调试**在 `http://localhost:18088`（本地预览）看效果，只读不录。
- **监控**：顶栏健康标签表示 `正常 / 降级 / 阻断 / 无响应`。
- **数据源**：云端 PyTDX 不可用（已知限制），行情走 Tencent/EM fallback，情绪 iwencai。

## 代码 vs 数据

- **代码走 git**：本地先 `git commit`；需要部署云端时，再按确认后的 git/rsync 代码同步流程执行。
- **数据不走 git**：`data/pnl.db`、`data/dashboard_data.json`、盘中快照。
- **数据走专用备份**：本地生成一致性 tar.gz，必要时上传 OSS。
  ```bash
  python3 scripts/ops/backup_live_dashboard_data.py --dry-run
  python3 scripts/ops/backup_live_dashboard_data.py --apply --pull-cloud-first --upload-oss
  ```
- **收工前**：
  ```bash
  git status --short          # 确认代码干净
  git diff -- data/           # 确认数据未混入
  ```

### 数据备份与恢复

专用备份脚本建议加 `--pull-cloud-first`，先在 hermes 生产机创建 SQLite 一致性备份，
再拉回本地。随后脚本会使用 SQLite online backup 复制本地 `data/pnl.db`，再把存在的运行 JSON
一起打包到 `data/backups/live-dashboard-data/live-dashboard-data-<stamp>.tar.gz`。
加 `--upload-oss` 后，同一个压缩包会上传到
`oss://ym-mac/yimu-capital/live-dashboard-data/`。

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

## 项目结构

```
live-dashboard/
├── index.html              # GridStack 画板
├── store.js                # DataStore 三层合并
├── widget-base.js          # 组件基类
├── widget-registry.js      # 23 组件注册表
├── widgets/                # W01-W23 组件
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
- `docs/audit/2026-05-28-v3.1-completion-baseline.md` — V3.1 完成基线
- `AGENTS.md` — 团队协作与任务派发

## 快捷键

| 键 | 功能 |
|----|------|
| R | 全局刷新 |
| P | 报数面板 |
| Ctrl+S | 保存布局 |
| Ctrl+Z | 撤销删除 |
| A | 打开组件面板 |
