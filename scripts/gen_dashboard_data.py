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

VAULT_DIR = Path(__file__).resolve().parent.parent.parent  # 弈沐资本根目录 (scripts/ → live-dashboard/ → 弈沐资本/)
REVIEW_DIR = VAULT_DIR / "复盘笔记"
STYLE_DETECT = Path.home() / "WorkBuddy/Tools/style_detect.py"
SECTOR_LOG = VAULT_DIR / "板块涨停日志.md"
OUTPUT_FILE = VAULT_DIR / "live-dashboard/data/dashboard_data.json"

def find_latest_review():
    """找最新的复盘笔记"""
    md_files = sorted(REVIEW_DIR.glob("**/*ReviewNote.md"), reverse=True)
    if not md_files:
        md_files = sorted(REVIEW_DIR.glob("**/*.md"), reverse=True)
    return str(md_files[0]) if md_files else None

def clean_value(val, field_name=""):
    """清洗复盘笔记 frontmatter 中的注释和格式"""
    if val is None:
        return None
    s = str(val).strip()

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


def _parse_table(body, col_map):
    """解析 Markdown 表格，返回 list[dict]"""
    lines = body.strip().split('\n')
    rows = []
    header = None

    for line in lines:
        line = line.strip()
        if not line or not line.startswith('|'):
            continue
        if '---' in line:  # 分隔行，跳过
            continue
        cells = [c.strip() for c in line.split('|')[1:-1]]
        if header is None:
            header = cells
        else:
            row = {}
            for i, cell in enumerate(cells):
                if i < len(header) and header[i] in col_map:
                    key = col_map[header[i]]
                    val = clean_value(cell, key)
                    if val is not None and val != '—' and val != '' and val != '待填' and val != '待定':
                        row[key] = val
            if row:
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


def get_style_data():
    """调用 style_detect.py 获取风格数据，映射为 dashboard 格式"""
    try:
        result = subprocess.run(
            ["python3", str(STYLE_DETECT), "--json"],
            capture_output=True, text=True, timeout=60, cwd=str(STYLE_DETECT.parent)
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
                # 字段映射: style_detect → dashboard_data.json
                return {
                    "总分": sd.get("total"),
                    "风格": sd.get("style"),
                    "连板占比": _compute_lianban_pct(sd),
                    "趋势占比": _compute_trend_pct(sd),
                    "总仓位上限": _compute_total_cap(sd),
                    "dim1_量能": (sd.get("dim1") or {}).get("score"),
                    "dim2_连板生态": (sd.get("dim2") or {}).get("score"),
                    "dim3_趋势": (sd.get("dim3") or {}).get("score"),
                }
        if result.returncode != 0:
            print(f"[warn] style_detect.py returned {result.returncode}: {result.stderr[:200]}")
    except Exception as e:
        print(f"[warn] style_detect.py failed: {e}")
    return {}

def _compute_lianban_pct(sd):
    """根据风格判定计算连板占比"""
    style = str(sd.get("style", ""))
    total = sd.get("total", 50) or 50
    if "连板" in style:
        return 75 + min(25, int((total - 50) / 2))
    elif "趋势" in style:
        return max(0, 25 - int((50 - total) / 2))
    else:  # 混合
        return 50 + int((total - 50) / 2)

def _compute_trend_pct(sd):
    return 100 - _compute_lianban_pct(sd)

def _compute_total_cap(sd):
    """根据总分计算总仓位上限"""
    total = sd.get("total", 50) or 50
    if total >= 80: return 60
    elif total >= 60: return 50
    elif total >= 40: return 40
    elif total >= 20: return 20
    else: return 10

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

def build_dashboard_data(review_path):
    """组装完整的 dashboard_data.json"""
    fm = parse_frontmatter(review_path)
    style = get_style_data()
    appendix = parse_appendix(review_path)

    raw_date = fm.get("date", datetime.now().strftime("%Y-%m-%d"))
    date_str = str(raw_date) if not isinstance(raw_date, str) else raw_date

    # 规则引擎：计算实际执行
    if not style:
        style = {}
    style["实际执行"] = compute_style_execution(fm, style)
    if style["实际执行"]["总仓位上限"] != style.get("总仓位上限", 30):
        style["总仓位上限"] = style["实际执行"]["总仓位上限"]

    data = {
        "meta": {
            "date": date_str,
            "weekday": fm.get("weekday", get_weekday_str(date_str)),
            "updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "source": "gen_dashboard_data.py",
            "note": f"自动生成自 {os.path.basename(review_path)}"
        },
        "market": {
            "上证指数": clean_value(fm.get("上证指数")),
            "上证涨幅": clean_value(fm.get("上证涨幅")),
            "市场量能": clean_value(fm.get("市场量能")),
            "涨跌比": clean_value(fm.get("涨跌比")),
            "涨停家数": clean_value(fm.get("涨停家数"), "涨停家数"),
            "跌停家数": clean_value(fm.get("跌停家数")),
            "炸板率": clean_value(fm.get("炸板率")),
            "封板率": clean_value(fm.get("封板率")),
        },
        "sentiment": {
            "情绪值": clean_value(fm.get("情绪值")),
            "情绪区间": clean_value(fm.get("情绪区间")),
            "昨日情绪": clean_value(fm.get("昨日情绪")),
            "情绪变化": clean_value(fm.get("情绪变化")),
            "赚钱效应": clean_value(fm.get("赚钱效应")),
            "昨日涨停收益": clean_value(fm.get("昨日涨停收益")),
            "昨日炸板收益": clean_value(fm.get("昨日炸板收益")),
            "连板收益": clean_value(fm.get("连板收益")),
            "连板风险值": clean_value(fm.get("连板风险值")),
            "晋级率": clean_value(fm.get("晋级率")),
            "最高板": clean_value(fm.get("最高板"), "最高板"),
            "次高板": clean_value(fm.get("次高板"), "次高板"),
            "连板梯队": clean_value(fm.get("连板梯队"), "连板梯队"),
            "竞价情绪值": clean_value(fm.get("竞价情绪值")) or clean_value(fm.get("情绪值")),
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
        "positions": appendix.get("positions", []),
        "lianban_pool": appendix.get("lianban_pool", []),
        "trend_pool": appendix.get("trend_pool", []),
        "sectors": appendix.get("sectors", []),
        "上证15min": [],
        "live_index": {},
        "live_sectors": {},
        "live_quotes": {},
        "decision": {
            "竞价": appendix.get("竞价", {}),
            "早盘": appendix.get("早盘", {}),
            "盘中": appendix.get("盘中", {}),
            "今日操作": appendix.get("今日操作", []),
            "锚定股状态": appendix.get("锚定股状态", []),
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

    return data

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
            with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"  → {len(json.dumps(data, ensure_ascii=False))} bytes written")
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
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[done] Written {len(json.dumps(data, ensure_ascii=False))} bytes → {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
