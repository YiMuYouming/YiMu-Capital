#!/usr/bin/env python3
"""poll_live.py — 多源实时数据轮询 → dashboard_live.json (Layer 2)
v2.0: PyTDX(个股+指数) + 东方财富(板块，境外IP可能受限) + easyquotation(兜底)

已知限制：东方财富板块API（push2.eastmoney.com）对境外IP返回rc=102。
板块数据暂用Layer 1基线（复盘笔记），后续可通过VPN或国内IP解决。

用法:
  python3 poll_live.py                 # 单次运行，输出到 stdout
  python3 poll_live.py --watch         # 守护模式，写入 data/dashboard_live.json
  python3 poll_live.py --no-sectors    # 跳过板块数据
"""

import json, os, sys, time, argparse, re
from pathlib import Path
from datetime import datetime, timedelta

ROOT_DIR = Path(__file__).resolve().parent.parent
DASHBOARD_DATA = ROOT_DIR / "data/dashboard_data.json"
OUTPUT_FILE = ROOT_DIR / "data/dashboard_live.json"

# === 板块名称映射：复盘笔记名称 → 东方财富 BK 代码 ===
# 首次运行自动匹配，匹配不到的需手动补充
SECTOR_NAME_MAP = {}

# 已知映射（后续通过 auto_discover_sectors() 自动扩充）
_SECTOR_SEEDS = {
    "机器人": "BK1192",
    "光通信": "BK0602",
    "算力租赁": "BK1131",
    "算力": "BK1131",
    "航天/军工": "BK0489",
    "航天": "BK0489",
    "军工": "BK0489",
    "PCB": "BK0433",
    "半导体": "BK0477",
    "电力": "BK0423",
    "锂电": "BK0573",
}
SECTOR_NAME_MAP.update(_SECTOR_SEEDS)

# 东方财富 sector 缓存（全量一次拉取，盘中复用）
_EM_SECTORS_CACHE = None
_EM_SECTORS_CACHE_TIME = 0

# TDX 板块指数代码映射（复盘笔记名称 → 88xxxx）
_TDX_SECTOR_CODE_MAP = {
    "机器人": "880905",
    "光通信": "880619",
    "半导体": "880491",
    "PCB": "880542",
    "锂电": "880534",
    "航天/军工": "880490",  # 国防军工
    # TODO: 算力租赁、电力 待查代码
}

# PyTDX 连接缓存
_tdx_api = None
_tdx_connect_time = 0
_tdx_server_ip = None
_tdx_fail_count = 0
_tdx_using_fallback = False

# 量比计算缓存：{code: avg_daily_vol}
_vol_avg_cache = {}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr)


# ========== 股票代码提取 ==========

def get_stock_codes():
    """从 dashboard_data.json 提取全部涉及股票的代码（全量 SSOT）"""
    codes = set()
    try:
        with open(DASHBOARD_DATA) as f:
            data = json.load(f)

        for p in data.get("positions", []):
            code = str(p.get("代码", ""))
            if code.isdigit() and len(code) == 6:
                codes.add(code)

        for pool_key in ["lianban_pool", "trend_pool"]:
            for s in data.get(pool_key, []):
                code = str(s.get("代码", ""))
                if code.isdigit() and len(code) == 6:
                    codes.add(code)

        for a in (data.get("decision", {}).get("锚定股状态") or []):
            code = str(a.get("代码", ""))
            if code.isdigit() and len(code) == 6:
                codes.add(code)

        for o in (data.get("decision", {}).get("今日操作") or []):
            code = str(o.get("代码", ""))
            if code.isdigit() and len(code) == 6:
                codes.add(code)

    except Exception as e:
        log(f"读取 dashboard_data.json 失败: {e}")

    codes = sorted(codes)
    log(f"发现 {len(codes)} 只股票: {', '.join(codes[:10])}{'...' if len(codes) > 10 else ''}")
    return codes


def to_tdx_code(code):
    """6位代码 → TDX (market, code) 格式"""
    code = str(code).zfill(6)
    if code.startswith("6") or code.startswith("688"):
        return (1, code)  # 上海
    elif code.startswith(("0", "3")):
        return (0, code)  # 深圳
    return None


# ========== PyTDX 数据获取 ==========

def _get_tdx_api():
    """获取或创建 PyTDX 连接（含自动重连）"""
    global _tdx_api, _tdx_connect_time, _tdx_server_ip, _tdx_fail_count

    # 连接有效期为 60s
    if _tdx_api and (time.time() - _tdx_connect_time) < 60:
        return _tdx_api

    from pytdx.hq import TdxHq_API

    servers = [
        ("110.41.147.114", 7709),
        ("119.147.212.81", 7709),
        ("124.70.176.52", 7709),
        ("47.100.236.28", 7709),
        ("121.36.54.217", 7709),
        ("124.71.85.110", 7709),
    ]

    if _tdx_api:
        try:
            _tdx_api.disconnect()
        except Exception:
            pass

    api = TdxHq_API()
    for ip, port in servers:
        try:
            if api.connect(ip, port):
                _tdx_api = api
                _tdx_connect_time = time.time()
                _tdx_server_ip = ip
                _tdx_fail_count = 0
                return api
        except Exception:
            continue

    _tdx_fail_count += 1
    return None


def fetch_quotes_pytdx(codes):
    """PyTDX 批量个股查询 → {code: {最新价, 涨幅, 量比, 换手}}"""
    api = _get_tdx_api()
    if not api:
        return None

    global _tdx_fail_count

    tdx_codes = []
    code_map = {}
    for c in codes:
        tdx = to_tdx_code(c)
        if tdx:
            tdx_codes.append(tdx)
            code_map[c] = tdx

    if not tdx_codes:
        return {}

    try:
        raw = api.get_security_quotes(tdx_codes)
        if not raw:
            _tdx_fail_count += 1
            return None
    except Exception as e:
        log(f"PyTDX 个股查询失败: {e}")
        _tdx_fail_count += 1
        return None

    result = {}
    now = datetime.now()
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    minutes_traded = max(1, min(240, (now - market_open).total_seconds() / 60))

    for row in raw:
        code = row.get("code", "")
        if not code:
            continue

        price = row.get("price", 0)
        last_close = row.get("last_close", 1)
        pct_chg = round((price - last_close) / last_close * 100, 2) if last_close else 0
        vol = row.get("vol", 0)

        # 量比计算
        vol_ratio = _compute_volume_ratio(api, code, vol, minutes_traded)

        # 换手率：尝试从 reversed_bytes 解码
        turnover = _decode_turnover(row, code)

        result[code] = {
            "最新价": price,
            "涨幅": f"{pct_chg:+.2f}%",
            "量比": f"{vol_ratio:.2f}" if vol_ratio else "—",
            "换手": f"{turnover:.2f}%" if turnover else "—",
        }

    return result


def _compute_volume_ratio(api, code, current_vol, minutes_traded):
    """量比 = 当前成交量 / (近5日均量 / 240 * 已交易分钟数)"""
    global _vol_avg_cache
    if current_vol <= 0:
        return None

    cache_key = str(code)
    if cache_key not in _vol_avg_cache:
        try:
            # 确定市场
            mkt = 1 if (str(code).startswith("6") or str(code).startswith("688")) else 0
            bars = api.get_security_bars(9, mkt, str(code), 0, 5)
            if bars and len(bars) >= 3:
                avg_vol = sum(b.get("vol", 0) for b in bars) / len(bars)
                _vol_avg_cache[cache_key] = avg_vol
            else:
                return None
        except Exception:
            return None

    avg_vol = _vol_avg_cache.get(cache_key)
    if not avg_vol or avg_vol <= 0:
        return None

    expected_vol = avg_vol * minutes_traded / 240
    if expected_vol <= 0:
        return None

    return round(current_vol / expected_vol, 2)


def _decode_turnover(row, code):
    """尝试从 TDX reversed_bytes 解码换手率
    已知问题：reversed_bytes3 低16位并非直接的换手率编码，可能产生虚假高值。
    暂时跳过解码，返回 None 走基线数据。
    """
    # TDX Level-1 标准行情中换手率不可靠，后续可通过东方财富API或流通股本计算
    return None


def fetch_index_pytdx():
    """PyTDX 三大指数查询 → live_index"""
    api = _get_tdx_api()
    if not api:
        return None

    # 上证综指、深证成指、创业板指
    idx_map = {
        "000001": "上证指数",
        "399001": "深证指数",
        "399006": "创业指数",
    }
    idx_codes = [(1, "000001"), (0, "399001"), (0, "399006")]

    try:
        raw = api.get_security_quotes(idx_codes)
        if not raw:
            return None
    except Exception as e:
        log(f"PyTDX 指数查询失败: {e}")
        return None

    result = {}
    for row in raw:
        code = row.get("code", "")
        name = idx_map.get(code)
        if not name:
            continue

        price = row.get("price", 0)
        last_close = row.get("last_close", 1)
        pct = round((price - last_close) / last_close * 100, 2) if last_close else 0
        amount = row.get("amount", 0)

        result[name] = price
        result[f"{name}涨幅"] = f"{pct:+.2f}%"
        result[f"{name}成交额"] = _format_amount(amount)

    # 成交额 = 上证 + 深证（不含创业板，创业板是深证子集，会重复计数）
    total_amt = sum(
        row.get("amount", 0) for row in raw if row.get("code", "") in ("000001", "399001")
    )
    result["成交额"] = _format_amount(total_amt)
    result["成交额差"] = "—"

    return result


def _format_amount(amt):
    """金额格式化：元 → 亿/万亿"""
    if not amt or amt == 0:
        return "—"
    yi = amt / 1e8
    if yi >= 10000:
        return f"{yi/10000:.2f}万亿"
    return f"{yi:.2f}亿"


# ========== 东方财富板块数据 ==========

def _load_em_sectors():
    """加载东方财富全量概念板块列表（缓存1小时）"""
    global _EM_SECTORS_CACHE, _EM_SECTORS_CACHE_TIME

    if _EM_SECTORS_CACHE and (time.time() - _EM_SECTORS_CACHE_TIME) < 3600:
        return _EM_SECTORS_CACHE

    try:
        import requests
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1", "pz": "500", "po": "1", "np": "1",
            "fltt": "2", "invt": "2",
            "fid": "f3", "fs": "m:90+t2",  # 概念板块
            "fields": "f2,f3,f12,f14",
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "https://quote.eastmoney.com/",
        }
        r = requests.get(url, params=params, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            diff = data.get("data", {}).get("diff", [])
            sectors = {}
            for item in diff:
                name = item.get("f14", "")
                code = item.get("f12", "")
                if name and code:
                    sectors[name] = code
            _EM_SECTORS_CACHE = sectors
            _EM_SECTORS_CACHE_TIME = time.time()
            log(f"加载东方财富板块列表: {len(sectors)} 个")
            return sectors
    except Exception as e:
        log(f"加载东方财富板块列表失败: {e}")

    return _EM_SECTORS_CACHE or {}


def _resolve_sector_code(name):
    """复盘笔记板块名 → 东方财富 BK 代码"""
    # 先查已知映射
    if name in SECTOR_NAME_MAP:
        return SECTOR_NAME_MAP[name]

    # 模糊匹配东方财富板块列表
    em_sectors = _load_em_sectors()
    if name in em_sectors:
        SECTOR_NAME_MAP[name] = em_sectors[name]
        return em_sectors[name]

    # 关键词匹配
    for em_name, em_code in em_sectors.items():
        if name in em_name or em_name in name:
            SECTOR_NAME_MAP[name] = em_code
            log(f"板块模糊匹配: '{name}' → '{em_name}' ({em_code})")
            return em_code

    log(f"未匹配板块: '{name}'，请在 SECTOR_NAME_MAP 中手动添加")
    return None


def fetch_sectors_eastmoney(sector_names):
    """东方财富板块查询 → live_sectors 格式"""
    if not sector_names:
        return {}

    codes = []
    name_map = {}
    for name in sector_names:
        bk = _resolve_sector_code(name)
        if bk:
            codes.append(bk)
            name_map[bk] = name

    if not codes:
        return {}

    try:
        import requests
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1", "pz": str(len(codes)),
            "po": "1", "np": "1",
            "fltt": "2", "invt": "2",
            "fid": "f3",
            "fs": ",".join(f"b:{c}" for c in codes),
            "fields": "f2,f3,f12,f62,f104,f20",
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "https://quote.eastmoney.com/",
        }
        r = requests.get(url, params=params, headers=headers, timeout=10)
        if r.status_code != 200:
            return {}

        data = r.json()
        diff = data.get("data", {}).get("diff", [])

        result = {}
        for item in diff:
            em_code = item.get("f12", "")
            name = name_map.get(em_code)
            if not name:
                continue

            price = item.get("f2", 0)
            pct = item.get("f3", 0)
            inflow = item.get("f62", 0)
            zt_count = item.get("f104", 0)
            ma5 = item.get("f20", 0)  # 5日线

            result[name] = {
                "涨跌幅": pct,
                "主力净流入": _format_amount(inflow) if inflow else "—",
                "5日线": "站上" if (price and ma5 and price > ma5) else ("跌破" if (price and ma5) else "—"),
                "今日涨停数": zt_count if zt_count else 0,
            }

        return result

    except Exception as e:
        log(f"东方财富板块查询失败: {e}")
        return {}


# ========== easyquotation 兜底 ==========

def fetch_quotes_fallback(codes):
    """easyquotation 兜底（PyTDX 连续失败后切换）"""
    try:
        from easyquotation import use
        eq = use("sina")
        all_data = eq.stocks(codes)
        result = {}
        for code in codes:
            d = all_data.get(code, {})
            if d:
                result[code] = {
                    "最新价": d.get("now", d.get("price", 0)),
                    "涨幅": d.get("涨跌(%)", "—"),
                    "量比": d.get("量比", "—"),
                    "换手": d.get("换手(%)", "—"),
                }
        return result
    except Exception as e:
        log(f"easyquotation 兜底查询失败: {e}")
        return {}


def get_sector_names():
    """从 dashboard_data.json 提取板块名称列表"""
    try:
        with open(DASHBOARD_DATA) as f:
            data = json.load(f)
        return [s["板块"] for s in data.get("sectors", []) if s.get("板块")]
    except Exception:
        return []


# ========== 15min 量价（上证/深证/创业）==========

_15MIN_YESTERDAY = {}  # {index_code: {time_key: vol}} 昨日缓存
_YESTERDAY_DAILY_AMT = {}  # {index_code: amount} 昨日全日成交额
_15MIN_INDEXES = {
    "上证15min": ("000001", 1),
    "深证15min": ("399001", 0),
    "创业15min": ("399006", 0),
}


def _load_yesterday_15min(code, market):
    """加载昨日15min K线，缓存成交量"""
    api = _get_tdx_api()
    if not api:
        return
    try:
        bars = api.get_index_bars(1, market, code, 0, 60)
        if not bars:
            return
        today_str = datetime.now().strftime("%Y-%m-%d")
        yesterday_bars = {}
        for b in bars:
            dt = b.get("datetime", "")
            if today_str not in dt and dt:
                time_key = dt.split(" ")[-1][:5] if " " in dt else dt[-5:]
                date_part = dt.split(" ")[0] if " " in dt else dt[:10]
                if date_part not in yesterday_bars:
                    yesterday_bars[date_part] = {}
                yesterday_bars[date_part][time_key] = b.get("vol", 0)
        if yesterday_bars:
            latest_date = sorted(yesterday_bars.keys())[-1]
            _15MIN_YESTERDAY[code] = yesterday_bars[latest_date]
    except Exception:
        pass


def _get_yesterday_daily_amt(code, market):
    """取昨日日线成交额（一次缓存）"""
    global _YESTERDAY_DAILY_AMT
    if code in _YESTERDAY_DAILY_AMT:
        return _YESTERDAY_DAILY_AMT[code]
    api = _get_tdx_api()
    if not api:
        return 0
    try:
        bars = api.get_index_bars(9, market, code, 0, 5)
        today_str = datetime.now().strftime("%Y-%m-%d")
        for b in reversed(bars):
            dt = b.get("datetime", "")
            if today_str not in dt and dt:
                amt = b.get("amount", 0)
                _YESTERDAY_DAILY_AMT[code] = amt
                return amt
    except Exception:
        pass
    return 0


def fetch_15min_bars(code, market, cache_key):
    """通用15min量价"""
    global _15MIN_YESTERDAY
    api = _get_tdx_api()
    if not api:
        return []

    if code not in _15MIN_YESTERDAY:
        _load_yesterday_15min(code, market)

    try:
        bars = api.get_index_bars(1, market, code, 0, 20)
        if not bars:
            return []
    except Exception:
        return []

    yesterday = _15MIN_YESTERDAY.get(code, {})
    today_str = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now()
    current_min = now.hour * 60 + now.minute
    result = []
    for b in bars:
        dt = b.get("datetime", "")
        if today_str not in dt:
            continue
        time_key = dt.split(" ")[-1][:5] if " " in dt else dt[-5:]
        slot_end_min = int(time_key.split(":")[0]) * 60 + int(time_key.split(":")[1])
        if current_min < slot_end_min:
            continue
        open_p = b.get("open", 0)
        close_p = b.get("close", 0)
        vol = b.get("vol", 0)
        chg = round((close_p - open_p) / open_p * 100, 2) if open_p else 0
        yesterday_vol = yesterday.get(time_key, vol)
        vol_ratio = round(vol / yesterday_vol, 2) if yesterday_vol > 0 else 1.0
        result.append({
            "t": time_key,
            "chg": chg,
            "vol": vol,
            "volRatio": vol_ratio,
            "amount": b.get("amount", 0),
        })

    # 追加累计汇总
    if result:
        cum_amount = sum(r["amount"] for r in result)
        # 用昨日vol比例估算昨日累计成交额
        total_vol = sum(r["vol"] for r in result)
        total_yv = sum(yesterday.get(r["t"], r["vol"]) for r in result)
        cum_ratio = round(total_vol / total_yv, 2) if total_yv > 0 else 1.0
        # 昨日全日成交额从日线直接获取
        cum_yesterday_amt = _get_yesterday_daily_amt(code, market)
        result.append({
            "t": "累计",
            "chg": 0,
            "vol": 0,
            "volRatio": cum_ratio,
            "amount": cum_amount,
            "cumYesterdayAmt": round(cum_yesterday_amt),
            "_cum": True,
        })

    return result


# ========== TDX 板块指数查询 ==========

def fetch_sectors_tdx(sector_names):
    """通过 PyTDX 查询板块指数 → live_sectors 格式"""
    if not sector_names:
        return {}

    api = _get_tdx_api()
    if not api:
        return {}

    # 构建代码→名称映射
    code_to_name = {}
    tdx_codes = []
    for name in sector_names:
        tdx_code = _TDX_SECTOR_CODE_MAP.get(name)
        if tdx_code:
            tdx_codes.append((1, tdx_code))
            code_to_name[tdx_code] = name

    if not tdx_codes:
        return {}

    try:
        raw = api.get_security_quotes(tdx_codes)
        if not raw:
            return {}
    except Exception as e:
        log(f"TDX 板块查询失败: {e}")
        return {}

    result = {}
    for row in raw:
        code = row.get("code", "")
        name = code_to_name.get(code)
        if not name:
            continue

        price = row.get("price", 0)
        last_close = row.get("last_close", 1)
        pct = round((price - last_close) / last_close * 100, 2) if last_close else 0
        amount = row.get("amount", 0)

        result[name] = {
            "涨跌幅": pct,
            "主力净流入": "—",     # TDX 板块指数无资金流向
            "5日线": "—",          # 需额外查 K 线
            "今日涨停数": "—",      # TDX 板块指数无涨停数
        }

    return result


# ========== 数据组装 ==========

_last_sectors_cache = {}  # 板块数据缓存，非刷新轮次复用

def build_live_data(codes, skip_sectors=False):
    """组装完整 live 数据"""
    global _tdx_using_fallback, _tdx_fail_count, _last_sectors_cache

    data = {"live_sectors": _last_sectors_cache}  # 默认复用上次板块数据

    # 个股 + 指数
    if _tdx_fail_count >= 3 and not _tdx_using_fallback:
        _tdx_using_fallback = True
        log("PyTDX 连续3次失败，切换到 easyquotation 兜底")

    if _tdx_using_fallback:
        data["live_quotes"] = fetch_quotes_fallback(codes)
        data["live_index"] = {}
    else:
        quotes = fetch_quotes_pytdx(codes)
        index_data = fetch_index_pytdx()

        if quotes is None and _tdx_fail_count >= 3:
            _tdx_using_fallback = True
            log("切换到 easyquotation")
            data["live_quotes"] = fetch_quotes_fallback(codes)
            data["live_index"] = {}
        else:
            data["live_quotes"] = quotes or {}
            data["live_index"] = index_data or {}

        # 每60s尝试切回PyTDX
        if _tdx_using_fallback and _tdx_fail_count == 0:
            _tdx_using_fallback = False
            log("切回 PyTDX")

    # 15min量价（三大指数）
    for key, (code, market) in _15MIN_INDEXES.items():
        data[key] = fetch_15min_bars(code, market, key)

    # 板块（通过 PyTDX 板块指数查询，无需外部 HTTP）
    if not skip_sectors:
        sector_names = get_sector_names()
        if sector_names:
            result = fetch_sectors_tdx(sector_names)
            if result:
                data["live_sectors"] = result
                _last_sectors_cache = result  # 更新缓存

    data["meta"] = {
        "fetched": datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "source": "easyquotation" if _tdx_using_fallback else "PyTDX",
        "stocks_count": len(codes),
    }

    return data


# ========== 守护模式 ==========

def watch_mode(interval_stocks=5, interval_sectors=30, skip_sectors=False):
    """守护模式：分层轮询写入 dashboard_live.json"""
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    log(f"启动: 个股/指数 {interval_stocks}s, 板块 {interval_sectors}s → {OUTPUT_FILE}")
    codes = get_stock_codes()
    last_sector_update = -999  # 首次立即查板块
    write_count = 0
    error_count = 0
    last_source = None

    try:
        while True:
            now = time.time()
            need_sectors = (not skip_sectors) and (now - last_sector_update >= interval_sectors)

            data = build_live_data(codes, skip_sectors=(not need_sectors))

            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            write_count += 1

            src = data["meta"]["source"]
            n_stocks = len(data.get("live_quotes", {}))
            # 只在数据源切换或异常时出声
            if src != last_source:
                log(f"{'⚠️ 兜底模式' if src == 'easyquotation' else 'PyTDX 正常'} — {n_stocks}只股票")
                last_source = src

            if need_sectors:
                last_sector_update = now

            time.sleep(interval_stocks)

    except KeyboardInterrupt:
        log(f"已停止 ({write_count}次写入, {error_count}次异常)")


def main():
    parser = argparse.ArgumentParser(description="多源实时数据轮询 v2.0")
    parser.add_argument("--watch", action="store_true", help="守护模式")
    parser.add_argument("--no-sectors", action="store_true", help="跳过板块数据")
    parser.add_argument("--interval", type=int, default=5, help="个股轮询间隔(秒)")
    parser.add_argument("--sector-interval", type=int, default=30, help="板块轮询间隔(秒)")
    args = parser.parse_args()

    if args.watch:
        watch_mode(
            interval_stocks=args.interval,
            interval_sectors=args.sector_interval,
            skip_sectors=args.no_sectors,
        )
    else:
        codes = get_stock_codes()
        data = build_live_data(codes, skip_sectors=args.no_sectors)
        print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
