# 看板 UX 优化 — 分步实施计划

**目标：** 7 项 UX 优化，不动数据管线、不碰 W22、每步独立验证

**架构：** 只改前端（widget-registry.js + index.html + widget-base.js + css/theme.css + 2 个 widget），不改 store.js 核心逻辑

**技术栈：** 纯 HTML/CSS/JS，零依赖

---

### 任务 1: [P0-BUG] W03/W15 tier 修复

**文件：** `widget-registry.js:14,28`

**问题：** `tier:'realtime'` 不存在于 `store.js` 的 `tiers`（只有 tick/fast/slow/manual/daily），`widget-base.js:222` 查 `DataStore.tiers['realtime']` → `undefined` → 定时器不创建。

**改动：**

```javascript
// L14: 'realtime' → 'tick'
{ id:'W03', type:'position-calc', title:'三层仓位计', category:'decision', tier:'tick', ...

// L28: 'realtime' → 'tick'
{ id:'W15', type:'positions', title:'持仓+操作+清仓', category:'risk', tier:'tick', ...
```

**验证：**
```bash
grep "'realtime'" widget-registry.js  # 应返回空
grep "W03\|W15" widget-registry.js    # 确认 tier:'tick'
```
刷新看板 → W03 标题栏显示"5秒"刷新标签 → W15 盘中自动更新。

**提交：**
```bash
git add widget-registry.js
git commit -m "fix: W03/W15 tier realtime→tick, timer was never created

store.js defines tick/fast/slow/manual/daily — no 'realtime'.
DataStore.tiers['realtime'] returned undefined, _startTimers
skipped setInterval for both W03 and W15.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### 任务 2: [P0-UX] W16 报数面板字段分组 + 折叠

**文件：** `index.html:455-527`（浮窗模态框）

**问题：** 23 个字段平铺在 5 列 grid 中，无分组、无折叠，每天操作耗时。

**范围说明：** W16 有两种渲染形态：
1. `index.html` 的浮窗模态框（`_showInputPanel()`，23 个字段）— **本次改这里**
2. `widgets/input-panel.js` 的内嵌组件（19 个字段）— **本次不动**，保持现有结构

> 如果后续需要内嵌形态也加分组，再单独处理。

```javascript
// 替换 L455-480 的 fields 数组定义：
var groups = [
  { name:'账户头寸', open:true, fields:[
    {id:'总资产'},{id:'可用资金'},{id:'总盈亏'}
  ]},
  { name:'情绪指标', open:true, fields:[
    {id:'情绪值'},{id:'涨停收益'},{id:'连板收益'},{id:'炸板收益'},{id:'赚钱效应'}
  ]},
  { name:'盘面数据', open:true, fields:[
    {id:'上涨'},{id:'下跌'},{id:'涨停家数'},{id:'跌停家数'},{id:'晋级率'},{id:'封板率'}
  ]},
  { name:'连板生态', open:false, fields:[
    {id:'风险值'},{id:'最高板'},{id:'次高板'},{id:'梯队'}
  ]},
  { name:'W1窗口', open:false, fields:[
    {id:'W1观察1'},{id:'W1观察2'},{id:'W1观察3'}
  ]},
  { name:'W2窗口', open:false, fields:[
    {id:'W2观察1'},{id:'W2观察2'},{id:'W2观察3'}
  ]}
];

// 字段元数据查表（保留原有的 type/label/opts）
var fieldMeta = {
  '总资产':{type:'number',label:'总资产(元)'},
  '可用资金':{type:'number',label:'可用资金(元)'},
  '总盈亏':{type:'number',label:'总盈亏(元)'},
  '情绪值':{type:'number',label:'情绪值(%)'},
  '上涨':{type:'number',label:'上涨家数'},
  '下跌':{type:'number',label:'下跌家数'},
  '涨停收益':{type:'text',label:'涨停收益(%)'},
  '连板收益':{type:'text',label:'连板收益(%)'},
  '炸板收益':{type:'text',label:'炸板收益(%)'},
  '风险值':{type:'text',label:'连板风险值'},
  '晋级率':{type:'text',label:'晋级率(%)'},
  '封板率':{type:'text',label:'封板率(%)'},
  '涨停家数':{type:'number',label:'涨停家数'},
  '跌停家数':{type:'number',label:'跌停家数'},
  '赚钱效应':{type:'select',label:'赚钱效应',opts:['','好','一般','差']},
  '最高板':{type:'text',label:'最高板'},
  '次高板':{type:'text',label:'次高板'},
  '梯队':{type:'text',label:'连板梯队'},
  'W1观察1':{type:'text',label:'W1观察1'},
  'W1观察2':{type:'text',label:'W1观察2'},
  'W1观察3':{type:'text',label:'W1观察3'},
  'W2观察1':{type:'text',label:'W2观察1'},
  'W2观察2':{type:'text',label:'W2观察2'},
  'W2观察3':{type:'text',label:'W2观察3'}
};
```

渲染 HTML（替换 L482-496）：
```javascript
var html = '';
groups.forEach(function(g) {
  html += '<div class="input-group-section">' +
    '<div class="input-group-header" data-group="' + g.name + '" style="cursor:pointer;display:flex;align-items:center;gap:6px;padding:8px 0;border-bottom:1px solid var(--border-light);margin-bottom:8px;font-weight:600;font-size:13px;color:var(--text)">' +
    '<span class="group-arrow" style="transition:transform .2s;display:inline-block">' + (g.open ? '▼' : '▶') + '</span>' +
    g.name + ' <span style="font-weight:400;font-size:10px;color:var(--text-disabled)">(' + g.fields.length + '项)</span>' +
    '</div>' +
    '<div class="input-group-fields" style="display:' + (g.open ? 'grid' : 'none') + ';grid-template-columns:repeat(5,1fr);gap:var(--sp-sm);margin-bottom:12px">';

  g.fields.forEach(function(f) {
    var m = fieldMeta[f.id];
    html += '<div class="input-group"><label for="in_' + f.id + '">' + m.label + '</label>';
    if (m.type === 'select') {
      html += '<select id="in_' + f.id + '" style="width:100%">';
      (m.opts||[]).forEach(function(o) {
        html += '<option value="' + o + '"' + (String(manual[f.id]||'') === o ? ' selected' : '') + '>' + (o||'—') + '</option>';
      });
      html += '</select>';
    } else {
      html += '<input type="' + m.type + '" id="in_' + f.id + '" value="' + (manual[f.id]||'') + '" style="width:100%">';
    }
    html += '</div>';
  });
  html += '</div></div>';
});
```

折叠事件（在 `body.innerHTML = html` 之后，L503 之前插入）：
```javascript
// 分组折叠
body.querySelectorAll('.input-group-header').forEach(function(hdr) {
  hdr.addEventListener('click', function() {
    var fields = this.nextElementSibling;
    var arrow = this.querySelector('.group-arrow');
    if (fields.style.display === 'none') {
      fields.style.display = 'grid';
      arrow.textContent = '▼';
    } else {
      fields.style.display = 'none';
      arrow.textContent = '▶';
    }
  });
});
```

**验证：** 点"报数"按钮 → 面板按 6 组显示 → 点击"连板生态"标题折叠 → 点"刷新全部数据"正常 → Toast 出现

**提交：**
```bash
git add index.html
git commit -m "feat(w16): group 23 input fields into 6 collapsible sections

Flat 5-column grid was hard to scan. Now grouped by decision flow:
账户头寸 / 情绪指标 / 盘面数据 / 连板生态 / W1窗口 / W2窗口.
Each group is collapsible via header click.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### 任务 3: [P1] 加载骨架屏

**文件：** `widget-base.js:27-30`（`mount` 方法）、`css/theme.css`

**问题：** 数据未就绪时组件区域空白。

**改动：**

`widget-base.js` — 在 `_renderBody()` 调用前插入骨架：

```javascript
// mount() 方法中，_renderShell() 后、_renderBody() 前插入：
var body = this.getBody();
if (body) {
  var skel = document.createElement('div');
  skel.className = 'widget-skeleton';
  skel.innerHTML = '<div class="skeleton-bar" style="width:60%;height:12px;margin:8px 0;border-radius:4px"></div>' +
                   '<div class="skeleton-bar" style="width:40%;height:12px;margin:8px 0;border-radius:4px"></div>' +
                   '<div class="skeleton-bar" style="width:50%;height:12px;margin:8px 0;border-radius:4px"></div>';
  body.appendChild(skel);
  this._skelEl = skel;
}

this._renderBody();

// _renderBody 完成后清除骨架：
if (this._skelEl) { this._skelEl.remove(); this._skelEl = null; }
```

`css/theme.css` — 新增：
```css
.widget-skeleton{padding:12px 16px}
.skeleton-bar{background:linear-gradient(90deg,#f0eeec 25%,#e5e2de 50%,#f0eeec 75%);background-size:200% 100%;animation:shimmer 1.5s infinite}
@keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}
```

**验证：** 强刷页面 → 每个组件短暂显示灰色闪烁骨架 → 数据加载后骨架消失。

**提交：**
```bash
git add widget-base.js css/theme.css
git commit -m "feat: skeleton loading screen for all widgets

Shows animated gray placeholder bars in each widget body
before DataStore delivers merged data. Removed on first render.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### 任务 4: [P1] W08/W09 信号灯视觉增强

**文件：** `widgets/w1-check.js`、`widgets/w2-check.js`

**问题：** emoji 信号灯辨识度不够。

**改动：**

`widgets/w1-check.js` — 修改 `signalDot()` 函数（L108）：

```javascript
// 改前：return emoji-based
// 改后：
function signalDot(ok, size) {
  if (ok === true) return '<span style="color:#059669;font-size:' + (size||20) + 'px;font-weight:700">✓</span>';
  if (ok === false) return '<span style="color:#DC2626;font-size:' + (size||20) + 'px;font-weight:700">✗</span>';
  return '<span style="color:var(--warn);font-size:' + (size||20) + 'px;font-weight:700">●</span>';
}
```

`widgets/w2-check.js` — 找到买入信号渲染处，同样把 emoji 替换为 styled span。

```bash
# 先定位 w2-check.js 中的信号渲染
grep -n "signalDot\|🟢\|🔴\|●\|买入信号" widgets/w2-check.js
```

根据实际代码位置，将信号标记改为 `<span style="color:#059669;font-weight:700;font-size:16px">●</span>` 等。

**验证：** W08 条件通过显示绿色粗体 ✓，失败显示红色粗体 ✗。W09 买入信号为绿色粗体 ●。

**提交：**
```bash
git add widgets/w1-check.js widgets/w2-check.js
git commit -m "feat(w08/w09): replace emoji signals with styled text indicators

Green bold ✓ for pass, red bold ✗ for fail, orange ● for blocked.
Better visibility across light/dark backgrounds.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### 任务 5: [P1] Ctrl+F 组件搜索 + 快速定位

**文件：** `index.html`（顶部栏 HTML + JS）

**问题：** 22 个组件平铺，找组件要滚很久。

**改动：**

在 `index.html` 顶部按钮栏（L102 附近）的 `<button id="inputPanelBtn">` 前面加：

```html
<input id="widgetSearch" type="text" placeholder="搜索组件..."
  style="width:140px;height:28px;border:1px solid var(--border);border-radius:var(--radius-sm);padding:0 var(--sp-sm);font-size:var(--fs-body);font-family:var(--font-sans);background:var(--bg-card);color:var(--text);outline:none"
  title="输入组件名快速定位 (Ctrl+F)">
```

在 `index.html` 的 `<script>` 尾部加搜索逻辑：

```javascript
// 组件搜索定位
(function() {
  var input = document.getElementById('widgetSearch');
  if (!input) return;

  // Ctrl+F 聚焦搜索框（只在没有其他输入框获得焦点时拦截）
  document.addEventListener('keydown', function(e) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
      var tag = document.activeElement ? document.activeElement.tagName : '';
      var isInInput = (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA');
      if (!isInInput) {
        e.preventDefault();
        input.focus();
        input.select();
      }
    }
  });

  // 搜索
  input.addEventListener('input', function() {
    var q = this.value.trim().toLowerCase();
    // 清除之前的高亮
    document.querySelectorAll('.widget').forEach(function(w) { w.style.outline = ''; });
    if (!q) return;

    var firstMatch = null;
    document.querySelectorAll('.widget').forEach(function(w) {
      var idEl = w.querySelector('[class*="widget-id"]') || w.querySelector('[class*="title"]');
      var title = (idEl ? idEl.textContent : '') + ' ' + (w.id || '');
      if (title.toLowerCase().includes(q)) {
        w.style.outline = '2px solid var(--accent)';
        w.style.outlineOffset = '-2px';
        if (!firstMatch) firstMatch = w;
      }
    });
    if (firstMatch) firstMatch.scrollIntoView({ behavior:'smooth', block:'center' });
  });

  // Esc 清除搜索
  input.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') { this.value = ''; this.dispatchEvent(new Event('input')); this.blur(); }
  });
})();
```

**验证：** 按 Ctrl+F → 搜索框聚焦 → 输入"W08" → 页面滚动到 W08 并高亮橙色边框 → Esc 清除。

**提交：**
```bash
git add index.html
git commit -m "feat: widget search with Ctrl+F quick-locate

Adds search input in toolbar. Ctrl+F focuses it. Typing filters
widgets by title/ID, scrolls to first match, highlights with accent
border. Esc clears.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### 任务 6: [P1] 字号微调

**文件：** `css/theme.css:83`

**问题：** 基础正文 12px 偏小。

**改动：**

```css
/* L83: 12px → 13px */
--fs-body: 13px;
```

只改一个变量，全局生效。不改 `--fs-subtitle`（15px 已够大）和 `--fs-label`（10px 标签够用）。

**验证：** 刷新页面 → 正文比之前大一号 → 检查 W01/W06 等信息密度大的组件无溢出或换行。

**提交：**
```bash
git add css/theme.css
git commit -m "style: bump base font from 12px to 13px

--fs-body: 12px → 13px. Affects all body text globally.
Subtitle (15px) and label (10px) unchanged.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### 任务 7: [P1] W06 竞价面板字号

**文件：** `css/theme.css`

**问题：** W06 表格数据密集，12px 太小。

**先验证 class 名再写 CSS：**

```bash
grep -n "class.*table\|className.*table" widgets/auction-5d.js | head -10
```

根据实际 class 名（如 `.auction-table` 或 `.data-table` 或自定义名），把下方选择器替换为真实名字。

**改动：** 在 `css/theme.css` 末尾追加：

```css
/* W06 竞价面板字号例外 — 数据密集表格 */
/* ⚠️ 选择器需根据实际 class 名替换，下方为示例 */
.auction-table td,.auction-table th{font-size:13px!important}
```

**验证：** 刷新页面 → W06 表格字号比之前大 → 无溢出。

**提交：**
```bash
git add css/theme.css
git commit -m "style(w06): bump auction panel table font to 13px

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## 执行顺序

```
1 → 2 → 3 → 4 → 5 → 6 → 7
```

无依赖关系，按优先级排列。每步独立 commit。

## 完成验证

```bash
git log --oneline -7  # 确认 7 个 commit
node -c widget-base.js && echo "widget-base OK"
node -c widgets/w1-check.js && echo "w1-check OK"
node -c widgets/w2-check.js && echo "w2-check OK"
```
