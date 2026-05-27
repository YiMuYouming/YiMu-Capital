#!/usr/bin/env python3
"""repair_day_start_price.py — 受控补录缺失的日初基准价（CLI 入口）

用法:
  # dry-run（默认，安全，只读连接）
  python3 scripts/repair_day_start_price.py \
    --date 2026-05-27 --code 002436 --price 38.11 \
    --source "eastmoney+sina daily close verified 2026-05-26" \
    --reason "manual_correction anchor missing overnight day_start_price"

  # 真实写入
  python3 scripts/repair_day_start_price.py ... --apply

安全设计:
  - dry-run 使用 sqlite3 URI mode=ro，不接触 db 模块，不创建 WAL/SHM
  - --apply 使用 sqlite3 online backup API 生成一致性备份
  - 备份后执行 PRAGMA integrity_check，失败则拒绝 apply
  - 不提供覆盖已有价格的默认能力
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _ro_connect(db_path):
    """以只读模式连接数据库（WAL-aware，不执行 init_db）。"""
    uri = f"file:{db_path}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _ro_query_anchor(db_path, date_str):
    """只读查询指定日期的 account_baselines 行。返回 dict 或 None。"""
    conn = _ro_connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT * FROM account_baselines WHERE date = ?",
            (date_str,))
        row = cur.fetchone()
        if not row:
            return None
        result = dict(row)
        result["positions"] = json.loads(result.pop("positions_json", "[]") or "[]")
        meta_raw = result.pop("_meta_json", None)
        if meta_raw:
            try:
                result["_meta"] = json.loads(meta_raw)
            except (json.JSONDecodeError, TypeError):
                pass
        return result
    finally:
        conn.close()


def _sqlite_backup(src_path, dst_path):
    """使用 sqlite3 online backup API 创建一致性备份（含已提交 WAL）。"""
    src = sqlite3.connect(str(src_path))
    dst = sqlite3.connect(str(dst_path))
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()


def _integrity_check(db_path):
    """对指定库执行 PRAGMA integrity_check，返回 (ok: bool, detail: str)。"""
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("PRAGMA integrity_check").fetchall()
        detail = "; ".join(r[0] for r in rows)
        return detail.strip().lower() == "ok", detail
    finally:
        conn.close()


def _apply_via_db_module(db_path, args):
    """通过 db 模块执行真实写入（仅在 backup+integrity 通过后调用）。"""
    from scripts import db as db_module
    import threading

    original_path = db_module.DB_PATH
    original_local = db_module._local

    try:
        db_module.DB_PATH = Path(db_path)
        db_module._local = threading.local()

        from scripts.db import query_account_baseline, _exec_write
        from scripts.account_ssot import backfill_day_start_price

        def get_anchor(d):
            return query_account_baseline(d)

        def update_meta(d, m):
            _exec_write(
                "UPDATE account_baselines SET _meta_json = ? WHERE date = ?",
                (json.dumps(m, ensure_ascii=False), d))

        result = backfill_day_start_price(
            date_str=args.date,
            code=args.code,
            price=args.price,
            source=args.source,
            reason=args.reason,
            dry_run=False,
            get_anchor=get_anchor,
            update_meta=update_meta,
        )
        return result
    finally:
        conn = getattr(db_module._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        db_module._local = original_local
        db_module.DB_PATH = original_path


def main():
    parser = argparse.ArgumentParser(
        description="受控补录缺失的日初基准价",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # dry-run（只读，安全）
  %(prog)s --date 2026-05-27 --code 002436 --price 38.11 \\
    --source "eastmoney+sina daily close verified 2026-05-26" \\
    --reason "anchor missing overnight day_start_price"

  # 真实写入
  %(prog)s ... --apply
        """,
    )
    parser.add_argument("--date", required=True, help="锚点日期 YYYY-MM-DD")
    parser.add_argument("--code", required=True, help="股票代码")
    parser.add_argument("--price", required=True, type=float, help="日初价 (>0)")
    parser.add_argument("--source", required=True, help="价格来源标识")
    parser.add_argument("--reason", required=True, help="修复原因")
    parser.add_argument("--apply", action="store_true",
                        default=False, help="显式授权写入（默认仅 dry-run）")
    parser.add_argument("--db", default=None,
                        help="数据库路径（默认: data/pnl.db）")
    args = parser.parse_args()

    if args.db:
        db_path = Path(args.db)
    else:
        db_path = ROOT / "data" / "pnl.db"

    if not db_path.exists():
        print(f"错误: 数据库不存在: {db_path}")
        sys.exit(1)

    if not args.apply:
        # —— dry-run：只读连接，不碰 db 模块 ——
        print("=" * 60)
        print("DRY-RUN 模式 — 只读连接，不会写入数据库")
        print("=" * 60)

        anchor = _ro_query_anchor(str(db_path), args.date)
        if anchor:
            print(f"锚点日期:    {args.date}")
            print(f"锚点来源:    {anchor.get('source', '?')}")
            print(f"锚点持仓数:  {len(anchor.get('positions') or [])}")
            existing_meta = anchor.get("_meta") or {}
            existing_prices = existing_meta.get("day_start_prices") or {}
            existing_repairs = existing_meta.get("day_start_price_repairs") or []
            print(f"已有 _meta:  {json.dumps(existing_meta, ensure_ascii=False) if existing_meta else '(空)'}")
            print(f"已有 day_start_prices: {existing_prices if existing_prices else '(空)'}")
            print(f"已有 repairs: {len(existing_repairs)} 条")
        else:
            print(f"锚点日期 {args.date} 无锚点记录")

        print(f"\n拟补录:")
        print(f"  代码:      {args.code}")
        print(f"  价格:      {args.price}")
        print(f"  来源:      {args.source}")
        print(f"  原因:      {args.reason}")

        # dry-run 走 backfill 全量校验（但 dry_run=True，不写入）
        from scripts.account_ssot import backfill_day_start_price as _bf

        result = _bf(
            date_str=args.date,
            code=args.code,
            price=args.price,
            source=args.source,
            reason=args.reason,
            dry_run=True,
            # dry-run 不提供 update_meta（被 dry_run 短路，不会调用）
            get_anchor=lambda d: _ro_query_anchor(str(db_path), d),
            update_meta=None,
        )

        print(f"\n结果: {json.dumps(result, ensure_ascii=False, indent=2)}")

        if result["action"] == "rejected":
            print(f"\n拒绝原因: {result.get('error', '?')}")
            sys.exit(1)
        elif result["action"] == "would_write":
            print("\nDRY-RUN 通过 — 加 --apply 执行真实写入")
        return

    # —— apply 路径 ——
    # 1. 备份
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = db_path.parent / f"{db_path.name}.bak.repair-{args.code}-{ts}"
    print(f"备份路径: {backup}")
    _sqlite_backup(str(db_path), str(backup))
    print(f"备份完成: {os.path.getsize(str(backup))} bytes")

    # 2. integrity_check on backup
    ok, detail = _integrity_check(str(backup))
    print(f"integrity_check: {detail}")
    if not ok:
        print(f"错误: 备份 integrity_check 失败，拒绝 apply")
        # 清理无效备份
        try:
            backup.unlink()
        except Exception:
            pass
        print(f"已删除无效备份: {backup}")
        sys.exit(1)

    # 3. 写入
    result = _apply_via_db_module(str(db_path), args)

    print(f"\n结果: {json.dumps(result, ensure_ascii=False, indent=2)}")

    if result["action"] == "written":
        print(f"\n写入成功 — 备份: {backup}")
        print("请重启 bridge 使 day_start_prices 生效")
    elif result["action"] == "rejected":
        print(f"\n拒绝: {result.get('error', '?')}")
        sys.exit(1)
    else:
        print(f"\n意外状态: {result.get('action')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
