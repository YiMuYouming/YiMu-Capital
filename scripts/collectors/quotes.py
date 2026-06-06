"""quotes.py — T1 实时行情采集器（替代 poll_live 内联 PyTDX）

使用 YM-data-pipeline fetch() 统一接口，不再直接调 PyTDX/easyquotation。
bridge.py APScheduler 调度：5s/30s/300s 三档频率。
"""
import os, sys, json, threading, urllib.parse, urllib.request
from pathlib import Path
from datetime import datetime, time as _time_module, timedelta

from scripts.file_utils import atomic_write_json

def _load_pipeline_path():
    """从环境变量或默认值解析 ym_stock_data 的路径。

    若用户显式提供 YM_DATA_PIPELINE_PATH 但路径不存在，立即报错。
    """
    env_path = os.environ.get("YM_DATA_PIPELINE_PATH", "")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
        raise RuntimeError(
            f"YM_DATA_PIPELINE_PATH='{env_path}' 不存在。"
            f"请检查路径是否正确，或取消设置该环境变量以使用默认路径。"
            f"默认路径: {Path(__file__).resolve().parent.parent.parent / 'YM-data-pipeline'}"
        )
    # scripts/collectors/quotes.py → parents[4] = YM_Capital/ (4 layers from file to YM_Capital)
    default = Path(__file__).resolve().parent.parent.parent.parent / "YM-data-pipeline"
    return default

_pip_path = None

def _ensure_pipeline():
    """确保 ym_stock_data 在 sys.path 中，返回路径"""
    global _pip_path
    if _pip_path is not None:
        return _pip_path
    p = _load_pipeline_path()
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
    _pip_path = p
    return p

def _pipeline_fetch(*args, **kwargs):
    """延迟导入 ym_stock_data.fetch，避免启动时崩溃"""
    _ensure_pipeline()
    from ym_stock_data.fetch import fetch as _f
    return _f(*args, **kwargs)

CACHE = {}
_tdx_lock = threading.Lock()  # PyTDX 共用连接保护锁


def _pytdx_disabled():
    return os.getenv("YIMU_DISABLE_PYTDX", "").strip().lower() in {"1", "true", "yes", "on"}


def _fetch_market_data(data_type, **kwargs):
    if _pytdx_disabled():
        return _pipeline_fetch(data_type, **kwargs)
    with _tdx_lock:
        return _pipeline_fetch(data_type, **kwargs)


def is_trading_time():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return _time_module(9, 15) <= t <= _time_module(15, 10)


def collect_quotes(force=False):
    """5s: 个股行情（从 CACHE 中的 codes 列表获取）"""
    if not force and not is_trading_time():
        return
    codes = CACHE.get("_stock_codes", [])
    if not codes:
        return
    try:
        r = _fetch_market_data("quotes", codes=codes)
        if r:
            if isinstance(r, dict):
                r.pop('_meta', None)
            # 上游偶发只返回 _meta；不能用空负载擦掉上一笔有效行情。
            if isinstance(r, dict) and r:
                CACHE["live_quotes"] = r
                CACHE["live_quotes"]["_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    except Exception as e:
        print(f"  [quotes] collect_quotes error: {e}", file=sys.stderr)


def collect_index(force=False):
    """5s: 三大指数 + 涨跌家数 + 成交额"""
    if not force and not is_trading_time():
        return
    try:
        r = _fetch_market_data("index")
        if r:
            if isinstance(r, dict):
                r.pop('_meta', None)
            # 上游收盘后可能只返回 _meta；不能用空负载制造一个只有
            # _updated 的 live_index，导致 W04 重启后失去收盘基线。
            if isinstance(r, dict) and r:
                li = CACHE.get("live_index", {})
                _drop_stale_turnover_compare(li, r)
                li.update(r)
                li["_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
                CACHE["live_index"] = li
    except Exception as e:
        print(f"  [quotes] collect_index error: {e}", file=sys.stderr)


def _drop_stale_turnover_compare(live_index, incoming):
    """Remove yesterday-same-period compare fields when the current source omits them."""
    compare_keys = []
    for name in ("上证", "深证"):
        compare_keys.extend([
            f"{name}昨成交额",
            f"{name}成交额差",
            f"{name}成交额差百分比",
        ])

    incoming_has_compare = any(k in incoming for k in compare_keys)
    incoming_has_amount = any(k in incoming for k in (
        "成交额",
        "上证指数成交额",
        "深证指数成交额",
    ))
    if incoming_has_amount and not incoming_has_compare:
        if _is_recent_turnover_compare(live_index.get("_turnover_compare_updated")):
            return
        for key in compare_keys:
            live_index.pop(key, None)
        live_index.pop("_turnover_compare_updated", None)


def _is_recent_turnover_compare(updated, max_age_seconds=90):
    if not updated:
        return False
    try:
        ts = datetime.strptime(str(updated).replace("+08:00", ""), "%Y-%m-%dT%H:%M:%S")
        return (datetime.now() - ts).total_seconds() <= max_age_seconds
    except Exception:
        return False


def collect_yesterday_compare(force=False):
    """30s: 成交额较昨日同时段对比"""
    if not force and not is_trading_time():
        return
    if _pytdx_disabled():
        _collect_yesterday_compare_eastmoney()
        return
    try:
        from datetime import datetime as _dt
        now = _dt.now()
        # 已交易分钟数（从9:30算起）
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        minutes_traded = max(1, min(240, (now - market_open).total_seconds() / 60))
        slot_count = int(minutes_traded / 15) + 1  # 多少个15分钟槽

        # 从 PyTDX 获取昨日15分钟K线
        api = _get_tdx_api()
        if not api:
            _collect_yesterday_compare_cached_15m(now=now)
            return

        result = {}
        for name, (mkt, code) in [("上证", (1, "000001")), ("深证", (0, "399001"))]:
            try:
                bars = api.get_index_bars(1, mkt, code, 0, 60)
                if not bars:
                    continue
                today_str = now.strftime("%Y-%m-%d")
                current_min = now.hour * 60 + now.minute

                # 找到昨天日期
                from datetime import timedelta
                yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

                yesterday_amt = 0
                for b in bars:
                    dt = str(b.get("datetime", ""))
                    if yesterday not in dt:
                        continue
                    # 解析时间，只取到当前时刻对应的时段
                    try:
                        bar_time = dt.split(" ")[-1] if " " in dt else dt[-5:]
                        h, m = bar_time.split(":")[0], bar_time.split(":")[1]
                        bar_min = int(h) * 60 + int(m)
                        if bar_min <= current_min:
                            yesterday_amt += b.get("amount", 0)
                    except (ValueError, IndexError):
                        continue
                yesterday_amt_yi = yesterday_amt / 1e8

                # 从 live_index 取今日累计
                li = CACHE.get("live_index", {})
                today_amt_str = li.get(f"{name}指数成交额", "")
                if today_amt_str:
                    try:
                        s = str(today_amt_str)
                        if '万亿' in s:
                            today_amt_yi = float(s.replace('万亿', '')) * 10000
                        else:
                            today_amt_yi = float(s.replace('亿', ''))
                    except ValueError:
                        today_amt_yi = 0
                else:
                    today_amt_yi = 0

                if yesterday_amt_yi > 0:
                    diff = today_amt_yi - yesterday_amt_yi
                    pct = round(diff / yesterday_amt_yi * 100, 1)
                    result[f"{name}昨成交额"] = f"{yesterday_amt_yi:.2f}亿"
                    result[f"{name}成交额差"] = f"{diff:+.2f}亿"
                    result[f"{name}成交额差百分比"] = f"{pct:+.1f}%"
            except Exception:
                continue

        if result:
            # 合并到 live_index
            li = CACHE.get("live_index", {})
            li.update(result)
            li["_turnover_compare_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
            CACHE["live_index"] = li
        else:
            _collect_yesterday_compare_cached_15m(now=now)
    except Exception as e:
        print(f"  [quotes] collect_yesterday_compare error: {e}", file=sys.stderr)


def _collect_yesterday_compare_eastmoney(now=None):
    now = now or datetime.now()
    cutoff = _current_15m_cutoff(now)
    if not cutoff:
        return
    result = {}
    li = CACHE.get("live_index", {})
    for name, secid in [("上证", "1.000001"), ("深证", "0.399001")]:
        try:
            rows = _eastmoney_15m_klines(secid, now=now)
            yesterday_amt_yi = _eastmoney_yesterday_same_period_yi(rows, now, cutoff)
            today_amt_yi = _amount_str_to_yi(li.get(f"{name}指数成交额"))
            if yesterday_amt_yi > 0 and today_amt_yi > 0:
                diff = today_amt_yi - yesterday_amt_yi
                pct = round(diff / yesterday_amt_yi * 100, 1)
                result[f"{name}昨成交额"] = f"{yesterday_amt_yi:.2f}亿"
                result[f"{name}成交额差"] = f"{diff:+.2f}亿"
                result[f"{name}成交额差百分比"] = f"{pct:+.1f}%"
        except Exception:
            continue
    if result:
        li.update(result)
        li["_turnover_compare_updated"] = now.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        CACHE["live_index"] = li
    else:
        _collect_yesterday_compare_cached_15m(now=now)


def _collect_yesterday_compare_cached_15m(now=None):
    """Fallback: use restored previous-day 15min rows as yesterday same-period basis."""
    now = now or datetime.now()
    cutoff = _current_15m_cutoff(now)
    if not cutoff:
        return False
    li = CACHE.get("live_index", {})
    result = {}
    for name, key in [("上证", "上证15min"), ("深证", "深证15min")]:
        rows = CACHE.get(key) or []
        yesterday_amt = 0.0
        for row in rows:
            if not isinstance(row, dict) or row.get("_cum"):
                continue
            slot = str(row.get("t") or "")
            if slot and slot <= cutoff:
                try:
                    basis = row.get("yesterdayAmt")
                    if basis in (None, "", 0):
                        basis = row.get("amount")
                    yesterday_amt += float(basis or 0)
                except (TypeError, ValueError):
                    continue
        today_amt_yi = _amount_str_to_yi(li.get(f"{name}指数成交额"))
        yesterday_amt_yi = yesterday_amt / 1e8
        if yesterday_amt_yi > 0 and today_amt_yi > 0:
            diff = today_amt_yi - yesterday_amt_yi
            pct = round(diff / yesterday_amt_yi * 100, 1)
            result[f"{name}昨成交额"] = f"{yesterday_amt_yi:.2f}亿"
            result[f"{name}成交额差"] = f"{diff:+.2f}亿"
            result[f"{name}成交额差百分比"] = f"{pct:+.1f}%"
    if result:
        li.update(result)
        li["_turnover_compare_updated"] = now.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        li["_turnover_compare_source"] = "cached_previous_15m"
        CACHE["live_index"] = li
        return True
    return False


def _current_15m_cutoff(now=None):
    now = now or datetime.now()
    minutes = now.hour * 60 + now.minute
    open_min = 9 * 60 + 30
    morning_close = 11 * 60 + 30
    afternoon_open = 13 * 60
    close_min = 15 * 60

    def fmt(total_min):
        return f"{total_min // 60:02d}:{total_min % 60:02d}"

    if minutes < open_min:
        return None
    if minutes <= morning_close:
        elapsed = max(1, minutes - open_min)
        slot_end = open_min + max(15, (elapsed // 15) * 15)
        return fmt(min(slot_end, morning_close))
    if minutes < afternoon_open:
        return "11:30"
    if minutes <= close_min:
        elapsed = max(1, minutes - afternoon_open)
        slot_end = afternoon_open + max(15, (elapsed // 15) * 15)
        return fmt(min(slot_end, close_min))
    return "15:00"


def _eastmoney_15m_klines(secid, now=None):
    now = now or datetime.now()
    beg = (now - timedelta(days=7)).strftime("%Y%m%d")
    end = now.strftime("%Y%m%d")
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": 15,
        "fqt": 0,
        "beg": beg,
        "end": end,
    }
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    payload = json.loads(urllib.request.urlopen(req, timeout=8).read().decode("utf-8"))
    return ((payload or {}).get("data") or {}).get("klines") or []


def _eastmoney_yesterday_same_period_yi(rows, now, cutoff):
    today = now.strftime("%Y-%m-%d")
    prior_dates = sorted({
        str(row).split(",", 1)[0][:10]
        for row in rows
        if str(row).split(",", 1)[0][:10] < today
    })
    if not prior_dates:
        return 0
    ydate = prior_dates[-1]
    total = 0.0
    for row in rows:
        parts = str(row).split(",")
        if len(parts) < 7:
            continue
        dt = parts[0]
        if not dt.startswith(ydate):
            continue
        time_key = dt[-5:]
        if time_key <= cutoff:
            try:
                total += float(parts[6])
            except ValueError:
                pass
    return total / 1e8


def _eastmoney_kline_15m_rows(secid, now=None):
    now = now or datetime.now()
    today = now.strftime("%Y-%m-%d")
    rows = _eastmoney_15m_klines(secid, now=now)
    prior_dates = sorted({
        str(row).split(",", 1)[0][:10]
        for row in rows
        if str(row).split(",", 1)[0][:10] < today
    })
    yesterday = prior_dates[-1] if prior_dates else None
    yesterday_by_time = {}
    today_rows = []

    for row in rows:
        parts = str(row).split(",")
        if len(parts) < 9:
            continue
        dt = parts[0]
        date = dt[:10]
        slot = dt[11:16]
        try:
            vol = float(parts[5] or 0)
            amount = float(parts[6] or 0)
            chg = float(parts[8] or 0)
        except (TypeError, ValueError):
            continue
        if yesterday and date == yesterday:
            yesterday_by_time[slot] = amount
        elif date == today:
            today_rows.append((slot, chg, vol, amount))

    result = []
    total_amount = 0.0
    total_yesterday = 0.0
    for slot, chg, vol, amount in today_rows:
        yesterday_amt = yesterday_by_time.get(slot) or 0.0
        total_amount += amount
        total_yesterday += yesterday_amt
        result.append({
            "t": slot,
            "chg": chg,
            "vol": vol,
            "volRatio": round(amount / yesterday_amt, 2) if yesterday_amt > 0 else 1,
            "amount": amount,
            "yesterdayAmt": yesterday_amt,
        })
    if result:
        result.append({
            "t": "累计",
            "chg": 0,
            "vol": 0,
            "volRatio": round(total_amount / total_yesterday, 2) if total_yesterday > 0 else 1,
            "amount": total_amount,
            "cumYesterdayAmt": total_yesterday,
            "_cum": True,
        })
    return result


def _collect_kline_15m_eastmoney(now=None):
    now = now or datetime.now()
    mapping = {
        "上证15min": "1.000001",
        "深证15min": "0.399001",
        "创业15min": "0.399006",
    }
    updated = False
    for key, secid in mapping.items():
        rows = _eastmoney_kline_15m_rows(secid, now=now)
        if rows:
            CACHE[key] = rows
            updated = True
    if updated:
        CACHE["kline_15m_date"] = now.strftime("%Y-%m-%d")
    return updated


def _amount_str_to_yi(value):
    if value in (None, "", "—"):
        return 0
    s = str(value).replace(",", "").strip()
    try:
        if "万亿" in s:
            return float(s.replace("万亿", "")) * 10000
        if "亿" in s:
            return float(s.replace("亿", ""))
        return float(s) / 1e8
    except ValueError:
        return 0


def _get_tdx_api():
    try:
        from ym_stock_data.sources.pytdx import _get_api
        return _get_api()
    except Exception:
        return None


def collect_breadth(force=False):
    """30s: 全市场涨跌分布（10档 + 涨停跌停数）"""
    if not force and not is_trading_time():
        return
    try:
        if _pytdx_disabled():
            li = CACHE.get("live_index") or {}
            up = int(float(li.get("上涨家数") or 0))
            down = int(float(li.get("下跌家数") or 0))
            if up or down:
                r = {
                    "涨停": 0, ">7%": 0, "5~7%": 0, "3~5%": 0,
                    "0~3%": up, "-0~-3%": down,
                    "-3~-5%": 0, "-5~-7%": 0, "<-7%": 0, "跌停": 0,
                    "_total": up + down, "_source": "live_index_fallback",
                }
            else:
                r = {}
        else:
            r = _fetch_market_data("breadth")
        if r:
            if isinstance(r, dict): r.pop('_meta', None)
            CACHE["breadth"] = r
            CACHE["breadth"]["_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    except Exception as e:
        print(f"  [quotes] collect_breadth error: {e}", file=sys.stderr)


def collect_sectors(force=False):
    """30s: 板块涨跌幅/MA5/20/方向"""
    if not force and not is_trading_time():
        return
    # 从 pools 或 sectors 缓存取板块名列表
    names = _get_sector_names()
    if not names:
        return
    if _pytdx_disabled():
        return
    try:
        r = _fetch_market_data("sector_index", names=names)
        if r:
            if isinstance(r, dict):
                r.pop('_meta', None)
                r.pop('error', None)
            CACHE["live_sectors"] = r
            CACHE["live_sectors"]["_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    except Exception as e:
        print(f"  [quotes] collect_sectors error: {e}", file=sys.stderr)


def _get_sector_names():
    """从 pools.json 和 sectors 缓存拼板块名列表"""
    names = set()
    # 从 pools CACHE
    pools = CACHE.get("pools", {})
    for s in pools.get("sectors", []):
        if s.get("板块"):
            names.add(s["板块"])
    # 从 dashboard_data.json 兜底
    if not names:
        try:
            import json
            ROOT = Path(__file__).resolve().parent.parent.parent
            with open(ROOT / "data" / "dashboard_data.json") as f:
                dd = json.load(f)
            for s in dd.get("sectors", []):
                if s.get("板块"):
                    names.add(s["板块"])
        except Exception:
            pass
    return sorted(names) if names else []


def collect_northbound(force=False):
    """60s: 北向资金实时累计净买入"""
    if not force and not is_trading_time():
        return
    try:
        r = _pipeline_fetch("northbound")
        if r:
            if isinstance(r, dict):
                r.pop('_meta', None)
                r.pop('error', None)
            CACHE["northbound"] = r
            CACHE["northbound"]["_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    except Exception as e:
        print(f"  [quotes] collect_northbound error: {e}", file=sys.stderr)


def collect_hot_list(force=False):
    """5min: 同花顺热榜 + 题材归因"""
    if not force and not is_trading_time():
        return
    try:
        r = _pipeline_fetch("ths_hot")
        if r:
            CACHE["hot_list"] = r
            CACHE["hot_list"]["_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
            # 持久化涨停历史：每日快照保存到 data/zt_history.json
            _save_zt_snapshot(r)
    except Exception as e:
        print(f"  [quotes] collect_hot_list error: {e}", file=sys.stderr)


def _save_zt_snapshot(hot_data):
    """保存涨停快照到 data/zt_history.json，含完整股票数据"""
    ROOT = Path(__file__).resolve().parent.parent.parent
    zt_file = ROOT / "data" / "zt_history.json"
    today = datetime.now().strftime("%Y-%m-%d")

    try:
        # 读取现有历史
        if zt_file.exists():
            with open(zt_file) as f:
                history = json.load(f)
        else:
            history = {}

        # 从 hot_data 提取今日确认涨停股票。
        # hot_data["stocks"] 是同花顺热榜/强势股，不等同于涨停，不能写入涨停历史。
        raw_stocks = hot_data.get("zt_stocks") or []
        today_snapshot = []
        for s in raw_stocks:
            if s.get("name", "").find("ST") >= 0:
                continue
            today_snapshot.append({
                "code": s.get("code", ""),
                "name": s.get("name", ""),
                "zhangfu": s.get("zhangfu"),
                "huanshou": s.get("huanshou"),
                "chengjiaoe": s.get("chengjiaoe"),
                "reason": s.get("reason", ""),
            })

        def _inject_recent():
            keys = sorted(history.keys(), reverse=True)
            recent = {k: history[k] for k in keys[:5]}
            CACHE.setdefault("hot_list", {})["zt_history"] = recent

        if today_snapshot:
            # 如果 gen 已完成收盘写入（含 _meta 标志），不覆盖
            existing_entry = history.get(today, [])
            is_gen_written = any(isinstance(s, dict) and s.get("_meta") for s in existing_entry if isinstance(s, dict))
            if not is_gen_written:
                history[today] = today_snapshot
            # 限制保留最近 60 天
            keys = sorted(history.keys(), reverse=True)
            if len(keys) > 60:
                history = {k: history[k] for k in keys[:60]}

            atomic_write_json(zt_file, history)
        # 注入到 hot_list CACHE（供 W21 前端读取）。即使今日没有确认涨停，也保留历史。
        _inject_recent()
    except Exception as e:
        print(f"  [quotes] _save_zt_snapshot error: {e}", file=sys.stderr)


def collect_kline_15m(force=False):
    """60s: 三大指数15分钟量价（同比昨日）"""
    if not force and not is_trading_time():
        return
    if _pytdx_disabled():
        _collect_kline_15m_eastmoney()
        return
    try:
        with _tdx_lock:
            r = _pipeline_fetch("kline_15m")
        if r and isinstance(r, dict):
            r.pop('_meta', None)
            updated = False
            if '上证15min' in r:
                CACHE['上证15min'] = r['上证15min']
                updated = True
            if '深证15min' in r:
                CACHE['深证15min'] = r['深证15min']
                updated = True
            if '创业15min' in r:
                CACHE['创业15min'] = r['创业15min']
                updated = True
            if updated:
                CACHE['kline_15m_date'] = datetime.now().strftime("%Y-%m-%d")
        else:
            _collect_kline_15m_eastmoney()
    except Exception as e:
        print(f"  [quotes] collect_kline_15m error: {e}", file=sys.stderr)


def _authoritative_available_cash(pnl, history_meta, current_mv):
    """Use settled cash from sync; fall back to the last close only when absent."""
    available = float((pnl or {}).get("可用资金", 0) or 0)
    if available > 0:
        return available
    last_asset = float((history_meta or {}).get("last_total_asset", 0) or 0)
    last_mv = float((history_meta or {}).get("last_mv", 0) or 0)
    if last_asset <= 0:
        return 0
    return max(0, last_asset - (last_mv if last_mv > 0 else current_mv))


def _pct(raw):
    try:
        return float(str(raw or 0).replace("%", "").replace("+", ""))
    except (TypeError, ValueError):
        return 0.0


def _snapshot_from_account(account_state, live_index, timestamp):
    """Convert an authoritative valuation to one disposable chart snapshot."""
    try:
        from scripts.db import is_trading_day
        if not is_trading_day(str(timestamp)[:10]):
            return None
    except Exception:
        pass
    if not account_state.get("valuation_complete"):
        return None
    total_asset = float(account_state.get("total_asset", 0) or 0)
    deposit = float(account_state.get("total_deposit", 0) or 0)
    return {
        "ts": timestamp,
        "date": timestamp[:10],
        "pnl_pct": float(account_state.get("pnl_pct", 0) or 0),
        "nav": round(total_asset / deposit, 6) if deposit > 0 else 1.0,
        "sh_pct": _pct(live_index.get("上证指数涨幅")),
        "sz_pct": _pct(live_index.get("深证指数涨幅")),
        "cy_pct": _pct(live_index.get("创业板指涨幅") or live_index.get("创业指数涨幅")),
        "pos_pct": float(account_state.get("pos_pct", 0) or 0),
        "mv": float(account_state.get("mv", 0) or 0),
        "total_asset": total_asset,
        "deposit": deposit,
    }


def _ensure_index_for_snapshot():
    live_index = CACHE.get("live_index") or {}
    required = ("上证指数涨幅", "深证指数涨幅")
    if all(live_index.get(k) is not None for k in required):
        return live_index
    collect_index(force=True)
    return CACHE.get("live_index") or live_index


def log_pnl_snapshot(force=False):
    """300s: persist one disposable snapshot derived from account SSOT."""
    if not force and not is_trading_time():
        return
    conn_opened = False
    try:
        from scripts.account_ssot import load_current_account_state
        from scripts.db import init_db, insert_daily_summary, insert_snapshot, query_pnl_summary, close_conn
        init_db()
        conn_opened = True
        now = datetime.now()
        state = load_current_account_state(CACHE.get("live_quotes", {}))

        # 快照偏差告警：对比最近一条快照与 SSOT 资产的偏离
        recent = query_pnl_summary()
        if recent.get("today_snapshots", 0) > 0 and recent.get("total_asset") is not None:
            ssot_asset = state.get("total_asset", 0)
            snap_asset = recent["total_asset"]
            if snap_asset > 0:
                deviation = abs(ssot_asset - snap_asset) / snap_asset
                if deviation > 0.05:  # 偏离超过 5%
                    print(f"  [quotes] ⚠️  SNAPSHOT DEVIATION: SSOT={ssot_asset} vs last_snapshot={snap_asset} ({deviation:.1%})")
                    # 写入告警快照（低 authority 标记）
                    CACHE["_snapshot_alert"] = {
                        "ts": now.strftime("%Y-%m-%dT%H:%M:%S"),
                        "ssot_asset": ssot_asset,
                        "snap_asset": snap_asset,
                        "deviation_pct": round(deviation * 100, 2),
                    }

        live_index = _ensure_index_for_snapshot()
        row = _snapshot_from_account(state, live_index, now.strftime("%Y-%m-%dT%H:%M:%S"))
        if row is None:
            print("  [quotes] PnL snapshot skipped: incomplete account valuation")
            return
        insert_snapshot(row)

        # 日结由 generate_closing_anchor（15:05）统一处理，避免双重写入
        # 此处只写日内快照，不写 daily_summary；15:00 之后的快照仍写入但不加锁
    except Exception as e:
        print(f"  [quotes] log_pnl_snapshot error: {e}", file=sys.stderr)
    finally:
        if conn_opened:
            close_conn()


def set_stock_codes(codes):
    """设置需要查询的股票代码列表"""
    CACHE["_stock_codes"] = codes
