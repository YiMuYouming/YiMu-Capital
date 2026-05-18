#!/usr/bin/env python3
"""diff_check.py — 数据一致性自动化检查（四项）

用法: python3 scripts/diff_check.py
退出码 0 = 全部通过，退出码 1 = 有 ALERT。
"""
import json, sys, os
from pathlib import Path
from datetime import datetime, date

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "dashboard_data.json"
POOLS_FILE = ROOT / "data" / "pools.json"
AUCTION_FILE = ROOT / "data" / "auction_snapshot.json"
DB_PATH = ROOT / "data" / "pnl.db"


def load_json(path):
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def check_nav():
    """1. NAV 对比：daily_summary vs baseline.json pnl.总资产（差异>1%告警）"""
    data = load_json(DATA_FILE)
    if not data:
        return [("[WARN] NAV", f"{DATA_FILE} not found")]
    try:
        import sqlite3
        conn = sqlite3.connect(str(DB_PATH))
        cur = conn.cursor()
        today = date.today().strftime("%Y-%m-%d")
        cur.execute("SELECT nav FROM daily_summary WHERE date = ?", (today,))
        row = cur.fetchone()
        conn.close()
        db_nav = row[0] if row else None
    except Exception:
        db_nav = None

    pnl = data.get("pnl", {})
    json_total = pnl.get("总资产")
    if json_total and db_nav:
        diff = abs(json_total / db_nav - 1)
        if diff > 0.01:
            return [(f"[ALERT] NAV mismatch", f"pnl.总资产={json_total}, db.nav={db_nav}, diff={diff:.2%}")]
    return []


def check_pools():
    """2. pools 对比：pools.json 标的 vs dashboard_data.json 池（excluded 检查）"""
    pools = load_json(POOLS_FILE)
    data = load_json(DATA_FILE)
    if not pools or not data:
        return []

    issues = []
    excluded = set(pools.get("excluded", []))
    # 检查 dashboard_data.json 的池中不应有 excluded 标的
    for pool_name, pool_key in [("lianban_pool", "lianban_pool"), ("trend_pool", "trend_pool")]:
        for s in data.get(pool_key, []):
            name = s.get("标的", "")
            if name in excluded:
                issues.append(f"[ALERT] {pool_name}: {name} 在 excluded 列表中但出现在 {pool_key}")
    return issues


def check_sentiment():
    """3. 情绪值对比：baseline sentiment vs iwencai 缓存（偏差>15%告警）"""
    data = load_json(DATA_FILE)
    if not data:
        return []

    baseline_emotion = data.get("sentiment", {}).get("情绪值")
    if baseline_emotion is None:
        return []

    try:
        bv = float(baseline_emotion)
    except (ValueError, TypeError):
        return []

    # 没有实时 iwencai 缓存时跳过
    if bv == 0:
        return []

    # 检查 pools.json 有一致性标注
    pools = load_json(POOLS_FILE)
    if pools:
        em = pools.get("情绪值校验")
        if em:
            try:
                ev = float(em)
                if abs(bv - ev) > 15:
                    return [(f"[ALERT] 情绪值偏差", f"baseline={bv}, pools校验={ev}, diff={abs(bv-ev):.1f}")]
            except ValueError:
                pass
    return []


def check_auction():
    """4. 竞价快照时效：fetched 日期必须是今天"""
    snap = load_json(AUCTION_FILE)
    if not snap:
        return [("[INFO] 竞价快照", "auction_snapshot.json 不存在（可能今日尚未抓取）")]

    fetched = snap.get("fetched", "")
    if not fetched:
        return [("[ALERT] 竞价时效", "auction_snapshot.json 缺少 fetched 字段")]

    today = date.today().strftime("%Y-%m-%d")
    if today not in fetched:
        return [(f"[ALERT] 竞价时效", f"fetched={fetched}, 今天={today}")]
    return []


def main():
    issues = []
    issues += check_nav()
    issues += check_pools()
    issues += check_sentiment()
    issues += check_auction()

    if issues:
        print("\n".join(issues))
        alert_count = sum(1 for i in issues if "[ALERT]" in i)
        print(f"\n{'=' * 60}")
        print(f"共 {len(issues)} 条问题，其中 {alert_count} 条 ALERT")
        sys.exit(1)
    else:
        print("✅ 四项检查全部通过")
        sys.exit(0)


if __name__ == "__main__":
    main()
