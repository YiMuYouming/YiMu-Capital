# LLM 自动填写复盘笔记 — 实施计划

**目标：** 废弃程序化字段映射，改用 LLM 在盘中 5 个时点自动读取全盘数据 + 理解笔记结构 + 填充数据与定性判断。收盘时复盘笔记已完稿，人只需补策略心得和次日预案。

**架构：** bridge APScheduler 5 时点 hook → DeepSeek API → 读 pipeline 数据 + 当前笔记 → LLM 理解 Markdown 上下文后填入数据 + 一句定性判断 → 不覆盖人写内容。

**技术栈：** DeepSeek V4 Flash + bridge API + APScheduler + 已有管线（零新依赖）

---

## 〇、为什么是 LLM 而不是程序

```
程序化 fill_review_note.py:
  字段A → 读数据源B → 填入模板C  ← 每个字段硬编码映射
  ❌ 字段名对不上就填不进去
  ❌ 数据源变了要改映射代码
  ❌ 只能填数字，写不了定性判断

LLM 填写:
  给它全盘数据 + 笔记模板 → 它理解上下文后自己填
  ✅ 不关心字段名，自己适配表头
  ✅ 数据源变了 LLM 自己适应
  ✅ 数据 + 定性一起出
```

---

## 一、五个时点 Hook

每个时点触发一次 LLM 调用，读取当前全盘数据 + 笔记内容，填入对应时间段。

```
┌────────┬─────────────────────────────────────────────────────────────┐
│ 9:25   │ 竞价结束 → LLM 填：frontmatter 竞价情绪值、表1 竞价行       │
│        │           表2 竞价列（竞价强势家数/涨停收益/竞价验证结论）   │
│        │           §一 竞价节点说明：定性判断 + 开盘预期              │
├────────┼─────────────────────────────────────────────────────────────┤
│ 10:00  │ W1 窗口结束 → LLM 填：表1 早盘行、表2 早盘列                │
│        │               情绪值/上证/涨跌比/量能                        │
│        │               §一 早盘节点说明：W1 操作结果 + 方向确认       │
├────────┼─────────────────────────────────────────────────────────────┤
│ 11:30  │ 午盘前 → LLM 填：表1 午盘行、表2 午盘列                     │
│        │           §一 午盘节点说明：上午总结 + 下午预判               │
├────────┼─────────────────────────────────────────────────────────────┤
│ 14:45  │ W2 窗口结束 → LLM 填：表1 尾盘行、表2 尾盘列                │
│        │               §一 尾盘节点说明：W2 操作 + 收盘前持仓状态      │
├────────┼─────────────────────────────────────────────────────────────┤
│ 15:05  │ 收盘 → LLM 填：表1 收盘行、表2 收盘列                       │
│        │         frontmatter 全部管线字段（涨停家数/晋级率/封板率等）  │
│        │         §一 收盘节点说明 + 一句话结论                         │
│        │         涨停结构 + 连板股列表                                 │
│        │         §一 收盘数据快照全部填完                              │
└────────┴─────────────────────────────────────────────────────────────┘
```

---

## 二、LLM Prompt 设计

每次调用给 LLM 三样东西：

### 2.1 系统 Prompt

```
你是弈沐资本复盘助手。每次被调用时，你会收到：
1. 当前时间段（竞价/早盘/午盘/尾盘/收盘）
2. 全盘实时数据快照（JSON）
3. 当前复盘笔记内容（Markdown）

你的任务：
- 理解笔记的 Markdown 结构（表头、字段名、章节）
- 将数据填入对应位置的空格子
- 为当前时段写一句 20-50 字的定性判断
- 绝对不覆盖人已经写过的内容（非空非模板格不碰）

数据填入规则：
- 涨停家数/跌停家数 → 从 breadth 取
- 情绪值 → 从 T3 涨跌比计算（上涨/(上涨+下跌)×100）
- 炸板率/封板率/晋级率/最高板/连板风险值 → 从 iwencai 取
- 赚钱效应 → 涨停收益>2%→好，<0→差，其余→一般
- 各节点数据 → 匹配当前时段填入表1/表2对应行列
- 空值或"—" → 留空不填

定性判断规则：
- 竞价：判断三件套（情绪/收益/高开）+ 开盘预期
- 早盘：W1 窗口操作结果 + 方向确认
- 午盘：上午总结 + 下午风险提示
- 尾盘：W2 窗口 + 收盘前持仓状态
- 收盘：全天一句话总结

输出格式：
直接输出修改后的完整 Markdown 笔记。不输出任何解释文字。
```

### 2.2 用户 Prompt（每次构建）

```
当前时段: {竞价|早盘|午盘|尾盘|收盘}

全盘数据:
{JSON snapshot from /api/live/quotes + /api/live/iwencai + auction_snapshot}

当前笔记:
{现有 Markdown 内容}

请填入 {当前时段} 的数据和定性判断。
```

### 2.3 数据快照构建

每次调用前，从 bridge CACHE 和磁盘文件构建一个精简数据包（不是全量，挑 LLM 需要的）：

```python
def build_llm_snapshot(node):
    return {
        "时段": node,
        "指数": {
            "上证": CACHE["live_index"].get("上证指数"),
            "上证涨幅": CACHE["live_index"].get("上证指数涨幅"),
            "深证涨幅": CACHE["live_index"].get("深证指数涨幅"),
            "创业涨幅": CACHE["live_index"].get("创业指数涨幅"),
            "成交额": CACHE["live_index"].get("成交额"),
            "上涨": CACHE["live_index"].get("上涨家数"),
            "下跌": CACHE["live_index"].get("下跌家数"),
        },
        "情绪": {
            "封板率": CACHE.get("iwencai", {}).get("封板率"),
            "炸板率": CACHE.get("iwencai", {}).get("炸板率"),
            "晋级率": CACHE.get("iwencai", {}).get("晋级率"),
            "最高板": CACHE.get("iwencai", {}).get("最高板"),
            "连板收益": CACHE.get("iwencai", {}).get("连板收益"),
            "炸板收益": CACHE.get("iwencai", {}).get("炸板收益"),
            "涨停收益": CACHE.get("iwencai", {}).get("昨日涨停收益"),
            "赚钱效应": CACHE.get("iwencai", {}).get("赚钱效应"),
        },
        "广度": CACHE.get("breadth", {}),
        "竞价": {  # 仅竞价时段
            "强势家数": auction_snapshot.get("竞价强势家数"),
            "指数竞价涨幅": auction_snapshot.get("指数竞价"),
            "涨跌比": auction_snapshot.get("涨跌家数"),
        } if node == "竞价" else None,
        "北向": CACHE.get("northbound", {}).get("hgt_current_yi"),
        "板块净流入": CACHE.get("sector_inflow", {}).get("top", [])[:5],
    }
```

---

## 三、关键设计决策

### 3.1 LLM 怎么知道填哪个格子

LLM 读 Markdown 原文，识别表头 `| 节点 | 情绪 | 上证(%) |` → 找到当前时段所在行 → 找到空单元格 → 填入数据。**不需要硬编码列索引。**

### 3.2 怎样不覆盖人写内容

Prompt 里明确指令：非空且非模板值（`—`、`%`、`待填`）的格子不碰。LLM 理解这条规则。

### 3.3 上下文长度控制

每次只给 LLM 当前时段需要的数据（精简 JSON），不是全量 dashboard_data.json。笔记内容只给 LLM 需要修改的章节（如 §一 当前节点的几行），不是全文。

### 3.4 DeepSeek 成本

DeepSeek V4 Flash，每次调用约 0.5-1 元。每天 5 次，月成本约 100 元。比人每天贴 45 分钟数据的成本低两个数量级。

### 3.5 事后验证

每次 LLM 填完后，bridge 跑一次轻量校验：检查填入的数值是否和快照数据一致（±5% 偏差内）。不一致就标记 ⚠️。

---

## 四、实施计划（两阶段）

### Phase 1：核心通道（1-2 天）

#### 任务 1.1：build_llm_snapshot() 数据打包函数

**文件**：修改 `scripts/bridge.py`，新增 `_build_llm_snapshot(node)` 函数。

从 CACHE 构建精简数据包，不同节点包含不同字段。

#### 任务 1.2：LLM 调用函数

**文件**：新建 `scripts/llm_fill.py`

```python
def fill_review_note(node, note_path, snapshot):
    """调用 DeepSeek，填入当前时段数据+定性"""
    system_prompt = "..."  # 上面的系统 prompt
    user_prompt = f"当前时段: {node}\n\n全盘数据:\n{json}\n\n当前笔记:\n{md}"
    # 调用 DeepSeek API
    # 返回修改后的 Markdown
```

复用 bridge.py 已有的 `_call_llm_api()` 和 `_load_api_config()`。

#### 任务 1.3：APScheduler 注册 5 个 Hook

**文件**：修改 `scripts/bridge.py`

```python
scheduler.add_job(lambda: llm_fill.fill_review_note('竞价', note_path, ...), 
                  'cron', hour=9, minute=25)
scheduler.add_job(lambda: llm_fill.fill_review_note('早盘', note_path, ...), 
                  'cron', hour=10, minute=0)
scheduler.add_job(lambda: llm_fill.fill_review_note('午盘', note_path, ...), 
                  'cron', hour=11, minute=30)
scheduler.add_job(lambda: llm_fill.fill_review_note('尾盘', note_path, ...), 
                  'cron', hour=14, minute=45)
scheduler.add_job(lambda: llm_fill.fill_review_note('收盘', note_path, ...), 
                  'cron', hour=15, minute=5)
```

#### 任务 1.4：笔记路径自动发现

每次 hook 触发时，自动找今天笔记文件，不存在则从模板创建一份新的。

### Phase 2：优化提效（3-5 天，Phase 1 跑通后）

- 上下文分段——只给 LLM 当前需要修改的章节而非全文
- 数值校验——填完后对比快照数据，标注差异
- 增量编辑——LLM 只输出修改的 diff 而不是全量 Markdown
- 人机协作——稳米收到通知后可一键审核 LLM 填的内容

---

## 五、和现有 fill_review_note.py 的关系

**废弃** `fill_review_note.py`。LLM 填完后如果还需要补充 P&L 等硬数据，可以跑一次 gen_dashboard_data.py 作为交叉校验。但主要填写逻辑不再走程序化路径。

---

## 六、和 live-dashboard 的关系

不变。live-dashboard 是**盘中实时看盘工具**，LLM 填笔记是**并行的自动记录系统**。两者共用同一份数据管线，互为备份：

```
盘中:
  ├── 弈沐哥看 live-dashboard → 实时决策
  └── LLM 5 次 hook 自动记笔记 → 策略留痕

收盘后:
  笔记已完稿 → 弈沐哥补心得+预案 → 稳米执行红方对抗 → Portal 发布
```

---

## 七、废弃项

| 废弃 | 原因 |
|------|------|
| `scripts/fill_review_note.py` | 程序化字段映射被 LLM 替代 |
| `scripts/snapshot_close.py` | LLM 直接从 CACHE 读，不需要收盘数据包 |
| 15:02 snapshot_close cron | 同上 |

---

## 八、验证方案

1. 非交易时段，手动触发一次 9:25 hook：`python3 -c "from scripts.llm_fill import fill_review_note; fill_review_note('竞价', '...')"`
2. 打开笔记检查竞价段数据+定性是否合理
3. 模拟 15:05 收盘 hook，检查 frontmatter + 所有表格是否填满
4. 确认稳米手写内容是否被覆盖（必须不能）
5. 跑完整一个交易日，对比 LLM 填入值和 source 数据偏差
