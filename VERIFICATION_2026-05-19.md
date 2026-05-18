# 2026-05-19 验证清单

> 开盘前启动 bridge，全天验证。

## 启动

```bash
cd ~/Documents/YM_Capital/live-dashboard
python3 scripts/bridge.py 8088
# 确认 12 APScheduler jobs，浏览器打开 http://localhost:8088
```

---

## 一、仪表盘 22 Widget 冒烟（开盘后逐个检查）

| # | 组件 | 检查项 | 通过 |
|---|------|--------|------|
| W01 | 时段时间线 | 当前时段正确，倒计时走字 | |
| W02 | 风格检测卡 | 分数/风格/四维度有值 | |
| W03 | 仓位计 | 仓位% >0，连板/趋势分配 | |
| W04 | 市场全景 | 上证实时、涨跌家数、**北向资金有数据** | |
| W05 | 情绪仪表盘 | 情绪值自动更新（T3涨跌比） | |
| W06 | 竞价5维 | 9:25后快照就位，高标/自选池 | |
| W07 | 高潮保护 | 保护等级判定 | |
| W08 | W1早盘确认 | 三件套信号灯 + 条件判定 | |
| W09 | W2实时观察 | 60min MA10回踩信号 | |
| W10 | 板块热力 | 板块涨跌+**主力净流入非空** | |
| W11 | 15min量价 | 三指数量价柱 | |
| W12 | 连板池 | 标的列表+实时涨幅 | |
| W13 | 趋势池 | 标的列表+实时涨幅 | |
| W14 | 账户风控 | 熔断/回撤/连亏数值 | |
| W15 | 持仓明细 | 持仓+市值+盈亏 | |
| W16 | 报数面板 | 可录入，可刷新 | |
| W17 | 今日操作 | 可添加操作 | |
| W18 | 锚定股 | 状态+灯色 | |
| W19 | 午盘复核 | V反+双冰判定 | |
| W20 | AI盯盘 | 15min自动研判 | |
| W21 | 涨停梯队 | 题材归因 | |
| W22 | P&L曲线 | 收益曲线+抽屉 | |

---

## 二、LLM 自动填笔记（5 个时点）

**每个时点跑两次——LLM 和程序化，对比结果。**

```bash
cd ~/Documents/YM_Capital/live-dashboard

# 先预览 LLM 填的
python3 scripts/llm_fill.py 竞价 --dry-run

# 确认OK后正式写
python3 scripts/llm_fill.py 竞价
```

| 时点 | 命令 | LLM填入 | vs手贴对比 | 定性判断OK? |
|------|------|---------|-----------|------------|
| 9:25 | `llm_fill.py 竞价` | | | |
| 10:00 | `llm_fill.py 早盘` | | | |
| 11:30 | `llm_fill.py 午盘` | | | |
| 14:45 | `llm_fill.py 尾盘` | | | |
| 15:05 | `llm_fill.py 收盘` | | | |

**对比要点：**
- 数据值是否和同花顺/问财报的一致（偏差<5%）
- 定性判断是否合理（不是胡说的）
- 人写内容是否被覆盖（必须不能）
- frontmatter 收盘后填入率（目标 25+/30）

---

## 三、数据管线

```bash
# 盘中随时检查
curl -s http://localhost:8088/api/live/quotes | python3 -c "import json,sys; d=json.load(sys.stdin); print('上证:', d.get('live_index',{}).get('上证指数'), '| 个股:', len([k for k in d.get('live_quotes',{}) if not k.startswith('_')]))"

curl -s http://localhost:8088/api/live/iwencai | python3 -c "import json,sys; d=json.load(sys.stdin); print('iwen keys:', len(d))"

curl -s http://localhost:8088/api/pnl/summary | python3 -c "import json,sys; d=json.load(sys.stdin); print('pnl:', d.get('_freshness',{}).get('level'))"
```

| 检查项 | 9:30 | 11:00 | 14:00 | 15:30 |
|--------|------|-------|-------|-------|
| T1 指数实时 | | | | |
| T1 个股行情 | | | | |
| T2 iwencai | | | | |
| P&L 可用 | | | | |
| SSE 推送 | | | | |
| APScheduler 0 skipped | | | | |

---

## 四、收盘后

```bash
# 跑全套测试
python3 -m pytest tests/ -q
python3 scripts/diff_check.py
```

| 检查项 | 结果 |
|--------|------|
| pytest | /23 |
| diff_check | /4 |
| 笔记 frontmatter 填入率 | /30 |
| 笔记表1 5节点全填 | /5 |
| 笔记表2 14指标填满 | /14 |

---

## 五、发现的问题

（随时记录）
```

（备注：9:25是竞价结束、10:00是W1窗口结束、11:30上午收盘、14:45W2结束、15:00收盘、15:05 LLM填收盘，和你有差异吗？）
