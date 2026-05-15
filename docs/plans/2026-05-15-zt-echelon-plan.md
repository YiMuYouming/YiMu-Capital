# 涨停梯队 W21 实施计划

**目标：** 新增涨停梯队实时组件，展示当日涨停全景（日期→概念→股票三层下钻）

**架构：** poll_live.py 追加 ths_hot 数据 → dashboard_live.json → DataStore merge → W21 widget 渲染。连板性质前端 JS 算，历史数据会话内缓存。

**技术栈：** Python (ym_stock_data), 原生 JS (YiMuWidget), theme.css 变量

---

## 分批概览

| 批 | 内容 | 文件 |
|----|------|------|
| 1 | 数据层：hot_list 进 poll_live | consumer/dashboard.py, poll_live.py |
| 2 | 前端骨架：W21 注册+渲染 | zt-echelon.js, widget-registry.js, index.html |
| 3 | 交互+LLM+打磨 | zt-echelon.js |

---

### 任务 1: consumer/dashboard.py — hot_list 扩展

**文件：** 修改 `YM-data-pipeline/ym_stock_data/consumer/dashboard.py:148-156`

**改动：** `hot_list` 字典追加 `zt_stocks` 数组

```python
# 改前 (line 150-154):
data["hot_list"] = {
    "total": r.get("total", 0),
    "zt_count": r.get("zt_count", 0),
    "reason_stats": r.get("reason_stats", {}),
}

# 改后:
data["hot_list"] = {
    "total": r.get("total", 0),
    "zt_count": r.get("zt_count", 0),
    "reason_stats": r.get("reason_stats", {}),
    "zt_stocks": r.get("zt_stocks", []),
}
```

**验证：**
```bash
cd /Users/YouMing/Documents/YM_Capital/YM-data-pipeline
python3 -c "from ym_stock_data.consumer.dashboard import build_live; d=build_live(); hl=d.get('hot_list',{}); print('zt_stocks:', len(hl.get('zt_stocks',[])), 'zt_count:', hl.get('zt_count',0))"
```

---

### 任务 2: poll_live.py — 追加 hot_list 数据

**文件：** 修改 `live-dashboard/scripts/poll_live.py`

**改动：**
1. 文件头追加 import（line 14 附近）
2. `build_live_data()` 末尾追加 hot_list 拉取（line 1208 附近）
3. 新增 `_fetch_hot_list()` 函数

```python
# 1. 追加 import (line 14 后):
try:
    from ym_stock_data.fetch import fetch
except ImportError:
    fetch = None

# 2. 新函数:
def _fetch_hot_list():
    """拉取同花顺热点涨停数据"""
    if not fetch:
        return None
    try:
        r = fetch("ths_hot")
        return {
            "total": r.get("total", 0),
            "zt_count": r.get("zt_count", 0),
            "reason_stats": r.get("reason_stats", {}),
            "zt_stocks": r.get("zt_stocks", []),
        }
    except Exception:
        return None

# 3. build_live_data() 中追加 (after line 1208, before "data["meta"]"):
    # 同花顺热榜涨停 (ths_hot)
    hl = _fetch_hot_list()
    if hl:
        data["hot_list"] = hl
```

**验证：**
```bash
cd /Users/YouMing/Documents/YM_Capital/live-dashboard
python3 scripts/poll_live.py 2>&1 | python3 -c "import sys,json; d=json.load(sys.stdin); hl=d.get('hot_list',{}); print('hot_list:', 'zt_count='+str(hl.get('zt_count','N/A')), 'zt_stocks='+str(len(hl.get('zt_stocks',[]))), 'reason_stats keys='+str(len(hl.get('reason_stats',{}))))"
```

---

### 任务 3: zt-echelon.js — 前端组件

**文件：** 新建 `live-dashboard/widgets/zt-echelon.js`

**结构：**
```
class ZtEchelonWidget extends YiMuWidget
  render(data):
    1. 读取 data.hot_list
    2. 无数据 → 渲染"等待开盘"占位
    3. 有数据 → 渲染完整三行结构
       - 日期Tab (默认今天)
       - 概念标签 (reason_stats Top5标火, 多选过滤)
       - 表头 (性质/板块可点击)
       - 股票列表 (名称/涨幅/换手/成交额/性质/板块)
       - 底部统计栏 (最高板/连板分布)
       - LLM槽位
  _computeLianbanNature(code, todayDate):
    对比 zt_history 跨日匹配 → 首板/二连板/N天M板
  _sortByNature():
    按连板高度降序
  _sortByReason():
    按板块名分组
  _loadHistory():
    会话内 fetch ths_history.json 一次
  _loadLLMInsight():
    复用 W10 模式读 llm_insights.json
```

**关键实现细节：**
- 连板判定：今日 zt_stocks 的 code → 查昨日 zt_stocks → 查前天 → ... → 连续N天="N连板", 非连续多次="N天M板", 仅今天="首板"
- 概念标签：取 reason_stats keys，按 count 降序，前 5 加 🔥 标记
- 过滤：选中概念标签 → 过滤 reason 包含该标签的股票，多选取并集
- 列宽：名称 flex, 涨幅 60px, 换手 56px, 成交额 64px, 性质 64px, 板块 flex
- 空字段：huanshou/chengjiaoe 为 null 显示 "—"

**验证：** Chrome 打开看板 → 确认 W21 卡片渲染
```bash
# 重启服务
kill $(pgrep -f "poll_live.py") 2>/dev/null
cd /Users/YouMing/Documents/YM_Capital/live-dashboard
python3 scripts/poll_live.py --watch &
sleep 6
cat data/dashboard_live.json | python3 -c "import sys,json; d=json.load(sys.stdin); hl=d.get('hot_list',{}); print('hot_list zt_count:', hl.get('zt_count'), 'zt_stocks sample:', hl.get('zt_stocks',[])[:2] if hl.get('zt_stocks') else 'EMPTY')"
```

---

### 任务 4: widget-registry.js — 注册 W21

**文件：** 修改 `live-dashboard/widget-registry.js`（在 W20 行后追加）

```javascript
{ id:'W21', type:'zt-echelon',  title:'涨停梯队',   category:'data',   tier:'tick',  defaultSize:{w:8,h:7}, dataPaths:['hot_list'], priority:'P1' },
```

---

### 任务 5: index.html — 引入脚本

**文件：** 修改 `live-dashboard/index.html`（在 W20 llm-monitor.js 后追加）

```html
<script src="widgets/zt-echelon.js"></script>
```

---

### 任务 6: 端到端验证

**步骤：**
1. 重启 poll_live → 确认 dashboard_live.json 含 hot_list.zt_stocks
2. 浏览器刷新看板 → W21 卡片渲染
3. 点击概念标签过滤 → 列表刷新
4. 点击性质/板块排序 → 排序生效
5. 检查主题颜色 → 与现有卡片一致
6. 检查 LLM 槽位 → 读取 llm_insights.json

---

## 不改的文件

- **store.js** — line 192 `if (liveData.hot_list) { d.hot_list = liveData.hot_list; }` 已就绪，不改
- **bridge.py** — 不新增端点，数据走 DataStore 现有管线
- **theme.css** — 全用现有变量，不新增
