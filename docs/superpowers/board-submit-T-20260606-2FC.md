# W25 态势证据屏 — Board Submit

**Task:** T-20260606-2FC
**执行者:** 黑米 (heimer)
**验收者:** 欧米

---

## 交付文件

| 文件 | 状态 | 说明 |
|------|------|------|
| `evidence-summary.js` | ✅ 新增 | pure function EvidenceSummary.build(data, runtime) |
| `widgets/evidence-board.js` | ✅ 新增 | W25 态势证据屏 Widget |
| `css/theme.css` | ✅ 修改 | W25 样式 + evidence-inline-ref marker |
| `widget-registry.js` | ✅ 修改 | 注册 W25 元数据 |
| `index.html` | ✅ 修改 | 加载脚本 + CORE_IDS + REQUIRED_LAYOUT_WIDGETS |
| `widgets/positions.js` | ✅ 修改 | 添加 E1 证据锚点 |
| `widgets/trade-tickets.js` | ✅ 修改 | 添加 E2 证据锚点 |
| `widgets/market-overview.js` | ✅ 修改 | 添加 E3 证据锚点 |
| `widgets/pnl-curve.js` | ✅ 修改 | 添加 E4 证据锚点 |
| `tests/test_evidence_summary.py` | ✅ 新增 | 纯函数单元测试（3个 case） |
| `tests/test_frontend_rule_state.py` | ✅ 修改 | W25 smoke test |

---

## 验证命令

### 1. 纯函数测试（核心）
```bash
cd /Users/yimu/Documents/YM_Capital/live-dashboard
python3 -m unittest tests.test_evidence_summary -v
```
**期望:** 3 tests OK

### 2. W25 Widget 渲染测试
```bash
cd /Users/yimu/Documents/YM_Capital/live-dashboard
python3 -m unittest tests.test_frontend_rule_state.EvidenceBoardWidgetTest -v
```
**期望:** 1 test OK

### 3. 全量回归（排除已知的 2 个 pre-existing 失败）
```bash
cd /Users/yimu/Documents/YM_Capital/live-dashboard
python3 -m unittest tests.test_evidence_summary tests.test_frontend_rule_state -v
```
**期望:** 4 tests + 41 existing = 45 tests OK

### 4. 语法检查
```bash
cd /Users/yimu/Documents/YM_Capital/live-dashboard
node --check evidence-summary.js && \
node --check widgets/evidence-board.js && \
node --check widget-registry.js
```
**期望:** 全部静默退出

### 5. 浏览器验证（本地预览 18088）
```bash
open http://localhost:18088
```
- [ ] 顶栏加载正常
- [ ] W25 出现在首屏顶部
- [ ] S0 态势条显示健康/连接/情绪/盈亏/仓位/交易状态
- [ ] Evidence 区显示 E1 核心持仓、E2 票据闭环、E3 市场情绪、E4 账户收益
- [ ] Alerts 区显示 A1 降级、A2 收盘快照
- [ ] Risks 区显示 R1 交易入口允许、R2 仓位上限
- [ ] W15 持仓标题显示 E1 徽标
- [ ] W24 票据区顶部显示 E2 徽标
- [ ] W04 顶部显示 E3 徽标
- [ ] W22 KPI 显示 E4 徽标
- [ ] 半屏宽度无文本溢出

---

## 实现说明

### 架构约束（已遵守）
- ✅ W25 不读其他组件 DOM
- ✅ W25 不发 POST
- ✅ 不在仪表板内新增聊天/确认/派单
- ✅ 不碰生产 8088
- ✅ 不部署云端
- ✅ 不重构 DataStore/GridStack 架构

### S0/E/A/R 编号约定（已遵守）
- `S0` = 当前总态势（固定）
- `E1` = 核心持仓（W15）
- `E2` = 交易票据闭环（W24）
- `E3` = 市场情绪（W04）
- `E4` = 账户收益（W22）
- `A1-A9` = 异常/注意项
- `R1-R2` = 风险/规则状态

### 关键设计决策
1. **EvidenceSummary.build()** 是纯函数，输入 DataStore.merged + runtime，返回标准化快照，不依赖 DOM
2. **runtime 降级**: `_runtime()` 在 test 环境下无 document.getElementById 时优雅回退为 `''`
3. **W25 自动置顶**: `_addWidgetToGrid` 对 W25 强制 `x=0, y=0`
4. **REQUIRED_LAYOUT_WIDGETS** 含 W25，保证首次加载即出现
5. **close_snapshot** 渲染为 `tone: 'neutral'`，不等于行情 dead
