#!/usr/bin/env python3
"""gen_dashboard_data.py — 复盘笔记 → dashboard_data.json (Layer 1 基线数据)
稳米维护 | v2.0 Phase 1.8

数据源:
  1. 最新复盘笔记 YAML frontmatter (market/sentiment/risk/positions/decision 域)
  2. style_detect.py --json (style 域, 从 WorkBuddy/Tools/)
  3. 板块涨停日志.md (sectors 域, 近3天板块数据)

输出: live-dashboard/data/dashboard_data.json
"""

import json, os, sys, re, glob, subprocess
from datetime import datetime
from pathlib import Path

VAULT_DIR = Path(__file__).resolve().parent.parent  # 弈沐资本根目录
REVIEW_DIR = VAULT_DIR / "复盘笔记"
STYLE_DETECT = Path.home() / "WorkBuddy/Tools/style_detect.py"
SECTOR_LOG = VAULT_DIR / "板块涨停日志.md"
OUTPUT_FILE = VAULT_DIR / "live-dashboard/data/dashboard_data.json"

def find_latest_review():
    """找最新的复盘笔记"""
    md_files = sorted(glob.glob(str(REVIEW_DIR / "**/*ReviewNote.md"), recursive=True), reverse=True)
    if not md_files:
        md_files = sorted(glob.glob(str(REVIEW_DIR / "**/*.md")), recursive=True, reverse=True)
    return md_files[0] if md_files else None

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

def get_style_data():
    """调用 style_detect.py 获取风格数据"""
    try:
        result = subprocess.run(
            ["python3", str(STYLE_DETECT), "--json"],
            capture_output=True, text=True, timeout=30, cwd=str(VAULT_DIR)
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        print(f"[warn] style_detect.py returned {result.returncode}: {result.stderr}")
    except Exception as e:
        print(f"[warn] style_detect.py failed: {e}")
    return {}

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

    raw_date = fm.get("date", datetime.now().strftime("%Y-%m-%d"))
    date_str = str(raw_date) if not isinstance(raw_date, str) else raw_date

    data = {
        "meta": {
            "date": date_str,
            "weekday": fm.get("weekday", get_weekday_str(date_str)),
            "updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "source": "gen_dashboard_data.py",
            "note": f"自动生成自 {os.path.basename(review_path)}"
        },
        "market": {
            "上证指数": fm.get("上证指数", None),
            "上证涨幅": fm.get("上证涨幅", None),
            "市场量能": fm.get("市场量能", None),
            "涨跌比": fm.get("涨跌比", None),
            "涨停家数": fm.get("涨停家数", None),
            "跌停家数": fm.get("跌停家数", None),
            "炸板率": fm.get("炸板率", None),
            "封板率": fm.get("封板率", None),
        },
        "sentiment": {
            "情绪值": fm.get("情绪值", None),
            "情绪区间": fm.get("情绪区间", None),
            "昨日情绪": fm.get("昨日情绪", None),
            "情绪变化": fm.get("情绪变化", None),
            "赚钱效应": fm.get("赚钱效应", None),
            "昨日涨停收益": fm.get("昨日涨停收益", None),
            "昨日炸板收益": fm.get("昨日炸板收益", None),
            "连板收益": fm.get("连板收益", None),
            "连板风险值": fm.get("连板风险值", None),
            "晋级率": fm.get("晋级率", None),
            "最高板": fm.get("最高板", None),
            "次高板": fm.get("次高板", None),
            "连板梯队": fm.get("连板梯队", None),
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
            "当日盈亏": fm.get("当日盈亏", 0),
            "当日盈亏金额": fm.get("当日盈亏金额", 0),
            "周累计回撤": fm.get("周累计回撤", 0),
            "月累计回撤": fm.get("月累计回撤", 0),
            "连亏天数": fm.get("连亏天数", 0),
            "单日熔断线": fm.get("单日熔断线", -3),
            "周回撤预警": fm.get("周回撤预警", 6),
            "月回撤预警": fm.get("月回撤预警", 10),
            "熔断触发": fm.get("熔断触发", False),
            "周回撤触发": fm.get("周回撤触发", False),
        },
        "positions": [],
        "lianban_pool": [],
        "trend_pool": [],
        "sectors": [],
        "上证15min": [],
        "live_index": {},
        "live_sectors": {},
        "live_quotes": {},
        "decision": {
            "竞价": {},
            "早盘": {},
            "盘中": {}
        }
    }
    return data

def main():
    review_path = find_latest_review()
    if not review_path:
        print("[ERROR] No review note found in", str(REVIEW_DIR))
        sys.exit(1)

    print(f"[info] Source: {review_path}")
    data = build_dashboard_data(review_path)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[done] Written {len(json.dumps(data, ensure_ascii=False))} bytes → {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
