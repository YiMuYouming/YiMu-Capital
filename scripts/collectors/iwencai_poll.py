"""iwencai_poll.py — T2 情绪数据定时轮询（每 2min）

通过 ym_stock_data 统一接口 → OpenAPI 优先，额度耗尽自动降级 pywencai。
非交易时段自动跳过。
"""
import sys, json, urllib.parse, urllib.request
from datetime import datetime, time
from pathlib import Path

try:
    from scripts.ym_data_query import _load_pipeline_path, compat_iwencai_query
except ModuleNotFoundError:  # Direct execution from outside the repository root.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.ym_data_query import _load_pipeline_path, compat_iwencai_query

def _iwencai_query(*args, **kwargs):
    """Route scheduled calls through the single rollout boundary."""
    return compat_iwencai_query(*args, **kwargs)

CACHE = {}

_BREADTH_UP_KEYS = ("涨停", ">7%", "5~7%", "3~5%", "0~3%")
_BREADTH_DOWN_KEYS = ("-0~-3%", "-3~-5%", "-5~-7%", "<-7%", "跌停")


def is_trading_time():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return (time(9, 25) <= t <= time(11, 30)) or (time(13, 0) <= t <= time(16, 0))


def _clean(v):
    if v is None: return None
    try: return float(str(v).replace("%", "").strip())
    except: return v


def _find_key(row, keyword):
    for k in row:
        if keyword in str(k): return k
    return None


def _val(row, keyword, clean=False):
    k = _find_key(row, keyword)
    v = row.get(k) if k else row.get(keyword)
    return _clean(v) if clean and v is not None else v


def _stock_code(row):
    raw = (
        _val(row, "股票代码")
        or _val(row, "代码")
        or row.get("code")
        or row.get("证券代码")
        or ""
    )
    code = str(raw).strip()
    if "." in code:
        code = code.split(".")[0]
    digits = "".join(ch for ch in code if ch.isdigit())
    return digits.zfill(6)[-6:] if digits else code


def _stock_name(row):
    return str(
        _val(row, "股票简称")
        or _val(row, "名称")
        or row.get("name")
        or row.get("股票名称")
        or ""
    ).strip()


def _limit_detail_row(row):
    code = _stock_code(row)
    name = _stock_name(row)
    reason = (
        _val(row, "涨停原因类别")
        or _val(row, "涨停原因")
        or _val(row, "所属概念")
        or _val(row, "概念")
        or _val(row, "所属行业")
        or _val(row, "行业")
        or ""
    )
    seal_time = (
        _val(row, "首次封板时间")
        or _val(row, "首封时间")
        or _val(row, "封板时间")
        or _val(row, "涨停时间")
        or ""
    )
    board_count = (
        _val(row, "连续涨停天数", clean=True)
        or _val(row, "连板数", clean=True)
        or _val(row, "几天几板", clean=True)
        or 1
    )
    item = {
        "code": code,
        "name": name,
        "reason": str(reason or "").strip(),
        "seal_time": str(seal_time or "").strip(),
        "board_count": int(board_count) if isinstance(board_count, (int, float)) else board_count,
        "industry": str(_val(row, "所属行业") or _val(row, "行业") or "").strip(),
        "concepts": str(_val(row, "所属概念") or _val(row, "概念") or "").strip(),
    }
    return item if code or name else None


def poll_limit_up_detail(force=False):
    """Poll confirmed limit-up stock details for W26 attack direction.

    This collector is best-effort. Empty/failed detail data must not block the
    dashboard: W26 can fall back to hot_list/reason_stats and explicitly mark
    early-seal validation as unavailable.
    """
    if not force and not is_trading_time():
        return

    queries = [
        "今日涨停 非st 股票代码 股票简称 涨停原因类别 首次封板时间 连续涨停天数 所属概念 所属行业",
        "今日涨停 非st 股票代码 股票简称 涨停原因 封板时间 连续涨停天数 所属行业",
        "今日涨停 非st 股票代码 股票简称 所属概念 所属行业",
    ]
    last_error = None
    for query in queries:
        try:
            result = _iwencai_query(query, limit=300) or {}
            datas = result.get("datas") or []
            stocks = []
            seen = set()
            for row in datas:
                if not isinstance(row, dict):
                    continue
                item = _limit_detail_row(row)
                if not item:
                    continue
                key = item.get("code") or item.get("name")
                if key in seen:
                    continue
                seen.add(key)
                stocks.append(item)
            payload = {
                "stocks": stocks,
                "returned": len(stocks),
                "total": len(datas),
                "query": query,
                "_source": "iwencai_limit_up_detail",
                "_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            }
            CACHE["limit_up_detail"] = payload
            return payload
        except Exception as e:
            last_error = e
            continue
    if last_error:
        print(f"  [iwencai_poll] limit_up_detail error: {last_error}", file=sys.stderr)
    return None


def _avg_pct(datas, col_keyword):
    """从 dict list 中提取涨跌幅列并算均值"""
    vals = []
    for row in datas:
        v = _val(row, col_keyword, clean=True)
        if isinstance(v, (int, float)):
            vals.append(v)
    return round(sum(vals) / len(vals), 2) if vals else None


def _max_board(datas):
    """提取最高板 + 次高板"""
    boards = []
    for row in datas:
        d = _val(row, "连续涨停天数", clean=True)
        if isinstance(d, (int, float)) and d >= 2:
            boards.append(int(d))
    if not boards:
        return None, None
    uniq = sorted(set(boards), reverse=True)
    return uniq[0], uniq[1] if len(uniq) >= 2 else None


def _eastmoney_limit_counts(date_str=None):
    """东方财富涨跌停池兜底，供云端问财返回空结果时使用。"""
    date_str = date_str or datetime.now().strftime("%Y%m%d")
    base = "https://push2ex.eastmoney.com/"
    common = {
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "dpt": "wz.ztzt",
        "Pageindex": 0,
        "pagesize": 200,
        "sort": "fbt:asc",
        "date": date_str,
    }

    def fetch_count(path):
        url = base + path + "?" + urllib.parse.urlencode(common)
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://quote.eastmoney.com/ztb/detail",
        })
        payload = json.loads(urllib.request.urlopen(req, timeout=10).read().decode("utf-8"))
        data = (payload or {}).get("data") or {}
        count = data.get("tc")
        if count is not None:
            return int(float(count))
        return len(data.get("pool") or [])

    try:
        return {
            "涨停家数": fetch_count("getTopicZTPool"),
            "跌停家数": fetch_count("getTopicDTPool"),
        }
    except Exception:
        return {}


def _is_same_local_date(updated, now=None):
    if not updated:
        return False
    now = now or datetime.now()
    return str(updated)[:10] == now.strftime("%Y-%m-%d")


def _preserve_same_day_iwencai_fields(results):
    prev = CACHE.get("iwencai", {})
    if not isinstance(prev, dict) or not _is_same_local_date(prev.get("_updated")):
        return results
    preserved = []
    for key in [
        "昨日涨停收益", "涨停溢价率", "赚钱效应",
        "连板收益", "炸板收益",
        "情绪值", "_emotion_source", "_emotion_counts",
    ]:
        if key not in results and key in prev:
            results[key] = prev[key]
            if not key.startswith("_"):
                preserved.append(key)
    if preserved:
        results["_preserved_fields"] = sorted(preserved)
    return results


def _pytdx_core_market():
    """Return zero-auth core market facts already collected by PyTDX breadth.

    The live-index fallback intentionally exposes the same bucket shape with
    zero limit counts, so it must not be treated as an exact PyTDX breadth
    sample.
    """
    breadth = CACHE.get("breadth") or {}
    if not isinstance(breadth, dict):
        return {}
    if breadth.get("_source") == "live_index_fallback":
        return {}
    try:
        total = int(float(breadth.get("_total") or 0))
        up = sum(int(float(breadth.get(key) or 0)) for key in _BREADTH_UP_KEYS)
        down = sum(int(float(breadth.get(key) or 0)) for key in _BREADTH_DOWN_KEYS)
        limit_up = int(float(breadth.get("涨停") or 0))
        limit_down = int(float(breadth.get("跌停") or 0))
    except (TypeError, ValueError):
        return {}
    if total <= 0 or up + down <= 0:
        return {}
    return {
        "up": up,
        "down": down,
        "limit_up": limit_up,
        "limit_down": limit_down,
        "source": "pytdx_breadth",
    }


def poll_iwencai_sentiment(force=False):
    if not force and not is_trading_time():
        return

    results = {}
    core_market = _pytdx_core_market()
    try:
        # === 涨停收益 + 赚钱效应 ===
        r = _iwencai_query("昨日涨停 今日涨跌幅 非st", limit=100)
        datas = r.get("datas", [])
        avg = _avg_pct(datas, "涨跌幅")
        if avg is not None:
            results["昨日涨停收益"] = avg
            vals = []
            for row in datas:
                v = _val(row, "涨跌幅", clean=True)
                if isinstance(v, (int, float)): vals.append(v)
            if vals:
                green = sum(1 for v in vals if v > 0)
                results["涨停溢价率"] = round(green / len(vals) * 100, 1)
                results["赚钱效应"] = "好" if avg > 2 else ("差" if avg < 0 else "一般")

        # === 连板收益 ===
        for q in [
            "昨日连续涨停天数>=2 今日涨跌幅 非st",
            "昨日连板 今日涨跌幅 非st",
            "昨日涨停 连续涨停天数>=2 今日涨跌幅 非st",
        ]:
            r = _iwencai_query(q, limit=30)
            avg = _avg_pct(r.get("datas", []), "涨跌幅")
            if avg is not None:
                results["连板收益"] = avg
                results["_lianban_profit_query"] = q
                break

        # === 炸板收益 ===
        r = _iwencai_query("昨日炸板 今日涨跌幅 非st", limit=30)
        avg = _avg_pct(r.get("datas", []), "涨跌幅")
        if avg is not None:
            results["炸板收益"] = avg

        # === 实时情绪值：PyTDX 全市场 breadth，零鉴权且已由 30s collector 维护 ===
        up_cnt = core_market.get("up")
        down_cnt = core_market.get("down")
        if up_cnt and down_cnt:
            results["情绪值"] = round(up_cnt / (up_cnt + down_cnt) * 100, 1)
            results["_emotion_source"] = core_market["source"]
            results["_emotion_counts"] = {"up": up_cnt, "down": down_cnt}

        # === 最高板 + 次高板 + 连板股列表 ===
        r = _iwencai_query("连续涨停天数>=2 非st 连续涨停天数 所属行业 封板时间 换手率", limit=50)
        datas = r.get("datas", [])
        max_b, sub_b = _max_board(datas)
        if max_b is not None: results["最高板"] = max_b
        if sub_b is not None: results["次高板"] = sub_b
        results["连板股数"] = len(datas) if datas else None

        # 晋级率 = 连板股数 / 昨日涨停股数
        r = _iwencai_query("昨日涨停 非st", limit=200)
        yest_zt = len(r.get("datas", []))
        if yest_zt > 0 and results.get("连板股数") is not None:
            rate = results["连板股数"] / yest_zt
            results["晋级率"] = round(rate, 4) if rate <= 1 else round(rate / 100, 4)

        # 分层晋级率
        for layer_q, layer_key in [
            ("昨日首板 今日涨跌幅 非st", "一进二晋级率"),
            ("昨日二板 今日涨跌幅 非st", "二进三晋级率"),
            ("昨日三板 今日涨跌幅 非st", "三进四晋级率"),
        ]:
            try:
                r = _iwencai_query(layer_q, limit=100)
                vals = []
                for row in r.get("datas", []):
                    v = _val(row, "涨跌幅", clean=True)
                    if isinstance(v, (int, float)): vals.append(v)
                if vals:
                    up = sum(1 for v in vals if v > 0)
                    results[layer_key] = round(up / len(vals), 4)
            except Exception:
                pass

        # === 连板股列表 ===
        lb_stocks = []
        for row in datas:
            code = str(_val(row, "股票代码") or "")
            code = code.split(".")[0] if "." in code else code
            name = str(_val(row, "股票简称") or "")
            days = _val(row, "连续涨停天数", clean=True)
            sector = str(_val(row, "所属行业") or "")
            ft = str(_val(row, "封板时间") or "")
            hs = _val(row, "换手率", clean=True)
            if code and days:
                lb_stocks.append({
                    "代码": code,
                    "名称": name,
                    "连板数": int(days),
                    "板块": sector,
                    "封板时间": ft,
                    "换手率": round(float(hs), 2) if hs else None,
                })
        if lb_stocks:
            results["连板股列表"] = lb_stocks

        # === 封板率 + 炸板率；涨跌停核心计数优先 PyTDX ===
        r = _iwencai_query("今日触及涨停 非st", limit=200)
        touch_cnt = len(r.get("datas", []))
        close_cnt = core_market.get("limit_up")
        dt_cnt = core_market.get("limit_down")
        counts_verified = bool(core_market)
        if close_cnt is not None and dt_cnt is not None:
            results["_limit_source"] = core_market["source"]
        else:
            em_counts = _eastmoney_limit_counts()
            close_cnt = em_counts.get("涨停家数")
            dt_cnt = em_counts.get("跌停家数")
            if em_counts:
                counts_verified = True
                results["_limit_source"] = "eastmoney_zt_pool"
        close_cnt = int(close_cnt or 0)
        dt_cnt = int(dt_cnt or 0)
        limit_counts_valid = counts_verified or touch_cnt > 0 or close_cnt > 0 or dt_cnt > 0
        if touch_cnt > 0 or close_cnt > 0:
            base = max(touch_cnt, close_cnt)
            results["封板率"] = round(min(close_cnt / base, 1.0), 4) if base > 0 else 0
            results["炸板率"] = round(max((touch_cnt - close_cnt) / base, 0), 4)
        if limit_counts_valid:
            results["涨停家数"] = close_cnt
            results["跌停家数"] = dt_cnt
        else:
            prev = CACHE.get("iwencai", {})
            prev_zt = int(prev.get("涨停家数") or 0)
            prev_dt = int(prev.get("跌停家数") or 0)
            if prev_zt > 0 or prev_dt > 0:
                results["涨停家数"] = prev.get("涨停家数")
                results["跌停家数"] = prev.get("跌停家数")
                results["_limit_source"] = prev.get("_limit_source", "previous_valid")

        # === 连板风险值 ===
        jj = results.get("晋级率")
        if jj is not None:
            results["连板风险值"] = round(max(0, min(1, 1.0 - jj * 1.8)), 2)

        if results:
            results = _preserve_same_day_iwencai_fields(results)
            results["_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
            CACHE["iwencai"] = results
    except Exception as e:
        print(f"  [iwencai_poll] error: {e}", file=sys.stderr)
