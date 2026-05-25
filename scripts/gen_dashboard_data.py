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
    string_fields = {"代码", "标的", "板块", "方向", "角色", "操作", "买点", "梯队", "龙头", "备注", "止损", "清仓原因", "原因", "影响", "灯", "指标", "判定", "时间", "价格"}
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
            result['lianban_pool'] = _parse_table(body, {
                '标的': '标的', '代码': '代码', '板块': '板块',
                '窗口': '窗口', '角色': '角色', '操作': '操作',
                '涨幅': '涨幅', '收盘价': '收盘价', 'MA5': 'MA5',
                '量比': '量比', '换手': '换手', '备注': '备注'
            })
        elif '趋势自选池' in title:
            result['trend_pool'] = _parse_table(body, {
                '标的': '标的', '代码': '代码', '板块': '板块',
                '窗口': '窗口', '角色': '角色', '操作': '操作',
                '涨幅': '涨幅', '收盘价': '收盘价', 'MA5': 'MA5',
                'MA20': 'MA20', '量比': '量比', '换手': '换手', '备注': '备注'
            })
        elif '板块状态' in title:
            result['sectors'] = _parse_table(body, {
                '板块': '板块', '类型': '类型', '涨停数': '涨停数',
                '梯队': '梯队', '龙头': '龙头', '状态': '状态'
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

# 风格总分 → 总仓位上限映射 (score_threshold, cap)
_TOTAL_CAP_BRACKETS = [(80, 60), (60, 50), (40, 40), (20, 20)]

def _compute_total_cap(sd):
    """根据总分计算总仓位上限"""
    total = sd.get("total", 50) or 50
    for threshold, cap in _TOTAL_CAP_BRACKETS:
        if total >= threshold:
            return cap
    return 10

def compute_style_execution(fm, style):
    """规则引擎：根据 trading-core.md 计算 style.实际执行

    判定优先级（从高到低）：
    1. 熔断触发 → 仓位归零
    2. 连亏 ≥ 2 天 → 强制空仓
    3. 周五 → 趋势占比上限 15%
    4. 无强支线 → 仓位从严
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
    is_friday = str(fm.get("weekday", "")).startswith("周五")

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
    # 规则 4: 周五
    if is_friday and tr_actual > 15:
        tr_actual = min(tr_actual, 15)
        reason2s.append("周五→趋势占比上限15%")

    # 规则 5: 无强支线（人工标注）
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

def build_dashboard_data(review_path):
    """组装完整的 dashboard_data.json"""
    fm = parse_frontmatter(review_path)
    prev_fm = _fallback_frontmatter(review_path)  # 今天空字段用昨天的值
    style_review_path = review_path
    if not _fm_has_data(fm, "情绪值"):
        fallback_path = _fallback_review_path(review_path)
        if fallback_path:
            print(f"[info] Fallback style_detect: using {Path(fallback_path).name}")
            style_review_path = fallback_path
    style = get_style_data(style_review_path)
    appendix = parse_appendix(review_path)
    # 自选池优先从附录A解析（与 pools.json 同源），数据附录为回退
    appendix_a = parse_appendix_a(review_path)
    lianban_pool_a = appendix_a.get("lianban_pool", []) if appendix_a else []
    trend_pool_a = appendix_a.get("trend_pool", []) if appendix_a else []
    anchor_a = appendix_a.get("anchor_stocks", []) if appendix_a else []
    sectors_a = appendix_a.get("sectors", []) if appendix_a else []
    # 合并 frontmatter：今天有值用今天，空字段回退昨天
    def fm_val(key, default=None):
        v = clean_value(fm.get(key))
        if v is not None and v != "" and v != "待收盘":
            return v
        return clean_value(prev_fm.get(key)) if prev_fm else default

    raw_date = fm.get("date", datetime.now().strftime("%Y-%m-%d"))
    date_str = str(raw_date) if not isinstance(raw_date, str) else raw_date

    # 规则引擎：计算实际执行
    if not style:
        style = {}
    style["实际执行"] = compute_style_execution(fm, style)
    if style["实际执行"]["总仓位上限"] != style.get("总仓位上限", 30):
        style["总仓位上限"] = style["实际执行"]["总仓位上限"]

    # 问财实时值兜底（笔记frontmatter有值优先，无值用问财）
    iw = {k.replace('_iwencai_', ''): v for k, v in style.items() if k.startswith('_iwencai_')}

    data = {
        "meta": {
            "date": date_str,
            "weekday": fm.get("weekday", get_weekday_str(date_str)),
            "updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "source": "gen_dashboard_data.py",
            "note": f"自动生成自 {os.path.basename(review_path)}"
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
            "情绪值": fm_val("情绪值") or iw.get("情绪值"),
            "情绪区间": fm_val("情绪区间"),
            "昨日情绪": fm_val("昨日情绪"),
            "情绪变化": fm_val("情绪变化"),
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
            "竞价情绪值": fm_val("竞价情绪值") or _bidding_emotion(parse_sentiment_nodes(review_path)) or fm_val("情绪值") or iw.get("情绪值"),
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
        "lianban_pool": _filter_excluded(lianban_pool_a or appendix.get("lianban_pool", []) or _fallback_appendix(review_path, "lianban_pool")),
        "trend_pool": _filter_excluded(trend_pool_a or appendix.get("trend_pool", []) or _fallback_appendix(review_path, "trend_pool")),
        "sectors": sectors_a or appendix.get("sectors", []) or _fallback_appendix(review_path, "sectors"),
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


def _filter_excluded(pool):
    """从 pools.json 读取 excluded 列表，过滤池中不应出现的标的"""
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
            qty_str = str(p.get("数量", "0"))
            qty = float(qty_str.replace("股", "")) if qty_str else 0
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
    """保留现有 dashboard_data.json 中的 pnl 字段（可用资金/总资产由W15实时维护）"""
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
            # 同步输出 pools.json（今天空则回退昨天）
            pools = parse_appendix_a(review_path)
            used_fallback = False
            if not pools or not (pools.get("lianban_pool") or pools.get("trend_pool")):
                fallback = _fallback_pools(review_path)
                if fallback:
                    pools = fallback
                    used_fallback = True
            if pools:
                pools["version"] = 1
                pools["updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
                pools["source"] = f"复盘笔记 附录A ({'fallback' if used_fallback else os.path.basename(review_path)})"
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

    # 输出 pools.json（附录A SSOT，今天空则回退昨天）
    pools = parse_appendix_a(review_path)
    used_fallback = False
    if not pools or not (pools.get("lianban_pool") or pools.get("trend_pool")):
        fallback = _fallback_pools(review_path)
        if fallback:
            pools = fallback
            used_fallback = True
    if pools:
        pools["version"] = 1
        pools["updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
        pools["source"] = f"复盘笔记 {'fallback' if used_fallback else '附录A'} ({os.path.basename(review_path)})"
        atomic_write_json(POOLS_FILE, pools)
        print(f"[done] Written pools → {POOLS_FILE}")

if __name__ == "__main__":
    main()
