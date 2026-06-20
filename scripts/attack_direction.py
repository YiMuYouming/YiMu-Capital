"""Build the early limit-up attack direction payload.

The dashboard needs a conclusion-first view, but the source data is still
best-effort: confirmed limit-up stocks may arrive without first seal time.
This module keeps that distinction explicit so the UI does not overstate the
opening 15-minute signal.
"""

from __future__ import annotations

import re
from datetime import datetime, time
from typing import Any, Dict, Iterable, List, Optional, Tuple


WINDOW_START = time(9, 30)
WINDOW_END = time(9, 45)

CONCEPT_MERGE = {
    "算力": "算力/半导体",
    "算力产业链": "算力/半导体",
    "半导体": "算力/半导体",
    "半导体产业链": "算力/半导体",
    "存储芯片": "算力/半导体",
    "芯片概念": "算力/半导体",
    "AI服务器": "算力/半导体",
    "电力": "电力",
    "绿色电力": "电力",
    "储能": "电力",
    "光通信": "光通信/CPO",
    "CPO": "光通信/CPO",
    "光模块": "光通信/CPO",
    "机器人": "机器人",
    "机器人概念": "机器人",
    "人形机器人": "机器人",
    "具身智能": "机器人",
    "PCB": "PCB链",
    "PCB链": "PCB链",
    "覆铜板": "PCB链",
    "航天": "航天/军工",
    "商业航天": "航天/军工",
    "军工": "航天/军工",
    "低空经济": "航天/军工",
    "特高压": "电力/中特估",
    "核电": "电力/中特估",
    "输变电": "电力/中特估",
    "锂电池": "锂电池",
    "锂电": "锂电池",
    "电池": "锂电池",
    "光伏": "光伏",
    "并购重组": "并购重组/股权",
    "股权转让": "并购重组/股权",
    "地产": "地产产业链",
    "房地产": "地产产业链",
    "大消费": "大消费",
    "医药": "医药",
    "液冷": "液冷",
    "有色金属": "有色/稀土",
    "稀土永磁": "有色/稀土",
    "钨": "有色/稀土",
    "建筑装饰": "建筑/装饰",
    "建筑": "建筑/装饰",
    "汽车零部件": "汽车零部件",
    "环保": "环保/水利",
    "水利": "环保/水利",
    "化工": "化工/新材料",
    "新材料": "化工/新材料",
    "AI应用": "AI应用",
    "AI": "AI应用",
}

CONCEPT_FILTER = (
    "央企",
    "国企",
    "国资",
    "复牌",
    "大单",
    "订单",
    "出口",
    "新股",
    "次新",
    "超跌",
    "拟收购",
    "机构",
    "询价",
    "一季报",
    "年报",
    "业绩增长",
    "连续涨停",
    "涨停",
    "更名",
    "重整预期",
    "流通盘小",
)


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_concept(raw: Any) -> str:
    clean = re.sub(r"[🆕⬇️🔄✅❌🔥★☆⭐]", "", _clean_text(raw)).strip()
    if not clean:
        return ""
    if clean in CONCEPT_MERGE:
        return CONCEPT_MERGE[clean]
    for key, merged in CONCEPT_MERGE.items():
        if key and key in clean:
            return merged
    return clean


def _is_valid_concept(tag: str) -> bool:
    if not tag:
        return False
    return not any(noise in tag for noise in CONCEPT_FILTER)


def _num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    match = re.search(r"[+-]?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group(0)) if match else None


def _stock_code(stock: Dict[str, Any]) -> str:
    return str(stock.get("code") or stock.get("代码") or "").zfill(6)[-6:]


def _stock_name(stock: Dict[str, Any]) -> str:
    return _clean_text(stock.get("name") or stock.get("名称") or stock.get("股票简称") or "—")


def _extract_seal_time(stock: Dict[str, Any]) -> Tuple[Optional[str], bool]:
    keys = (
        "seal_time",
        "first_limit_time",
        "limit_time",
        "firstSealTime",
        "封板时间",
        "首次封板时间",
        "首封时间",
        "涨停时间",
    )
    raw = next((stock.get(k) for k in keys if stock.get(k)), None)
    if not raw:
        return None, False
    text = str(raw).strip()
    match = re.search(r"(\d{1,2})[:：](\d{2})(?::\d{2})?", text)
    if not match:
        compact = re.sub(r"\D", "", text)
        if len(compact) >= 4:
            match = re.match(r"(\d{1,2})(\d{2})", compact[-6:] if len(compact) >= 6 else compact)
    if not match:
        return text, False
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return text, False
    return f"{hour:02d}:{minute:02d}", True


def _in_early_window(seal_time: Optional[str]) -> bool:
    if not seal_time:
        return False
    match = re.match(r"^(\d{2}):(\d{2})$", seal_time)
    if not match:
        return False
    current = time(int(match.group(1)), int(match.group(2)))
    return WINDOW_START <= current <= WINDOW_END


def _history_codes_by_date(zt_history: Dict[str, Any]) -> List[set]:
    days = []
    for date_key in sorted((zt_history or {}).keys(), reverse=True):
        codes = set()
        for item in zt_history.get(date_key) or []:
            if isinstance(item, dict):
                code = _stock_code(item)
                if code:
                    codes.add(code)
            elif item:
                codes.add(str(item).zfill(6)[-6:])
        if codes:
            days.append(codes)
    return days


def _board_count(stock: Dict[str, Any], previous_days: Iterable[set]) -> Tuple[int, str]:
    for key in ("board_count", "连板数", "连续涨停天数", "连板高度", "几连板"):
        n = _num(stock.get(key))
        if n is not None and n >= 1:
            return int(n), "field"
    code = _stock_code(stock)
    if code and any(code in day_codes for day_codes in previous_days):
        return 2, "history"
    return 1, "inferred"


def _extract_concepts(stock: Dict[str, Any]) -> List[str]:
    reason_values = [
        stock.get("reason"),
        stock.get("涨停原因类别"),
        stock.get("涨停原因"),
    ]
    fallback_values = [
        stock.get("所属概念"),
        stock.get("概念"),
        stock.get("所属行业"),
        stock.get("行业"),
        stock.get("板块"),
        stock.get("industry"),
        stock.get("sector"),
        stock.get("concepts"),
    ]

    def collect(raw_values: List[Any]) -> List[str]:
        values: List[str] = []
        seen = set()
        for raw in raw_values:
            if not raw:
                continue
            for part in re.split(r"[+＋,，、;；|｜]+", str(raw)):
                norm = normalize_concept(part)
                if _is_valid_concept(norm) and norm not in seen:
                    seen.add(norm)
                    values.append(norm)
        return values

    concepts = collect(reason_values)
    if concepts:
        return concepts

    concepts = collect(fallback_values)
    return concepts or ["未归因"]


def _reason_stat_counts(reason_stats: Any) -> Dict[str, int]:
    if not isinstance(reason_stats, dict):
        return {}
    merged: Dict[str, int] = {}
    for raw, count in reason_stats.items():
        sector = normalize_concept(raw)
        if not _is_valid_concept(sector) or sector == "未归因":
            continue
        n = _num(count)
        if n is None or n <= 0:
            continue
        merged[sector] = merged.get(sector, 0) + int(n)
    return merged


def _inflow_rows(sector_inflow: Any) -> List[Dict[str, Any]]:
    if isinstance(sector_inflow, list):
        return [r for r in sector_inflow if isinstance(r, dict)]
    if isinstance(sector_inflow, dict):
        data = sector_inflow.get("data") or sector_inflow.get("top") or []
        return [r for r in data if isinstance(r, dict)]
    return []


def _sector_key(name: Any) -> str:
    return re.sub(r"[\s（）()【】\[\]/]+", "", normalize_concept(name).lower())


def _match_inflow(sector: str, sector_inflow: Any) -> Dict[str, Any]:
    target = _sector_key(sector)
    for row in _inflow_rows(sector_inflow):
        name = row.get("name") or row.get("名称") or row.get("板块") or row.get("行业")
        key = _sector_key(name)
        if key and (key == target or key in target or target in key):
            return row
    return {}


def _match_live_sector(sector: str, live_sectors: Any) -> Dict[str, Any]:
    if not isinstance(live_sectors, dict):
        return {}
    target = _sector_key(sector)
    for name, row in live_sectors.items():
        if str(name).startswith("_") or not isinstance(row, dict):
            continue
        key = _sector_key(name)
        if key and (key == target or key in target or target in key):
            return row
    return {}


def _sector_market_stats(sector: str, sector_inflow: Any, live_sectors: Any) -> Dict[str, Any]:
    row = _match_inflow(sector, sector_inflow)
    live = _match_live_sector(sector, live_sectors)
    pct = _num(row.get("涨跌幅") or row.get("涨幅") or row.get("change_pct"))
    if pct is None:
        pct = _num(live.get("涨跌幅") or live.get("板块涨跌幅") or live.get("change_pct"))
    flow = _num(row.get("主力净流入") or row.get("净流入") or row.get("net_inflow"))
    if flow is None:
        flow = _num(live.get("主力净流入") or live.get("净流入") or live.get("net_inflow"))
    return {"sector_change_pct": pct, "net_inflow_yi": flow}


def _score_sector(row: Dict[str, Any], has_time_source: bool) -> int:
    score = 0
    reason_count = row.get("reason_stat_count") or 0
    if has_time_source:
        score += row["early_first_count"] * 22
        score += row["follow_count"] * 8
    else:
        score += row["untimed_first_count"] * 7
        score += row["all_limit_count"] * 5
        score += min(reason_count, 10) * 6
    score += min(row["all_limit_count"], 8) * 4
    pct = row.get("sector_change_pct")
    flow = row.get("net_inflow_yi")
    if pct is not None and pct > 0:
        score += min(int(pct * 4), 16)
    if flow is not None and flow > 0:
        score += min(int(flow / 2), 14)
    return min(100, max(0, score))


def _sector_conclusion(row: Dict[str, Any], has_time_source: bool) -> str:
    if not has_time_source:
        return "源待验收" if row["all_limit_count"] >= 3 else "归因观察"
    if row["early_first_count"] >= 3 and row["follow_count"] >= 2:
        return "主攻确认"
    if row["early_first_count"] >= 2 and row["all_limit_count"] >= 3:
        return "主攻观察"
    if row["early_first_count"] >= 1 and row["all_limit_count"] >= 2:
        return "异动跟随"
    return "分散观察"


def _source_freshness(updated: Any, now: datetime) -> Dict[str, Any]:
    try:
        source_time = datetime.fromisoformat(str(updated))
        ref_time = now
        if source_time.tzinfo and not ref_time.tzinfo:
            ref_time = ref_time.replace(tzinfo=source_time.tzinfo)
        elif ref_time.tzinfo and not source_time.tzinfo:
            source_time = source_time.replace(tzinfo=ref_time.tzinfo)
        age = max(0, int((ref_time - source_time).total_seconds()))
    except Exception:
        return {"level": "unknown", "label": "时间未知", "age_seconds": None}

    minutes = max(1, round(age / 60))
    if age <= 6 * 60:
        return {"level": "live", "label": "实时", "age_seconds": age}
    if age <= 10 * 60:
        return {"level": "delayed", "label": f"数据滞后 {minutes}m", "age_seconds": age}
    return {"level": "stale", "label": f"源失效 {minutes}m", "age_seconds": age}


def _attach_freshness(payload: Dict[str, Any], updated: Any, now: datetime) -> Dict[str, Any]:
    freshness = _source_freshness(updated, now)
    payload["source_freshness"] = freshness
    if freshness["level"] in ("delayed", "stale"):
        minutes = max(1, round((freshness.get("age_seconds") or 0) / 60))
        warnings = list(payload.get("warnings") or [])
        warnings.insert(0, f"核心涨停明细已滞后{minutes}分钟")
        payload["warnings"] = warnings
    return payload


def build_attack_direction(
    hot_list: Any,
    sector_inflow: Any = None,
    live_sectors: Any = None,
    now: Optional[datetime] = None,
    limit_up_detail: Any = None,
) -> Dict[str, Any]:
    """Return a 5-minute level attack-direction payload for the frontend."""
    now = now or datetime.now()
    hot = hot_list if isinstance(hot_list, dict) else {}
    detail = limit_up_detail if isinstance(limit_up_detail, dict) else {}
    detail_stocks = detail.get("stocks") or []
    has_detail_source = bool(detail_stocks)
    raw_stocks = detail_stocks if has_detail_source else (hot.get("zt_stocks") or [])
    zt_stocks = [s for s in raw_stocks if isinstance(s, dict) and "ST" not in _stock_name(s)]
    updated = (detail.get("_updated") if has_detail_source else None) or hot.get("_updated") or now.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    source_label = "limit_up_detail + sector_inflow" if has_detail_source else "hot_list.zt_stocks + sector_inflow"

    if has_detail_source:
        hot_by_code = {
            _stock_code(stock): stock
            for stock in (hot.get("stocks") or hot.get("zt_stocks") or [])
            if isinstance(stock, dict) and _stock_code(stock)
        }
        merged_stocks = []
        for stock in zt_stocks:
            code = _stock_code(stock)
            hot_stock = hot_by_code.get(code) or {}
            if hot_stock:
                merged = dict(stock)
                for key in ("reason", "所属概念", "概念", "所属行业", "行业", "sector", "industry"):
                    if not merged.get(key) and hot_stock.get(key):
                        merged[key] = hot_stock.get(key)
                merged_stocks.append(merged)
            else:
                merged_stocks.append(stock)
        zt_stocks = merged_stocks

    if not zt_stocks:
        reason_counts = _reason_stat_counts(hot.get("reason_stats") or {})
        if reason_counts:
            sectors = []
            for sector, count in reason_counts.items():
                row = {
                    "sector": sector,
                    "early_first_count": 0,
                    "untimed_first_count": 0,
                    "all_limit_count": count,
                    "follow_count": 0,
                    "linked_count": 0,
                    "sample": [],
                    "board_source": "reason_stats",
                    "reason_stat_count": count,
                }
                row.update(_sector_market_stats(sector, sector_inflow, live_sectors))
                row["score"] = _score_sector(row, False)
                row["conclusion"] = "题材观察"
                row["evidence"] = [
                    "涨停名单缺失",
                    "早封未验收",
                    f"题材归因{count}次",
                ]
                if row.get("sector_change_pct") is not None:
                    row["evidence"].append(f"板块{row['sector_change_pct']:+.2f}%")
                if row.get("net_inflow_yi") is not None:
                    row["evidence"].append(f"资金{row['net_inflow_yi']:+.1f}亿")
                sectors.append(row)
            sectors.sort(key=lambda r: (r["score"], r["reason_stat_count"]), reverse=True)
            leader = sectors[0] if sectors else {}
            zt_count = int(
                _num(hot.get("zt_count"))
                or _num(hot.get("total"))
                or (max(reason_counts.values()) if reason_counts else 0)
                or 0
            )
            return _attach_freshness({
                "_updated": updated,
                "source": "hot_list.reason_stats + sector_inflow",
                "source_status": "partial_reason_stats",
                "window": "09:30-09:45",
                "summary": {
                    "leader_sector": leader.get("sector", ""),
                    "conclusion": "题材方向观察",
                    "confidence": min(55, leader.get("score", 0)),
                    "early_first_count": 0,
                    "first_count": 0,
                    "all_limit_count": zt_count,
                    "sector_count": len(sectors),
                },
                "sectors": sectors[:8],
                "warnings": ["今日确认涨停名单缺失，仅按题材归因观察，不能验收早封首板"],
            }, updated, now)
        return _attach_freshness({
            "_updated": updated,
            "source": "hot_list.zt_stocks + sector_inflow",
            "source_status": "missing_source",
            "window": "09:30-09:45",
            "summary": {
                "leader_sector": "",
                "conclusion": "涨停源缺失",
                "confidence": 0,
                "early_first_count": 0,
                "all_limit_count": 0,
                "sector_count": 0,
            },
            "sectors": [],
            "warnings": ["今日确认涨停源暂不可用"],
        }, updated, now)

    previous_days = _history_codes_by_date(hot.get("zt_history") or {})
    sectors: Dict[str, Dict[str, Any]] = {}
    first_total = 0
    early_first_total = 0
    stocks_with_parseable_time = 0
    first_without_time = 0

    for stock in zt_stocks:
        code = _stock_code(stock)
        name = _stock_name(stock)
        board_count, board_source = _board_count(stock, previous_days)
        is_first = board_count <= 1
        seal_time, time_ok = _extract_seal_time(stock)
        if time_ok:
            stocks_with_parseable_time += 1
        early = is_first and _in_early_window(seal_time)
        if is_first:
            first_total += 1
            if early:
                early_first_total += 1
            elif not time_ok:
                first_without_time += 1

        for sector in _extract_concepts(stock):
            row = sectors.setdefault(
                sector,
                {
                    "sector": sector,
                    "early_first_count": 0,
                    "untimed_first_count": 0,
                    "all_limit_count": 0,
                    "follow_count": 0,
                    "linked_count": 0,
                    "sample": [],
                    "evidence": [],
                    "board_source": board_source,
                },
            )
            row["all_limit_count"] += 1
            if is_first and early:
                row["early_first_count"] += 1
                if len(row["sample"]) < 4:
                    row["sample"].append(
                        {
                            "code": code,
                            "name": name,
                            "seal_time": seal_time,
                            "reason": _clean_text(stock.get("reason") or stock.get("所属概念") or ""),
                        }
                    )
            elif is_first and not time_ok:
                row["untimed_first_count"] += 1
            elif not is_first:
                row["linked_count"] += 1

    reason_counts = _reason_stat_counts(hot.get("reason_stats") or {})
    for sector, count in reason_counts.items():
        row = sectors.setdefault(
            sector,
            {
                "sector": sector,
                "early_first_count": 0,
                "untimed_first_count": 0,
                "all_limit_count": 0,
                "follow_count": 0,
                "linked_count": 0,
                "sample": [],
                "evidence": [],
                "board_source": "reason_stats",
            },
        )
        row["reason_stat_count"] = max(row.get("reason_stat_count") or 0, count)
        if row["all_limit_count"] == 0:
            row["all_limit_count"] = count

    if reason_counts and len(sectors) > 1 and "未归因" in sectors:
        sectors.pop("未归因", None)

    has_time_source = stocks_with_parseable_time > 0
    warnings = []
    if not has_time_source:
        warnings.append("确认涨停源缺封板时间，早封首板只能等待源补齐")
    elif first_without_time:
        warnings.append(f"{first_without_time}只首板缺封板时间，早封统计可能偏低")
    detail_total = _num(detail.get("total")) if has_detail_source else None
    detail_returned = _num(detail.get("returned")) if has_detail_source else None
    if detail_total and detail_returned and detail_returned < detail_total:
        warnings.append(f"问财明细返回{int(detail_returned)}/{int(detail_total)}只，方向按已返回样本统计")
    hot_total = _num(hot.get("zt_count"))
    detail_coverage = detail_returned or detail_total or len(zt_stocks)
    if has_detail_source and hot_total and detail_coverage and hot_total > detail_coverage:
        warnings.append(f"明细源返回{int(detail_coverage)}只，hot_list总数{int(hot_total)}只，方向按明细样本统计")

    for sector, row in sectors.items():
        reason_only = row.get("board_source") == "reason_stats" and not (
            row.get("early_first_count") or row.get("untimed_first_count") or row.get("linked_count")
        )
        row["follow_count"] = 0 if reason_only else max(0, row["all_limit_count"] - row["early_first_count"])
        row.update(_sector_market_stats(sector, sector_inflow, live_sectors))
        row["score"] = _score_sector(row, has_time_source)
        row["conclusion"] = _sector_conclusion(row, has_time_source)
        row["evidence"] = [
            f"早封首板{row['early_first_count']}只" if has_time_source else (
                "早封未验收" if reason_only else f"首板待验收{row['untimed_first_count']}只"
            ),
            f"跟随封板{row['follow_count']}只",
            f"全板{row['all_limit_count']}只",
        ]
        if row.get("reason_stat_count"):
            row["evidence"].append(f"题材归因{row['reason_stat_count']}次")
        if row.get("sector_change_pct") is not None:
            row["evidence"].append(f"板块{row['sector_change_pct']:+.2f}%")
        if row.get("net_inflow_yi") is not None:
            row["evidence"].append(f"资金{row['net_inflow_yi']:+.1f}亿")

    if has_time_source:
        ranked = sorted(
            sectors.values(),
            key=lambda r: (r["early_first_count"], r["follow_count"], r["all_limit_count"], r["score"]),
            reverse=True,
        )[:8]
    else:
        ranked = sorted(
            sectors.values(),
            key=lambda r: (r["score"], r["early_first_count"], r["all_limit_count"]),
            reverse=True,
        )[:8]
    leader = ranked[0] if ranked else None

    if not leader:
        conclusion = "分散轮动"
        confidence = 0
        leader_sector = ""
    elif not has_time_source:
        conclusion = "首板源待验收"
        confidence = min(55, leader["score"])
        leader_sector = leader["sector"]
    elif leader["conclusion"] == "主攻确认":
        conclusion = "主攻确认"
        confidence = max(70, leader["score"])
        leader_sector = leader["sector"]
    elif leader["early_first_count"] > 0:
        conclusion = "主攻观察"
        confidence = min(78, max(45, leader["score"]))
        leader_sector = leader["sector"]
    else:
        conclusion = "分散轮动"
        confidence = min(50, leader["score"])
        leader_sector = leader["sector"]

    return _attach_freshness({
        "_updated": updated,
        "source": source_label,
        "source_status": "confirmed" if has_time_source else "missing_time",
        "window": "09:30-09:45",
        "summary": {
            "leader_sector": leader_sector,
            "conclusion": conclusion,
            "confidence": confidence,
            "early_first_count": early_first_total,
            "first_count": first_total,
            "all_limit_count": int(detail_total) if detail_total else len(zt_stocks),
            "sector_count": len(sectors),
        },
        "sectors": ranked,
        "warnings": warnings,
    }, updated, now)
