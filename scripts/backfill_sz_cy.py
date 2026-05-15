#!/usr/bin/env python3
"""一次性回填 daily_summary 中缺失的 sz_pct/cy_pct（历史数据补全）

用法: python3 scripts/backfill_sz_cy.py [--dry-run]
"""
import sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "pnl.db"

DRY_RUN = '--dry-run' in sys.argv


def main():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # 找 sz_pct=0 或 cy_pct=0 的 daily_summary 行
    rows = conn.execute("""
        SELECT date, sh_pct, sz_pct, cy_pct FROM daily_summary
        WHERE sz_pct = 0 OR cy_pct = 0
        ORDER BY date
    """).fetchall()

    print(f"找到 {len(rows)} 条需要补全的日频记录")

    updated = 0
    for r in rows:
        date = r['date']
        # 取当天最后一个 intraday 快照的 sz/cy 值
        snap = conn.execute("""
            SELECT sz_pct, cy_pct FROM intraday_snapshots
            WHERE date = ? ORDER BY ts DESC LIMIT 1
        """, (date,)).fetchone()

        if not snap:
            print(f"  {date}: 无 intraday 数据，跳过")
            continue

        new_sz = r['sz_pct'] if r['sz_pct'] != 0 else round(snap['sz_pct'], 4)
        new_cy = r['cy_pct'] if r['cy_pct'] != 0 else round(snap['cy_pct'], 4)

        if new_sz == r['sz_pct'] and new_cy == r['cy_pct']:
            continue  # 无需更新

        if DRY_RUN:
            print(f"  [DRY-RUN] {date}: sz {r['sz_pct']:.4f}→{new_sz:.4f}, cy {r['cy_pct']:.4f}→{new_cy:.4f}")
        else:
            conn.execute("UPDATE daily_summary SET sz_pct=?, cy_pct=? WHERE date=?",
                         (new_sz, new_cy, date))
            print(f"  {date}: sz {r['sz_pct']:.4f}→{new_sz:.4f}, cy {r['cy_pct']:.4f}→{new_cy:.4f}")
        updated += 1

    if not DRY_RUN:
        conn.commit()
        print(f"\n提交完成: 更新 {updated} 条记录")
    else:
        print(f"\n[DRY-RUN] 将更新 {updated} 条记录（未实际写入）")

    # 验证
    zero_left = conn.execute(
        "SELECT COUNT(*) AS n FROM daily_summary WHERE sz_pct = 0 OR cy_pct = 0"
    ).fetchone()['n']
    print(f"剩余 sz/cy=0 的记录: {zero_left}")

    conn.close()


if __name__ == '__main__':
    main()
