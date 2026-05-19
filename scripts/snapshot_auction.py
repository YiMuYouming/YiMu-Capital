#!/usr/bin/env python3
"""snapshot_auction.py — 竞价5维快照 (9:25 跑一次)

从问财抓取竞价全景数据 → dashboard_live.json 的 auction 域
用法: python3 snapshot_auction.py [--output json]

数据源: 问财 OpenAPI (5-6次查询)
输出: 写入 data/dashboard_live.json 的 auction 字段
"""

import json, os, sys, time, re
from pathlib import Path
from datetime import datetime

# 统一走 ym_stock_data
sys.path.insert(0, "/Users/YouMing/Documents/YM_Capital/YM-data-pipeline")
from ym_stock_data.sources.iwencai import query as _iwencai_query

ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_FILE = ROOT_DIR / "data" / "auction_snapshot.json"
DASHBOARD_DATA = ROOT_DIR / "data" / "dashboard_data.json"


def q(query_str, limit=100):
    """调用 ym_stock_data 问财查询，返回原始 JSON"""
    try:
        return _iwencai_query(query_str, limit=limit)
    except Exception:
        return {}


def find_field(fields, keyword):
    """查找字段名包含关键字的"""
    for f in fields:
        if keyword in str(f):
            return f
    return None


def val(row, field, default=None):
    """安全取值"""
    if field and field in row:
        return row[field]
    return default


def get_pool_codes():
    """从 dashboard_data.json 提取自选池+锚定股代码列表"""
    codes = {}
    try:
        with open(DASHBOARD_DATA) as f:
            data = json.load(f)
        for pool_key in ["lianban_pool", "trend_pool"]:
            for s in data.get(pool_key, []):
                code = str(s.get("代码", ""))
                name = s.get("标的", "")
                if len(code) == 6:
                    codes[code] = {"name": name, "pool": "连板" if pool_key == "lianban_pool" else "趋势"}
        for a in data.get("decision", {}).get("锚定股状态", []):
            code = str(a.get("代码", ""))
            name = a.get("标的", "")
            if len(code) == 6 and code not in codes:
                codes[code] = {"name": name, "pool": "锚定"}
    except Exception:
        pass
    return codes


def fetch_index_auction():
    """三大指数竞价涨跌 + 涨跌家数"""
    result = {"指数": [], "涨跌家数": {}}

    # 三大指数
    r = q("竞价涨幅 上证指数 深证成指 创业板指", limit=5)
    for d in r.get("datas", []):
        name = d.get("指数简称", d.get("股票简称", ""))
        if not name:
            continue
        if "指" not in str(name):
            continue
        chg_field = find_field(d.keys(), "竞价涨幅")
        chg = val(d, chg_field, 0)
        price = d.get("最新价", 0)
        # 简称标准化
        short = str(name).replace("指数", "").replace("成指", "")
        result["指数"].append({
            "名称": short,
            "竞价涨幅": round(float(chg), 2) if chg else 0,
            "最新价": round(float(price), 2) if price else 0,
        })

    # 涨跌家数
    r = q("竞价上涨家数 竞价下跌家数", limit=5)
    for d in r.get("datas", []):
        up_field = find_field(d.keys(), "竞价上涨家数")
        dn_field = find_field(d.keys(), "竞价下跌家数")
        up = int(val(d, up_field, 0) or 0)
        dn = int(val(d, dn_field, 0) or 0)
        if up + dn > 0:
            result["涨跌家数"] = {"上涨": up, "下跌": dn, "涨跌比": round(up / max(dn, 1), 2)}

    return result


def fetch_strong_count():
    """竞价强势家数（高开≥7%）"""
    r = q("竞价涨幅大于7% 非st 非新股", limit=200)
    return len(r.get("datas", []))


def fetch_high_grade_auction():
    """连板高标竞价（连续涨停≥2）"""
    r = q("连续涨停天数>=2 竞价涨幅 竞价评级 竞价异动类型 竞价量 竞价未匹配量 非st 非新股", limit=30)
    stocks = []
    for d in r.get("datas", []):
        name = d.get("股票简称", "")
        code = d.get("股票代码", "").split(".")[0] if "." in str(d.get("股票代码", "")) else d.get("股票代码", "")
        board = int(val(d, find_field(d.keys(), "连续涨停天数"), 0) or 0)
        chg = val(d, find_field(d.keys(), "竞价涨幅"), 0)
        rating = d.get("竞价评级", d.get("竞价评级[2026", "")) or "—"
        # 处理嵌套的竞价评级
        if isinstance(rating, dict):
            rating = str(rating)
        anomaly = d.get("竞价异动类型", d.get("竞价异动类型[2026", "")) or ""
        if isinstance(anomaly, dict):
            anomaly = str(anomaly)
        vol_field = find_field(d.keys(), "竞价量")
        match_vol = int(val(d, vol_field, 0) or 0)

        stocks.append({
            "名称": str(name),
            "代码": str(code),
            "板数": board,
            "竞价涨幅": round(float(chg), 2) if chg else 0,
            "竞价评级": str(rating)[:10],
            "竞价量": match_vol,
            "异动": str(anomaly)[:20] if anomaly else "",
        })

    # 按板数降序
    stocks.sort(key=lambda x: -x["板数"])
    return stocks


def fetch_pool_auction(codes):
    """锚定股+自选池竞价（指定代码列表）"""
    if not codes:
        return []

    code_list = ",".join(list(codes.keys())[:20])
    r = q(f"竞价涨幅 竞价评级 竞价异动类型 竞价量 竞价未匹配量 股票代码:{code_list}", limit=50)

    stocks = []
    returned_codes = set()
    for d in r.get("datas", []):
        code = d.get("股票代码", "").split(".")[0] if "." in str(d.get("股票代码", "")) else d.get("股票代码", "")
        code = str(code)
        returned_codes.add(code)
        name = d.get("股票简称", "")
        chg = val(d, find_field(d.keys(), "竞价涨幅"), 0)
        rating = d.get("竞价评级", d.get("竞价评级[2026", "")) or "—"
        if isinstance(rating, dict):
            rating = "—"
        anomaly = d.get("竞价异动类型", d.get("竞价异动类型[2026", "")) or ""
        if isinstance(anomaly, dict):
            anomaly = ""
        vol_field = find_field(d.keys(), "竞价量")
        match_vol = int(val(d, vol_field, 0) or 0)

        info = codes.get(code, {})
        stocks.append({
            "名称": str(name),
            "代码": code,
            "来源": info.get("pool", ""),
            "竞价涨幅": round(float(chg), 2) if chg else 0,
            "竞价评级": str(rating)[:10],
            "竞价量": match_vol,
            "异动": str(anomaly)[:20] if anomaly else "",
        })

    # 补位：问财没返回的标的用兜底数据，至少展示出来
    for code, info in codes.items():
        if code not in returned_codes:
            stocks.append({
                "名称": info.get("name", code),
                "代码": code,
                "来源": info.get("pool", ""),
                "竞价涨幅": None,
                "竞价评级": "—",
                "竞价量": 0,
                "异动": "",
            })

    return stocks


def fetch_sector_auction():
    """方向锚定：板块竞价"""
    sectors = []
    try:
        with open(DASHBOARD_DATA) as f:
            data = json.load(f)
        sectors = [s["板块"] for s in data.get("sectors", []) if s.get("板块")]
    except Exception:
        pass

    if not sectors:
        return []

    result = []
    for sec in sectors[:6]:
        # 用板块名+竞价查询
        r = q(f"{sec} 板块指数 竞价涨幅 竞价评级", limit=5)
        for d in r.get("datas", []):
            name = d.get("板块名称", d.get("股票简称", ""))
            chg_field = find_field(d.keys(), "竞价涨幅")
            chg = val(d, chg_field, 0)
            if chg or name:
                result.append({
                    "板块": sec,
                    "竞价涨幅": round(float(chg), 2) if chg else 0,
                })
                break

    return result


def fetch_thx_sentiment():
    """从 bridge iwencai CACHE 获取竞价情绪数据"""
    return _fetch_from_iwencai_api()


def _fetch_from_iwencai_api():
    """从 bridge /api/live/iwencai 获取实时情绪数据"""
    try:
        import urllib.request
        url = "http://localhost:8088/api/live/iwencai"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
    except Exception:
        return {}

    if not data or not data.get("_updated"):
        return {}

    # 字段映射: iwencai CACHE → 竞价情绪指标
    result = {}
    field_map = {
        "情绪值": "情绪值",
        "昨日涨停收益": "昨日涨停收益",
        "连板收益": "昨日连板收益",
        "炸板收益": "昨日炸板收益",
        "连板风险值": "连板风险值",
        "赚钱效应": "赚钱效应",
        "最高板": "最高板",
    }
    for src_key, dst_key in field_map.items():
        val = data.get(src_key)
        if val is not None and val != "":
            result[dst_key] = str(val)

    return result


def build_auction_snapshot():
    """组装竞价5维完整快照"""
    now = datetime.now()
    snapshot = {
        "fetched": now.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "time": now.strftime("%H:%M:%S"),
    }

    # 1. 指数+涨跌家数
    idx = fetch_index_auction()
    snapshot["指数竞价"] = idx["指数"]
    snapshot["涨跌家数"] = idx["涨跌家数"]

    # 2. 强势家数
    snapshot["竞价强势家数"] = fetch_strong_count()

    # 3. 高标竞价
    snapshot["高标竞价"] = fetch_high_grade_auction()

    # 4. 自选池竞价
    codes = get_pool_codes()
    snapshot["自选池竞价"] = fetch_pool_auction(codes)

    # 5. 板块竞价
    snapshot["板块竞价"] = fetch_sector_auction()

    # 6. 竞价情绪指标（从 bridge iwencai CACHE）
    snapshot["情绪指标"] = fetch_thx_sentiment()

    # 7. 自动判定
    snapshot["信号灯"] = _auto_lights(snapshot)

    # 8. 高潮保护判定（从 poll_iwencai 合并）
    snapshot["高潮保护"] = _judge_auction(snapshot)

    return snapshot


def _auto_lights(snap):
    """根据数据自动判定灯色"""
    lights = {}

    # 涨跌比判定
    ud = snap.get("涨跌家数", {})
    ratio = ud.get("涨跌比", 1)
    if ratio > 1.5:
        lights["涨跌"] = {"灯": "green", "label": "普涨"}
    elif ratio > 1.0:
        lights["涨跌"] = {"灯": "green", "label": "偏涨"}
    elif ratio > 0.6:
        lights["涨跌"] = {"灯": "orange", "label": "分化"}
    elif ratio > 0.3:
        lights["涨跌"] = {"灯": "red", "label": "偏跌"}
    else:
        lights["涨跌"] = {"灯": "red", "label": "普跌"}

    # 强势家数判定
    strong = snap.get("竞价强势家数", 0)
    if strong > 30:
        lights["强势"] = {"灯": "red", "label": f"过热({strong}只)"}
    elif strong > 10:
        lights["强势"] = {"灯": "green", "label": f"正常({strong}只)"}
    else:
        lights["强势"] = {"灯": "orange", "label": f"偏少({strong}只)"}

    # 高标判定
    highs = snap.get("高标竞价", [])
    bull_count = sum(1 for h in highs if h.get("竞价涨幅", 0) > 3)
    bear_count = sum(1 for h in highs if h.get("竞价涨幅", 0) < -3)
    if bull_count >= 3 and bear_count <= 1:
        lights["高标"] = {"灯": "green", "label": f"{bull_count}只高开"}
    elif bear_count >= 3:
        lights["高标"] = {"灯": "red", "label": f"{bear_count}只低开"}
    else:
        lights["高标"] = {"灯": "orange", "label": "分化"}

    # 综合
    green_cnt = sum(1 for v in lights.values() if v["灯"] == "green")
    red_cnt = sum(1 for v in lights.values() if v["灯"] == "red")
    if red_cnt >= 2:
        lights["综合"] = {"灯": "red", "label": "🚨偏空"}
    elif green_cnt >= 2:
        lights["综合"] = {"灯": "green", "label": "偏多"}
    else:
        lights["综合"] = {"灯": "orange", "label": "分化"}

    return lights


def _judge_auction(snap):
    """高潮保护判定
    根据竞价情绪值判定保护级别：>=90 极端/>=85 高潮/>=80 接近沸点/<80 正常
    """
    sentiment_val = 0
    sentiment = snap.get("情绪指标", {})
    if isinstance(sentiment, dict):
        raw = sentiment.get("情绪值", "")
        try:
            sentiment_val = float(str(raw).replace("%", ""))
        except (ValueError, TypeError):
            pass

    if sentiment_val >= 90:
        level = "一级高潮保护"
        light = "red"
        action = "全天只卖不买，连板+趋势全关"
    elif sentiment_val >= 85:
        level = "二级高潮保护"
        light = "red"
        action = "连板全关，趋势降半仓"
    elif sentiment_val >= 80:
        level = "三级高潮保护"
        light = "orange"
        action = "连板降半仓，趋势正常"
    else:
        level = "正常"
        light = "green"
        action = "正常执行W1/W2"

    return {
        "级别": level,
        "灯": light,
        "竞价情绪值": sentiment_val,
        "动作": action
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="竞价5维快照")
    parser.add_argument("--output", choices=["json", "file"], default="file")
    args = parser.parse_args()

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 竞价快照抓取中...", file=sys.stderr)
    snap = build_auction_snapshot()

    if args.output == "json":
        print(json.dumps(snap, ensure_ascii=False, indent=2))
        return

    # 写入独立文件（不被 poll_live 覆盖）
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)

    # 简要输出
    lights = snap.get("信号灯", {})
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 竞价快照完成 → {OUTPUT_FILE}", file=sys.stderr)
    print(f"  指数: {len(snap.get('指数竞价',[]))}个", file=sys.stderr)
    print(f"  涨跌: {snap.get('涨跌家数',{})}", file=sys.stderr)
    print(f"  强势: {snap.get('竞价强势家数',0)}只", file=sys.stderr)
    print(f"  高标: {len(snap.get('高标竞价',[]))}只", file=sys.stderr)
    print(f"  自选: {len(snap.get('自选池竞价',[]))}只", file=sys.stderr)
    print(f"  综合: {lights.get('综合',{}).get('label','')}", file=sys.stderr)


if __name__ == "__main__":
    main()
