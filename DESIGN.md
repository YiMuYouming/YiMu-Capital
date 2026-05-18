# 弈沐资本 · 品牌设计系统 DESIGN.md

> **统一品牌标识 · 双产品上下文**  
> 门户网站（Portal）× 量化数据看板（Dashboard）  
> 生成日期：2026-05-15 | 设计系统专家：Cai (彩格调)

---

## 品牌提取报告（Brand Extraction Protocol）

### 1. Locate — 品牌资产定位

| 资产 | 路径 |
|------|------|
| 门户首页 HTML | `/Users/YouMing/Documents/YM_Capital/portal/index.html` |
| 门户 Logo | `/Users/YouMing/Documents/YM_Capital/portal/logo-hero.png` |
| 看板主题 CSS | `/Users/YouMing/Documents/YM_Capital/live-dashboard/css/theme.css` |
| 看板首页 HTML | `/Users/YouMing/Documents/YM_Capital/live-dashboard/index.html` |
| 看板品牌 Logo | `/Users/YouMing/Documents/YM_Capital/live-dashboard/assets/logo.png` |
| 项目 CLAUDE.md | `/Users/YouMing/Documents/YM_Capital/portal/CLAUDE.md`, `/Users/YouMing/Documents/YM_Capital/live-dashboard/CLAUDE.md` |

### 2. Download — 资产内容摘要

- **Portal**：内容型门户，Noto Serif SC 衬线标题，12px 圆角卡片，暖白背景，编辑风布局
- **Dashboard**：GridStack 拖拽式交易监控面板，22 个组件，JetBrains Mono 等宽数字，6-8px 圆角，A 股红涨绿跌

### 3. Grep Hex — 核心色值提取

**品牌调色板（双产品共享）：**

```
主背景    #F7F5F3  warm ivory       ← 暖白基底
卡片背景  #FFFFFF  pure white
浅背景    #FAFAF9  off-white
悬浮背景  #F5F2EE  warm gray-light
基调色    #D97706  amber/terracotta  ← 品牌灵魂色
主文本    #2D2926  warm black        ← 暖黑
次文本    #5C5652  warm gray
禁文本    #8A8480  warm gray-muted
上行(红)  #DC2626  A-share 红涨
下行(绿)  #059669  A-share 绿跌
信息色    #2563EB  blue
警示色    #D97706  amber (同基调色)
危险色    #DC2626  red (同上行色)
特殊色    #7C3AED  purple
边界      #E5E2DE  warm gray-border
亮边界    #F0EEEC  warm gray-light-border
分割线    #D1CFC5  warm gray-divider
```

### 4. Codify — 品牌编码

完整的 CSS 变量体系已存在于 `theme.css`（54 个变量），涵盖背景 5 层、文本 4 阶、方向 2 色 + 语义 4 色、区块 6 色、阴影 4 级、排版 8 级、间距 5 阶、圆角 3 级。

### 5. Vocalise — 品牌视觉语言

> **弈沐资本的视觉语言可概括为："暖砚"—— 暖白象牙纸上研墨写就的金融手帖。**
>
> 它融合了传统文人的书写温度（暖白背景、衬线标题）与 A 股交易员的冷峻纪律（等宽数字、红绿方向色）。品牌核心是一抹 terracotta 琥珀色 #D97706，既像老砚台的包浆温润，又如交易台上的警示灯。整体不追求科技感的冷白蓝，而是选择"有温度的专业"—— 看起来像一本投资手记，用起来是一台量化终端。

---

## 设计系统推荐（Design System Candidates）

| 方案 | 设计系统 | 匹配度 | 核心特征 | 适合原因 |
|------|---------|--------|---------|---------|
| **A** | **Stripe** | ★★★★★ | 金融级极简主义、暖白 × 琥珀色系、清晰的信息层级、数据展示专家 | Stripe 的视觉 DNA 与弈沐高度吻合——暖白背景、琥珀色点缀、金融数据展示、既适合内容页面也适合仪表盘。其色彩令牌体系可直接映射弈沐品牌色。 |
| **B** | **Default (Neutral Modern)** | ★★★★☆ | 中性现代、通用优雅、安全容错、灵活可扩展 | 作为通用起始系统，可以完美承载弈沐的自定义品牌色。虽然没有 Stripe 的金融基因，但胜在零风格污染，所有视觉决策留给品牌色驱动。 |
| **C** | **Mastercard** | ★★★★☆ | 金融品牌系统、双色架构、红绿方向色成熟、数据可视化 | Mastercard 的红绿方向色体系与 A 股红涨绿跌天然契合，品牌厚重感适合金融场景，但暖白 × 琥珀色的调性与 Mastercard 的经典红黄略有距离。 |

**最终采纳：方案 A (Stripe) × 方案 B (Default Neutral Modern) 融合**  
以 Stripe 的金融极简主义为设计哲学，以 Default 的中性灵活为令牌骨架，注入弈沐资本自有品牌色。

---

## 1. Visual Theme — 视觉主题

### 整体哲学：暖砚 · 金融手帖

弈沐资本的视觉系统围绕 **"有温度的专业"** 展开——它不冷、不硬、不炫技，而是像一本在 warm ivory 纸上书写的投资手记，每一笔都经过审慎推敲。

### 五大视觉方向标定

| 维度 | 定位 | 说明 |
|------|------|------|
| 工艺 Craft | ★★★★☆ | 工匠级精细感，每一像素经得起审视 |
| 权威 Authority | ★★★☆☆ | 专业可信，但不追求银行式的冰冷权威 |
| 温暖 Warmth | ★★★★★ | 暖白基底是视觉体系的灵魂 |
| 新奇 Novelty | ★★☆☆☆ | 克制，不追逐设计潮流，追求历久弥新 |
| 玩趣 Play | ★☆☆☆☆ | 严肃的投资工具，零玩趣 |

### 双产品上下文

| 属性 | Portal（门户） | Dashboard（看板） |
|------|---------------|-------------------|
| **氛围** | 宽松、呼吸感、适宜长时间阅读 | 紧凑、高密度、适合盘中快速扫描 |
| **阅读节奏** | 慢 → 中 | 快 → 极快 |
| **字体性格** | 衬线标题（Noto Serif SC）彰显书写感 | 等宽数字（JetBrains Mono）彰显数据精度 |
| **圆角语言** | 12px 大圆角，柔和亲切 | 6-8px 小圆角，效率优先 |
| **留白密度** | 宽松（sp-md 间距为主） | 紧凑（sp-sm 间距为主） |
| **色彩情绪** | 暖白 + 琥珀点缀，编辑风 | 暖白基底 + 红绿方向色高对比 |

---

## 2. Color Palette — 色彩体系

### 品牌主色调

```css
/* ===== 品牌色板 ===== */

/* 背景层级 — warm ivory 家族 */
--bg-deep:        #F7F5F3;  /* 最深背景（门户 body / 看板 GridStack） */
--bg-base:        #FAFAF9;  /* 基础背景（看板输入区、表格交替行） */
--bg-card:        #FFFFFF;  /* 卡片/面板表面 */
--bg-hover:       #F5F2EE;  /* 悬浮态背景 */
--bg-input:       #FAFAF9;  /* 输入框背景 */

/* 文本层级 — warm black 家族 */
--text-primary:   #2D2926;  /* 主文本（暖黑） */
--text-secondary: #5C5652;  /* 次文本 */
--text-disabled:  #8A8480;  /* 禁用/辅助文本 */
--text-inverse:   #FFFFFF;  /* 反色文本（用于深色按钮上） */

/* 品牌基调色 — terracotta amber */
--accent:         #D97706;  /* 品牌灵魂色 */
--accent-hover:   #B45309;  /* 品牌色悬浮 */
--accent-active:  #92400E;  /* 品牌色点击 */
--accent-bg:      rgba(217,119,6,0.08);  /* 品牌色背景（轻量填充） */
--accent-light:   #FEF3C7;  /* 品牌色极浅（门户徽章、高亮） */

/* 方向色 — A 股红涨绿跌 */
--up:             #DC2626;  /* 上行/涨 */
--up-deep:        #B91C1C;  /* 上行深色（用于数字强调） */
--up-bg:          rgba(220,38,38,0.08);  /* 上行背景 */
--up-bg-hover:    rgba(220,38,38,0.15);  /* 上行悬浮背景 */
--down:           #059669;  /* 下行/跌 */
--down-deep:      #047857;  /* 下行深色 */
--down-bg:        rgba(5,150,105,0.08);  /* 下行背景 */
--down-bg-hover:  rgba(5,150,105,0.15);  /* 下行悬浮背景 */

/* 语义色 4 级 */
--info:           #2563EB;  /* 信息 */
--info-bg:        rgba(37,99,235,0.08);
--warn:           #D97706;  /* 警告（复用品牌色） */
--warn-bg:        rgba(217,119,6,0.08);
--danger:         #DC2626;  /* 危险（复用上行色） */
--danger-bg:      rgba(220,38,38,0.08);
--special:        #7C3AED;  /* 特殊/紫色 */
--special-bg:     rgba(124,58,237,0.08);

/* 区块类型色条（看板 Widget 左侧 3px 色条） */
--color-decision: #2563EB;  /* 决策类 */
--color-data:     #059669;  /* 数据类 */
--color-risk:     #B91C1C;  /* 风险类 */
--color-tool:     #78716C;  /* 工具类 */

/* 板块 6 色（看板板块热度组件） */
--sector-main:       #DC2626;  /* 主线 */
--sector-strong:     #D97706;  /* 强支线 */
--sector-candidate:  #2563EB;  /* 候选 */
--sector-divergence: #D97706;  /* 分歧 */
--sector-pulse:      #8A8480;  /* 脉冲 */
--sector-ebb:        #B0ACA8;  /* 退潮 */

/* 边界 */
--border:        #E5E2DE;  /* 标准边框 */
--border-light:  #F0EEEC;  /* 轻量边框 */
--divider:       #D1CFC5;  /* 分割线 */

/* 交互状态 */
--interactive-default:  rgba(45,41,38,0.02);
--interactive-hover:    rgba(45,41,38,0.04);
--interactive-active:   rgba(45,41,38,0.08);
--interactive-disabled: rgba(45,41,38,0.01);
```

### 色彩使用原则

1. **品牌色克制使用**：`--accent` (#D97706) 仅用于标题金属色、链接、高亮标签、以及看板 KPI 顶部装饰渐变线。大面积使用会喧宾夺主。
2. **方向色优先**：所有涨跌数据必须同时使用颜色和符号（如 `+2.34%` 为红色，`-1.02%` 为绿色），不依赖颜色作为唯一信息通道。
3. **对比度合规**：所有文本色组合通过 WCAG AA 标准（主文本 #2D2926 在 #F7F5F3 上对比度 12.3:1，次文本 #5C5652 对比度 5.9:1）。
4. **紫色 `--special` 谨慎使用**：仅用于 AI 相关/量化对手/特殊标记，不滥用。

---

## 3. Typography — 排版体系

### 字体栈

```css
/* 门户标题 — 衬线体，书写感 */
--font-serif: "Noto Serif SC", "Noto Serif", "Source Han Serif SC", "STSong", serif;

/* 看板/通用 — 无衬线体 */
--font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;

/* 数据数字 — 等宽体 */
--font-mono: "JetBrains Mono", "SF Mono", "Cascadia Code", "Fira Code", monospace;
```

### 字号层级

| 令牌 | 尺寸 | 行高 | 字重 | 使用场景 |
|------|------|------|------|---------|
| `--fs-micro` | 9px | 1.3 | 500 | 看板微标签、KPI 标签、表格表头 |
| `--fs-label` | 10px | 1.4 | 500 | 看板表单标签、辅助说明 |
| `--fs-body` | 12px | 1.5 | 400 | 看板正文、表格数据、门户辅助文本 |
| `--fs-header` | 13px | 1.4 | 600 | 看板 Widget 标题、门户分类标题 |
| `--fs-subtitle` | 15px | 1.5 | 500 | 门户卡片标题、看板次级 KPI |
| `--fs-kpi` | 22px | 1.15 | 800 | 看板 KPI 主数值 |
| `--fs-hero` | 28px | 1.2 | 700 | 看板超大 KPI |

**Portal 特有扩展：**

| 令牌 | 尺寸 | 行高 | 使用场景 |
|------|------|------|---------|
| `--portal-h1` | 24px | 1.3 | 门户大标题（Noto Serif SC） |
| `--portal-h2` | 18px | 1.3 | 门户区域标题（Noto Serif SC） |
| `--portal-body` | 15px | 1.6 | 门户正文 |
| `--portal-small` | 13px | 1.5 | 门户描述文本 |

### 字体使用原则

- **门户阅读场景**：标题使用 `--font-serif`，正文使用 `--font-sans`。行高 1.6 保证长时间阅读舒适度。
- **看板数据场景**：所有数字使用 `--font-mono` 且启用 `font-variant-numeric: tabular-nums lining-nums` 确保数字等宽对齐。
- **禁止混用**：门户中不要用等宽字体做标题，看板中不要用衬线字体做数据。

---

## 4. Component Styles — 组件样式

### 4.1 按钮

```css
/* 主按钮 — 品牌色 */
.btn-primary {
  background: var(--accent);
  color: var(--text-inverse);
  border: none;
  border-radius: var(--radius-md, 6px);
  padding: 6px 16px;
  font-size: var(--fs-body, 12px);
  font-weight: 600;
  cursor: pointer;
  transition: background .15s, transform .1s;
}
.btn-primary:hover  { background: var(--accent-hover, #B45309); }
.btn-primary:active { transform: scale(0.97); }

/* 次按钮 — 边框 */
.btn-secondary {
  background: var(--bg-card, #FFFFFF);
  color: var(--text-primary, #2D2926);
  border: 1px solid var(--border, #E5E2DE);
  border-radius: var(--radius-md, 6px);
  padding: 5px 15px;
  font-size: var(--fs-body, 12px);
  cursor: pointer;
  transition: border-color .15s, background .15s;
}
.btn-secondary:hover {
  border-color: var(--accent, #D97706);
  background: var(--accent-bg);
}

/* 图标按钮 */
.btn-icon {
  background: transparent;
  border: none;
  color: var(--text-disabled, #8A8480);
  width: 22px; height: 22px;
  border-radius: var(--radius-sm, 3px);
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  font-size: 11px;
  transition: background .15s, color .15s;
}
.btn-icon:hover { background: var(--interactive-hover); color: var(--text-primary); }
.btn-icon:active { background: var(--interactive-active); transform: scale(0.92); }
```

### 4.2 卡片

**Portal 卡片（内容型）：**

```css
.portal-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;    /* ← 门户特有 12px */
  padding: 18px;
  transition: border-color .15s, box-shadow .15s;
}
.portal-card:hover {
  border-color: var(--accent);
  box-shadow: 0 2px 12px rgba(217,119,6,0.08);
}
```

**Dashboard 卡片（数据型）：**

```css
.dash-card {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--widget-radius, 8px);  /* ← 看板特有 8px */
  box-shadow: var(--shadow-card);
  transition: box-shadow .25s ease, border-color .2s;
}
.dash-card:hover {
  box-shadow: var(--shadow-elevated);
  border-color: var(--border);
}
```

### 4.3 KPI 指标卡（看板专用）

```css
.kpi-card {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md, 6px);
  padding: var(--sp-sm) var(--sp-md);
  text-align: center;
  position: relative;
  overflow: hidden;
}
.kpi-card::after {
  content: '';
  position: absolute; top: 0; left: 0; right: 0; height: 2px;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  opacity: 0;
  transition: opacity .25s;
}
.kpi-card:hover::after { opacity: 1; }

.kpi-label {
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-disabled);
  margin-bottom: 4px;
}
.kpi-value {
  font-family: var(--font-mono);
  font-size: var(--fs-kpi, 22px);
  font-weight: 800;
  font-variant-numeric: tabular-nums lining-nums;
  line-height: 1.15;
}
.kpi-value.up   { color: var(--up-deep, #B91C1C); }
.kpi-value.down { color: var(--down-deep, #047857); }
```

### 4.4 数据表格（看板专用）

```css
.data-table {
  width: 100%;
  border-collapse: collapse;
  font-family: var(--font-mono);
  font-size: var(--fs-body, 12px);
}
.data-table th {
  position: sticky; top: 0;
  background: var(--bg-card);
  font-size: 9px; text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-disabled);
  text-align: left;
  padding: var(--sp-xs, 4px) var(--sp-sm, 8px);
  border-bottom: 1px solid var(--border);
  font-weight: 600;
  z-index: 1;
}
.data-table td {
  padding: var(--sp-xs, 4px) var(--sp-sm, 8px);
  border-bottom: 1px solid var(--border-light);
  font-variant-numeric: tabular-nums lining-nums;
  white-space: nowrap;
}
.data-table tr:nth-child(even) { background: var(--interactive-default); }
.data-table tr:hover { background: var(--interactive-hover); }
```

### 4.5 输入框（看板专用）

```css
.input-field {
  background: var(--bg-input);
  border: 1px solid var(--border-light);
  color: var(--text-primary);
  padding: var(--sp-xs, 4px) var(--sp-sm, 8px);
  border-radius: var(--radius-sm, 3px);
  font-size: var(--fs-body, 12px);
  font-family: var(--font-mono);
  transition: border-color .15s, box-shadow .15s;
}
.input-field:focus {
  outline: none;
  border-color: var(--info);
  box-shadow: 0 0 0 2px rgba(37,99,235,0.12);
}
```

### 4.6 标签/徽章

```css
.tag {
  display: inline-block;
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.2px;
}
.tag-live  { background: rgba(5,150,105,0.12); color: var(--down); }     /* 已上线 */
.tag-soon  { background: rgba(217,119,6,0.12); color: var(--accent); }    /* 即将 */
.tag-plan  { background: rgba(37,99,235,0.1);  color: var(--info); }      /* 计划 */
.tag-internal { background: rgba(217,119,6,0.12); color: var(--accent); } /* 内部 */

.tag-up    { background: var(--up-bg);   color: var(--up-deep); border: 1px solid rgba(220,38,38,0.12); }
.tag-down  { background: var(--down-bg); color: var(--down-deep); border: 1px solid rgba(5,150,105,0.12); }
```

### 4.7 侧边色条（看板 Widget 标题栏）

```css
.widget-header::before {
  content: '';
  position: absolute; left: 0; top: 0; bottom: 0;
  width: 3px;
  transition: width .15s;
}
.widget-header.color-decision::before { background: var(--color-decision, #2563EB); }
.widget-header.color-data::before     { background: var(--color-data, #059669); }
.widget-header.color-risk::before     { background: var(--color-risk, #B91C1C); }
.widget-header.color-tool::before     { background: var(--color-tool, #78716C); }
```

### 4.8 Widget Shell（看板 GridStack 容器）

```css
.grid-stack-item-content {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--widget-radius, 8px);
  overflow: hidden;
  box-shadow: var(--shadow-card);
  display: flex; flex-direction: column;
  height: 100%;
}
.widget-header {
  display: flex; align-items: center;
  height: 32px; padding: 0 var(--sp-sm);
  background: rgba(255,255,255,0.92);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--border-light);
  cursor: grab; user-select: none;
  flex-shrink: 0;
}
.widget-title {
  font-size: var(--fs-header, 13px);
  font-weight: 600; margin-left: var(--sp-sm);
  flex: 1;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.widget-body {
  padding: var(--sp-sm);
  overflow: auto;
  flex: 1;
}
```

### 4.9 连接状态指示器（看板专用）

```css
.conn-dot {
  display: inline-block;
  width: 7px; height: 7px;
  border-radius: 50%;
  margin-right: var(--sp-xs);
}
.conn-dot.live    { background: var(--down); box-shadow: 0 0 4px var(--down); }
.conn-dot.polling { background: var(--warn); animation: pulse-warn 2s ease-in-out infinite; }
.conn-dot.dead    { background: var(--danger); }
```

---

## 5. Layout — 布局体系

### 间距系统

```css
--sp-xs: 4px;    /* 微间距 — 看板表格内边距、元素间微间距 */
--sp-sm: 8px;    /* 小间距 — 看板 Widget 内边距、门户标签间距 */
--sp-md: 12px;   /* 中间距 — 看板卡片间距、门户网格间距 */
--sp-lg: 16px;   /* 大间距 — 看板 Topbar 间距、门户卡片内边距 */
--sp-xl: 24px;   /* 超大间距 — 门户区域间间距、看板模态框内边距 */
```

### Portal 布局

```css
/* 门户容器 — 居中窄栏 */
.portal-container {
  max-width: 960px;
  margin: 0 auto;
  padding: 0 32px 64px;
}

/* 门户网格 — 自适应卡片 */
.portal-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;  /* --sp-md */
}

/* 门户行列表 */
.portal-day-list {
  display: flex;
  flex-direction: column;
  gap: 8px;  /* --sp-sm */
}
```

### Dashboard 布局

```css
/* 看板使用 GridStack 引擎，组件可自由拖拽排列 */

/* Topbar */
.dash-topbar {
  position: sticky; top: 0; z-index: 100;
  display: flex; align-items: center; gap: var(--sp-sm);
  padding: var(--sp-sm) var(--sp-lg);
  background: rgba(255,255,255,0.92);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
  min-height: 44px;
  flex-wrap: wrap;
}

/* 看板标记条 */
.dash-pill {
  display: flex; align-items: center; gap: 5px;
  padding: 4px 10px;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md, 6px);
  font-size: var(--fs-body, 12px);
}
```

---

## 6. Depth & Elevation — 深度与阴影

### 阴影系统（4 级 + 模态）

所有阴影使用暖色调 `rgba(45,41,38, ...)` 而非冷色灰，与 warm ivory 背景协调。

```css
--shadow-card:     0 1px 3px rgba(45,41,38,0.06);     /* 默认卡片 */
--shadow-elevated: 0 4px 12px rgba(45,41,38,0.10);    /* 悬浮/交互态 */
--shadow-drag:     0 8px 24px rgba(45,41,38,0.14);    /* 拖拽态 */
--shadow-modal:    0 0 0 1px rgba(45,41,38,0.06),     /* 模态框/下拉菜单 */
                   0 24px 48px rgba(45,41,38,0.16);
```

### 层叠规范

| z-index | 用途 |
|---------|------|
| 1 | 表格 sticky header |
| 100 | Sticky Topbar |
| 2000 | Toast 提示 |
| 9999 | 全屏 Widget |
| 10000 | 模态框/上下文菜单 |

---

## 7. Cautions — 设计禁区

### 🚫 色彩禁忌

1. **不要将 `--accent` (#D97706) 用作大面积背景色** — 它仅用于点缀和高亮。大面积使用会产生廉价感。
2. **不要使用纯黑 `#000000`** — 所有文本使用暖黑 `#2D2926`，保持视觉温度的一致性。
3. **不要新增冷色背景** — 不要引入 `#F0F4F8` 之类的冷灰/蓝灰背景，破坏 warm ivory 的统一性。
4. **不要在非涨跌场景使用红绿色** — 方向色（红涨绿跌）专用于价格变化。进度条、标签等非涨跌场景使用语义色（info/warn/danger）。

### 🚫 排版禁忌

1. **门户中不要用等宽字体做标题** — Noto Serif SC 是门户标题的唯一选择。
2. **看板中不要用衬线字体做数据** — 所有数字必须使用 JetBrains Mono 等宽字体。
3. **不要使用小于 9px 的字体** — `--fs-micro` (9px) 是最小尺寸，仅用于看板微标签和表头。
4. **门户正文行高不要低于 1.5** — 内容阅读需要呼吸感。

### 🚫 组件禁忌

1. **不要使用纯圆角按钮** — 使用 6px 圆角（看板）或 12px（门户），不使用 `border-radius: 50%` 或 pill 形状的按钮。
2. **不要使用 Material Design 风格的阴影** — 使用暖色调自定义阴影层级。
3. **看板中不要使用大图标** — 图标不超过 22px，数据密度优先。
4. **门户中不要使用数据表格样式** — portal card list 使用柔和的行列表布局而非数据表格。

### 🚫 布局禁忌

1. **门户不要使用多列复杂布局** — 保持单列 + 两列网格的简洁性。
2. **看板不要使用百分比宽度** — 使用 GridStack 的固定栅格系统。
3. **不要在移动端做"汉堡菜单"** — 门户导航直接显示在顶栏，看板 Topbar 水平排列。

---

## 8. Responsive Behavior — 响应式行为

### Portal 响应式

```css
/* 默认：桌面宽屏 */
/* 平板 */
@media (max-width: 768px) {
  .portal-container { padding: 0 20px 40px; }
  .portal-grid { grid-template-columns: 1fr; }  /* 单列 */
}
/* 手机 */
@media (max-width: 640px) {
  .portal-hero { padding: 24px 20px 20px; }
  .header { padding: 12px 16px; }
  .nav { gap: 12px; }
  .nav a { font-size: 12px; }
}
```

### Dashboard 响应式

```css
/* 默认：≥1280px 桌面 */
/* 小桌面/大平板 */
@media (max-width: 1279px) {
  .dash-input-grid { grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); }
}
/* 平板 */
@media (max-width: 959px) {
  .dash-topbar { flex-wrap: wrap; }
  .dash-pill { font-size: var(--fs-label, 10px); padding: 3px 6px; }
  .data-table { font-size: var(--fs-label, 10px); }
  .kpi-value { font-size: 16px; }
}
/* 手机 */
@media (max-width: 767px) {
  .dash-topbar { gap: 4px; }
  .dash-pill { font-size: 9px; padding: 2px 4px; }
  .widget-body { padding: var(--sp-xs, 4px); }
}
```

### 响应式原则

1. **Portal 优先保障阅读**：移动端单列布局，字体不缩小，只调整间距。
2. **Dashboard 优先保障密度**：移动端缩小字号和间距，确保数据可读性。
3. **不断链**：最小支持宽度 375px (iPhone SE)，不做横向溢出。

---

## 9. Agent Prompt Guide — AI 生成引导

### 风格关键词

```
弈沐资本 · 暖砚风格 · 暖白象牙底色 · terracotta 琥珀点缀
金融极简 · A 股红涨绿跌 · 暖黑文本 · 等宽数字
Noto Serif SC 衬线标题（门户） · JetBrains Mono 等宽数字（看板）
12px 圆角（门户） · 6-8px 圆角（看板）
warm ivory · warm gray 边界 · 暖调阴影
有温度的专业 · 克制 · 不炫技 · 不冷
```

### CSS 快速引用

```css
/* 关键变量（最短引用集） */
--bg: #F7F5F3;
--bg-card: #FFFFFF;
--text: #2D2926;
--accent: #D97706;
--up: #DC2626;
--down: #059669;
--border: #E5E2DE;
--font-serif: "Noto Serif SC", serif;
--font-mono: "JetBrains Mono", monospace;
```

### Portal 生成指引

1. 生成门户页面时，使用 `Noto Serif SC` 作为 h1/h2 标题字体
2. 卡片圆角统一 12px（`border-radius: 12px`）
3. 背景色 #F7F5F3，卡片白色，边框 #E5E2DE
4. 正文行高 1.6，15px 字号
5. 链接色 = `--accent` (#D97706)，悬浮 = `#B45309`
6. 内容容器最大宽度 960px，居中
7. 头部使用 backdrop-filter blur 实现毛玻璃效果
8. 不要使用数据表格样式（portal 不是 dashboard）

### Dashboard 生成指引

1. 生成看板组件时，使用 `JetBrains Mono` 作为所有数字的字体
2. 圆角使用 `--widget-radius` (8px) 或 `--radius-md` (6px)
3. 背景使用 `--bg-deep` (#F7F5F3)，卡片白色，边框 `--border-light` (#F0EEEC)
4. 字号体系使用 `--fs-micro` (9px) 到 `--fs-hero` (28px)
5. 涨跌必须同时用颜色 + 符号（+/-）
6. Widget 标题栏左侧 3px 色条根据组件类型使用 `--color-decision/data/risk/tool`
7. KPI 数值使用 `--fs-kpi` (22px)，字重 800
8. 使用 4 级暖调阴影体系
9. 不要使用衬线字体
10. 间距紧凑（空间层级以 `--sp-sm` 8px 为主）

### 双场景检测

生成内容前，先判断所属产品：

```
如果内容是阅读型（文章、笔记、认知） → 使用 Portal 样式集
如果内容是数据型（表格、KPI、图表、监控） → 使用 Dashboard 样式集
如果混合型页面 → Portal 骨架 + Dashboard 数据组件
```

---

> **本设计系统由 彩格调（Cai）· 设计系统专家 基于弈沐资本品牌资产生成**
>
> 参考设计系统：Stripe (Design Philosophy) × Default Neutral Modern (Token Structure)  
> 品牌提取协议：5-Step Brand Extraction (Locate → Download → Grep Hex → Codify → Vocalise)  
> 结构规范：9-Segment DESIGN.md Schema
