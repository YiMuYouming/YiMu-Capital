#!/usr/bin/env python3
"""gen_dashboard_data.py — 复盘笔记 → dashboard_data.json (Layer 1 基线数据)
稳米维护 | v2.0 Phase 1.8

数据源:
  1. 最新复盘笔记 YAML frontmatter (market/sentiment/risk/positions/decision 域)
  2. style_detect.py --json (style 域, 从 WorkBuddy/Tools/)
  3. 板块涨停日志.md (sectors 域, 近3天板块数据)

输出: live-dashboard/data/dashboard_data.json
"""

import json, os, sys, re, subprocess
from datetime import datetime
from pathlib import Path

try:
    from scripts.file_utils import atomic_write_json
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.file_utils import atomic_write_json

ROOT_DIR = Path(__file__).resolve().parent.parent  # live-dashboard/
TRADING_DIR = Path.home() / "Documents/YouMingVault/10_⚡Now/01_💰弈沐资本"  # 交易系统根 (复盘笔记在此)
REVIEW_DIR = TRADING_DIR / "复盘笔记"
STYLE_DETECT = ROOT_DIR / "scripts" / "style_detect.py"
SECTOR_LOG = TRADING_DIR / "板块涨停日志.md"
OUTPUT_FILE = ROOT_DIR / "data/dashboard_data.json"
POOLS_FILE = ROOT_DIR / "data/pools.json"

def find_latest_review():
    """找最新有实质内容的复盘笔记（跳过模板，回退到有数据的笔记）"""
    md_files = sorted(REVIEW_DIR.glob("**/*ReviewNote.md"), reverse=True)
    if not md_files:
        md_files = sorted(REVIEW_DIR.glob("**/*.md"), reverse=True)

    for f in md_files:
        try:
            # 先看附录有没有持仓/自选池数据
            appendix = parse_appendix(str(f))
            has_appendix = (
                len(appendix.get('positions', [])) > 0 or
                len(appendix.get('lianban_pool', [])) > 0 or
                len(appendix.get('trend_pool', [])) > 0 or
                len(appendix.get('锚定股状态', [])) > 0
            )
            if has_appendix:
                return str(f)

            # 盘前当日笔记：frontmatter 仍为空，但第〇部分已经承载今日基线。
            premarket = _parse_premarket_plan(str(f))
            if premarket.get("style"):
                print(f"[info] Using {f.name} (premarket plan)")
                return str(f)

            # 附录空但正文5节点表格有数据 → 也算有效
            nodes = parse_sentiment_nodes(str(f))
            filled = [n for n in ['竞价','早盘','午盘','尾盘','收盘'] if nodes.get(n)]
            if len(filled) >= 2:  # 至少有2个节点有数据
                print(f"[info] Using {f.name} (appendix empty, but {len(filled)} segments filled)")
                return str(f)
        except Exception:
            pass

    # 回退
    return str(md_files[0]) if md_files else None

def clean_value(val, field_name=""):
    """清洗复盘笔记 frontmatter 中的注释和格式"""
    if val is None:
        return None
    s = str(val).strip()
    # 占位符 —/--/… 等同空值，触发回退逻辑
    if s in ('—', '--', '…', '...', '??', '待收盘'):
        return None

    # 去掉括号内注释： "一般（涨停收益2.92%一般）" → "一般"
    # 但保留标签型字段的括号内容
    label_fields = {"最高板", "次高板", "连板梯队", "高潮保护", "动作", "状态", "结论", "当前状态", "W2出手时机"}
    string_fields = {"代码", "标的", "板块", "方向", "角色", "操作", "今日定位", "今日检查", "触发/失效", "买点", "梯队", "龙头", "备注", "止损", "清仓原因", "原因", "影响", "灯", "指标", "判定", "时间", "价格"}
    if field_name not in label_fields:
        s = re.sub(r'（[^）]*）', '', s)  # 中文括号
        s = re.sub(r'\([^)]*\)', '', s)   # 英文括号

    # 去掉百分号并转数字
    if s.endswith('%'):
        try:
            return float(s.replace('%', ''))
        except ValueError:
            return s

    # 纯数字字符串转数字（string_fields 不转换）
    if field_name not in string_fields:
        try:
            if '.' in s:
                return float(s)
            return int(s)
        except ValueError:
            pass

    # "X / Y" 格式取第一个数字: "126 / 98" → 126
    if field_name not in string_fields:
        m = re.match(r'^(\d+)\s*/\s*\d+', s)
        if m:
            return int(m.group(1))

    return s.strip()


def parse_frontmatter(filepath):
    """解析 YAML frontmatter（简单实现，不依赖 PyYAML）"""
    data = {}
    try:
        with open(filepath) as f:
            content = f.read()
    except:
        return data

    # 提取 frontmatter
    m = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if not m:
        return data
    fm = m.group(1)

    # 逐行解析简单 YAML
    for line in fm.split('\n'):
        line = line.rstrip()
        if not line or line.startswith('#'):
            continue
        # key: value
        m2 = re.match(r'^([\w一-鿿]+):\s*(.*)', line)
        if m2:
            key, val = m2.group(1), m2.group(2).strip()
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            if val.startswith("'") and val.endswith("'"):
                val = val[1:-1]
            # 尝试转数字
            if val.endswith('%'):
                try:
                    val = str(val)  # 保持百分比字符串
                except: pass
            try:
                if val.replace('.','',1).replace('-','',1).isdigit():
                    val = float(val)
                    if val == int(val):
                        val = int(val)
            except: pass
            data[key] = val
    return data

def _normalize_pool_rows(rows):
    """Convert legacy role/action-only pool rows into observation-only rows."""
    for row in rows or []:
        today_role = row.get("今日定位")
        today_check = row.get("今日检查")
        trigger_invalid = row.get("触发/失效") or row.get("触发失效")
        legacy_role = row.get("角色")
        legacy_action = row.get("操作")
        has_legacy = bool(legacy_role or legacy_action)
        has_today_contract = bool(today_role or today_check or trigger_invalid)

        if not has_today_contract and has_legacy:
            row["derived_from_legacy_fields"] = True
            row["legacy_role"] = legacy_role or ""
            row["legacy_action"] = legacy_action or ""
            row["今日定位"] = "观察标"
            row["今日检查"] = "旧字段兼容：需补今日检查"
            row["触发/失效"] = "缺少新版触发/失效；只观察，不授权买卖"
            legacy_note = f"旧字段：角色={legacy_role or '—'}；操作={legacy_action or '—'}"
            row["备注"] = (str(row.get("备注") or "").strip() + "；" + legacy_note).strip("；")
        elif not trigger_invalid:
            row["missing_trigger_invalid"] = True
            row["触发/失效"] = "缺少触发/失效；只观察，不授权买卖"
    return rows

def parse_appendix(filepath):
    """解析复盘笔记末尾的「## 数据附录」章节，返回结构化数据"""
    try:
        with open(filepath) as f:
            content = f.read()
    except:
        return {}

    # 找到数据附录章节
    m = re.search(r'##\s*数据附录.*?\n(.*)', content, re.DOTALL)
    if not m:
        return {}
    appendix = m.group(1)

    result = {}

    # 按 ### 标题分节
    sections = re.split(r'\n###\s+', appendix)
    for section in sections:
        if not section.strip():
            continue
        lines = section.strip().split('\n')
        title = lines[0].strip()
        body = '\n'.join(lines[1:]).strip()

        if '持仓明细' in title:
            result['positions'] = _parse_positions(body)
        elif '连板自选池' in title:
            result['lianban_pool'] = _normalize_pool_rows(_parse_table(body, {
                '标的': '标的', '代码': '代码', '板块': '板块',
                '今日定位': '今日定位', '窗口': '窗口',
                '今日检查': '今日检查', '触发/失效': '触发/失效',
                '角色': '角色', '操作': '操作',
                '涨幅': '涨幅', '收盘价': '收盘价', 'MA5': 'MA5',
                '量比': '量比', '换手': '换手', '备注': '备注'
            }))
        elif '趋势自选池' in title:
            result['trend_pool'] = _normalize_pool_rows(_parse_table(body, {
                '标的': '标的', '代码': '代码', '板块': '板块',
                '今日定位': '今日定位', '窗口': '窗口',
                '今日检查': '今日检查', '触发/失效': '触发/失效',
                '角色': '角色', '操作': '操作',
                '涨幅': '涨幅', '收盘价': '收盘价', 'MA5': 'MA5',
                'MA20': 'MA20', '量比': '量比', '换手': '换手', '备注': '备注'
            }))
        elif '板块状态' in title:
            result['sectors'] = _parse_table(body, {
                '板块': '板块', '类型': '类型', '涨停数': '涨停数',
                '梯队': '梯队', '龙头': '龙头',
                '板块涨跌幅': '板块涨跌幅', '涨跌幅': '板块涨跌幅',
                '主力净流入': '主力净流入', '净流入': '主力净流入',
                '5日线位置': '5日线位置', 'MA5位置': '5日线位置',
                '状态': '状态'
            })
        elif '竞价5维' in title:
            result['竞价'] = _parse_auction(body)
        elif 'W1早盘确认' in title:
            result['早盘'] = _parse_key_values(body)
        elif 'W2盘中跟踪' in title:
            result['盘中'] = _parse_key_values(body)
        elif '今日操作' in title:
            result['今日操作'] = _parse_table(body, {
                '时间': '时间', '动作': '动作', '标的': '标的',
                '价格': '价格', '盈亏': '盈亏', '原因': '原因'
            })
        elif '锚定股状态' in title:
            result['锚定股状态'] = _parse_table(body, {
                '标的': '标的', '代码': '代码', '窗口': '窗口',
                '状态': '状态', '影响': '影响', '灯': '灯'
            })

    return result


def parse_appendix_a(filepath):
    """解析复盘笔记「附录A：次日盘前速查」章节，返回 pools.json SSOT 数据"""
    try:
        with open(filepath) as f:
            content = f.read()
    except Exception:
        return {}

    m = re.search(r'##\s*附录A[：:]\s*次日盘前速查.*?\n(.*?)(?=\n##\s|\Z)', content, re.DOTALL)
    if not m:
        return {}

    appendix_a = m.group(1)
    result = {
        "lianban_pool": [],
        "trend_pool": [],
        "anchor_stocks": [],
        "sectors": [],
        "excluded": []
    }

    sections = re.split(r'\n###\s+', appendix_a)
    for section in sections:
        if not section.strip():
            continue
        lines = section.strip().split('\n')
        title = lines[0].strip()
        body = '\n'.join(lines[1:]).strip()

        if '连板板块' in title and '操作映射' in title:
            result['lianban_pool'] = _parse_appendix_a_table(body, {
                '板块': '板块', '温度标（只盯）': '温度标', '操作标的': '操作标的',
                '窗口': '窗口', '触发条件': '触发条件'
            })
        elif '趋势板块' in title and '操作映射' in title:
            result['trend_pool'] = _parse_appendix_a_table(body, {
                '板块': '板块', '观察标的（只盯）': '观察标的', '操作标的': '操作标的',
                '触发条件': '触发条件'
            })
        elif '操作指南' in title:
            _extract_excluded(body, result)

    # 附录A 不碰列表为空时回退搜索全文档
    if not result['excluded']:
        _extract_excluded(content, result)

    return result


def _extract_excluded(text, result):
    """从文本中提取不碰列表"""
    for line in text.split('\n'):
        line = line.strip()
        if '不碰' not in line.replace('**', ''):
            continue
        excluded_text = re.sub(r'\*\*不碰\*\*[：:]?\s*', '', line)
        excluded_text = re.sub(r'不碰[：:]?\s*', '', excluded_text)
        if not excluded_text.strip():
            continue
        names = re.split(r'[/、；;]', excluded_text)
        for name in names:
            name = re.sub(r'[；;].*$', '', name).strip()
            if name and len(name) < 10 and name not in result['excluded'] and not name.startswith('#'):
                result['excluded'].append(name)


def _parse_appendix_a_table(body, col_map):
    """解析附录A简化表格（列名与数据附录不同），返回 list[dict]"""
    import re as _re
    lines = body.strip().split('\n')
    rows = []
    header = None
    _TEMPLATE_VALS = {'—', '', '待填', '...', 'N/A'}

    def _is_separator(cells):
        """检测模板行：全为连续虚线（如 ------、---------）"""
        return all(_re.match(r'^-{3,}$', c) for c in cells)

    for line in lines:
        line = line.strip()
        if not line or not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.split('|')]
        cells = cells[1:-1] if len(cells) > 2 else cells
        if not cells:
            continue
        if all(c in _TEMPLATE_VALS for c in cells):
            continue
        if _is_separator(cells):
            continue
        if header is None:
            header = cells
            continue
        if len(cells) != len(header):
            continue
        row = {}
        for i, h in enumerate(header):
            key = col_map.get(h, h)
            val = cells[i] if i < len(cells) else ''
            if val and val not in _TEMPLATE_VALS:
                row[key] = val
        if row:
            rows.append(row)
    return rows


def _infer_style_label(lb_pct, tr_pct):
    lb = float(lb_pct or 0)
    tr = float(tr_pct or 0)
    if lb >= 80 and lb - tr >= 20:
        return "连板行情"
    if tr >= 80 and tr - lb >= 20:
        return "趋势行情"
    if lb >= 65 and lb - tr >= 15:
        return "混合（偏连板）"
    if tr >= 65 and tr - lb >= 15:
        return "混合（偏趋势）"
    return "混合（均衡）"


def _parse_premarket_plan(filepath):
    """解析当日笔记「第〇部分：昨日预案」中的盘前风格基线。

    这个段落是 D-1 复盘终审后写入的当日盘前执行口径；当当天
    frontmatter 仍为空时，它比前一日收盘 refresh 的旧风格更权威。
    """
    try:
        with open(filepath) as f:
            content = f.read()
    except Exception:
        return {}

    appendix_m = re.search(r'##\s*附录A[：:]\s*次日盘前速查.*?\n(.*?)(?=\n##\s|\Z)', content, re.DOTALL)
    if appendix_m:
        appendix_text = appendix_m.group(1)
        style = {}
        if "被动趋势日" in appendix_text:
            style["风格"] = "被动趋势日"
        elif "趋势行情" in appendix_text or "趋势日" in appendix_text:
            style["风格"] = "趋势行情"
        elif "连板行情" in appendix_text or "连板日" in appendix_text:
            style["风格"] = "连板行情"

        if re.search(r'连板(?:各层)?gate全关|连板全关', appendix_text):
            style["连板占比"] = 0
            style["趋势占比"] = 100
        else:
            alloc_m = re.search(
                r'连板\s*(\d+(?:\.\d+)?)\s*%.*?趋势\s*(\d+(?:\.\d+)?)\s*%',
                appendix_text,
                re.DOTALL,
            )
            if alloc_m:
                lb_pct, tr_pct = (float(v) for v in alloc_m.groups())
                style["连板占比"] = int(lb_pct) if lb_pct.is_integer() else lb_pct
                style["趋势占比"] = int(tr_pct) if tr_pct.is_integer() else tr_pct

        cap_m = re.search(r'(?:总仓位上限|总上限)\s*(?:正常)?[（(]?\s*(\d+(?:\.\d+)?)\s*%', appendix_text)
        if not cap_m:
            cap_m = re.search(r'(?:总仓位上限|总上限)[^。\n]*?(\d+(?:\.\d+)?)\s*%', appendix_text)
        if cap_m:
            cap = float(cap_m.group(1))
            style["总仓位上限"] = int(cap) if cap.is_integer() else cap

        w2_m = re.search(r'新开趋势W2上限\s*[~约]*\s*(\d+(?:\.\d+)?\s*[-~]\s*\d+(?:\.\d+)?)\s*%', appendix_text)
        if w2_m:
            style["新开趋势W2上限"] = re.sub(r'\s+', '', w2_m.group(1)) + "%"

        if style:
            return {"style": style, "source": "appendix_a_plan"}

    m = re.search(r'##\s*第[〇零0]部分[：:][^\n]*昨日预案[^\n]*\n(.*?)(?=\n##\s|\Z)', content, re.DOTALL)
    if not m:
        return {}
    text = m.group(1)
    style = {}

    style_m = re.search(
        r'风格[：:]\s*(\d+(?:\.\d+)?)\s*分.*?连板\s*(\d+(?:\.\d+)?)\s*%?\s*/\s*趋势\s*(\d+(?:\.\d+)?)\s*%?',
        text,
        re.DOTALL,
    )
    if style_m:
        total, lb_pct, tr_pct = (float(v) for v in style_m.groups())
        style["总分"] = int(total) if total.is_integer() else total
        style["连板占比"] = int(lb_pct) if lb_pct.is_integer() else lb_pct
        style["趋势占比"] = int(tr_pct) if tr_pct.is_integer() else tr_pct
        style["风格"] = _infer_style_label(lb_pct, tr_pct)

    cap_m = re.search(r'(?:总仓位上限|仓位)[：:][^\n]*?(\d+(?:\.\d+)?)\s*%', text)
    if cap_m:
        cap = float(cap_m.group(1))
        style["总仓位上限"] = int(cap) if cap.is_integer() else cap

    return {"style": style, "source": "premarket_plan"} if style else {}


def _data_appendix_has_section(filepath, title):
    """Return True when the machine data appendix explicitly contains a section."""
    try:
        with open(filepath) as f:
            content = f.read()
    except Exception:
        return False
    m = re.search(r'##\s*数据附录.*?\n(.*)', content, re.DOTALL)
    if not m:
        return False
    return re.search(r'\n###\s*' + re.escape(title) + r'\s*(?:\n|$)', m.group(1)) is not None


def _pool_has_stock_rows(pool):
    """W12/W13 need stock rows with codes; appendix A sector mappings are not enough."""
    return any(str(s.get("代码", "")).strip() for s in (pool or []))


def _select_machine_pool(review_path, appendix, appendix_a, key):
    """Select W12/W13 machine pool rows.

    Data appendix stock tables are the SSOT for W12/W13.  If a same-day table is
    present but empty, that is an explicit empty pool and must not fall back to
    yesterday's stale candidates.
    """
    title = "连板自选池" if key == "lianban_pool" else "趋势自选池"
    if _data_appendix_has_section(review_path, title):
        return appendix.get(key, []) or []

    data_rows = appendix.get(key, []) or []
    if _pool_has_stock_rows(data_rows):
        return data_rows

    appendix_a_rows = (appendix_a or {}).get(key, []) or []
    if _pool_has_stock_rows(appendix_a_rows):
        return appendix_a_rows

    return _fallback_appendix(review_path, key)


def _build_pools_payload(review_path):
    """Build data/pools.json from machine-readable stock pools."""
    appendix = parse_appendix(review_path)
    appendix_a = parse_appendix_a(review_path)
    excluded = (appendix_a or {}).get("excluded", [])

    lianban_pool = _select_machine_pool(review_path, appendix, appendix_a, "lianban_pool")
    trend_pool = _select_machine_pool(review_path, appendix, appendix_a, "trend_pool")

    if not lianban_pool and not trend_pool:
        has_explicit_pool = (
            _data_appendix_has_section(review_path, "连板自选池") or
            _data_appendix_has_section(review_path, "趋势自选池")
        )
        if not has_explicit_pool:
            fallback = _fallback_pools(review_path)
            if fallback:
                return fallback

    return {
        "lianban_pool": _filter_excluded(lianban_pool, excluded),
        "trend_pool": _filter_excluded(trend_pool, excluded),
        "anchor_stocks": (appendix_a or {}).get("anchor_stocks", []) or appendix.get("锚定股状态", []),
        "sectors": (appendix_a or {}).get("sectors", []) or appendix.get("sectors", []),
        "excluded": excluded,
    }


def _parse_table(body, col_map):
    """解析 Markdown 表格，返回 list[dict]"""
    lines = body.strip().split('\n')
    rows = []
    header = None

    _TEMPLATE_VALS = {'—', '', '待填', '待定', '...', 'N股', 'N/A'}
    _TEMPLATE_ROW_PATTERNS = ['龙头/高度板', 'W1/W2', 'W1追涨/只盯不买',
                              '主趋势股/趋势候选', '主线/强支线', '持有/已清仓']

    def _is_template_row(cells):
        """检测整行是否为模板行（看标的列是否为指令文本而非真实名称）"""
        # 第一个非空cell通常是指标名称
        name = str(cells[0]).strip() if cells else ''
        if name in _TEMPLATE_VALS:
            return True
        for p in _TEMPLATE_ROW_PATTERNS:
            if p in name:
                return True
        return False

    for line in lines:
        line = line.strip()
        if not line or not line.startswith('|'):
            continue
        if '---' in line:
            continue
        cells = [c.strip() for c in line.split('|')[1:-1]]
        if header is None:
            header = cells
        else:
            if _is_template_row(cells):
                continue
            row = {}
            for i, cell in enumerate(cells):
                if i < len(header) and header[i] in col_map:
                    key = col_map[header[i]]
                    val = clean_value(cell, key)
                    if val is not None and val not in _TEMPLATE_VALS:
                        row[key] = val
            if row and len(row) >= 2:  # 至少2个有效字段
                rows.append(row)
    return rows


def _parse_auction(body):
    """解析竞价5维：key=value + #### 子标题表格"""
    result = {}
    # 先按 #### 拆分
    parts = re.split(r'\n####\s+', body)
    # 第一部分是 key=value
    result.update(_parse_key_values(parts[0]))
    # 后续部分是子表格
    for part in parts[1:]:
        lines = part.strip().split('\n')
        sub_title = lines[0].strip()
        sub_body = '\n'.join(lines[1:])
        if '大盘指数' in sub_title:
            result['大盘指数'] = _parse_table(sub_body, {
                '指数': '指数', '竞价涨幅': '竞价涨幅', '涨家': '涨家', '跌家': '跌家', '灯': '灯'
            })
        elif '市场情绪' in sub_title:
            result['市场情绪'] = _parse_table(sub_body, {
                '名称': '名称', '值': '值', '灯': '灯'
            })
        elif '高标竞价' in sub_title:
            result['高标竞价'] = _parse_table(sub_body, {
                '名称': '名称', '竞价': '竞价', '灯': '灯'
            })
        elif '方向锚定' in sub_title:
            result['方向锚定'] = _parse_table(sub_body, {
                '板块': '板块', '竞价': '竞价', '灯': '灯'
            })
        elif '锚定股竞价' in sub_title:
            result['锚定股竞价'] = _parse_table(sub_body, {
                '标的': '标的', '竞价': '竞价', '灯': '灯'
            })
    return result


def _parse_key_values(body):
    """解析 key=value 行和 指标N=label|desc|status 行"""
    result = {}
    checks = []
    lines = body.strip().split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 指标行: 指标N=label|desc|status 或 指标N=label|code|desc|status
        m = re.match(r'指标\d+=([^|]+)\|([^|]+)\|([a-z]+)', line)
        if m:
            # 3段格式: label|desc|status
            checks.append({
                '指标': m.group(1), '代码': '',
                '判定': m.group(2), '状态': m.group(3)
            })
        else:
            m = re.match(r'指标\d+=([^|]+)\|([^|]+)\|([^|]+)\|([a-z]+)', line)
            if m:
                # 4段格式: label|code|desc|status
                checks.append({
                    '指标': m.group(1), '代码': m.group(2).strip(),
                    '判定': m.group(3), '状态': m.group(4)
            })
            continue
        # 指标行（旧格式兼容）: 指标N=label|desc|status
        m = re.match(r'指标\d+=(.+)\|(.+)\|(.+)', line)
        if m:
            checks.append({
                '指标': m.group(1), '代码': '',
                '判定': m.group(2), '状态': m.group(3)
            })
            continue
        # 普通 key=value
        m = re.match(r'(.+?)=(.+)', line)
        if m:
            result[m.group(1)] = clean_value(m.group(2), m.group(1))
    if checks:
        # 根据标题判断是 W2出手条件 还是 方向确认
        result['条件列表'] = checks
    return result


def _parse_positions(body):
    """解析持仓表格，过滤空行"""
    rows = _parse_table(body, {
        '标的': '标的', '代码': '代码', '方向': '方向',
        '数量': '数量', '成本': '成本', '现价': '现价',
        '卖出价': '卖出价', '盈亏%': '浮盈',
        '止损': '止损', '状态': '状态',
        '清仓日期': '清仓日期', '清仓原因': '清仓原因'
    })
    return [r for r in rows if r.get('标的') and r.get('标的') != '...']


def parse_sentiment_nodes(filepath):
    """解析复盘笔记中的5节点情绪数据（表1 大盘全景 + 表2 情绪高标）
    返回: { '竞价': {...}, '早盘': {...}, '午盘': {...}, '尾盘': {...}, '收盘': {...} }
    """
    try:
        with open(filepath) as f:
            content = f.read()
    except Exception:
        return {}

    nodes = {}

    # === 表1：大盘全景 ===
    # | 节点 | 情绪 | 上证(%) | 涨/跌停 | 量能 | 涨跌比 | 总竞价涨幅 | 关键异动 |
    t1 = re.search(r'### 表1.*?\n(.*?)(?:\n###|\n---|\Z)', content, re.DOTALL)
    if t1:
        lines = t1.group(1).strip().split('\n')
        header = None
        for line in lines:
            if not line.startswith('|') or '---' in line:
                continue
            cells = [c.strip() for c in line.split('|')[1:-1]]
            if header is None:
                header = [h.strip() for h in cells]
                continue
            if len(cells) < 2:
                continue
            node_name = cells[0]
            if node_name not in ('竞价', '早盘', '午盘', '尾盘', '收盘'):
                continue
            # 跳过模板行（情绪列为 % 或 - 等无效值）
            emotion_val = cells[1] if len(cells) > 1 else ''
            if emotion_val in ('%', '—', '', '/') or emotion_val.startswith('点位'):
                continue
            entry = {}
            for i, h in enumerate(header[1:], 1):
                if i < len(cells) and cells[i] and cells[i] not in ('—', '%', '/', ''):
                    entry[h] = cells[i]
            if len(entry) > 0:
                # 已有同节点数据则不覆盖（保留第一次真实数据）
                if node_name not in nodes:
                    nodes[node_name] = entry

    # === 表2：情绪高标 ===
    # | 指标 | 竞价 | 早盘 | 午盘 | 收盘 | 门槛 |
    t2 = re.search(r'### 表2.*?\n(.*?)(?:\n###|\n---|\Z)', content, re.DOTALL)
    if t2:
        lines = t2.group(1).strip().split('\n')
        for line in lines:
            if not line.startswith('|') or '---' in line:
                continue
            cells = [c.strip() for c in line.split('|')[1:-1]]
            if len(cells) < 3:
                continue
            indicator = cells[0]
            # 指标名映射
            key_map = {
                '竞价强势家数': '竞价强势家数',
                '涨停收益': '涨停收益',
                '连板收益': '连板收益',
                '炸板收益': '炸板收益',
                '封板率': '封板率',
                '炸板率': '炸板率',
                '晋级率': '晋级率',
                '最高板/次高板': '最高板',
                '最高板': '最高板',
                '次高板': '次高板',
                '赚钱效应': '赚钱效应',
                '情绪值': '情绪值',
            }
            key = key_map.get(indicator, indicator)
            time_cols = [None, '竞价', '早盘', '午盘', '尾盘', '收盘']  # 支持5列
            for i, time_name in enumerate(time_cols[1:], 1):
                if i < len(cells) and cells[i] and cells[i] not in ('—', '%', ''):
                    val = cells[i].strip('*').strip()  # 去掉加粗标记
                    if time_name not in nodes:
                        nodes[time_name] = {}
                    nodes[time_name][key] = val

    return nodes


def _extract_iwencai_val(sd, dim_key, detail_key):
    """从 style_detect 输出提取问财实时值，去掉单位和括号注释"""
    dim = sd.get(dim_key) or {}
    details = dim.get("details") or {}
    raw = details.get(detail_key)
    if raw is None:
        return None
    # 提取数字部分: "4.33%" → 4.33, "6板" → 6, "32642亿" → 32642
    import re
    s = str(raw).strip()
    # 去掉括号注释
    s = re.sub(r'（[^）]*）', '', s)
    s = re.sub(r'\([^)]*\)', '', s)
    # 纯数值提取
    m = re.match(r'([+-]?[\d.]+)', s)
    if m:
        val = float(m.group(1))
        if val == int(val):
            val = int(val)
        return val
    # "好"/"一般"/"差" 等文字值
    if s in ("好", "一般", "差", "较好", "较差"):
        return s
    return raw


def get_style_data(review_path=None):
    """调用 style_detect.py 获取风格数据，映射为 dashboard 格式"""
    try:
        cmd = ["python3", str(STYLE_DETECT), "--json"]
        if review_path:
            cmd.extend(["--review", review_path])
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, cwd=str(STYLE_DETECT.parent)
        )
        if result.returncode == 0 and result.stdout:
            # style_detect --json 输出：先打印可读文本，最后一行是 JSON
            # 取最后一个 { 开始的部分作为 JSON
            raw = result.stdout.strip()
            brace_idx = raw.rfind('\n{')
            if brace_idx < 0:
                brace_idx = raw.find('{')
            if brace_idx >= 0:
                sd = json.loads(raw[brace_idx:])
                # V0.3 字段映射: style_detect → dashboard_data.json
                # 优先用 allocation（trading-core 插值表），信号强度作为参考
                alloc = sd.get("allocation") or {}
                tiered = sd.get("tiered_jjl") or {}
                dim4 = sd.get("dim4") or {}
                return {
                    "总分": sd.get("total"),
                    "风格": sd.get("style"),
                    "置信度": sd.get("confidence"),
                    # V0.3 直接用信号强度和分配表，不再用旧的风格名推算
                    "连板占比": alloc.get("连板资金占比") or sd.get("lianban_conf"),
                    "趋势占比": alloc.get("趋势资金占比") or sd.get("trend_conf"),
                    "连板信号强度": sd.get("lianban_signal_pct"),
                    "趋势信号强度": sd.get("trend_signal_pct"),
                    "连板信号描述": sd.get("lianban_detail"),
                    "趋势信号描述": sd.get("trend_detail"),
                    "总仓位上限": _compute_total_cap(sd),
                    "dim1_量能": (sd.get("dim1") or {}).get("score"),
                    "dim2_连板生态": (sd.get("dim2") or {}).get("score"),
                    "dim3_趋势": (sd.get("dim3") or {}).get("score"),
                    "dim4_情绪广度": dim4.get("score"),
                    # 分层晋级率（供 trading-core 硬卡判定）
                    "一进二晋级率": tiered.get("一进二晋级率"),
                    "二进三晋级率": tiered.get("二进三晋级率"),
                    "三进四晋级率": tiered.get("三进四晋级率"),
                    # === 问财实时情绪值（供 sentiment 域兜底）===
                    "_iwencai_情绪值": _extract_iwencai_val(sd, "dim4", "情绪值"),
                    "_iwencai_涨停收益": _extract_iwencai_val(sd, "dim2", "涨停收益"),
                    "_iwencai_连板收益": _extract_iwencai_val(sd, "dim2", "连板收益"),
                    "_iwencai_炸板收益": _extract_iwencai_val(sd, "dim2", "炸板收益"),
                    "_iwencai_晋级率": _extract_iwencai_val(sd, "dim2", "晋级率"),
                    "_iwencai_封板率": _extract_iwencai_val(sd, "dim2", "封板率"),
                    "_iwencai_炸板率": _extract_iwencai_val(sd, "dim2", "炸板率"),
                    "_iwencai_连板风险值": _extract_iwencai_val(sd, "dim2", "连板风险值"),
                    "_iwencai_最高板": _extract_iwencai_val(sd, "dim2", "最高板"),
                    "_iwencai_赚钱效应": _extract_iwencai_val(sd, "dim4", "赚钱效应"),
                    "_iwencai_全市场成交额": _extract_iwencai_val(sd, "dim1", "全市场成交额"),
                    # 过渡预警
                    "预警": sd.get("warnings", []),
                    "持续天数": sd.get("days_in_regime"),
                }
        if result.returncode != 0:
            print(f"[warn] style_detect.py returned {result.returncode}: {result.stderr[:200]}")
    except Exception as e:
        print(f"[warn] style_detect.py failed: {e}")
    return {}

def _compute_total_cap(sd):
    """按 Vault 三层规则估算每日基线总仓位上限。

    第一层正常仓位 = max(连板侧上限, 趋势侧上限)，不是风格总分直接映射。
    """
    emotion = _extract_iwencai_val(sd, "dim4", "情绪值")
    try:
        emotion = float(emotion) if emotion is not None else None
    except (TypeError, ValueError):
        emotion = None
    if emotion is None:
        lianban_cap = 0
    elif emotion < 20:
        lianban_cap = 0
    elif emotion < 40:
        lianban_cap = 40
    elif emotion < 80:
        lianban_cap = 60
    else:
        lianban_cap = 0

    dim3 = sd.get("dim3") or {}
    trend_score = dim3.get("score")
    try:
        trend_score = float(trend_score) if trend_score is not None else None
    except (TypeError, ValueError):
        trend_score = None
    if trend_score is None:
        trend_cap = 20
    elif trend_score >= 18:
        trend_cap = 60
    elif trend_score >= 10:
        trend_cap = 40
    else:
        trend_cap = 20
    return max(lianban_cap, trend_cap)

def _cap_truthy(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on", "是", "确认", "已确认", "已抬高")

def _cap_position_pnl_pct(position):
    for key in ("floating_pnl_pct", "total_pnl_pct", "today_pnl_pct", "浮盈%", "浮盈pct", "pnl_pct", "浮盈"):
        raw = (position or {}).get(key)
        if raw is None:
            continue
        match = re.search(r'([-+]?\d+\.?\d*)\s*%', str(raw))
        if match:
            try:
                return float(match.group(1))
            except (ValueError, TypeError):
                pass
        try:
            return float(raw)
        except (ValueError, TypeError):
            pass

    def _clean_md(val):
        if isinstance(val, str):
            return val.strip().lstrip('*').rstrip('*').strip()
        return val

    price_raw = _clean_md((position or {}).get('现价', ''))
    cost_raw = _clean_md((position or {}).get('成本', '') or (position or {}).get('成本价', ''))
    try:
        price = float(price_raw) if price_raw else None
        cost = float(cost_raw) if cost_raw else None
        if price is not None and cost is not None and cost > 0:
            return round((price - cost) / cost * 100, 2)
    except (ValueError, TypeError):
        pass
    return None

def _cap_position_ids(position):
    ids = set()
    for key in ("代码", "code", "标的", "名称", "name"):
        val = str((position or {}).get(key) or "").strip().strip("*").strip()
        if val:
            ids.add(val)
    return ids

def _build_mainline_ids(data):
    ids = set()
    for section in ("lianban_pool", "trend_pool"):
        for item in data.get(section) or []:
            ids.update(_cap_position_ids(item))
    for item in ((data.get("decision") or {}).get("锚定股状态") or []):
        ids.update(_cap_position_ids(item))
    return ids

def _compute_earned_cap(positions, mainline_ids=None, mainline_confirmed=False, protection_raised=False):
    """按 POS-SIZE-005 盈利解锁层计算 earned_cap_pct。

    计数浮盈主线持仓，按盈利解锁阶梯返回：
    - 无主线、无浮盈: 10%
    - 主线确认但未浮盈: 20%
    - 1只浮盈: 40%
    - 2只浮盈: 60%
    - 3只及以上浮盈且保护位抬高: 80%
    """
    mainline_ids = set(mainline_ids or [])
    mainline_confirmed = bool(mainline_confirmed or mainline_ids)
    profitable = 0
    for p in positions:
        if not isinstance(p, dict):
            continue
        name = str(p.get('标的', '') or '')
        if name.startswith('~~'):
            continue
        explicit_mainline = p.get("is_mainline")
        is_mainline = _cap_truthy(explicit_mainline) if explicit_mainline is not None else bool(_cap_position_ids(p) & mainline_ids)
        if not is_mainline:
            continue
        pnl_val = _cap_position_pnl_pct(p)
        if pnl_val is not None and pnl_val > 0:
            profitable += 1

    if not mainline_confirmed:
        return 10
    if profitable >= 3:
        return 80 if _cap_truthy(protection_raised) else 60
    if profitable >= 2:
        return 60
    if profitable >= 1:
        return 40
    return 20

def compute_style_execution(fm, style):
    """规则引擎：根据 trading-core.md 计算 style.实际执行

    判定优先级（从高到低）：
    1. 熔断触发 → 仓位归零
    2. 连亏 ≥ 2 天 → 强制空仓
    3. 无强支线 → 仓位从严
    （晋级率判定交给 dashboard W08 实时规则引擎，gen 只传分数不阻断）
    """
    reasons = []
    reason2s = []
    lb_pct = style.get("连板占比", 75) if style else 75
    tr_pct = style.get("趋势占比", 25) if style else 25
    total_cap = style.get("总仓位上限", 30) if style else 30
    first_limit = 10  # 默认首笔上限

    meltdown = fm.get("熔断触发", False)
    if isinstance(meltdown, str):
        meltdown = meltdown.lower() in ("true", "yes", "是")
    lose_streak = int(fm.get("连亏天数", 0) or 0)
    jjl_str = str(fm.get("晋级率", "0") or "0").replace("%", "")
    try:
        jjl = float(jjl_str)
    except:
        jjl = 0
    lb_actual = lb_pct
    tr_actual = tr_pct

    # 规则 1: 熔断
    if meltdown:
        lb_actual = 0
        tr_actual = 0
        total_cap = 0
        first_limit = 0
        reasons.append("单日熔断触发，仓位归零")

    # 规则 2: 连亏
    if lose_streak >= 2:
        lb_actual = 0
        tr_actual = 0
        total_cap = 0
        first_limit = 0
        reasons.append(f"连亏{lose_streak}天≥2天，强制空仓")

    # 规则 3: 晋级率分层判定（交给 dashboard W08 实时判定，gen 只传分数不硬卡）
    # 规则 4: 无强支线（人工标注）
    no_strong = fm.get("无强支线", None)
    if no_strong:
        total_cap = min(total_cap, 20)
        reason2s.append(f"无强支线({no_strong})→仓位从严")

    return {
        "连板实际": lb_actual,
        "趋势实际": tr_actual,
        "总仓位上限": total_cap,
        "首笔上限": first_limit,
        "原因": "；".join(reasons) if reasons else "",
        "原因2": "；".join(reason2s) if reason2s else "",
    }


def get_weekday_str(date_str):
    """从日期字符串推断星期几"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        weekdays = ["周一","周二","周三","周四","周五","周六","周日"]
        return weekdays[dt.weekday()]
    except:
        return ""

def _fallback_pools(current_path):
    """当今天笔记附录A为空时，回退到最近完整笔记的数据附录（个股格式）"""
    review_dir = Path(current_path).parent.parent
    md_files = sorted(review_dir.glob("**/*ReviewNote.md"), reverse=True)
    current_name = Path(current_path).name

    for f in md_files:
        if f.name == current_name:
            continue
        try:
            appendix = parse_appendix(str(f))
            lb = appendix.get("lianban_pool", [])
            tr = appendix.get("trend_pool", [])
            if lb or tr:
                print(f"[info] Fallback pools: using {f.name} ({len(lb)} lianban, {len(tr)} trend)")
                return {
                    "lianban_pool": lb,
                    "trend_pool": tr,
                    "anchor_stocks": appendix.get("锚定股状态", []),
                    "sectors": appendix.get("sectors", []),
                    "excluded": _extract_excluded_from_appendix_a(str(f)),
                }
        except Exception:
            pass
    return {}

def _extract_excluded_from_appendix_a(filepath):
    """从附录A提取不碰列表"""
    try:
        with open(filepath) as f:
            content = f.read()
    except Exception:
        return []
    m = re.search(r'\*\*不碰\*\*[：:]\s*(.+?)(?:\n|$)', content)
    if m:
        return [s.strip() for s in m.group(1).replace('/', '、').replace('；', '、').split('、') if s.strip()]
    return []

def _fallback_appendix(current_path, key):
    """当今天笔记附录为空时，回退到最近一个完整笔记的附录数据"""
    review_dir = Path(current_path).parent.parent  # 复盘笔记根目录
    md_files = sorted(review_dir.glob("**/*ReviewNote.md"), reverse=True)
    current_name = Path(current_path).name

    for f in md_files:
        if f.name == current_name:
            continue  # 跳过当前笔记
        try:
            appendix = parse_appendix(str(f))
            val = appendix.get(key)
            if val and len(val) > 0:
                print(f"[info] Fallback {key}: using {f.name} ({len(val)} items)")
                return val
        except Exception:
            pass
    return []

def _fm_has_data(fm, key):
    """检查 frontmatter 字段是否有实质数据（排除占位符）"""
    v = fm.get(key)
    if v is None:
        return False
    s = str(v).strip()
    return s not in ('', '—', '--', '…', '...', '??', '待收盘')

def _fallback_frontmatter(current_path):
    """当今天笔记 frontmatter 为空时，回退到最近一个完整笔记的 frontmatter"""
    review_dir = Path(current_path).parent.parent
    md_files = sorted(review_dir.glob("**/*ReviewNote.md"), reverse=True)
    current_name = Path(current_path).name

    for f in md_files:
        if f.name == current_name:
            continue
        fm = parse_frontmatter(str(f))
        # 检查是否有实质数据（情绪值不为空）
        if _fm_has_data(fm, "情绪值"):
            print(f"[info] Fallback frontmatter: using {f.name}")
            return fm
    return {}


def _bidding_emotion(sentiment_nodes):
    """从竞价节点提取情绪值数值"""
    bidding = sentiment_nodes.get('竞价', {})
    raw = bidding.get('情绪', '')
    if not raw:
        return None
    # "41%" → 41, "-0.09%(4174)" → skip(not sentiment)
    try:
        import re
        m = re.match(r'^([+-]?[\d.]+)', str(raw))
        if m:
            v = float(m.group(1))
            if 0 <= v <= 100:  # 情绪值应该在这个范围
                return v
    except:
        pass
    return None


def _fallback_review_path(current_path):
    """当今天笔记 frontmatter 为空时，返回最近完整笔记的路径"""
    review_dir = Path(current_path).parent.parent
    md_files = sorted(review_dir.glob("**/*ReviewNote.md"), reverse=True)
    current_name = Path(current_path).name
    for f in md_files:
        if f.name == current_name:
            continue
        fm = parse_frontmatter(str(f))
        if fm.get("情绪值") is not None and fm.get("情绪值") != "":
            return str(f)
    return None

def _review_note_date(path):
    """Return YYYY-MM-DD for a review note from frontmatter or filename."""
    fm_date = parse_frontmatter(str(path)).get("date")
    if fm_date:
        s = str(fm_date).strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            return s
    m = re.search(r"(\d{4})_(\d{1,2})_(\d{1,2})_", Path(path).name)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    return None


def _pool_source_has_machine_section(path):
    return (
        _data_appendix_has_section(path, "连板自选池") or
        _data_appendix_has_section(path, "趋势自选池")
    )


def _select_pools_review_path(current_path, as_of_date=None):
    """Select the completed review note that defines today's W12/W13 pools."""
    trading_date = as_of_date or os.environ.get("YIMU_TRADING_DATE") or datetime.now().strftime("%Y-%m-%d")
    review_dir = Path(current_path).parent.parent
    candidates = []
    for f in sorted(review_dir.glob("**/*ReviewNote.md"), reverse=True):
        note_date = _review_note_date(f)
        if not note_date or note_date >= trading_date:
            continue
        if not _pool_source_has_machine_section(str(f)):
            continue
        candidates.append((note_date, f))
    if not candidates:
        return current_path
    candidates.sort(key=lambda item: item[0], reverse=True)
    return str(candidates[0][1])


def _previous_review_path(current_path, as_of_date=None):
    trading_date = as_of_date or os.environ.get("YIMU_TRADING_DATE") or datetime.now().strftime("%Y-%m-%d")
    review_dir = Path(current_path).parent.parent
    candidates = []
    for f in sorted(review_dir.glob("**/*ReviewNote.md"), reverse=True):
        note_date = _review_note_date(f)
        if note_date and note_date < trading_date:
            candidates.append((note_date, f))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return str(candidates[0][1])


def _fmt_pct(v):
    if v in (None, "", "—"):
        return None
    s = str(v).strip()
    if s.endswith("%"):
        return s
    try:
        return f"{float(s):+.2f}%"
    except ValueError:
        return s


def _format_turnover_yi(yi):
    if yi is None:
        return None
    if abs(yi) >= 10000:
        return f"{yi / 10000:.2f}万亿"
    return f"{yi:.0f}亿"


def _turnover_to_yi(v):
    if v in (None, "", "—"):
        return None
    s = str(v).replace(",", "").strip()
    try:
        if "万亿" in s:
            n = float(s.replace("万亿", ""))
            return n / 100000000 if n > 1000 else n * 10000
        if "亿" in s:
            return float(s.replace("亿", ""))
        n = float(s)
        return n / 100000000 if abs(n) > 1000000 else n * 10000
    except ValueError:
        return None


def _fmt_wanyi(v):
    yi = _turnover_to_yi(v)
    if yi is not None:
        return _format_turnover_yi(yi)
    if v in (None, "", "—"):
        return None
    return str(v).strip()


def _wanyi_number(v):
    yi = _turnover_to_yi(v)
    return yi / 10000 if yi is not None else None


def _first_present(mapping, keys):
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", "—"):
            return value
    return None


def _derive_sh_turnover_wanyi(fm):
    explicit = _first_present(fm, ["上证成交额", "上证指数成交额", "沪市成交额", "上海成交额"])
    if explicit not in (None, "", "—"):
        return explicit
    total = _wanyi_number(fm.get("市场量能"))
    sz = _wanyi_number(_first_present(fm, ["深证成交额", "深圳成交额", "深证指数成交额", "深圳指数成交额"]))
    if total is not None and sz is not None and total >= sz:
        return round(total - sz, 2)
    return None


def _extract_review_section_text(content, section_name):
    m = re.search(
        rf"\*\*{re.escape(section_name)}\*\*\s*\n(.*?)(?=\n\*\*[^*\n]+\*\*\s*\n|\n###\s|\Z)",
        content,
        re.DOTALL,
    )
    return m.group(1) if m else ""


def _extract_last_pct(text, labels):
    values = []
    for label in labels:
        pattern = rf"{label}(?:板|指|指数)?(?:\*\*)?\s*([+-]?\d+(?:\.\d+)?)\s*%"
        values.extend(re.findall(pattern, text))
    return values[-1] if values else None


def _extract_turnover(text):
    m = re.search(r"(?:上午总成交|半日量能|午盘量能)\s*([0-9]+(?:\.\d+)?)\s*万亿", text)
    return f"{m.group(1)}万亿" if m else None


def _load_sentiment_auto_close(date_str):
    try:
        with open(ROOT_DIR / "data" / "sentiment_auto.json") as f:
            data = json.load(f)
    except Exception:
        return {}
    rows = data.get(date_str) if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return {}
    close_rows = [r for r in rows if str(r.get("node") or r.get("节点") or "").find("收盘") >= 0]
    source = close_rows[-1] if close_rows else (rows[-1] if rows else {})
    return source if isinstance(source, dict) else {}


def _parse_up_down(raw):
    m = re.search(r"(\d+)\s*/\s*(\d+)", str(raw or ""))
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def _build_yesterday_baseline(current_path, as_of_date=None):
    prev_path = _previous_review_path(current_path, as_of_date)
    if not prev_path:
        return {}
    fm = parse_frontmatter(prev_path)
    if not fm:
        return {}
    try:
        content = Path(prev_path).read_text()
    except Exception:
        content = ""
    close_text = _extract_review_section_text(content, "收盘")
    midday_text = _extract_review_section_text(content, "午盘")
    prev_date = _review_note_date(prev_path)
    auto_close = _load_sentiment_auto_close(prev_date) if prev_date else {}
    up, down = _parse_up_down(fm.get("涨跌比"))
    if (up is None or down is None) and auto_close:
        up = auto_close.get("上涨家数")
        down = auto_close.get("下跌家数")
    baseline = {
        "上证昨涨幅": _fmt_pct(fm.get("上证涨幅") or auto_close.get("上证涨幅")),
        "上证昨成交额": _fmt_wanyi(_derive_sh_turnover_wanyi(fm)),
        "深证昨涨幅": _fmt_pct(_first_present(fm, ["深证涨幅", "深圳涨幅", "深证指数涨幅", "深圳指数涨幅"]) or auto_close.get("深证涨幅")),
        "深证昨成交额": _fmt_wanyi(_first_present(fm, ["深证成交额", "深圳成交额", "深证指数成交额", "深圳指数成交额"])),
        "创业昨涨幅": _fmt_pct(
            _first_present(fm, ["创业涨幅", "创业板涨幅", "创业指数涨幅", "创业板指涨幅"])
            or auto_close.get("创业板涨幅")
            or auto_close.get("创业涨幅")
            or _extract_last_pct(close_text or content, ["创业板", "创业"])
        ),
        "创业昨成交额": _fmt_wanyi(_first_present(fm, ["创业成交额", "创业板成交额", "创业指数成交额", "创业板指成交额"])),
        "昨日午间成交额": _fmt_wanyi(_extract_turnover(midday_text)),
        "昨日全天成交额": _fmt_wanyi(fm.get("市场量能")),
        "上证昨上涨": up,
        "上证昨下跌": down,
        "_source_note": Path(prev_path).name,
        "_source_note_date": prev_date,
    }
    return {k: v for k, v in baseline.items() if v is not None}


def _build_pools_payload_for_trading_day(current_path, as_of_date=None):
    pools_review_path = _select_pools_review_path(current_path, as_of_date)
    pools = _build_pools_payload(pools_review_path)
    pools["source_note"] = Path(pools_review_path).name
    pools["source_note_date"] = _review_note_date(pools_review_path)
    return pools

def build_dashboard_data(review_path):
    """组装完整的 dashboard_data.json"""
    fm = parse_frontmatter(review_path)
    prev_fm = _fallback_frontmatter(review_path)  # 今天空字段用昨天的值
    premarket_plan = _parse_premarket_plan(review_path)
    premarket_style = premarket_plan.get("style", {})
    style_review_path = review_path
    if not _fm_has_data(fm, "情绪值"):
        fallback_path = _fallback_review_path(review_path)
        if fallback_path:
            print(f"[info] Fallback style_detect: using {Path(fallback_path).name}")
            style_review_path = fallback_path
    style = get_style_data(style_review_path)
    appendix = parse_appendix(review_path)
    # W12/W13 自选池使用「数据附录」个股表；附录A是盘前速查映射，不作为表格数据源。
    appendix_a = parse_appendix_a(review_path)
    pools_payload = _build_pools_payload_for_trading_day(review_path)
    anchor_a = appendix_a.get("anchor_stocks", []) if appendix_a else []
    sectors_a = appendix_a.get("sectors", []) if appendix_a else []
    # 合并 frontmatter：今天有值用今天，空字段回退昨天
    def fm_val(key, default=None):
        v = clean_value(fm.get(key))
        if v is not None and v != "" and v != "待收盘":
            return v
        return clean_value(prev_fm.get(key)) if prev_fm else default

    def fm_current_val(key):
        v = clean_value(fm.get(key))
        if v is not None and v != "" and v != "待收盘":
            return v
        return None

    raw_date = fm.get("date", datetime.now().strftime("%Y-%m-%d"))
    date_str = str(raw_date) if not isinstance(raw_date, str) else raw_date

    # 规则引擎：计算实际执行
    if not style:
        style = {}
    premarket_source = premarket_plan.get("source", "premarket_plan")
    if premarket_style and (premarket_source == "appendix_a_plan" or not _fm_has_data(fm, "情绪值")):
        style.update(premarket_style)
        style["_source"] = premarket_source
    style["实际执行"] = compute_style_execution(fm, style)
    if style["实际执行"]["总仓位上限"] != style.get("总仓位上限", 30):
        style["总仓位上限"] = style["实际执行"]["总仓位上限"]

    # 问财实时值兜底（笔记frontmatter有值优先，无值用问财）
    iw = {k.replace('_iwencai_', ''): v for k, v in style.items() if k.startswith('_iwencai_')}
    iw_current = iw if Path(style_review_path).resolve() == Path(review_path).resolve() else {}

    data = {
        "meta": {
            "date": date_str,
            "weekday": fm.get("weekday", get_weekday_str(date_str)),
            "updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "source": "gen_dashboard_data.py",
            "note": f"自动生成自 {os.path.basename(review_path)}",
            "pools_note": pools_payload.get("source_note"),
            "pools_note_date": pools_payload.get("source_note_date")
        },
        # === market 域：T1(实时)/T2(阶段) 优先，frontmatter 仅做收盘校验回退 ===
        "market": {
            # T1: PyTDX 5s 实时 → live_index / live_breadth
            "上证指数": fm_val("上证指数"),
            "上证涨幅": fm_val("上证涨幅"),
            "市场量能": fm_val("市场量能"),
            "涨跌比": fm_val("涨跌比"),
            "涨停家数": fm_val("涨停家数") or iw.get("涨停家数"),
            "跌停家数": fm_val("跌停家数"),
            # T2: iwencai 2min → frontmatter 仅做收盘校验
            "炸板率": fm_val("炸板率") or iw.get("炸板率"),
            "封板率": fm_val("封板率") or iw.get("封板率"),
        },
        # === sentiment 域：T3(实时计算)/T2(校验) 优先，frontmatter 仅做回退 ===
        "sentiment": {
            # T3 主源: store.js merge() 涨跌家数比 → frontmatter 仅做人工校验
            "情绪值": fm_current_val("情绪值") or iw_current.get("情绪值"),
            "情绪区间": fm_current_val("情绪区间"),
            "昨日情绪": fm_current_val("昨日情绪"),
            "情绪变化": fm_current_val("情绪变化"),
            # T2: iwencai 2min → frontmatter 回退
            "赚钱效应": fm_val("赚钱效应") or iw.get("赚钱效应"),
            "昨日涨停收益": fm_val("昨日涨停收益") or iw.get("涨停收益"),
            "昨日炸板收益": fm_val("昨日炸板收益") or iw.get("炸板收益"),
            "连板收益": fm_val("昨日连板收益") or fm_val("连板收益") or iw.get("连板收益"),
            "连板风险值": fm_val("连板风险值") or iw.get("连板风险值"),
            "晋级率": fm_val("整体晋级率") or fm_val("晋级率") or iw.get("晋级率"),
            "一进二晋级率": fm_val("一进二晋级率"),
            "二进三晋级率": fm_val("二进三晋级率"),
            "三进四晋级率": fm_val("三进四晋级率"),
            "最高板": fm_val("最高板") or iw.get("最高板"),
            "次高板": fm_val("次高板"),
            "连板梯队": fm_val("连板梯队"),
            # T2: auction snapshot (9:25) → frontmatter 回退
            "竞价情绪值": fm_current_val("竞价情绪值") or _bidding_emotion(parse_sentiment_nodes(review_path)),
        },
        "style": style if style else {
            "总分": None, "风格": None, "连板占比": None, "趋势占比": None,
            "总仓位上限": None,
            "dim1_量能": None, "dim2_连板生态": None, "dim3_趋势": None,
            "实际执行": {}
        },
        "time_window": {
            "当前时段": "盘前",
            "W1状态": fm.get("W1状态", "开放"),
            "W2状态": fm.get("W2状态", "开放"),
            "周五": fm.get("weekday") == "周五",
        },
        "risk": {
            "当日盈亏": clean_value(fm.get("当日盈亏", 0)),
            "当日盈亏金额": clean_value(fm.get("当日盈亏金额", 0)),
            "周累计回撤": clean_value(fm.get("周累计回撤", 0)),
            "月累计回撤": clean_value(fm.get("月累计回撤", 0)),
            "连亏天数": clean_value(fm.get("连亏天数", 0)),
            "单日熔断线": clean_value(fm.get("单日熔断线", -3)),
            "周回撤预警": clean_value(fm.get("周回撤预警", 6)),
            "月回撤预警": clean_value(fm.get("月回撤预警", 10)),
            "熔断触发": fm.get("熔断触发", False),
            "周回撤触发": fm.get("周回撤触发", False),
        },
        "positions": appendix.get("positions", []) or _fallback_appendix(review_path, "positions"),
        "lianban_pool": pools_payload.get("lianban_pool", []),
        "trend_pool": pools_payload.get("trend_pool", []),
        "sectors": sectors_a or appendix.get("sectors", []) or _fallback_appendix(review_path, "sectors"),
        "yesterday_baseline": _build_yesterday_baseline(review_path, date_str),
        "上证15min": [],
        "live_index": {},
        "live_sectors": {},
        "live_quotes": {},
        "sentiment_nodes": parse_sentiment_nodes(review_path),
        "decision": {
            "竞价": appendix.get("竞价") or {},
            "早盘": appendix.get("早盘") or {},
            "盘中": appendix.get("盘中") or {},
            "今日操作": appendix.get("今日操作", []) or _fallback_appendix(review_path, "今日操作"),
            "锚定股状态": anchor_a or appendix.get("锚定股状态", []) or _fallback_appendix(review_path, "锚定股状态"),
        }
    }

    # 自动计算情绪区间
    qx = data["sentiment"].get("情绪值")
    if qx is not None and not data["sentiment"].get("情绪区间"):
        try:
            qx_num = float(qx) if not isinstance(qx, (int, float)) else qx
            data["sentiment"]["情绪区间"] = (
                "冰点" if qx_num < 20 else "低迷" if qx_num < 40 else
                "主升" if qx_num < 60 else "强势" if qx_num < 80 else "高潮"
            )
        except (ValueError, TypeError):
            pass

    # 保留现有 dashboard_data.json 中的清仓持仓（bridge sync 写入，复盘笔记不含）
    _preserve_cleared(data)
    # 保留日内新增持仓（盘中 W15 sync 写入，复盘笔记不含，如沪电股份）
    _preserve_active_positions(data)
    # 保留活跃持仓的现价（复盘笔记只有成本，bridge live 报价盘前可能为 0）
    _preserve_active_price(data)
    # 保留 pnl 字段（可用资金/总资产由 W15 记流水实时维护，gen 不覆盖）
    _preserve_pnl(data)
    # 三层仓位：盈利解锁层（POS-SIZE-005）
    positions_for_cap = data.get("positions", [])
    mainline_ids_for_cap = _build_mainline_ids(data)
    mainline_confirmed_for_cap = bool(mainline_ids_for_cap) or any(
        isinstance(p, dict) and _cap_truthy(p.get("is_mainline"))
        for p in positions_for_cap
    )
    protection_raised = style.get("protection_raised") or style.get("保护位已抬高")
    if positions_for_cap and mainline_confirmed_for_cap:
        style["earned_cap_pct"] = _compute_earned_cap(
            positions_for_cap,
            mainline_ids=mainline_ids_for_cap,
            mainline_confirmed=mainline_confirmed_for_cap,
            protection_raised=protection_raised,
        )
        opportunity_from_compute = style.get("总仓位上限", 60)
        # 硬风控触发时 cap=0，不叠加 earned
        if opportunity_from_compute > 0:
            final_cap = min(opportunity_from_compute, style["earned_cap_pct"])
            style["opportunity_cap_pct"] = opportunity_from_compute
            style["总仓位上限"] = final_cap

    # 从 pnl.db 自动计算风控指标（连亏天数/周回撤/月回撤，笔记不用维护）
    _compute_risk_from_pnl(data)

    return data


def _compute_risk_from_pnl(data):
    """从 pnl.db daily_summary 自动计算连亏天数/周回撤/月回撤"""
    import sqlite3
    from datetime import datetime, timedelta
    pnl_db = OUTPUT_FILE.parent / "pnl.db"
    if not pnl_db.exists():
        return
    try:
        conn = sqlite3.connect(str(pnl_db))
        cur = conn.cursor()
        cur.execute("SELECT date, pnl_pct FROM daily_summary ORDER BY date")
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return

        risk = data.setdefault("risk", {})

        # 连亏天数
        streak = 0
        for _, pnl in reversed(rows):
            if (pnl or 0) < 0:
                streak += 1
            else:
                break
        risk["连亏天数"] = streak

        # 周回撤 / 月回撤
        now = datetime.now()
        periods = {
            "周累计回撤": now - timedelta(days=now.weekday()),
            "月累计回撤": datetime(now.year, now.month, 1),
        }
        for key, since in periods.items():
            cum = 1.0; peak = 1.0; max_dd = 0.0
            since_str = since.strftime("%Y-%m-%d")
            for _, dp in rows:
                if _ < since_str:
                    continue
                cum *= (1 + (dp or 0) / 100)
                if cum > peak:
                    peak = cum
                dd = (cum - peak) / peak * 100
                if dd < max_dd:
                    max_dd = dd
            risk[key] = round(max_dd, 2)
    except Exception:
        pass


def _filter_excluded(pool, excluded=None):
    """从 pools.json 读取 excluded 列表，过滤池中不应出现的标的"""
    if excluded:
        excluded_set = set(excluded)
        return [s for s in pool if s.get("标的", "") not in excluded_set]
    try:
        if POOLS_FILE.exists():
            with open(POOLS_FILE) as f:
                pools = json.load(f)
            excluded = set(pools.get("excluded", []))
            if excluded:
                return [s for s in pool if s.get("标的", "") not in excluded]
    except Exception:
        pass
    return pool


def _preserve_active_positions(new_data):
    """保留旧文件中存在但新数据中没有的活跃持仓（盘中 W15 sync 新增的持仓不会被笔记覆盖）"""
    if not OUTPUT_FILE.exists():
        return
    try:
        with open(OUTPUT_FILE) as f:
            old = json.load(f)
    except Exception:
        return
    new_codes = {p.get("代码") for p in new_data.get("positions", []) if p.get("代码")}
    for p in old.get("positions", []):
        if p.get("状态", "").find("持有") < 0:
            continue
        if p.get("代码") and p.get("代码") not in new_codes:
            new_data.setdefault("positions", []).append(p)


def _parse_position_qty(value):
    text = str(value or "").replace(",", "")
    m = re.search(r"\d+(?:\.\d+)?", text)
    return float(m.group(0)) if m else 0.0


def _preserve_active_price(new_data):
    """保留活跃持仓现价：旧文件 > pnl_history 推算昨日收盘"""
    old_price_map = {}
    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE) as f:
                old = json.load(f)
            for p in old.get("positions", []):
                code, price = p.get("代码"), p.get("现价")
                if code and price:
                    old_price_map[code] = price
        except Exception:
            pass
    pnl_mv = None
    ph_path = ROOT_DIR / "data" / "pnl_history.json"
    if ph_path.exists():
        try:
            with open(ph_path) as f:
                ph = json.load(f)
            pnl_mv = ph.get("meta", {}).get("last_mv")
        except Exception:
            pass
    for p in new_data.get("positions", []):
        code = p.get("代码")
        if not code or p.get("现价"):
            continue
        if code in old_price_map:
            p["现价"] = old_price_map[code]
        elif pnl_mv:
            qty = _parse_position_qty(p.get("数量", "0"))
            if qty > 0:
                p["现价"] = round(pnl_mv / qty, 2)
    # 兜底：仍未设置现价的持仓用成本价
    for p in new_data.get("positions", []):
        if not p.get("现价") and p.get("成本"):
            p["现价"] = p["成本"]


def _preserve_cleared(new_data):
    """从现有 dashboard_data.json 中提取清仓持仓（7日内），合并到新数据中"""
    if not OUTPUT_FILE.exists():
        return
    try:
        with open(OUTPUT_FILE) as f:
            old = json.load(f)
    except Exception:
        return
    old_positions = old.get("positions", [])
    if not old_positions:
        return
    now = datetime.now()
    cleared = []
    for p in old_positions:
        if p.get("状态", "").find("清") < 0:
            continue
        d = p.get("清仓日期", "")
        if d:
            try:
                age = (now - datetime.strptime(d, "%Y-%m-%d")).days
                if age > 7:
                    continue
            except Exception:
                pass
        cleared.append(p)
    if not cleared:
        return
    existing_names = {p.get("标的") for p in new_data.get("positions", [])}
    for p in cleared:
        if p.get("标的") not in existing_names:
            new_data.setdefault("positions", []).append(p)


def _preserve_pnl(new_data):
    """历史兼容：保留旧 dashboard_data.json 的 pnl 字段供前端展示降级兜底。

    注意：pnl.可用资金/总资产 已由 account_ssot 接管权威来源，gen 仅做兼容保留。
    每日只跑一次 gen，不覆盖当日由 bridge 维护的实时持仓/pnl 数据。
    """
    if not OUTPUT_FILE.exists():
        return
    try:
        with open(OUTPUT_FILE) as f:
            old = json.load(f)
    except Exception:
        return
    old_pnl = old.get("pnl", {})
    # 累计入金：优先从 pnl_history.json 读取（权威来源），其次旧文件
    deposit = None
    total_asset = None
    pnl_history_path = ROOT_DIR / "data" / "pnl_history.json"
    if pnl_history_path.exists():
        try:
            with open(pnl_history_path) as f:
                ph = json.load(f)
            meta = ph.get("meta", {})
            deposit = str(meta.get("total_deposit", "")) or None
            total_asset = meta.get("day_start_asset") or meta.get("last_total_asset")
        except Exception:
            pass
    if not deposit and old_pnl:
        deposit = old_pnl.get("累计入金", "200000")
    if deposit:
        new_data["pnl"] = {"累计入金": deposit}
        if total_asset is not None:
            new_data["pnl"]["总资产"] = total_asset


def watch_mode(review_path, interval=10):
    """监控复盘笔记文件变化，自动重跑管线"""
    import time as time_mod
    last_mtime = os.path.getmtime(review_path)
    print(f"[watch] Monitoring {review_path} every {interval}s...")

    while True:
        time_mod.sleep(interval)
        try:
            mtime = os.path.getmtime(review_path)
        except:
            continue
        if mtime == last_mtime:
            continue
        last_mtime = mtime
        print(f"\n[{time_mod.strftime('%H:%M:%S')}] File changed, regenerating...")
        try:
            data = build_dashboard_data(review_path)
            OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(OUTPUT_FILE, data)
            print(f"  → {len(json.dumps(data, ensure_ascii=False))} bytes written")
            # 同步输出 pools.json（机器个股池；今天未填写时才回退昨天）
            pools = _build_pools_payload_for_trading_day(review_path)
            used_fallback = bool(pools.get("source", "").find("fallback") >= 0)
            if pools:
                pools["version"] = 1
                pools["updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
                pools["source"] = f"复盘笔记 {'fallback' if used_fallback else '数据附录'} ({os.path.basename(review_path)})"
                atomic_write_json(POOLS_FILE, pools)
        except Exception as e:
            print(f"  [ERROR] {e}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="复盘笔记 → dashboard_data.json")
    parser.add_argument("--watch", action="store_true", help="监控模式，文件变化自动重跑")
    parser.add_argument("--interval", type=int, default=10, help="监控间隔(秒)，默认10")
    args = parser.parse_args()

    review_path = find_latest_review()
    if not review_path:
        print("[ERROR] No review note found in", str(REVIEW_DIR))
        sys.exit(1)

    if args.watch:
        watch_mode(review_path, args.interval)
        return

    print(f"[info] Source: {review_path}")
    data = build_dashboard_data(review_path)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(OUTPUT_FILE, data)
    print(f"[done] Written {len(json.dumps(data, ensure_ascii=False))} bytes → {OUTPUT_FILE}")

    # 输出 pools.json（机器个股池；今天未填写时才回退昨天）
    pools = _build_pools_payload_for_trading_day(review_path)
    used_fallback = bool(pools.get("source", "").find("fallback") >= 0)
    if pools:
        pools["version"] = 1
        pools["updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
        pools["source"] = f"复盘笔记 {'fallback' if used_fallback else '数据附录'} ({os.path.basename(review_path)})"
        atomic_write_json(POOLS_FILE, pools)
        print(f"[done] Written pools → {POOLS_FILE}")

if __name__ == "__main__":
    main()
