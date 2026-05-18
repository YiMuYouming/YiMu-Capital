# W22 之后：看板 UX 优化方案

> 来源：综合洋米初审 + 稳米深度审计 + 黑米独立审计 + UX Report
> 目标：筛选 P0/P1 中"不影响现有功能、只提升体验"的优化项，洋米可独立执行
> 原则：不碰核心架构、不重写数据管线、不动 W22/pnl-curve（刚修完所有 bug）

---

## 原则：哪些不做

以下类别**不做本轮**（影响稳定性或改动量过大）：

- 数据管线/存储层改造（poll_live、db.py 任何改动）
- DataStore 订阅系统重构（notifyAll、脏检查、rAF 批量渲染）
- W22 组件重构（W22 刚落地，稳定期不动）
- 事件总线
- XSS 防护（本地仪表盘，风险极低）
- W12/W13 合并（W21 涨停梯队同逻辑，暂不动）

---

## P0 — 必须修（影响正确性的 bug）

### P0-BUG-1: W03/W15 tier 映射错误，定时器不启动

**文件**：`widget-registry.js`

**问题**：`store.js` 定义了 `tick/fast/slow/manual/daily`，没有 `realtime`。`W03` 和 `W15` 注册为 `tier: 'realtime'`，`widget-base.js` 查 `DataStore.tiers['realtime']` → `undefined` → 定时器不创建。

- W03（三层仓位计）：完全不刷新，盘中仓位信息永远停在启动时
- W15（持仓明细）：实际通过 `refresh('tick')` 间接刷新，但路径不规范

**修复**：两行改动

```javascript
// widget-registry.js L14
{ id:'W03', ..., tier:'tick', ... }   // 改 realtime → tick

// widget-registry.js L28
{ id:'W15', ..., tier:'tick', ... }   // 改 realtime → tick
```

**验证**：启动看板，W03 标题栏显示"5秒"标签；W15 每 5s 更新市值和盈亏。

---

## P0-UX: 必须做（影响核心使用效率）

### P0-UX-1: W16 报数面板字段分组 + 排序

**文件**：`index.html`（W16 的 HTML 在 index.html 里）、`widget-registry.js`（位置）

**问题**：23 个字段无分组、无排序、无保存反馈。每天在 W16 耽误 5-10 分钟。

**改动范围**：只改 HTML 结构（字段排序 + 分组标题）和 CSS（加分组样式），不动 JS 数据逻辑。

**字段分组方案**（按决策流程排序）：

```
┌─ 账户头寸 ──────────────────────────┐
│ 总资产    可用资金    总盈亏          │
├─ 情绪指标 ──────────────────────────┤
│ 情绪值    涨停收益    连板收益        │
│ 炸板收益  赚钱效应                  │
├─ 盘面数据 ──────────────────────────┤
│ 上涨      下跌      涨停家数        │
│ 跌停家数  晋级率      封板率         │
├─ 连板生态 ──────────────────────────┤
│ 风险值    最高板    次高板    梯队   │
├─ W1窗口 ────────────────────────────┤
│ W1观察1   W1观察2   W1观察3         │
├─ W2窗口 ────────────────────────────┤
│ W2观察1   W2观察2   W2观察3         │
└────────────────────────────────────┘
```

**额外**：每个分组标题加 `cursor: pointer` + 折叠功能（点击标题展开/折叠该分组）。

**验证**：刷新页面 → 字段按分组显示 → 点击分组标题可折叠 → 输入后 Toast 提示"已保存"。

---

## P1 — 做了体验大幅提升

### P1-1: 字号层级微调（不破坏现有布局）

**文件**：`css/theme.css`

**改动**（三行）：

```css
/* 改动 1：基础正文 12 → 13px */
:root { --fs-body: 13px; }

/* 改动 2：KPI 数值 22 → 26px（W22 的 KPI 卡片已用 24px 可不动）*/
/* 改动 3：标签 10px 不变，但 W01/W06 等信息密度大的组件内加例外 */
```

**注意**：只在 `theme.css` 里改 CSS 变量，全局生效。先小步试探，26px 如果太大就调回 24px。

**验证**：刷新页面 → 整体字比之前大一号 → 组件没有溢出或换行。

---

### P1-2: 加载骨架屏（widget-base.js）

**文件**：`widget-base.js`

**问题**：数据未就绪时组件区域空白，用户不知道在加载。

**改动**：在 `_renderBody()` 执行前，显示一个灰色占位块（骨架屏），数据到来后替换为真实内容。

```javascript
// 在 _mount() 中，render() 之前插入：
var skeleton = document.createElement('div');
skeleton.className = 'widget-skeleton';
skeleton.innerHTML = '<div class="skeleton-bar" style="width:60%;height:12px;margin:8px 0"></div>' +
                     '<div class="skeleton-bar" style="width:40%;height:12px;margin:8px 0"></div>';
body.appendChild(skeleton);

// render() 完成后：
skeleton.remove();
```

```css
/* theme.css 加两行 */
.widget-skeleton { padding: 12px 16px; }
.skeleton-bar { background: linear-gradient(90deg, #f0eeec 25%, #e5e2de 50%, #f0eeec 75%); background-size: 200% 100%; animation: shimmer 1.5s infinite; border-radius: 4px; }
@keyframes shimmer { 0%{background-position:200% 0} 100%{background-position:-200% 0} }
```

**验证**：强刷页面 → 组件显示灰色骨架动画 → 3-5s 后数据加载完成，骨架消失。

---

### P1-3: W08/W09 信号灯视觉增强

**文件**：`widgets/w1-check.js`、`widgets/w2-check.js`

**问题**：`🟢` / `🔴` emoji 在深色或浅色背景上辨识度不够，且条件通过/失败状态不够醒目。

**改动**（CSS + HTML，不动 JS 逻辑）：

```css
/* w1-check.css 新增 */
.signal-pass { color: #059669; font-size: 20px; font-weight: 700; }
.signal-fail { color: #DC2626; font-size: 20px; font-weight: 700; }
.signal-block { color: var(--warn); font-size: 20px; font-weight: 700; }
```

在 w1-check.js 的信号输出处，把 `🟢` → `<span class="signal-pass">✓</span>`，`🔴` → `<span class="signal-fail">✗</span>`。

W09 同理：买入信号 `<span class="signal-pass">●</span>` 放大 2 倍并加粗。

**验证**：W08 条件通过 → 显示绿色 ✓ + 粗体；失败 → 红色 ✗；阻断 → 橙色 ●。

---

### P1-4: Ctrl+F 组件搜索 + 快速定位

**文件**：`index.html`（HTML）、`store.js`（事件监听）

**问题**：22 个组件平铺，找特定组件要滚半天。

**改动**（轻量，不动 store.js 核心逻辑）：

```javascript
// index.html 顶部栏加入搜索框（现有快捷键 P/R/A/Ctrl+S 旁边）：
// <input id="widget-search" placeholder="搜索组件 (Ctrl+F)" ...>

// 在 store.js 或 index.html 的 keydown 监听里加：
document.addEventListener('keydown', function(e) {
  if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
    e.preventDefault();
    var input = document.getElementById('widget-search');
    if (input) { input.focus(); input.select(); }
  }
});

// 搜索框 input 事件：输入后滚动到对应组件
input.addEventListener('input', function() {
  var q = this.value.trim().toLowerCase();
  document.querySelectorAll('.widget').forEach(function(w) {
    var title = (w.querySelector('.widget-title') || {}).textContent || '';
    if (!q || title.toLowerCase().includes(q)) {
      w.scrollIntoView({ behavior: 'smooth', block: 'center' });
      w.style.outline = q ? '2px solid var(--accent)' : '';
    } else {
      w.style.outline = '';
    }
  });
});
```

**验证**：Ctrl+F → 搜索框聚焦 → 输入"W08" → 页面滚动到 W08 并高亮橙色边框。

---

### P1-5: W06 竞价面板 12px → 13px + 历史对比箭头

**文件**：`widgets/auction-5d.js`（仅改动 CSS class）

**改动**：同 P1-3，在 theme.css 里加 `auction-table` 字号例外：

```css
.auction-table td, .auction-table th { font-size: 13px !important; }
```

历史对比箭头：找数据源中是否有昨日同期值，若有则在数值旁加 `↑`（绿）或 `↓`（红）。

**验证**：W06 刷新后表格数字更易读。

---

## 优先级排序（洋米执行顺序）

| 顺序 | 任务 | 工作量 | 风险 |
|------|------|--------|------|
| 1 | P0-BUG-1 W03/W15 tier 修复 | 2 行 | 极低 |
| 2 | P0-UX-1 W16 字段分组 | 中等 | 极低（只改 HTML/CSS） |
| 3 | P1-2 加载骨架屏 | 小 | 极低 |
| 4 | P1-3 W08/W09 信号灯 | 小 | 极低 |
| 5 | P1-4 Ctrl+F 搜索 | 小 | 极低 |
| 6 | P1-1 字号微调 | 3 行 | 低 |
| 7 | P1-5 W06 字号+箭头 | 小 | 极低 |

---

## 不做本轮（可后续单独做）

| 项 | 原因 |
|----|------|
| DataStore 脏检查 + rAF 渲染 | 200+ 行架构改动，动核心稳定性 |
| 预设布局系统 | 需要重新设计 index.html，工作量大 |
| 顶部固定 Pills | 需要重新设计 index.html 布局 |
| W22 组件拆分 | W22 刚落地，稳定期不动 |
| 事件总线 | 增加复杂度，收益不明确 |
| data/ 目录清理 | 顺手的事，可单独做 |
| XSS 防护 | 本地仪表盘风险极低 |
| W12/W13 合并 | 同 W21，需要整体设计 |
