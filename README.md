# 弈沐资本数据看板 v2.0

## 打开方式

双击 `index.html`，Chrome 浏览器直接打开。

## 依赖

- GridStack.js v12（CDN 自动加载，版本锁定 12.0.0）
- 无 Node.js/npm 依赖
- 纯原生 HTML/CSS/JS

## 目录

```
live-dashboard/
├── index.html              # 主入口
├── store.js                # DataStore 数据中枢
├── widget-base.js          # 组件基类
├── widget-registry.js      # 16 组件注册表
├── widgets/                # 16 个独立组件
├── presets/                # 4 套布局预设
├── css/theme.css           # 全局主题
├── data/                   # 数据文件
│   ├── dashboard_data.json     # Layer 1 基线（scripts/ 产出）
│   ├── dashboard_live.json     # Layer 2 实时（scripts/ 产出）
│   └── embedded-data.js        # Layer 0 兜底
└── assets/logo.svg          # 标签页图标
```

## 数据管线

数据由 `../scripts/` 中的 Python 脚本产出到 `data/` 目录：

```
scripts/gen_dashboard_data.py   → data/dashboard_data.json   (每日复盘后)
scripts/poll_iwencai.py         → data/dashboard_live.json   (盘中轮询)
scripts/sync_embedded.py        → data/embedded-data.js      (每日复盘后)
```

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
