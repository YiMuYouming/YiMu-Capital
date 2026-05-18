#!/usr/bin/env python3
"""llm_fill.py — LLM 自动填写复盘笔记（按节点触发）

用法:
  python3 scripts/llm_fill.py 竞价    # 填竞价段
  python3 scripts/llm_fill.py 早盘    # 填早盘段
  python3 scripts/llm_fill.py 午盘    # 填午盘段
  python3 scripts/llm_fill.py 尾盘    # 填尾盘段
  python3 scripts/llm_fill.py 收盘    # 填收盘段 + frontmatter

设计:
  从 bridge CACHE 读全盘数据 → 构建精简快照 → 读当前笔记
  → DeepSeek 理解上下文后填入数据+定性 → 不覆盖人写内容
"""

import json, os, sys, re, urllib.request
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
NOTE_DIR = Path.home() / "Documents/YouMingVault/10_⚡Now/01_💰弈沐资本/复盘笔记"

SYSTEM_PROMPT = """你是弈沐复盘助手。你会收到：1) 当前时段 2) 全盘数据JSON 3) 当前复盘笔记Markdown。

你的任务——理解笔记结构后填入数据，并写一句定性判断。

填入规则（重要）：
- 找当前时段对应的行/列，只填空格子和"—"、"%"
- 不覆盖人已经写的内容（非空非模板值不碰）
- 数值保留2位小数或整数，带单位(%)
- 模板值包括: "—" "" "%" "待填" "待定" "待确认" "N/A" "..."

各时段具体任务：
- 竞价(9:25): 填frontmatter竞价情绪值、表1竞价行(情绪/上证/涨跌停/量能/涨跌比/总竞价涨幅)、表2竞价列(竞价强势家数/涨停收益/连板收益/炸板收益/封板率/炸板率/晋级率/最高板次高板/赚钱效应/竞价验证结论)、竞价节点说明(一句定性)
- 早盘(10:00): 填表1早盘行、表2早盘列(同上)、涨停家数/跌停家数、早盘节点说明
- 午盘(11:30): 填表1午盘行、表2午盘列、午盘节点说明
- 尾盘(14:45): 填表1尾盘行、表2尾盘列、尾盘节点说明
- 收盘(15:05): 填表1收盘行、表2收盘列、frontmatter全部管线字段(涨停家数/跌停家数/炸板率/封板率/晋级率/最高板/次高板/连板风险值/赚钱效应/昨日涨停收益/昨日连板收益/昨日炸板收益/情绪值/情绪区间/上证指数/上证涨幅/市场量能)、涨停结构表(从连板股列表生成)、连板股列表、收盘节点说明、一句话结论

数据来源映射：
- 涨停家数/跌停家数 → 数据里的"广度"字段
- 情绪值 → 上涨/(上涨+下跌)×100
- 情绪区间 → <20冰点 <40低迷 <60主升 <80强势 ≥80高潮
- 封板率/炸板率/晋级率/最高板/连板风险值 → 数据里的"情绪"字段
- 赚钱效应 → 涨停收益>2%好, <0差
- 昨日涨停收益/连板收益/炸板收益 → 数据里的"情绪"字段
- 竞价强势家数 → 数据里的"竞价"字段
- 总竞价涨幅 → 数据里的"竞价.涨跌比"
- 竞价验证结论 → 涨停收益<2%+情绪<40%→"A差+B差", 涨停收益>2%+情绪≥40%→"A好+B好"
- 涨停结构 → 从连板股列表按板块归类生成Markdown表格

定性判断风格：20-50字，结论优先，简洁直白。格式如"竞价三件套A*B*→结果。龙头*→影响。方向*。"

输出: 直接输出修改后的完整Markdown笔记。不输出任何解释、不输出代码块标记。"""


def _load_api_config():
    settings_path = Path.home() / ".claude" / "settings.json"
    if settings_path.exists():
        try:
            with open(settings_path) as f:
                s = json.load(f)
            env = s.get("env", {})
            return {
                "base_url": env.get("ANTHROPIC_BASE_URL", "").rstrip("/"),
                "token": env.get("ANTHROPIC_AUTH_TOKEN", ""),
                "model": env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL", "DeepSeek-V4-Flash"),
            }
        except Exception:
            pass
    return {}


def call_llm(prompt_text):
    cfg = _load_api_config()
    if not cfg.get("token"):
        return {"ok": False, "error": "API token not found"}
    url = cfg["base_url"] + "/v1/messages"
    body = json.dumps({
        "model": cfg["model"],
        "max_tokens": 4000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt_text}],
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        "x-api-key": cfg["token"],
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            result = json.loads(resp.read())
            content = result.get("content", [])
            text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
            return {"ok": True, "text": text}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def find_today_note():
    today = f"{datetime.now().year}_{datetime.now().month}_{datetime.now().day}"
    for md in sorted(NOTE_DIR.glob("**/*.md"), reverse=True):
        if today in str(md) and "ReviewNote" in str(md):
            return str(md)
    return None


def build_snapshot(node):
    """从 bridge CACHE 和磁盘文件构建精简数据包"""
    snap = {"时段": node, "时间": datetime.now().strftime("%H:%M:%S")}

    try:
        import urllib.request as _req
        live = json.loads(_req.urlopen("http://localhost:8088/api/live/quotes", timeout=5).read())
        iwen = json.loads(_req.urlopen("http://localhost:8088/api/live/iwencai", timeout=5).read())

        snap["指数"] = {
            "上证": live.get("live_index", {}).get("上证指数"),
            "上证涨幅": live.get("live_index", {}).get("上证指数涨幅"),
            "上涨家数": live.get("live_index", {}).get("上涨家数"),
            "下跌家数": live.get("live_index", {}).get("下跌家数"),
            "成交额": live.get("live_index", {}).get("成交额"),
        }
        snap["情绪"] = {k: v for k, v in iwen.items() if not k.startswith("_")}
        breadth = live.get("breadth", {})
        snap["广度"] = {k: v for k, v in breadth.items() if not k.startswith("_")}

        # 竞价专用
        if node == "竞价":
            auction_file = ROOT / "data" / "auction_snapshot.json"
            if auction_file.exists():
                with open(auction_file) as f:
                    auc = json.load(f)
                snap["竞价"] = {
                    "强势家数": auc.get("竞价强势家数"),
                    "涨跌比": str(auc.get("涨跌家数", {})),
                    "指数竞价": auc.get("指数竞价"),
                }
        # 收盘专用
        if node == "收盘":
            with open(ROOT / "data" / "pools.json") as f:
                pools = json.load(f)
            snap["连板股列表"] = pools.get("lianban_pool", [])
            snap["趋势股列表"] = pools.get("trend_pool", [])
    except Exception as e:
        snap["_error"] = str(e)[:200]

    return snap


def fill_note(node, note_path=None, dry_run=False):
    print(f"[llm_fill] 时段: {node}")
    note_path = note_path or find_today_note()
    if not note_path:
        print("[llm_fill] 找不到今天笔记")
        return

    with open(note_path) as f:
        original = f.read()

    snap = build_snapshot(node)
    prompt = f"当前时段: {node}\n\n全盘数据:\n{json.dumps(snap, ensure_ascii=False, indent=2)}\n\n当前笔记:\n{original}\n\n请填入{node}的数据和定性判断。"

    print(f"[llm_fill] 调用 DeepSeek...")
    result = call_llm(prompt)
    if not result.get("ok"):
        print(f"[llm_fill] LLM 调用失败: {result.get('error')}")
        return

    filled = result["text"]
    if not filled or len(filled) < 100:
        print(f"[llm_fill] LLM 返回异常 (长度 {len(filled)})")
        return

    if dry_run:
        print(f"[llm_fill] DRY RUN - 预览:\n{filled[:500]}...")
        return

    # 备份原笔记
    bak = note_path + f".bak_{datetime.now().strftime('%H%M')}"
    with open(bak, 'w') as f:
        f.write(original)
    print(f"[llm_fill] 备份: {os.path.basename(bak)}")

    with open(note_path, 'w') as f:
        f.write(filled)
    print(f"[llm_fill] 写入: {note_path} ({len(filled)} 字)")


if __name__ == "__main__":
    node = sys.argv[1] if len(sys.argv) > 1 else "早盘"
    dry = "--dry-run" in sys.argv
    fill_note(node, dry_run=dry)
