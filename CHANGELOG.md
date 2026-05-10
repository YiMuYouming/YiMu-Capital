# 开发日志

## 2026-05-10

### v2.1 — 纯组件化架构

- **去掉所有预设布局**：删除 `presets/` 目录、`INLINE_PRESETS`、`loadPreset()`、快捷键 1/2/3/4
- **空白画布启动**：初始无 widget，右键菜单逐个添加，用户自己拖拽摆放
- **顶栏简化**：只保留品牌名 + 连接状态 + 保存/导出/导入
- **localStorage key 升级**：`dash_layout` → `dash_layout_v2`，格式 `{v:'2.1', items:[...]}`
- **GridStack v12 API 适配**：`addWidget(el)` 用 HTMLElement 不用 content 字符串
- **删除按钮修复**：`removeWidget(el, true, false)` 立即移除 DOM
- **独立 Git 仓库**：`live-dashboard/` 初始化为独立仓库，与 Vault 解耦

### v2.0 — 四方针审阅通过（初始版本）

- PRD v2.0 正式施工蓝图（1540 行）
- DataStore 核心：三层合并 + 订阅发布 + manualData + dataAdapter
- 16 个独立 Widget 组件
- CSS 主题：阴影 4 级 + 紫色高亮 + 交互四态 + 响应式断点
- 3 个 Python 数据管线脚本
