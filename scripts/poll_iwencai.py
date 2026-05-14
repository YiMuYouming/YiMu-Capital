#!/usr/bin/env python3
"""poll_iwencai.py — iwencai 盘后复盘查询工具
v2.1: 盘中实时数据已迁移到 poll_live.py（PyTDX + 东方财富）。
       本脚本仅用于盘后按需查询：热榜、龙虎榜、连板生态等 iwencai 独占数据。

用法:
  python3 poll_iwencai.py --review       # 盘后复盘查询（热榜+龙虎榜+连板生态）
  python3 poll_iwencai.py --review --save # 查询并保存到 data/iwencai_review.json
  python3 poll_iwencai.py --tier index   # 单查大盘（手工调试用）
  python3 poll_iwencai.py --tier quotes  # 单查个股（手工调试用）
"""

import json, os, sys, time, re
from datetime import datetime
from pathlib import Path

# 统一走 ym_stock_data
sys.path.insert(0, "/Users/YouMing/Documents/YM_Capital/ym-stock-data")
from ym_stock_data.sources.iwencai import query as _iwencai_query

ROOT_DIR = Path(__file__).resolve().parent.parent  # live-dashboard/
OUTPUT_FILE = ROOT_DIR / "data/dashboard_live.json"
DASHBOARD_DATA = ROOT_DIR / "data/dashboard_data.json"

# 频率配置 (v2.0)
TIER_INTERVALS = {
    "index": 30,
    "quotes": 15,
    "sectors": 60,
    "all": 30,  # 综合模式取最小值
}

def run_iwencai(q, extra_args=None):
    """调用 ym_stock_data 问财查询，返回 datas 列表"""
    try:
        raw = _iwencai_query(q)
        if "error" in raw:
            print(f"[warn] iwencai: {raw['error']}", file=sys.stderr)
            return None
        return raw.get("datas", [])
    except Exception as e:
        print(f"[warn] iwencai error: {e}", file=sys.stderr)
        return None

def fetch_live_index():
    """Q1: 大盘指数实时数据"""
    result = run_iwencai("上证指数 深证指数 创业板指 成交额 涨跌幅")
    if not result:
        return {}
    # 解析 iwencai 返回的表格数据
    # 简单实现：返回上一次缓存的数据（iwencai 输出解析较复杂）
    return {"note": "live_index from iwencai Q1", "last_fetch": time.strftime("%H:%M:%S")}

def fetch_live_quotes(stock_codes):
    """Q4: 批量个股报价"""
    if not stock_codes:
        return {}
    codes_str = ",".join(stock_codes[:20])  # 限制批量查询大小
    result = run_iwencai(codes_str, extra_args=["--fields", "涨跌幅,量比,换手,最新价"])
    if not result:
        return {}
    return {"note": "live_quotes from iwencai Q4", "last_fetch": time.strftime("%H:%M:%S"), "codes": stock_codes[:20]}

def fetch_live_sectors():
    """板块实时涨跌幅"""
    result = run_iwencai("板块涨幅 主力净流入", extra_args=["--fields", "涨跌幅,主力净流入"])
    if not result:
        return {}
    return {"note": "live_sectors from iwencai", "last_fetch": time.strftime("%H:%M:%S")}

def get_stock_codes_from_dashboard():
    """从 dashboard_data.json 提取所有涉及股票的代码（全量SSOT）"""
    codes = set()
    try:
        with open(DASHBOARD_DATA) as f:
            data = json.load(f)

        # 持仓（活跃 + 清仓）
        for p in data.get("positions", []):
            code = p.get("代码")
            if code and str(code).isdigit():
                codes.add(str(code))

        # 连板自选池
        for s in data.get("lianban_pool", []):
            code = s.get("代码")
            if code and str(code).isdigit():
                codes.add(str(code))

        # 趋势自选池
        for s in data.get("trend_pool", []):
            code = s.get("代码")
            if code and str(code).isdigit():
                codes.add(str(code))

        # 锚定股状态
        for a in (data.get("decision", {}).get("锚定股状态") or []):
            code = a.get("代码")
            if code and str(code).isdigit():
                codes.add(str(code))

        # 今日操作
        for o in (data.get("decision", {}).get("今日操作") or []):
            code = o.get("代码")
            if code and str(code).isdigit():
                codes.add(str(code))

        # 竞价5维-高标竞价和锚定股竞价（名字匹配到pool里的代码）
        auction = data.get("decision", {}).get("竞价", {})
        for item in (auction.get("高标竞价") or []) + (auction.get("锚定股竞价") or []):
            name = item.get("名称", "")
            # 尝试从 pool 中匹配
            for pool in [data.get("lianban_pool", []), data.get("trend_pool", [])]:
                for s in pool:
                    if s.get("标的") and s["标的"] in name:
                        code = s.get("代码")
                        if code and str(code).isdigit():
                            codes.add(str(code))

    except Exception as e:
        print(f"[warn] get_stock_codes: {e}", file=sys.stderr)

    codes = sorted(codes)
    print(f"[info] Found {len(codes)} stock codes: {', '.join(codes[:10])}{'...' if len(codes)>10 else ''}")
    return codes

def build_live_data(tier="all"):
    """组装 live 数据"""
    data = {}

    if tier in ("index", "all"):
        data["live_index"] = fetch_live_index()
    if tier in ("sectors", "all"):
        data["live_sectors"] = fetch_live_sectors()
    if tier in ("quotes", "all"):
        codes = get_stock_codes_from_dashboard()
        data["live_quotes"] = fetch_live_quotes(codes)

    data["meta"] = {
        "fetched": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "tier": tier
    }
    return data

def watch_mode(tier="all"):
    """守护模式：循环轮询写入文件"""
    interval = TIER_INTERVALS.get(tier, 30)
    print(f"[watch] Polling every {interval}s, tier={tier}, output={OUTPUT_FILE}")
    print("[watch] Press Ctrl+C to stop")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    try:
        while True:
            data = build_live_data(tier)
            with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"  [{time.strftime('%H:%M:%S')}] Updated dashboard_live.json")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[done] Polling stopped.")

def review_mode(save=False):
    """盘后复盘查询：热榜、龙虎榜、连板生态"""
    print("[poll_iwencai] 盘后复盘查询...", file=sys.stderr)
    queries = {
        "热榜": "今日热榜 人气排行",
        "龙虎榜": "今日龙虎榜 净买入",
        "连板生态": "连板股票 晋级率 最高板 涨停家数",
    }
    results = {}
    for name, query in queries.items():
        result = run_iwencai(query)
        results[name] = result[:500] if result else "查询失败"
        print(f"  [{name}] {'OK' if result else 'FAIL'}", file=sys.stderr)

    if save:
        output = ROOT_DIR / "data/iwencai_review.json"
        with open(output, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"[poll_iwencai] 已保存到 {output}", file=sys.stderr)
    else:
        print(json.dumps(results, ensure_ascii=False, indent=2))


def _parse_iwencai_table(datas):
    """归一化字段名：去掉 [日期] 后缀 (如 涨跌幅[20260514] → 涨跌幅)"""
    if not datas:
        return []
    rows = []
    for item in datas:
        row = {}
        for k, v in item.items():
            clean_key = re.sub(r'\[.*\]', '', k).strip()
            row[clean_key] = v
        rows.append(row)
    return rows


# ========== 竞价研判规则（来自 trading-core.md §竞价高潮保护）==========

def _judge_auction(auction, base):
    """根据规则自动填充结论、灯号、高潮保护、动作"""

    # 1. 竞价情绪值
    sentiment_val = 0
    for s in auction.get("市场情绪", []):
        if "竞价情绪" in s.get("名称", ""):
            try:
                sentiment_val = int(s["值"].replace("%", ""))
            except ValueError:
                pass

    # 2. 高潮保护判定
    if sentiment_val >= 90:
        climax = "⚠️ 极端高潮(≥90%) — 全天只卖不买，连板+趋势全关"
        climax_light = "red"
        w1_action = "全关"
        w2_action = "全关"
    elif sentiment_val >= 85:
        climax = "⚠️ 高潮(85-90%) — 连板全关，趋势降半仓"
        climax_light = "red"
        w1_action = "全关"
        w2_action = "降半仓"
    elif sentiment_val >= 80:
        climax = "⚡ 接近沸点(80-85%) — 连板降半仓，趋势正常"
        climax_light = "orange"
        w1_action = "降半仓"
        w2_action = "正常"
    else:
        climax = f"未触发({sentiment_val}%<80%)"
        climax_light = "green"
        w1_action = "正常"
        w2_action = "正常"

    # 3. 方向确认：统计 green 灯的方向数
    dir_count = sum(1 for fx in auction.get("方向锚定", []) if fx.get("灯") == "green")

    # 4. 高标表现
    gaobiao_green = sum(1 for g in auction.get("高标竞价", []) if g.get("灯") == "green")
    gaobiao_red = sum(1 for g in auction.get("高标竞价", []) if g.get("灯") == "red")

    # 5. 结论
    if sentiment_val >= 85:
        conclusion = "⚠️ 偏空 — 高潮保护触发，新仓暂停"
        conclusion_light = "red"
    elif sentiment_val >= 60 and gaobiao_green >= 2 and dir_count >= 2:
        conclusion = "偏多 → 方向确认，可执行W1/W2"
        conclusion_light = "green"
    elif sentiment_val >= 40 and gaobiao_green >= 1:
        conclusion = "中性偏多 → 精选方向，控制仓位"
        conclusion_light = "green"
    elif sentiment_val >= 20:
        conclusion = "偏空 → 等待方向确认"
        conclusion_light = "orange"
    else:
        conclusion = "⚠️ 冰点 — 等待V反信号，暂不开仓"
        conclusion_light = "red"

    # 6. 动作建议
    w1_open = climax_light != "red" and w1_action != "全关"
    w2_open = climax_light == "green" or w2_action == "正常"
    if w1_open and w2_open:
        action = f"连板W1({w1_action}) + 趋势W2({w2_action})"
    elif w1_open:
        action = f"仅趋势W2({w2_action})，连板W1关闭"
    elif w2_open:
        action = f"仅连板W1({w1_action})，趋势W2降仓"
    else:
        action = "全天只卖不买，等待次日修复"

    # 7. 写回
    auction["结论"] = conclusion
    auction["灯"] = conclusion_light
    auction["高潮保护"] = climax
    auction["动作"] = action

    # 8. 细化灯号
    _refine_lights(auction, sentiment_val)
    return auction


def _refine_lights(auction, sentiment_val):
    """细化各子项的灯号"""
    # 情绪灯号
    for s in auction.get("市场情绪", []):
        if s.get("灯") == "green" and sentiment_val < 50:
            s["灯"] = "orange"

    # 方向锚定灯号：结合板块竞价数据
    # 如果板块 live_sectors 有数据，用实时涨跌判定
    for fx in auction.get("方向锚定", []):
        if fx.get("灯") == "green":
            continue  # 保持
        # 没有额外信息的保持原灯号


def auction_mode():
    """竞价快照：9:26 运行一次，从 iwencai 拉竞价数据更新 Layer 1"""
    print("[poll_iwencai] 竞价快照查询...", file=sys.stderr)

    try:
        with open(DASHBOARD_DATA) as f:
            base = json.load(f)
    except Exception:
        print("[poll_iwencai] 无法读取 dashboard_data.json", file=sys.stderr)
        return

    # Q1: 大盘竞价 — 三大指数竞价涨幅+涨跌家数
    idx_result = run_iwencai("上证指数 深证成指 创业板指 竞价涨幅 上涨家数 下跌家数")
    idx_rows = _parse_iwencai_table(idx_result)

    auction = {
        "结论": "⏳ 待判定（9:26 iwencai 快照）",
        "灯": "green",
        "高潮保护": "待判定",
        "动作": "待判定",
        "大盘指数": [],
        "市场情绪": [],
        "高标竞价": [],
        "方向锚定": [],
        "锚定股竞价": [],
    }

    # 解析指数数据
    idx_name_map = {"上证指数": "上证", "深证成指": "深证", "创业板指": "创业"}
    up_total = 0
    dn_total = 0
    for row in idx_rows:
        short = idx_name_map.get(row.get("指数简称", ""))
        if not short:
            continue
        up_n = int(float(row.get("上涨家数", 0))) if row.get("上涨家数") else 0
        dn_n = int(float(row.get("下跌家数", 0))) if row.get("下跌家数") else 0
        up_total += up_n
        dn_total += dn_n
        auc_pct = row.get("竞价涨幅", "—")
        try:
            auc_val = float(auc_pct)
            auc_pct = f"{auc_val:+.2f}%"
        except ValueError:
            pass
        auction["大盘指数"].append({
            "指数": short,
            "竞价涨幅": auc_pct,
            "涨家": up_n,
            "跌家": dn_n,
            "灯": "green" if up_n > dn_n else "orange",
        })

    # 竞价情绪 = 涨家/(涨+跌)*100
    if up_total + dn_total > 0:
        sentiment_val = round(up_total / (up_total + dn_total) * 100)
        sentiment_light = "green" if sentiment_val >= 60 else ("orange" if sentiment_val >= 40 else "red")
    else:
        sentiment_val = 0
        sentiment_light = "orange"
    auction["市场情绪"] = [{"名称": "竞价情绪", "值": f"{sentiment_val}%", "灯": sentiment_light}]

    # Q2: 收集所有需要查竞价的标的
    gaobiao_names = [s["标的"] for s in base.get("lianban_pool", []) if "高度板" in str(s.get("角色", ""))]
    maoding_names = [a["标的"] for a in base.get("decision", {}).get("锚定股状态", [])]
    # 趋势锚定股：trend_pool 中角色=主趋势股的
    trend_anchor_names = [s["标的"] for s in base.get("trend_pool", []) if "主趋势" in str(s.get("角色", ""))]
    all_auction_stocks = list(dict.fromkeys(gaobiao_names + maoding_names + trend_anchor_names))

    stock_rows_all = []
    if all_auction_stocks:
        stock_query = " ".join(all_auction_stocks[:15]) + " 竞价涨幅"
        stock_result = run_iwencai(stock_query)
        stock_rows_all = _parse_iwencai_table(stock_result)

        gaobiao_set = set(gaobiao_names)
        for row in stock_rows_all:
            name = row.get("股票简称", "")
            pct_str = row.get("竞价涨幅", "")
            try:
                pct = float(pct_str)
                pct_str = f"{pct:+.2f}%"
                light = "green" if pct >= 3 else ("orange" if pct >= 0 else "red")
            except ValueError:
                light = "orange"

            entry_gaobiao = {"名称": name, "竞价": pct_str, "灯": light}
            entry_maoding = {"标的": name, "竞价": pct_str, "灯": light}
            if name in gaobiao_set:
                auction["高标竞价"].append(entry_gaobiao)
            if name in maoding_names or name in trend_anchor_names:
                auction["锚定股竞价"].append(entry_maoding)

    # Q3: 补充市场情绪字段
    # 强势家数(>=7%): 竞价涨幅>=7的个数
    strong_count = sum(1 for row in stock_rows_all if float(row.get("竞价涨幅", 0) or 0) >= 7)
    if strong_count > 0:
        auction["市场情绪"].append({"名称": "强势家数(>=7%)", "值": f"{strong_count}只", "灯": "green" if strong_count >= 10 else "orange"})

    # 昨日涨停竞价收益: 查昨日涨停股今日竞价表现
    zt_result = run_iwencai("昨日涨停股 今日竞价涨幅")
    zt_rows = _parse_iwencai_table(zt_result)
    if zt_rows:
        zt_pcts = []
        for row in zt_rows:
            try:
                zt_pcts.append(float(row.get("竞价涨幅", 0) or 0))
            except ValueError:
                pass
        if zt_pcts:
            avg_zt_pct = round(sum(zt_pcts) / len(zt_pcts), 2)
            auction["市场情绪"].append({
                "名称": "昨日涨停竞价收益",
                "值": f"{avg_zt_pct:+.2f}%",
                "灯": "green" if avg_zt_pct > 2 else ("orange" if avg_zt_pct > 0 else "red"),
            })

    # 竞价量比（取高标+锚定的均值）
    vb_vals = []
    for row in stock_rows_all:
        try:
            vb = float(row.get("竞价量", 0) or 0)
            if vb > 0:
                vb_vals.append(vb)
        except ValueError:
            pass
    if vb_vals:
        avg_vb = round(sum(vb_vals) / len(vb_vals) / 10000, 0)  # 万股
        auction["市场情绪"].append({"名称": "竞价量能", "值": f"均{avg_vb:.0f}万股", "灯": "green" if avg_vb > 100 else "orange"})

    # Q4: 方向锚定 — 结合板块+实际竞价数据
    # 构建 标的→竞价涨幅 映射
    stock_pct_map = {}
    for row in stock_rows_all:
        n = row.get("股票简称", "")
        try:
            stock_pct_map[n] = float(row.get("竞价涨幅", 0) or 0)
        except ValueError:
            pass

    gaobiao_sectors = set()
    for s in base.get("lianban_pool", []):
        if s["标的"] in gaobiao_set:
            sector = s.get("板块", "")
            if sector and sector not in gaobiao_sectors:
                gaobiao_sectors.add(sector)
                # 找这个板块里所有 auction 股
                sector_stocks = []
                for s2 in base.get("lianban_pool", []):
                    if s2.get("板块") == sector and s2["标的"] in stock_pct_map:
                        sector_stocks.append(f"{s2['标的']}{stock_pct_map[s2['标的']]:+.1f}%")
                for s2 in base.get("trend_pool", []):
                    if s2.get("板块") == sector and s2["标的"] in stock_pct_map:
                        sector_stocks.append(f"{s2['标的']}{stock_pct_map[s2['标的']]:+.1f}%")
                dir_text = "/".join(sector_stocks[:3]) if sector_stocks else f"{s['标的']}竞价"
                # 灯号：板块内绿(≥3)多=green
                green_n = sum(1 for t in sector_stocks if t.endswith("+") or any(float(t.split("+")[-1].replace("%","")) >= 3 for _ in [1] if "+" in t))
                if not any(green_n for _ in [1]):
                    green_n = sum(1 for p in [stock_pct_map.get(s2["标的"], 0) for s2 in base.get("lianban_pool", []) + base.get("trend_pool", []) if s2.get("板块") == sector] if p >= 3)
                dir_light = "green" if green_n >= 1 else "orange"
                auction["方向锚定"].append({
                    "板块": sector,
                    "竞价": dir_text,
                    "灯": dir_light,
                })

    # 研判
    auction = _judge_auction(auction, base)

    # 同步 sentiment.竞价情绪值（W07 高潮保护读取此路径）
    for s in auction.get("市场情绪", []):
        if "竞价情绪" in s.get("名称", ""):
            try:
                base["sentiment"]["竞价情绪值"] = float(s["值"].replace("%", ""))
            except ValueError:
                pass

    # 回写 dashboard_data.json
    try:
        base["decision"]["竞价"] = auction
        base["meta"]["updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
        with open(DASHBOARD_DATA, "w", encoding="utf-8") as f:
            json.dump(base, f, ensure_ascii=False, indent=2)
        print(f"[poll_iwencai] ✅ 竞价数据已更新: {len(auction['大盘指数'])}指数 {len(auction['高标竞价'])}高标 {len(auction['锚定股竞价'])}锚定", file=sys.stderr)
    except Exception as e:
        print(f"[poll_iwencai] 写入失败: {e}", file=sys.stderr)
        print(json.dumps(auction, ensure_ascii=False, indent=2))


def main():
    import argparse
    parser = argparse.ArgumentParser(description="iwencai 盘后复盘查询工具")
    parser.add_argument("--auction", action="store_true", help="竞价快照：9:26跑一次，自动更新Layer 1竞价数据")
    parser.add_argument("--review", action="store_true", help="盘后复盘查询（热榜+龙虎榜+连板生态）")
    parser.add_argument("--save", action="store_true", help="保存到 data/iwencai_review.json")
    parser.add_argument("--tier", default="all", choices=["index","quotes","sectors","all"], help="数据层（手工调试用）")
    args = parser.parse_args()

    if args.auction:
        auction_mode()
    elif args.review:
        review_mode(save=args.save)
    else:
        data = build_live_data(args.tier)
        print(json.dumps(data, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
