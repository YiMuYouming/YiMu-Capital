# 代码质量稳定性修复 实施计划

**目标：** 基于黑米 12 项建议 + 洋米评估，修复并发安全、内存泄漏、测试覆盖等稳定性问题。不包含架构重构（gen_dashboard_data.py 拆分、bridge.py 拆分等，待稳定后统一做）。

**架构：** 补完 filelock 保护覆盖（gen_dashboard_data.py 接入 + bridge.py 遗漏写入点）→ 修前端事件泄漏 → 补核心测试 → API 去重 + 魔法数字 → CLAUDE.md 文档。

**技术栈：** Python (filelock, sqlite3), JavaScript (vanilla), pytest

---

## 任务 1: gen_dashboard_data.py 迁移到 atomic_write_json

**文件：**
- 修改: `scripts/gen_dashboard_data.py:13-15, 1020-1023, 1037-1040, 1065-1068, 1083-1086`

**步骤 1:** 顶部 import 区添加 `from scripts.file_utils import atomic_write_json`
**步骤 2:** main() 的 2 个写入点替换为 atomic_write_json
**步骤 3:** watch_mode() 的 2 个写入点替换为 atomic_write_json
**步骤 4:** 验证: `grep -n "os.replace" scripts/gen_dashboard_data.py` 应输出 0 行
**步骤 5:** 提交

---

## 任务 2: bridge.py 遗漏写入点加 filelock

**文件：**
- 修改: `scripts/bridge.py:60-66, 587-589`

**步骤 1:** `_dump_cache` (line 60-66) 替换为 `atomic_write_json(CACHE_FILE, dump)`
**步骤 2:** `/api/llm` (line 587-589) 替换为 `atomic_write_json(LLM_INSIGHTS_FILE, insights)`
**步骤 3:** 验证: `grep -n "os.replace\|json.dump.*open" scripts/bridge.py` 确认无遗漏 raw write
**步骤 4:** 提交

---

## 任务 3: market-overview.js toggle 事件泄漏修复

**文件：**
- 修改: `widgets/market-overview.js:164-175`

**步骤 1:** 在 render() 的 toggle 绑定处加 `if (this._baselineBound) return; this._baselineBound = true;` guard
**步骤 2:** 验证: 确认 render() 多次调用不会再添加 listener

---

## 任务 4: widget-base.js unmount 加 DOM listener 清理

**文件：**
- 修改: `widget-base.js:63-70, 109-122`

**步骤 1:** 添加 `_on(el, event, fn)` 辅助方法
**步骤 2:** `_bindShellEvents` 改为使用 `this._on()`
**步骤 3:** `unmount()` 加 DOM listener 清理逻辑
**步骤 4:** 验证: 确认 unmount 后所有 DOM listener 被移除

---

## 任务 5: 补充核心测试

**文件：**
- 新建: `tests/test_rule_engine.py`
- 新建: `tests/test_store_merge.py` (pytest + subprocess 跑 JS)

**步骤 1:** test_rule_engine.py: 测试熔断归零、连亏≥2天空仓、周五趋势上限15%、无强支线仓位从严
**步骤 2:** 运行 `python3 -m pytest tests/test_rule_engine.py -v`
**步骤 3:** 提交

---

## 任务 6: bridge.py /api/live/* 端点去重

**文件：**
- 修改: `scripts/bridge.py:359-385`

**步骤 1:** 提取 `_serve_cached(key, data_type)` 辅助函数
**步骤 2:** `/api/live/iwencai`、`/api/live/sectors`、`/api/live/news` 改为调用 `_serve_cached`
**步骤 3:** 验证: 启动 bridge.py，curl 三个端点确认返回正确

---

## 任务 7: 魔法数字提取为常量

**文件：**
- 修改: `store.js:23-27`
- 修改: `scripts/gen_dashboard_data.py:618-625`
- 修改: `scripts/db.py:152-157`

**步骤 1:** store.js: tiers 对象上面的数字提取为 `REFRESH_INTERVALS` 常量 → 实际已在 tiers 里用 interval 字段，改 store.js 顶部加注释即可
**步骤 2:** gen_dashboard_data.py: `_compute_total_cap` 阈值提取为 `TOTAL_CAP_THRESHOLDS`
**步骤 3:** db.py: 时段数字提取为 `TRADING_HOURS`
**步骤 4:** 验证: 代码可读性提升，功能不变

---

## 任务 8: CLAUDE.md 补充 API 文档

**文件：**
- 修改: `CLAUDE.md`

**步骤 1:** 补充 /api/* 端点列表（路径、方法、响应格式、刷新频率）
**步骤 2:** 补充 pnl.db 表结构
**步骤 3:** 补充故障排查指南

---

## 执行顺序

```
T1 (gen 写入) → T2 (bridge 写入) → 验证写入安全
T3 (事件泄漏) → T4 (unmount 清理) → 验证前端稳定
T5 (核心测试) → 验证规则正确
T6 (API 去重) → T7 (魔法数字) → T8 (文档)
```

每批完成后提交。
