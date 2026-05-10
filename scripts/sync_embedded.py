#!/usr/bin/env python3
"""sync_embedded.py — dashboard_data.json → embedded-data.js (Layer 0 兜底同步)
稳米维护 | v2.0 Phase 1.11

每次复盘生成 dashboard_data.json 后运行此脚本，自动同步兜底数据。
用法: python3 scripts/sync_embedded.py
"""

import json, os, sys
from datetime import datetime
from pathlib import Path

VAULT_DIR = Path(__file__).resolve().parent.parent
SOURCE = VAULT_DIR / "live-dashboard/data/dashboard_data.json"
TARGET = VAULT_DIR / "live-dashboard/data/embedded-data.js"

def main():
    if not SOURCE.exists():
        print(f"[ERROR] Source not found: {SOURCE}")
        print("[info] Run gen_dashboard_data.py first.")
        sys.exit(1)

    with open(SOURCE) as f:
        data = json.load(f)

    # 标记为兜底快照
    data["meta"]["stale"] = True
    data["meta"]["source"] = "sync_embedded.py"
    data["meta"]["updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")

    js_content = "// embedded-data.js — Layer 0 兜底数据\n"
    js_content += "// 由 sync_embedded.py 每日复盘后自动从 dashboard_data.json 同步\n"
    js_content += f"// 最后同步: {data['meta']['date']}\n"
    js_content += f"const EMBEDDED_DATA = {json.dumps(data, ensure_ascii=False)};"

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with open(TARGET, 'w', encoding='utf-8') as f:
        f.write(js_content)

    size = len(json.dumps(data, ensure_ascii=False))
    print(f"[done] Synced {size} bytes → {TARGET}")

if __name__ == "__main__":
    main()
