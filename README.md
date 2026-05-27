# 弈沐资本数据看板 v2.5

## 打开方式

```bash
cd ~/Documents/YM_Capital/live-dashboard
python3 scripts/bridge.py 8088
```

然后 Chrome 打开 **http://localhost:8088**（收藏到书签栏）。

> 离线调试用：双击 `index.html`（file:// 协议不具备实时 API、账户 SSOT 或成交录入能力）。

## 依赖

### Python（服务端）

```bash
# 推荐：用虚拟环境隔离
python3 -m venv .venv
source .venv/bin/activate          # macOS/Linux
# .\.venv\Scripts\Activate.ps1     # Windows

# 安装依赖
pip install -r requirements.txt

# 数据管道（ym_stock_data，详见 requirements.txt 中的安装说明）
cd ~/Documents/YM_Capital/YM-data-pipeline && pip install -e .
# 或使用环境变量指定本地路径（开发模式）:
# export YM_DATA_PIPELINE_PATH=/Users/xxx/YM_Capital/YM-data-pipeline
```

### 前端

- GridStack.js v12（CDN 自动加载，版本锁定 12.0.0）
- 无 Node.js/npm 依赖
- 纯原生 HTML/CSS/JS

### 运行环境检查

```bash
python3 scripts/check_runtime.py
```

## 启动

```
live-dashboard/
├── index.html              # 主入口
├── store.js                # DataStore 数据中枢
├── widget-base.js          # 组件基类
├── widget-registry.js      # 23 组件注册表
├── widgets/                # W01-W23 + W20 浮动聊天框
├── presets/                # 4 套布局预设
├── css/theme.css           # 全局主题
├── data/                   # 数据文件
│   ├── dashboard_data.json     # Layer 1 基线（scripts/ 产出）
│   ├── pnl.db                  # 账户锚点/流水/PnL/复盘事实
│   └── embedded-data.js        # Layer 0 兜底
├── docs/audit/             # 当前验收与运维基线
└── docs/_archive/          # 已完成计划与历史审计
└── assets/logo.svg          # 标签页图标
```

## 数据管线

当前核心数据流：

```
scripts/gen_dashboard_data.py                  → data/dashboard_data.json (每日基线)
bridge CACHE + scripts/rule_engine.py          → /api/live/quotes + rule_state
account_baselines + trade_records + live quote → /api/account/state       (账户 SSOT)
pnl.db                                         → /api/pnl/* + /api/trades/review
```

当前验收和数据保护规则见 [`docs/audit/2026-05-27-升级改造完成验收与运维基线.md`](docs/audit/2026-05-27-升级改造完成验收与运维基线.md)。

## 快捷键

| 键 | 功能 |
|----|------|
| R | 全局刷新 |
| P | 跳转报数面板 |
| 1/2/3/4 | 切换预设布局 |
| Ctrl+S | 保存布局 |
| Ctrl+Z | 撤销删除 |
| A | 打开组件面板 |

## 出问题找谁

| 问题类型 | 负责人 |
|---------|--------|
| 数据管线（JSON 文件更新/iwencai） | 稳米 |
| 组件代码、UI 显示 | 洋米/黑米 |
| 架构设计、PRD | 洋米 |
