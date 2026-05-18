# 复盘笔记自动填充 — 项目 Handoff

> 创建：2026-05-18 傍晚 | 状态：核心流程已通，字段匹配和覆盖率需要调

## 一、项目目标

收盘后，管线数据自动填入复盘笔记。人不再贴涨停家数、情绪值、晋级率等数据，只写定性内容（盘面分析、操作理由、心得、预案）。

## 二、数据流

```
盘中: collectors → bridge CACHE + sentiment_auto.json (30min快照)

15:02: snapshot_close cron → close_snapshot_{date}.json (收盘数据包)
15:10: iwencai 采集最后一次 → 最终数据入 CACHE

收盘后: fill_review_note.py --date 2026-05-19
  ├── 读 close_snapshot_{date}.json (frontmatter 主力源)
  ├── 读 sentiment_auto.json (表1/表2 按节点匹配)
  ├── 读 auction_snapshot.json (竞价数据)
  ├── 读 pools.json (自选池)
  ├── 读 pnl.db (P&L)
  └── → 填入笔记，只填空格子，不覆盖已有内容
```

## 三、关键文件

| 文件 | 用途 | 状态 |
|------|------|------|
| `scripts/fill_review_note.py` | 核心填充脚本，674行 | 逻辑对，字段匹配不全 |
| `scripts/collectors/iwencai_poll.py` | iwencai 2min轮询，含8个查询 | 已扩增连板/炸板收益查询 |
| `scripts/collectors/sentiment_snapshot.py` | 30min快照，已扩增字段 | 快照字段需继续扩 |
| `scripts/collectors/market_data.py` | 板块净流入+财联社电报 | 正常 |
| `scripts/bridge.py` | snapshot_close cron (15:02) | 已注册 |
| `data/close_snapshot_{date}.json` | 收盘数据包 | bridge自动生成 |
| `data/sentiment_auto.json` | 30min快照 | 按日期分组的快照列表 |

## 四、当前问题清单

### 4.1 字段匹配不全（数据有但填不进去）

fill_review_note.py 读 close_snapshot 时，iwencai 字段的 key 名和脚本期望的不一致。具体来说：

- iwencai_poll 返回的字段名（如 `封板率`、`涨停晋级率`）存在 CACHE 里
- snapshot_close 把它们 dump 到 close_snapshot.json 的 `iwencai` 字段
- fill 脚本读的时候期望的 key 名和实际不完全匹配

**需要做**：逐字段对一遍——fill 脚本期望什么 key → iwencai_poll 实际存了什么 key → 对齐。

### 4.2 涨停家数/跌停家数来源

这两个数据在 close_snapshot 的 `live_index` 和 `breadth` 里有，不是 iwencai 字段。fill 脚本应该从 `live_index.上涨家数/下跌家数` 或 `breadth` 取，但当前没读到。

### 4.3 sentiment_auto 快照数太少

今天 bridge 反复重启，只有 3 个快照（竞价/早盘/午盘），尾盘和收盘的快照缺失。正常交易日应该 12-14 个。明天稳定跑一天应该够。

### 4.4 CACHE 共享

sentiment_snapshot.py 和 bridge.py 的 CACHE 是同一个引用（bridge 里 `sentiment_snapshot.CACHE = CACHE`），但快照里有些 iwencai 字段是 null——说明快照时 iwencai CACHE 还没被 iwencai_poll 填充。需要确认 iwencai_poll 的 CACHE 也是同一个引用。

### 4.5 一进二/二进三/三进四晋级率

这些需要 style_detect.py 才能算。fill 脚本需要读 dashboard_data.json 的 style 域。当前 style_detect.py 已复制到 live-dashboard/scripts/，gen 也改路径了。但 fill 脚本还不会自动触发 style_detect。

### 4.6 P&L 数据

pnl.db 连不上，所有 P&L 字段为空。

### 4.7 表2 部分列空

封板率/炸板率/晋级率 的 竞价/早盘/午盘 三列是空的——iwencai 数据是收盘后一次性查的，没有盘中各节点的历史值。这需要在 iwencai_poll 每次轮询时把当时的封板率/炸板率也写进 sentiment_snapshot。

## 五、验证方法

```bash
cd ~/Documents/YM_Capital/live-dashboard

# 1. 检查收盘快照有没有今天的数据
ls -la data/close_snapshot_$(date +%Y-%m-%d).json

# 2. 手动查一次 iwencai（确认数据可获取）
python3 -c "
import sys, json
sys.path.insert(0, '/Users/YouMing/Documents/YM_Capital/YM-data-pipeline')
from ym_stock_data.sources.iwencai import query
r = query('封板率 炸板率 涨停晋级率 最高板 赚钱效应 非st', limit=5)
print(json.dumps(r.get('datas',[])[:2], ensure_ascii=False, indent=2))
"

# 3. 预览填充效果（不实际写）
python3 scripts/fill_review_note.py --date $(date +%Y-%m-%d) --dry-run | head -60

# 4. 正式写入
python3 scripts/fill_review_note.py --date $(date +%Y-%m-%d)
```

## 六、下一步

1. **对齐字段名**：fill_review_note.py 里读 iwencai 数据的 key 和 iwencai_poll 实际存的 key 完全对齐
2. **涨停家数/跌停家数**：从 close_snapshot 的 breadth 取
3. **扩增 sentiment_snapshot**：每次快照时把 iwencai 数据（封板率/炸板率/晋级率）也写进去
4. **表2 每个节点列**：从 sentiment_auto 的每条快照取 iwencai 数据
5. **pnl.db 连通**：fill 脚本读 P&L
6. **端到端测试**：跑完整的一天，frontmatter 填入率达到 25+/30

## 七、相关计划

- `~/Documents/YM_Capital/plans/review-note-automation.md` — 解耦计划
- `~/Documents/YM_Capital/live-dashboard/docs/plans/2026-05-18-data-architecture-refactor.md` — 架构重构计划（已完成）
