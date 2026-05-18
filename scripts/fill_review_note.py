#!/usr/bin/env python3
"""fill_review_note.py — 管线数据自动填入复盘笔记

收盘后运行，读管线数据源 → 填入笔记的绿色字段，不动红色字段（人写内容）。

用法:
  python3 scripts/fill_review_note.py                        # 填今天笔记
  python3 scripts/fill_review_note.py --date 2026-05-18      # 填指定日期
  python3 scripts/fill_review_note.py --dry-run               # 预览，不写入

数据源（全部读磁盘文件，不碰 bridge CACHE）:
  data/close_snapshot_{date}.json  — 收盘快照（frontmatter 主力源）
  data/sentiment_auto.json         — 30min 快照（表1/表2 按节点取值）
  data/auction_snapshot.json       — 竞价数据
  data/pools.json                  — 自选池 SSOT
  data/dashboard_data.json         — baseline（style 检测兜底）
  data/pnl.db                      — P&L 计算
"""
import json, os, re, sys, sqlite3
from pathlib import Path
from datetime import datetime, date as _date, timedelta

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
TRADING_DIR = Path.home() / "Documents/YouMingVault/10_⚡Now/01_💰弈沐资本"
REVIEW_DIR = TRADING_DIR / "复盘笔记"

# 占位符：这些值表示"未填"，会被管线数据替换
PLACEHOLDERS = {"待收盘", "待确认", "待填", "待定", "待计算", "", "—", "%", "N/A", "..."}

# 表1 节点名映射（笔记中的节点 → sentiment_auto 中的 node 值）
NODE_MAP = {"竞价": "竞价", "早盘": "早盘", "午盘": "午盘", "尾盘": "尾盘", "收盘": "收盘"}
# 30min 快照 node 实际值 → 笔记节点
SNAP_NODE_TO_TABLE = {
    "早盘": "早盘", "午盘前": "早盘", "午盘": "午盘",
    "下午": "午盘", "尾盘": "尾盘", "收盘": "收盘",
}


# ═══════════════════════════════════════════════════════════════
# 数据源加载
# ═══════════════════════════════════════════════════════════════

def load_close_snapshot(date_str):
    """读收盘快照，不存在则返回 None"""
    path = DATA_DIR / f"close_snapshot_{date_str}.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def load_sentiment_auto(date_str=None):
    """读 30min 情绪快照，返回指定日期的快照列表

    新版格式: {"2026-05-18": [{...}, ...], "2026-05-19": [...]}
    兼容旧版格式: [{...}, {...}] (平铺数组)
    """
    path = DATA_DIR / "sentiment_auto.json"
    if not path.exists():
        return []
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list):
        return data  # 旧版兼容
    if date_str is None:
        date_str = _date.today().strftime("%Y-%m-%d")
    return data.get(date_str, [])


def load_auction_snapshot():
    """读竞价快照"""
    path = DATA_DIR / "auction_snapshot.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def load_pools():
    """读 pools.json"""
    path = DATA_DIR / "pools.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def load_baseline():
    """读 dashboard_data.json"""
    path = DATA_DIR / "dashboard_data.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def load_pnl(date_str):
    """从 pnl.db 读当日 P&L 摘要"""
    db_path = DATA_DIR / "pnl.db"
    if not db_path.exists():
        return {}
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM daily_summary WHERE date = ?", (date_str,))
        row = cur.fetchone()
        cur.execute(
            "SELECT COUNT(*) AS n FROM trade_records WHERE trade_date = ?", (date_str,))
        trade_count = cur.fetchone()["n"] if cur.fetchone() else 0
        conn.close()
        if row:
            return {"nav": row["nav"], "pnl_pct": row["pnl_pct"],
                    "pos_pct": row["pos_pct"], "trade_count": trade_count}
    except Exception:
        pass
    return {}


# ═══════════════════════════════════════════════════════════════
# 笔记查找
# ═══════════════════════════════════════════════════════════════

def find_note(date_str):
    """根据日期找复盘笔记路径"""
    patterns = [
        date_str,                                    # 2026-05-18
        date_str.replace("-", "_"),                  # 2026_05_18
        f"{_date.fromisoformat(date_str).year}_{_date.fromisoformat(date_str).month}_{_date.fromisoformat(date_str).day}",  # 2026_5_18
    ]
    for md in sorted(REVIEW_DIR.glob("**/*ReviewNote.md"), reverse=True):
        name = str(md)
        for p in patterns:
            if p in name:
                return str(md)
    return None


# ═══════════════════════════════════════════════════════════════
# Frontmatter 填充
# ═══════════════════════════════════════════════════════════════

def _is_placeholder(val):
    """判断值是否为占位符（需要被管线数据替换）"""
    if val is None:
        return True
    s = str(val).strip()
    if s in PLACEHOLDERS:
        return True
    if s.startswith("待"):
        return True
    return False


def _fmt_pct(val):
    """格式化百分比: 0.587 → '58.70%'"""
    if val is None:
        return None
    try:
        f = float(val)
        if 0 < f <= 1:
            return f"{f * 100:.2f}%"
        return f"{f:.2f}%"
    except (ValueError, TypeError):
        return str(val)


def _fmt_float(val, decimals=2):
    """格式化浮点数"""
    if val is None:
        return None
    try:
        f = float(val)
        return round(f, decimals)
    except (ValueError, TypeError):
        return val


def _fmt_emotion_zone(val):
    """情绪值 → 情绪区间"""
    try:
        v = float(val)
        if v < 20:
            return "冰点"
        elif v < 40:
            return "低迷"
        elif v < 60:
            return "主升"
        elif v < 80:
            return "强势"
        else:
            return "高潮"
    except (ValueError, TypeError):
        return None


def _fmt_money_effect(val):
    """涨停收益 → 赚钱效应"""
    try:
        v = float(val)
        if v > 2:
            return "好"
        elif v < 0:
            return "差"
        else:
            return "一般"
    except (ValueError, TypeError):
        return None


def _get_fm(snapshot, pools, auction):
    """构建 frontmatter 字段映射表

    返回 {英文字段名: (值, 来源标记)}
    """
    fm = {}
    iw = snapshot.get("iwencai", {}) if snapshot else {}
    li = snapshot.get("live_index", {}) if snapshot else {}
    br = snapshot.get("breadth", {}) if snapshot else {}
    baseline = load_baseline()
    style = baseline.get("style", {})

    def v(key, default=None, fmt=None, source="snapshot"):
        """取值并应用格式化"""
        val = default
        s = source
        if snapshot:
            val = iw.get(key) or li.get(key) or br.get(key) or val
            s = "snapshot"
        if val is None:
            val = baseline.get("market", {}).get(key) or baseline.get("sentiment", {}).get(key)
            s = "baseline"
        if val is None and style:
            val = style.get(key)
            s = "style"
        if fmt and val is not None:
            val = fmt(val)
        return (val, s)

    # 情绪类
    fm["情绪值"] = v("情绪值")
    fm["情绪区间"] = (_fmt_emotion_zone(fm.get("情绪值", (None,))[0]), "calculated")

    # 涨停/跌停
    up = v("涨停", default=v("涨停家数")[0])[0] or br.get("涨停") or (iw.get("涨停家数"))
    dn = v("跌停", default=v("跌停家数")[0])[0] or br.get("跌停")
    fm["涨停家数"] = (up, "snapshot")
    fm["跌停家数"] = (dn, "snapshot")

    # 晋级率
    jjl = iw.get("晋级率")
    if jjl is not None:
        try:
            jjl_f = float(jjl)
            if jjl_f <= 1:
                jjl_f = round(jjl_f * 100, 2)
            fm["整体晋级率"] = (f"{jjl_f}%", "iwencai")
        except (ValueError, TypeError):
            fm["整体晋级率"] = (jjl, "iwencai")
    else:
        fm["整体晋级率"] = (None, None)

    # 分层晋级率（来自 style_detect）
    for key in ["一进二晋级率", "二进三晋级率", "三进四晋级率"]:
        val = style.get(key)
        if val is not None:
            try:
                fv = float(val)
                fm[key] = (f"{fv:.2f}%", "style_detect")
            except (ValueError, TypeError):
                fm[key] = (val, "style_detect")
        else:
            fm[key] = (None, None)

    # 封板/炸板率
    for key in ["封板率", "炸板率"]:
        val = iw.get(key)
        if val is not None:
            try:
                fv = float(val)
                fm[key] = (f"{fv * 100 if fv <= 1 else fv:.2f}%", "iwencai")
            except (ValueError, TypeError):
                fm[key] = (val, "iwencai")
        else:
            fm[key] = (None, None)

    # 收益类
    fm["昨日涨停收益"] = (iw.get("昨日涨停收益"), "iwencai")
    fm["昨日连板收益"] = (iw.get("连板收益"), "iwencai")
    fm["昨日炸板收益"] = (iw.get("炸板收益"), "iwencai")
    fm["连板风险值"] = (iw.get("连板风险值"), "iwencai")
    fm["赚钱效应"] = (iw.get("赚钱效应") or _fmt_money_effect(iw.get("昨日涨停收益")), "iwencai")
    fm["涨停溢价率"] = (iw.get("涨停溢价率"), "iwencai")

    # 最高板/次高板
    max_board = iw.get("最高板")
    fm["最高板"] = (f"{max_board}板" if max_board else None, "iwencai")
    lb_list = iw.get("连板股列表") or []
    if len(lb_list) >= 2:
        fm["次高板"] = (f"{lb_list[1].get('连板数', '?')}板", "iwencai")

    # 大盘指数
    fm["上证指数"] = (li.get("上证指数"), "live_index")
    fm["上证涨幅"] = (_fmt_pct(li.get("上证指数涨幅")), "live_index")
    fm["市场量能"] = (li.get("成交额"), "live_index")

    # 风格
    fm["风格分数验证"] = (style.get("风格"), "style_detect")

    # 竞价情绪
    if auction:
        auction_sent = auction.get("情绪指标", {}).get("情绪值")
        fm["竞价情绪值"] = (auction_sent, "auction")

    fm["连板股"] = (None, None)  # 需要人填

    return fm


# ═══════════════════════════════════════════════════════════════
# 表1 大盘全景填充
# ═══════════════════════════════════════════════════════════════

def _best_snapshot_for_node(snapshots, node_name):
    """从指定日期的快照列表中找最匹配 node_name 的那条

    snapshots 已由 load_sentiment_auto(date_str) 过滤为当天列表 [{...}]
    """
    candidates = []
    for s in snapshots:
        snap_node = s.get("node", "")
        mapped = SNAP_NODE_TO_TABLE.get(snap_node)
        if mapped == node_name:
            candidates.append(s)
    if not candidates:
        return None
    return candidates[-1]  # 同节点取最后一条（最接近节点结束时刻）


def _fill_table1(content, snapshots, auction=None):
    """填充表1：大盘全景

    找 | 竞价 | ... 这样的行，填管线数据到空单元格。
    策略：找到表1 在 Markdown 中的位置，逐行替换。
    """
    # 找表1 区域：### 表1 到下一个 ###
    t1_start = content.find("### 表1")
    if t1_start < 0:
        return content
    t1_end = content.find("\n###", t1_start + 8)
    if t1_end < 0:
        t1_end = content.find("\n---", t1_start + 8)
    if t1_end < 0:
        t1_end = len(content)
    t1_section = content[t1_start:t1_end]

    # 解析 header 行，找到列索引
    lines = t1_section.split("\n")
    header = None
    col_index = {}  # column_name → position in row
    new_lines = []
    for i, line in enumerate(lines):
        if not line.startswith("|") or "---" in line:
            new_lines.append(line)
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if header is None:
            header = cells
            # 映射列名
            for j, h in enumerate(header):
                if "节点" in h or "时段" in h:
                    col_index["节点"] = j
                elif "情绪" in h:
                    col_index["情绪"] = j
                elif "上证" in h:
                    col_index["上证"] = j
                elif "涨" in h and "跌" in h and "停" in h:
                    col_index["涨跌停"] = j
                elif "量能" in h:
                    col_index["量能"] = j
                elif "涨跌比" in h:
                    col_index["涨跌比"] = j
                elif "竞价涨幅" in h:
                    col_index["总竞价涨幅"] = j
                elif "异动" in h:
                    col_index["关键异动"] = j
            new_lines.append(line)
            continue

        # 数据行
        if len(cells) < 2 or "节点" not in col_index:
            new_lines.append(line)
            continue

        node = cells[col_index["节点"]]
        if node not in NODE_MAP:
            new_lines.append(line)
            continue

        snap = _best_snapshot_for_node(snapshots, node)

        # 竞价节点额外用 auction_snapshot
        if node == "竞价" and auction:
            snap = snap or {}
            snap["总竞价涨幅"] = auction.get("涨跌家数", {}).get("涨跌比")

        if snap is None:
            new_lines.append(line)
            continue

        # 填各列
        fill_map = {
            "情绪": str(snap.get("情绪值", "")) if snap.get("情绪值") is not None else "",
            "上证": f"{snap.get('上证涨幅', '')}%({snap.get('上证指数', '')})" if snap.get("上证指数") else "",
            "涨跌停": f"{snap.get('涨停家数', '')}/{snap.get('跌停家数', '')}" if snap.get("涨停家数") is not None else "",
            "量能": snap.get("成交额", ""),
            "涨跌比": f"{snap.get('上涨家数', '')}/{snap.get('下跌家数', '')}" if snap.get("上涨家数") is not None else "",
        }

        for col_name, col_pos in col_index.items():
            if col_name in ("节点", "关键异动", "总竞价涨幅"):
                continue
            if col_pos >= len(cells):
                continue
            current = cells[col_pos]
            if _is_placeholder(current) and col_name in fill_map:
                new_val = fill_map[col_name]
                if new_val:
                    cells[col_pos] = str(new_val)

        new_line = "| " + " | ".join(cells) + " |"
        new_lines.append(new_line)

    # 替换回原内容
    new_t1 = "\n".join(new_lines)
    return content[:t1_start] + new_t1 + content[t1_end:]


# ═══════════════════════════════════════════════════════════════
# 表2 情绪高标填充
# ═══════════════════════════════════════════════════════════════

def _fill_table2(content, snapshots, auction=None):
    """填充表2：情绪高标

    表2 结构：每行一个指标，每列一个时间节点。
    | 指标 | 竞价 | 早盘 | 午盘 | 收盘 | 门槛 |
    """
    t2_start = content.find("### 表2")
    if t2_start < 0:
        return content
    t2_end = content.find("\n###", t2_start + 8)
    if t2_end < 0:
        t2_end = content.find("\n---", t2_start + 8)
    if t2_end < 0:
        t2_end = len(content)
    t2_section = content[t2_start:t2_end]

    # 指标名映射到快照字段
    indicator_map = {
        "竞价强势家数": "竞价强势家数",
        "涨停收益": "涨停收益",
        "连板收益": "连板收益",
        "炸板收益": "炸板收益",
        "封板率": "封板率",
        "炸板率": "炸板率",
        "整体晋级率": "晋级率",
        "赚钱效应": "赚钱效应",
        "梯队": "梯队",
    }

    # 门槛值（用于自动判定 ✅/❌）
    thresholds = {
        "涨停收益": (2, ">2%"),
        "竞价强势家数": (10, ">10"),
        "封板率": (50, ">50%"),
    }

    lines = t2_section.split("\n")
    header = None
    time_cols = []  # [(col_index, node_name), ...]
    new_lines = []
    for i, line in enumerate(lines):
        if not line.startswith("|") or "---" in line:
            new_lines.append(line)
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if header is None:
            header = cells
            for j, h in enumerate(header):
                if j == 0:
                    continue
                for node_key in ["竞价", "早盘", "午盘", "尾盘", "收盘"]:
                    if node_key in h:
                        time_cols.append((j, node_key))
                        break
            new_lines.append(line)
            continue

        if not cells:
            new_lines.append(line)
            continue

        indicator_raw = cells[0]
        # 找匹配的指标
        mapped_key = None
        for ik, snap_key in indicator_map.items():
            if ik in indicator_raw:
                mapped_key = snap_key
                break
        if not mapped_key:
            # 特殊: 最高板/次高板
            if "最高板" in indicator_raw and "次高板" not in indicator_raw:
                mapped_key = "最高板"
            else:
                new_lines.append(line)
                continue

        # 填各时间列
        for col_pos, node_name in time_cols:
            if col_pos >= len(cells):
                continue
            current = cells[col_pos]
            if not _is_placeholder(current):
                continue

            snap = _best_snapshot_for_node(snapshots, node_name)
            if snap is None:
                continue

            val = snap.get(mapped_key)
            if val is None:
                continue

            # 格式化
            if isinstance(val, float):
                if mapped_key in ("封板率", "炸板率", "晋级率"):
                    val_str = f"{val * 100 if val <= 1 else val:.1f}%"
                else:
                    val_str = f"{val:.2f}"
            else:
                val_str = str(val)

            # 阈值判定
            if mapped_key in thresholds:
                th, desc = thresholds[mapped_key]
                try:
                    fv = float(val) if not isinstance(val, (int, float)) else val
                    if fv >= th:
                        val_str += "✅"
                    else:
                        val_str += "❌"
                except (ValueError, TypeError):
                    pass

            cells[col_pos] = val_str

        new_line = "| " + " | ".join(cells) + " |"
        new_lines.append(new_line)

    new_t2 = "\n".join(new_lines)
    return content[:t2_start] + new_t2 + content[t2_end:]


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def fill_note(date_str=None, dry_run=False):
    """主函数：填充复盘笔记"""
    if date_str is None:
        date_str = _date.today().strftime("%Y-%m-%d")

    # 1. 找笔记
    note_path = find_note(date_str)
    if not note_path:
        print(f"[fill_review_note] No note found for {date_str}")
        return None
    print(f"[fill_review_note] Note: {note_path}")

    # 2. 读管线数据
    snapshot = load_close_snapshot(date_str)
    snapshots = load_sentiment_auto(date_str)
    auction = load_auction_snapshot()
    pools = load_pools()
    pnl = load_pnl(date_str)

    has_snapshot = snapshot is not None
    has_snapshots = len(snapshots) > 0
    print(f"[fill_review_note] Data: close_snapshot={'✅' if has_snapshot else '❌'}"
          f"  sentiment_auto={'✅' if has_snapshots else '❌'} ({len(snapshots)} snapshots)"
          f"  auction={'✅' if auction else '❌'}"
          f"  pools={'✅' if pools else '❌'}"
          f"  pnl={'✅' if pnl else '❌'}")

    # 3. 读现有笔记
    with open(note_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 4. 填充 frontmatter
    fm_map = _get_fm(snapshot, pools, auction)
    content = _fill_frontmatter(content, fm_map)

    # 5. 填充表1/表2（需要 30min 快照）
    if has_snapshots:
        content = _fill_table1(content, snapshots, auction)
        content = _fill_table2(content, snapshots, auction)

    # 6. 写回
    if dry_run:
        print(f"\n[fill_review_note] DRY RUN — would write to {note_path}")
        print(content[:2000])
    else:
        tmp = Path(note_path).with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, note_path)
        print(f"[fill_review_note] Written → {note_path}")

    return note_path


def _fill_frontmatter(content, fm_map):
    """填充 YAML frontmatter 中的字段

    只替换占位符值，不动已有数据。
    """
    m = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if not m:
        return content

    fm_text = m.group(1)
    original_fm = fm_text
    new_lines = []

    for line in fm_text.split("\n"):
        kv = re.match(r'^([\w一-鿿]+):\s*(.*)', line)
        if not kv:
            new_lines.append(line)
            continue

        key, raw_val = kv.group(1), kv.group(2).strip().strip('"').strip("'")

        # 跳过人写字段
        if key in ("date", "type", "subtype", "weekday", "盘后持仓", "连板股"):
            new_lines.append(line)
            continue

        # 检查是否有管线数据
        if key in fm_map:
            entry = fm_map[key]
            if isinstance(entry, tuple) and len(entry) == 2:
                fm_val, source = entry
            else:
                fm_val, source = entry, "unknown"
            if fm_val is not None and _is_placeholder(raw_val):
                # 替换
                val_str = str(fm_val)
                if " " in val_str or ":" in val_str:
                    val_str = f'"{val_str}"'
                new_lines.append(f"{key}: {val_str}")
                continue

        new_lines.append(line)

    new_fm = "\n".join(new_lines)
    return content.replace(original_fm, new_fm, 1)


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="管线数据 → 复盘笔记自动填充")
    parser.add_argument("--date", help="日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不写入")
    args = parser.parse_args()

    fill_note(args.date, dry_run=args.dry_run)
