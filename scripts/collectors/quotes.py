"""quotes.py — T1 实时行情采集器（替代 poll_live 内联 PyTDX）

使用 YM-data-pipeline fetch() 统一接口，不再直接调 PyTDX/easyquotation。
bridge.py APScheduler 调度：5s/30s/300s 三档频率。
"""
import os, sys, json, threading
from pathlib import Path
from datetime import datetime, time as _time_module

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
    return (_time_module(9, 15) <= t <= _time_module(11, 30)) or (_time_module(13, 0) <= t <= _time_module(15, 10))


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
            if isinstance(r, dict): r.pop('_meta', None)
            li = CACHE.get("live_index", {})
            li.update(r)
            li["_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
            CACHE["live_index"] = li
    except Exception as e:
        print(f"  [quotes] collect_index error: {e}", file=sys.stderr)


def collect_yesterday_compare(force=False):
    """30s: 成交额较昨日同时段对比"""
    if not force and not is_trading_time():
        return
    if _pytdx_disabled():
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
            CACHE["live_index"] = li
    except Exception as e:
        print(f"  [quotes] collect_yesterday_compare error: {e}", file=sys.stderr)


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
        r = _fetch_market_data("breadth")
        if (not r or (isinstance(r, dict) and not any(k in r for k in ("_total", "涨停", "0~3%", "-0~-3%")))) and _pytdx_disabled():
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

        # 从 hot_data 提取今日涨停股票
        raw_stocks = hot_data.get("zt_stocks") or hot_data.get("stocks") or []
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
            # 注入到 hot_list CACHE（供 W21 前端读取）
            CACHE["hot_list"]["zt_history"] = dict(list(history.items())[:5])  # 最近5天
    except Exception as e:
        print(f"  [quotes] _save_zt_snapshot error: {e}", file=sys.stderr)


def collect_kline_15m(force=False):
    """60s: 三大指数15分钟量价（同比昨日）"""
    if not force and not is_trading_time():
        return
    if _pytdx_disabled():
        return
    try:
        with _tdx_lock:
            r = _pipeline_fetch("kline_15m")
        if r and isinstance(r, dict):
            r.pop('_meta', None)
            if '上证15min' in r: CACHE['上证15min'] = r['上证15min']
            if '深证15min' in r: CACHE['深证15min'] = r['深证15min']
            if '创业15min' in r: CACHE['创业15min'] = r['创业15min']
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

        row = _snapshot_from_account(
            state, CACHE.get("live_index") or {}, now.strftime("%Y-%m-%dT%H:%M:%S")
        )
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
