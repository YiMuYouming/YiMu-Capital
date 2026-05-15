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
from datetime import datetime, timedelta, date

try:
    from ym_stock_data.fetch import fetch
except ImportError:
    import sys as _sys
    _pipeline_path = os.path.expanduser("~/Documents/YM_Capital/YM-data-pipeline")
    if _pipeline_path not in _sys.path:
        _sys.path.insert(0, _pipeline_path)
    try:
        from ym_stock_data.fetch import fetch
    except ImportError:
        fetch = None

ROOT_DIR = Path(__file__).resolve().parent.parent
DASHBOARD_DATA = ROOT_DIR / "data/dashboard_data.json"
OUTPUT_FILE = ROOT_DIR / "data/dashboard_live.json"
# PnL 数据库（db.py SQLite）
try:
    from scripts.db import init_db, insert_snapshot, insert_daily_summary
except ImportError:
    import sys as _sys
    _scripts_path = os.path.join(os.path.dirname(__file__), '..', 'scripts')
    if _scripts_path not in _sys.path:
        _sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from scripts.db import init_db, insert_snapshot, insert_daily_summary

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
    # === 涨停日志出现板块 → TDX概念板块代码 ===
    # 科技/算力
    "算力": "880565",
    "算力租赁": "880565",
    "算力产业链": "880565",
    "东数西算": "880565",
    "算力/光通信/PCB": "880565",  # 取主方向
    "算力/半导体产业链": "880565",
    "算力/半导体": "880565",
    # 光通信/CPO
    "光通信": "880619",
    "CPO/光通信": "880619",
    "光通信/CPO": "880619",
    "光通信/光纤": "880619",
    # 半导体
    "半导体": "880491",
    "半导体产业链": "880491",
    "半导体封装": "880491",
    "半导体/存储": "880491",
    "存储芯片": "880589",
    "电子特气": "880491",
    # PCB
    "PCB": "880542",
    "PCB链": "880542",
    "PCB链/铜箔": "880542",
    "PCB/电子": "880542",
    # 机器人
    "机器人": "880905",
    # 电力
    "电力": "880582",
    "电力/算电": "880582",
    "电力/燃气轮机": "880582",
    "电力/燃气": "880582",
    "电力/电缆": "880582",
    "电力改革": "880582",
    # 新能源
    "锂电": "880534",
    "锂电池": "880534",
    "电池": "880534",
    "光伏": "880544",
    "风电": "880543",
    "储能": "880573",
    "氢能": "880574",
    # 航天/军工
    "航天": "880490",
    "航天/军工": "880490",
    "国防军工": "880490",
    "商业航天": "880490",
    "航天/光伏": "880490",  # 取航天方向
    # AI/软件
    "人工智能": "880569",
    "AI": "880569",
    "AI应用": "880569",
    "ChatGPT": "880569",
    "数据要素": "880567",
    "信创": "880568",
    "数字经济": "880567",
    # 消费/医药
    "医药": "880400",
    "大消费": "880375",
    # 化工/材料
    "化工": "880324",
    "化工/新材料": "880324",
    # 有色/稀土
    "有色金属": "880535",
    "有色/钨/稀土": "880535",
    "稀土永磁": "880335",
    # 环保/水利
    "环保/水利": "880453",
    "环保": "880453",
    # 汽车
    "汽车零部件": "880452",
    # 地产
    "地产产业链": "880482",
    # 建筑
    "建筑/装饰": "880596",
    # 液冷
    "液冷": "880570",
    "液冷服务器": "880570",
    # 其他
    "光电/LED": "880549",
    "低空经济": "880905",
    # 以下为无对应TDX板块的纯主题概念，跳过查询：
    # "业绩增长", "并购重组", "华为合作", "其他概念"
}

def _resolve_tdx_sector(name):
    """解析板块名称 → TDX代码，支持别名"""
    if not name:
        return None
    if name in _TDX_SECTOR_CODE_MAP:
        return _TDX_SECTOR_CODE_MAP[name]
    for key, code in _TDX_SECTOR_CODE_MAP.items():
        if key in name or name in key:
            return code
    return None

# PyTDX 连接缓存
_tdx_api = None
_tdx_connect_time = 0
_tdx_server_ip = None
_tdx_fail_count = 0
_tdx_using_fallback = False

# 量比计算缓存：{code: avg_daily_vol}
_vol_avg_cache = {}
# 均线缓存：{code: {ma5_d, ma10_d, ma20_d, ma10_60m, is_strong}}，每日计算一次
_ma_cache = {}
# 60分钟K线缓存：{code: [(time, open, high, low, close, vol), ...]}
_60m_cache = {}


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

    # 查询成功 → 重置失败计数
    _tdx_fail_count = 0

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

        # 均线（每日计算一次，盘中不变）
        mas = _get_mas(api, code, price)

        result[code] = {
            "最新价": price,
            "涨幅": f"{pct_chg:+.2f}%",
            "量比": f"{vol_ratio:.2f}" if vol_ratio else "—",
            "换手": f"{turnover:.2f}%" if turnover else "—",
            "MA5_d": mas.get("ma5_d"),        # 日线MA5（方向/强弱）
            "MA10_d": mas.get("ma10_d"),      # 日线MA10
            "MA20_d": mas.get("ma20_d"),      # 日线MA20
            "MA10_60m": mas.get("ma10_60m"),  # 60分钟MA10（核心回踩锚点·强势股）
            "MA10_60m_dir": mas.get("ma10_60m_dir", "—"),
            "is_strong": mas.get("_strong", False),  # 强势趋势股标记
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


def _get_mas(api, code, current_price):
    """获取均线：日线 MA5/MA10/MA20 + 60分钟 MA10 + 强势/普通分类"""
    global _ma_cache, _60m_cache
    cache_key = str(code)
    if cache_key in _ma_cache:
        return _ma_cache[cache_key]

    mas = {}
    mkt = 1 if (str(code).startswith("6") or str(code).startswith("688")) else 0

    # 1. 日线均线 MA5/MA10/MA20
    try:
        bars_d = api.get_security_bars(9, mkt, str(code), 0, 25)
        if bars_d:
            closes = [b.get("close", 0) for b in bars_d if b.get("close", 0) > 0]
            for n, key in [(5, "ma5_d"), (10, "ma10_d"), (20, "ma20_d")]:
                if len(closes) >= n:
                    mas[key] = round(sum(closes[-n:]) / n, 2)

            # 强势趋势股判定：近5日收盘从未跌破MA5
            if len(closes) >= 10 and mas.get("ma5_d"):
                ma5 = mas["ma5_d"]
                recent_closes = closes[-5:]  # 最近5天
                # 用昨天的MA5判断（今天盘中MA5可能还没到位）
                prev_closes = closes[-6:-1] if len(closes) >= 6 else closes[-5:]
                prev_ma5 = round(sum(prev_closes) / min(5, len(prev_closes)), 2)
                below_ma5 = sum(1 for c in recent_closes if c < ma5)
                mas["_strong"] = below_ma5 == 0  # True = 强势趋势股
    except Exception:
        pass

    # 2. 60分钟均线 MA10（近10根60分钟K线）
    try:
        bars_60m = api.get_security_bars(3, mkt, str(code), 0, 15)
        if bars_60m:
            _60m_cache[cache_key] = []
            closes_60m = []
            for b in bars_60m[-12:]:  # 取最近12根
                c = b.get("close", 0)
                if c > 0:
                    closes_60m.append(c)
                _60m_cache[cache_key].append({
                    "time": b.get("datetime", ""),
                    "open": b.get("open", 0),
                    "close": b.get("close", 0),
                    "high": b.get("high", 0),
                    "low": b.get("low", 0),
                    "vol": b.get("vol", 0),
                })
            if len(closes_60m) >= 8:
                mas["ma10_60m"] = round(sum(closes_60m[-10:]) / min(10, len(closes_60m)), 2)
                # 60分钟MA10方向：比较前5根和后5根的均值
                half = len(closes_60m) // 2
                prev_half = closes_60m[:half]
                later_half = closes_60m[half:]
                prev_avg = sum(prev_half) / len(prev_half) if prev_half else 0
                later_avg = sum(later_half) / len(later_half) if later_half else 0
                if later_avg > prev_avg * 1.005:
                    mas["ma10_60m_dir"] = "向上"
                elif later_avg < prev_avg * 0.995:
                    mas["ma10_60m_dir"] = "向下"
                else:
                    mas["ma10_60m_dir"] = "走平"
    except Exception:
        pass

    if mas:
        _ma_cache[cache_key] = mas
    return mas


def _decode_turnover(row, code):
    """尝试从 TDX reversed_bytes 解码换手率
    已知问题：reversed_bytes3 低16位并非直接的换手率编码，可能产生虚假高值。
    暂时跳过解码，返回 None 走基线数据。
    """
    # TDX Level-1 标准行情中换手率不可靠，后续可通过东方财富API或流通股本计算
    return None


def _get_market_vol_ratio():
    """全市场量比 = 今日累计量 / 昨日同时段累计量（上证15min数据）"""
    global _15MIN_YESTERDAY
    if '000001' not in _15MIN_YESTERDAY:
        _load_yesterday_15min('000001', 1)
    yest_data = _15MIN_YESTERDAY.get('000001', {})
    if not yest_data:
        return None
    api = _get_tdx_api()
    if not api:
        return None
    try:
        bars = api.get_index_bars(1, 1, '000001', 0, 20)
        if not bars:
            return None
        today_str = datetime.now().strftime("%Y-%m-%d")
        now = datetime.now()
        current_min = now.hour * 60 + now.minute
        today_vol = 0
        yest_vol = 0
        for b in bars:
            dt = b.get("datetime", "")
            if today_str in dt:
                time_key = dt.split(" ")[-1][:5] if " " in dt else dt[-5:]
                slot_end = int(time_key.split(":")[0]) * 60 + int(time_key.split(":")[1])
                if current_min >= slot_end:
                    today_vol += b.get("vol", 0)
                    yv = yest_data.get(time_key, {})
                    yest_vol += yv.get("vol", b.get("vol", 0)) if isinstance(yv, dict) else (yv if isinstance(yv, (int, float)) else b.get("vol", 0))
        if yest_vol > 0 and today_vol > 0:
            return round(today_vol / yest_vol, 2)
    except Exception:
        pass
    return None


def _get_cum_yesterday_amt():
    """昨日同时段累计成交额（上证+深证，从15min缓存推算）"""
    total = 0
    now = datetime.now()
    current_min = now.hour * 60 + now.minute
    for code in ['000001', '399001']:
        slots = _15MIN_YESTERDAY_AMT_BY_SLOT.get(code, {})
        for time_key, amt in slots.items():
            parts = time_key.split(':')
            slot_end = int(parts[0]) * 60 + int(parts[1])
            if current_min >= slot_end:
                total += amt
    return total


def _get_up_down_count():
    """沪深合计涨跌家数（上证+深证最新15min K线）"""
    api = _get_tdx_api()
    if not api:
        return None
    today_str = datetime.now().strftime("%Y-%m-%d")
    total_up, total_dn = 0, 0
    queries = [(1, '000001'), (0, '399001')]  # 上证, 深证
    for mkt, code in queries:
        try:
            bars = api.get_index_bars(1, mkt, code, 0, 2)
            if not bars:
                continue
            for b in reversed(bars):
                if today_str in b.get("datetime", ""):
                    total_up += b.get("up_count", 0)
                    total_dn += b.get("down_count", 0)
                    break
        except Exception:
            pass
    if total_up > 0 or total_dn > 0:
        return (total_up, total_dn)
    return None


# ========== 全市场涨跌分布 ==========

_A_SHARE_CODES = None  # 缓存A股代码列表（真实股票）
_STOCK_NAMES = {}  # 缓存 code→name 映射

def _get_a_share_codes():
    """精准获取全A股代码列表 + 名称映射"""
    global _A_SHARE_CODES, _STOCK_NAMES
    if _A_SHARE_CODES:
        return _A_SHARE_CODES

    api = _get_tdx_api()
    if not api:
        return []

    codes = []
    name_map = {}
    for mkt, start, end in [(0, 0, 2000), (1, 24000, 27000)]:
        for offset in range(start, end, 1000):
            try:
                items = api.get_security_list(mkt, offset) or []
                for item in items:
                    code = str(item.get('code', ''))
                    if not code.isdigit() or len(code) != 6:
                        continue
                    name = str(item.get('name', ''))
                    if mkt == 1 and code.startswith(('600','601','602','603','604','605','688','689')):
                        codes.append((mkt, code))
                        name_map[code] = name
                    elif mkt == 0 and code.startswith(('000','001','002','003','004','300','301')):
                        codes.append((mkt, code))
                        name_map[code] = name
            except Exception:
                pass

    codes = sorted(set(codes))
    _A_SHARE_CODES = codes
    _STOCK_NAMES = name_map
    log(f"加载A股代码: {len(codes)} 只")
    return codes


def fetch_breadth():
    """全市场涨跌分布 + 涨停股收集 → {cats: {label: count}, zt_codes: [{code,zhangfu,amount}]}"""
    api = _get_tdx_api()
    if not api:
        return None
    all_codes = _get_a_share_codes()
    batch_size = 50  # 小批量避免单次失败整批丢数据
    cats = {'涨停': 0, '>7%': 0, '5~7%': 0, '3~5%': 0, '0~3%': 0,
            '-0~-3%': 0, '-3~-5%': 0, '-5~-7%': 0, '<-7%': 0, '跌停': 0}
    zt_codes = []
    total_valid = 0
    errors = 0

    for i in range(0, len(all_codes), batch_size):
        batch = all_codes[i:i + batch_size]
        try:
            raw = api.get_security_quotes(batch)
        except Exception:
            errors += 1
            if errors > 5:
                break
            continue
        errors = 0
        if not raw:
            continue
        for r in raw:
            price = r.get('price', 0)
            last_close = r.get('last_close', 0)
            if not price or not last_close:
                continue
            code = r.get('code', '')
            pct = round((price - last_close) / last_close * 100, 2)
            total_valid += 1
            if pct >= 9.9:
                cats['涨停'] += 1
                # zt_codes only for real zt: ST不记、科创/创业>=19.5%
                is_st = code.startswith(('ST', '*ST', 'S'))
                is_kcb_cyb = code.startswith(('688', '300', '301'))
                is_real_zt = (is_kcb_cyb and pct >= 19.5) or (not is_kcb_cyb and pct >= 9.8)
                if is_real_zt and not is_st:
                    zt_codes.append({
                        'code': code,
                        'zhangfu': pct,
                        'amount': r.get('amount', 0),
                    })
            elif pct > 7:
                cats['>7%'] += 1
            elif pct > 5:
                cats['5~7%'] += 1
            elif pct > 3:
                cats['3~5%'] += 1
            elif pct >= 0:
                cats['0~3%'] += 1
            elif pct >= -3:
                cats['-0~-3%'] += 1
            elif pct >= -5:
                cats['-3~-5%'] += 1
            elif pct >= -7:
                cats['-5~-7%'] += 1
            elif pct > -9.9:
                cats['<-7%'] += 1
            else:
                cats['跌停'] += 1

    if total_valid == 0:
        return None
    cats['_total'] = total_valid
    return {'cats': cats, 'zt_codes': zt_codes}


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
        # 振幅 = (最高-最低)/昨收
        high = row.get("high", 0)
        low = row.get("low", 0)
        if high and low and last_close:
            amp = round((high - low) / last_close * 100, 2)
            result[f"{name}振幅"] = f"{amp:.2f}%"

    # 成交额 = 上证 + 深证（不含创业板，创业板是深证子集，会重复计数）
    total_amt = sum(
        row.get("amount", 0) for row in raw if row.get("code", "") in ("000001", "399001")
    )
    result["成交额"] = _format_amount(total_amt)

    # 成交额差 = 今日累计 vs 昨日同时段累计（从15min缓存推算）
    cum_yest = _get_cum_yesterday_amt()
    if cum_yest > 0 and total_amt > 0:
        diff = (total_amt - cum_yest) / 1e8
        result["成交额差"] = f"{diff:+.0f}亿" if abs(diff) < 10000 else f"{diff/10000:+.2f}万亿"
    else:
        result["成交额差"] = "—"

    # 涨跌家数（从最新15min K线）
    ud = _get_up_down_count()
    if ud:
        result["上涨家数"] = ud[0]
        result["下跌家数"] = ud[1]

    # 全市场量比（上证15min累计量/昨日同时段）
    vr = _get_market_vol_ratio()
    if vr is not None:
        result["量比"] = vr

    return result


def _get_yesterday_baseline():
    """昨日收盘基线：三大指数涨跌幅+成交量+涨跌家数（从TDX日线）"""
    api = _get_tdx_api()
    if not api:
        return None
    idx_list = [(1, '000001', '上证'), (0, '399001', '深证'), (0, '399006', '创业')]
    today_str = datetime.now().strftime("%Y-%m-%d")
    result = {}
    for mkt, code, name in idx_list:
        try:
            bars = api.get_index_bars(9, mkt, code, 0, 4)
            if not bars or len(bars) < 2:
                continue
            yesterday = None
            prev = None
            for b in reversed(bars):
                dt = b.get("datetime", "")
                if today_str in dt:
                    continue
                if yesterday is None:
                    yesterday = b
                elif prev is None:
                    prev = b
                    break
            if not yesterday:
                continue
            close = yesterday.get("close", 0)
            prev_close = prev.get("close", close) if prev else close
            pct = round((close - prev_close) / prev_close * 100, 2) if prev_close else 0
            result[f"{name}昨收"] = close
            result[f"{name}昨涨幅"] = f"{pct:+.2f}%"
            result[f"{name}昨成交额"] = _format_amount(yesterday.get("amount", 0))
            result[f"{name}昨上涨"] = yesterday.get("up_count", 0)
            result[f"{name}昨下跌"] = yesterday.get("down_count", 0)
        except Exception:
            pass
    return result if result else None


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

_15MIN_YESTERDAY = {}  # {index_code: {time_key: {vol, amount}}} 昨日15min缓存
_15MIN_YESTERDAY_AMT_BY_SLOT = {}  # {index_code: {time_key: amount}} 昨日各时段成交额（供前端卡）
_15MIN_INDEXES = {
    "上证15min": ("000001", 1),
    "深证15min": ("399001", 0),
    "创业15min": ("399006", 0),
}


def _load_yesterday_15min(code, market):
    """加载昨日15min K线，缓存成交量和成交额"""
    api = _get_tdx_api()
    if not api:
        return
    try:
        bars = api.get_index_bars(1, market, code, 0, 60)
        if not bars:
            return
        today_str = datetime.now().strftime("%Y-%m-%d")
        yesterday_bars = {}
        yesterday_amt = {}
        for b in bars:
            dt = b.get("datetime", "")
            if today_str not in dt and dt:
                time_key = dt.split(" ")[-1][:5] if " " in dt else dt[-5:]
                date_part = dt.split(" ")[0] if " " in dt else dt[:10]
                if date_part not in yesterday_bars:
                    yesterday_bars[date_part] = {}
                    yesterday_amt[date_part] = {}
                yesterday_bars[date_part][time_key] = {"vol": b.get("vol", 0), "amount": b.get("amount", 0)}
                yesterday_amt[date_part][time_key] = b.get("amount", 0)
        if yesterday_bars:
            latest_date = sorted(yesterday_bars.keys())[-1]
            _15MIN_YESTERDAY[code] = yesterday_bars[latest_date]
            _15MIN_YESTERDAY_AMT_BY_SLOT[code] = yesterday_amt[latest_date]
    except Exception:
        pass


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
    yesterday_amt_slots = _15MIN_YESTERDAY_AMT_BY_SLOT.get(code, {})
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
        ydata = yesterday.get(time_key, {})
        yesterday_vol = ydata.get("vol", vol) if isinstance(ydata, dict) else ydata
        yesterday_amt = ydata.get("amount", 0) if isinstance(ydata, dict) else 0
        vol_ratio = round(vol / yesterday_vol, 2) if yesterday_vol > 0 else 1.0
        result.append({
            "t": time_key,
            "chg": chg,
            "vol": vol,
            "volRatio": vol_ratio,
            "amount": b.get("amount", 0),
            "yesterdayAmt": yesterday_amt,
        })

    # 追加累计汇总
    if result:
        cum_amount = sum(r["amount"] for r in result)
        # 量比：今日累计vol / 昨日同时段累计vol
        total_vol = sum(r["vol"] for r in result)
        total_yv = 0
        for r in result:
            yv = yesterday.get(r["t"], {})
            total_yv += yv.get("vol", r["vol"]) if isinstance(yv, dict) else (yv if isinstance(yv, (int, float)) else r["vol"])
        cum_ratio = round(total_vol / total_yv, 2) if total_yv > 0 else 1.0
        # 昨日同时段累计成交额（与今日同口径）
        cum_yesterday_amt = 0
        for r in result:
            ya = yesterday_amt_slots.get(r["t"], 0)
            cum_yesterday_amt += ya
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

def _get_sector_mas(api, code, price):
    """板块指数均线 MA5/MA20 + 成交额趋势（每日计算一次）"""
    global _sector_ma_cache
    cache_key = str(code)
    if cache_key in _sector_ma_cache:
        return _sector_ma_cache[cache_key]

    info = {}
    try:
        bars = api.get_security_bars(9, 1, str(code), 0, 30)
        if bars and len(bars) >= 3:
            # 检查基准是否一致：最近一根日K收盘价应在实时价±50%范围内
            last_close = bars[-1].get("close", 0) if bars else 0
            if last_close <= 0 or (price > 0 and (last_close < price * 0.3 or last_close > price * 3)):
                return info  # 基准不一致，跳过
            # 过滤脏数据：从最新往前取，遇到价格跳变(>30%)即停止
            valid = []
            prev_c = price
            for b in reversed(bars):
                c = b.get("close", 0)
                if c <= 0: continue
                if prev_c > 0 and (c < prev_c * 0.5 or c > prev_c * 2.0): break
                valid.insert(0, b)
                prev_c = c
            closes = [b.get("close", 0) for b in valid]
            amounts = [b.get("amount", 0) for b in valid if b.get("amount", 0) > 0]
            # 板块指数数据稀疏，≥3根即可算趋势
            if len(closes) >= 3:
                n_ma = min(5, len(closes))
                info["ma5"] = round(sum(closes[-n_ma:]) / n_ma, 2)
                # MA5方向：后半段 vs 前半段
                half = len(closes) // 2
                recent = closes[-half:] if half > 0 else closes
                earlier = closes[:half] if half > 0 else closes[:1]
                if sum(recent)/len(recent) > sum(earlier)/len(earlier) * 1.005:
                    info["ma5_dir"] = "向上"
                elif sum(recent)/len(recent) < sum(earlier)/len(earlier) * 0.995:
                    info["ma5_dir"] = "向下"
                else:
                    info["ma5_dir"] = "走平"
                # 站上/跌破5日线
                info["vs_ma5"] = "站上" if price > info["ma5"] else "跌破"
            if len(closes) >= 20:
                info["ma20"] = round(sum(closes[-20:]) / 20, 2)
            if len(amounts) >= 3:
                n_amt = min(5, len(amounts))
                ma5_amt = sum(amounts[-n_amt:]) / n_amt
                today_amt = amounts[-1] if amounts else 0
                if today_amt > ma5_amt * 1.15:
                    info["amt_trend"] = "放量"
                elif today_amt < ma5_amt * 0.85:
                    info["amt_trend"] = "缩量"
                else:
                    info["amt_trend"] = "持平"
    except Exception:
        pass

    if info:
        _sector_ma_cache[cache_key] = info
    return info


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
        tdx_code = _resolve_tdx_sector(name)
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

        # 板块均线（每日计算一次）
        ma_info = _get_sector_mas(api, code, price)

        # 距MA5距离
        dist_ma5 = None
        if ma_info.get("ma5") and price:
            dist_ma5 = round((price - ma_info["ma5"]) / ma_info["ma5"] * 100, 2)

        result[name] = {
            "涨跌幅": pct,
            "最新价": price,
            "MA5": ma_info.get("ma5"),
            "MA20": ma_info.get("ma20"),
            "MA5方向": ma_info.get("ma5_dir", "—"),
            "站上MA5": ma_info.get("vs_ma5", "—"),
            "距MA5": dist_ma5,
            "成交额趋势": ma_info.get("amt_trend", "—"),
            "今日涨停数": "—",
        }

    return result


# ========== 数据组装 ==========

_sector_ma_cache = {}  # 板块均线缓存：{code: {ma5, ma20, vol_ma5}}
_last_sectors_cache = {}  # 板块数据缓存，非刷新轮次复用
_last_yesterday_baseline = {}  # 昨日基线缓存，仅30s刷新一次
_live_zt_cache = []  # PyTDX 全市场扫描涨停缓存（30s更新一次，5s周期不覆盖）
_last_breadth_cache = {}  # 全市场涨跌分布缓存（同理防覆盖）

# 涨停梯队历史缓存：{date_str: [zt_stocks]}
_zt_history_cache = None
_zt_history_loaded = False

# P&L 快照：每 60 秒写入一次 SQLite
_last_pnl_log = 0
_PNL_LOG_INTERVAL = 300  # 5分钟快照粒度
_last_rollup_date = None  # 日终 rollup 防重复


def is_trading_time():
    now = datetime.now()
    if now.weekday() >= 5:  # Sat=5, Sun=6
        return False
    t = now.hour * 60 + now.minute
    return 570 <= t < 900  # 9:30-15:00


def calc_pnl(data, quotes):
    """从持仓+实时报价计算浮动盈亏"""
    pnl_section = data.get('pnl', {}) or {}
    total_asset = pnl_section.get('总资产', 0) or 0
    positions = data.get('positions', [])
    mv, cost = 0.0, 0.0
    for p in positions:
        status = str(p.get('状态', ''))
        if '清' in status:
            continue
        code = str(p.get('代码', ''))
        qty_str = str(p.get('数量', '0')).replace('股', '')
        try:
            qty = float(qty_str) if qty_str else 0
        except ValueError:
            qty = 0
        try:
            cost_price = float(p.get('成本', 0))
        except (ValueError, TypeError):
            cost_price = 0
        live = quotes.get(code, {})
        try:
            cur_price = float(live.get('最新价', 0))
        except (ValueError, TypeError):
            cur_price = 0
        if cur_price <= 0:
            cur_price = cost_price
        mv += qty * cur_price
        cost += qty * cost_price
    pnl_amount = mv - cost
    pnl_pct = (pnl_amount / total_asset * 100) if total_asset > 0 else 0
    pos_pct = (mv / total_asset * 100) if total_asset > 0 else 0
    return {
        'mv': round(mv, 2),
        'cost': round(cost, 2),
        'pnl_amount': round(pnl_amount, 2),
        'pnl_pct': round(pnl_pct, 4),
        'pos_pct': round(pos_pct, 2),
        'total_asset': total_asset,
    }


def log_pnl_snapshot(pnl, live_index):
    """写入一条日内 P&L 快照到 SQLite"""
    now = datetime.now()
    today = now.strftime('%Y-%m-%d')
    ts_iso = now.strftime('%Y-%m-%dT%H:%M:%S')

    def safe_float(v, default=0.0):
        if v is None: return default
        try: return round(float(str(v).replace('%', '')), 4)
        except (ValueError, TypeError): return default

    li = live_index or {}
    try:
        insert_snapshot({
            'ts': ts_iso,
            'date': today,
            'pnl_pct': pnl['pnl_pct'],
            'nav': 1.0,  # TWR NAV 由日终 rollup 更新
            'sh_pct': safe_float(li.get('上证指数涨幅', 0)),
            'sz_pct': safe_float(li.get('深证指数涨幅', 0)),
            'cy_pct': safe_float(li.get('创业指数涨幅', 0)),
            'pos_pct': pnl['pos_pct'],
            'mv': pnl['mv'],
            'total_asset': pnl['total_asset'],
        })
        log(f"PnL: {now.strftime('%H:%M')} pnl={pnl['pnl_pct']:.2f}% pos={pnl['pos_pct']:.0f}%")
    except Exception as e:
        log(f"PnL snapshot error: {e}")


def rollup_daily():
    """收盘后汇总当日日内数据写入 daily_summary"""
    global _last_rollup_date
    now = datetime.now()
    today = now.strftime('%Y-%m-%d')
    if _last_rollup_date == today:
        return  # 当天已 rollup
    try:
        from scripts.db import query_pnl as db_query_pnl
        data = db_query_pnl('today')
        if not data or not data['portfolio']:
            return
        n = len(data['portfolio'])
        if n < 2: return  # 数据太少不 rollup
        # 计算日内最大回撤
        peak = data['portfolio'][0]
        max_dd = 0
        dd_start = dd_end = None
        peak_idx = 0
        for i, v in enumerate(data['portfolio']):
            if v > peak: peak = v; peak_idx = i
            dd = v - peak
            if dd < max_dd:
                max_dd = dd
                dd_start = data['labels'][peak_idx] if data['labels'] else None
                dd_end = data['labels'][i] if data['labels'] else None
        insert_daily_summary({
            'date': today,
            'nav': 1.0,
            'pnl_pct': round(data['portfolio'][-1], 4),
            'sh_pct': round(data['benchmark'][-1], 4) if data['benchmark'] else 0,
            'sz_pct': 0,
            'cy_pct': 0,
            'pos_pct': round(data['position'][-1], 2) if data['position'] else 0,
            'deposit': 0,
            'max_dd': round(max_dd, 4),
            'max_dd_start': dd_start,
            'max_dd_end': dd_end,
        })
        _last_rollup_date = today
        log(f"Daily rollup: pnl={data['portfolio'][-1]:.2f}% dd={max_dd:.2f}%")
    except Exception as e:
        log(f"Rollup error: {e}")


def _load_zt_history():
    """加载近5个交易日涨停数据（会话内一次）"""
    global _zt_history_cache, _zt_history_loaded
    if _zt_history_loaded:
        return _zt_history_cache
    if not fetch:
        _zt_history_loaded = True
        return None

    from datetime import timedelta as _td
    history = {}
    today = date.today()
    for i in range(5):
        d = (today - _td(days=i)).strftime("%Y-%m-%d")
        try:
            r = fetch("ths_hot", date_str=d)
            if r and r.get("zt_stocks"):
                history[d] = r["zt_stocks"]
        except Exception:
            pass
    _zt_history_loaded = True
    _zt_history_cache = history if history else None
    return _zt_history_cache


def _fetch_hot_list():
    """拉取同花顺热点涨停数据"""
    if not fetch:
        return None
    try:
        r = fetch("ths_hot")
        hl = {
            "total": r.get("total", 0),
            "zt_count": r.get("zt_count", 0),
            "reason_stats": r.get("reason_stats", {}),
            "zt_stocks": r.get("zt_stocks", []),
            "all_stocks": r.get("stocks", []),  # 全量强势股（供名称查表）
        }
        history = _load_zt_history()
        if history:
            hl["zt_history"] = history
        return hl
    except Exception:
        return None


def build_live_data(codes, skip_sectors=False):
    """组装完整 live 数据"""
    global _tdx_using_fallback, _tdx_fail_count, _last_sectors_cache, _last_yesterday_baseline, _live_zt_cache, _last_breadth_cache

    data = {"live_sectors": _last_sectors_cache}  # 默认复用上次板块数据
    if _last_breadth_cache:
        data["live_breadth"] = _last_breadth_cache  # 每个周期都写入缓存
    if _last_yesterday_baseline:
        data["yesterday_baseline"] = _last_yesterday_baseline  # 非刷新轮次复用缓存

    # 个股 + 指数
    # 兜底切换：连续3次PyTDX失败 → 切到 easyquotation
    if _tdx_fail_count >= 3 and not _tdx_using_fallback:
        _tdx_using_fallback = True
        log("PyTDX 连续3次失败，切换到 easyquotation 兜底")

    if _tdx_using_fallback:
        # 兜底模式：每 30s 尝试一次 PyTDX 重连，不阻塞
        now_ts = time.time()
        if not hasattr(build_live_data, '_last_reconnect_attempt'):
            build_live_data._last_reconnect_attempt = 0
        if now_ts - build_live_data._last_reconnect_attempt >= 30:
            build_live_data._last_reconnect_attempt = now_ts
            test_api = _get_tdx_api()
            if test_api:
                # 尝试查询一只股票验证连接
                try:
                    test_result = test_api.get_security_quotes([(1, '000001')])
                    if test_result and len(test_result) > 0:
                        _tdx_fail_count = 0
                        _tdx_using_fallback = False
                        log("切回 PyTDX")
                except Exception:
                    pass

        if _tdx_using_fallback:
            data["live_quotes"] = fetch_quotes_fallback(codes)
            data["live_index"] = {}
        else:
            # 切回成功，走正常 PyTDX 路径
            quotes = fetch_quotes_pytdx(codes)
            index_data = fetch_index_pytdx()
            data["live_quotes"] = quotes or {}
            data["live_index"] = index_data or {}
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

        # 昨日收盘基线（与板块同频，30s）
        yest_base = _get_yesterday_baseline()
        if yest_base:
            data["yesterday_baseline"] = yest_base
            _last_yesterday_baseline = yest_base  # 更新缓存

        # 全市场涨跌分布 + 涨停收集（与板块同频，30s）
        try:
            breadth_result = fetch_breadth()
            if breadth_result:
                _last_breadth_cache = breadth_result['cats']
                data["live_breadth"] = _last_breadth_cache
                _live_zt_cache = breadth_result.get('zt_codes', [])
                log(f"全市场扫描: {breadth_result['cats'].get('涨停',0)}涨停 {len(_live_zt_cache)}只")
            else:
                log("全市场扫描返回空")
        except Exception as e:
            log(f"全市场扫描异常: {e}")

    # 同花顺热榜涨停 (每轮更新当日 + 历史缓存)
    hl = _fetch_hot_list()
    if hl:
        # PyTDX 全市场扫描涨停：用 ths_hot 名称补全，缓存防覆盖
        live_zt_codes = _live_zt_cache
        if live_zt_codes:
            # 名称查表：ths_hot + stock_names + zt_history
            name_map = dict(_STOCK_NAMES)
            for s in hl.get('all_stocks', []):
                name_map[s['code']] = s['name']
            for s in hl.get('zt_stocks', []):
                name_map[s['code']] = s['name']
            for d_stocks in hl.get('zt_history', {}).values():
                for s in d_stocks:
                    name_map[s['code']] = s['name']
            live_zt = []
            for z in live_zt_codes:
                code = z['code']
                name = name_map.get(code, code)
                live_zt.append({
                    'code': code,
                    'name': name,
                    'zhangfu': z['zhangfu'],
                    'chengjiaoe': round(z['amount'] / 10000, 1) if z['amount'] else None,
                    'huanshou': None,
                    'reason': '',
                })
            # 如果 ths_hot 今天没数据（zhangfu全0），用 live 数据覆盖
            ths_zt = hl.get('zt_stocks', [])
            ths_all_zero = all(s.get('zhangfu', 0) == 0 for s in ths_zt) if ths_zt else True
            if live_zt and ths_all_zero:
                hl['zt_stocks'] = live_zt
                hl['zt_count'] = len(live_zt)
            elif live_zt:
                # ths_hot 有数据：合并去重
                existing = {s['code'] for s in ths_zt}
                for z in live_zt:
                    if z['code'] not in existing:
                        ths_zt.append(z)
                hl['zt_stocks'] = ths_zt
                hl['zt_count'] = len(ths_zt)
        data["hot_list"] = hl

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
    last_code_refresh = time.time()  # 定期刷新代码列表（纳入 bridge sync 后的清仓股）
    write_count = 0
    error_count = 0
    last_source = None

    try:
        while True:
            now = time.time()
            # 每60秒刷新代码列表，纳入通过 bridge sync 新加入的清仓股票
            if now - last_code_refresh >= 60:
                new_codes = get_stock_codes()
                if set(new_codes) != set(codes):
                    log(f"代码列表更新: {len(codes)} → {len(new_codes)} (新增: {set(new_codes)-set(codes)})")
                codes = new_codes
                last_code_refresh = now
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

            # P&L 快照（每60s一次，仅交易时段）
            # 非交易时间跳过所有数据写入
            global _last_pnl_log, _last_rollup_date
            in_trading = is_trading_time()
            if not in_trading:
                time.sleep(interval_stocks * 20)  # 非交易时间降低轮询频率
                continue
            if data.get("live_quotes") and (now - _last_pnl_log >= _PNL_LOG_INTERVAL):
                try:
                    base = {}
                    if DASHBOARD_DATA.exists():
                        with open(DASHBOARD_DATA) as f:
                            base = json.load(f)
                    pnl = calc_pnl(base, data.get("live_quotes", {}))
                    live_idx = data.get("live_index", {})
                    log_pnl_snapshot(pnl, live_idx)
                    _last_pnl_log = now
                except Exception as e:
                    log(f"PnL calc error: {e}")

            # 日终 rollup（15:01 后执行一次）
            rollup_now = datetime.now()
            if in_trading and rollup_now.hour == 15 and rollup_now.minute >= 1:
                rollup_daily()

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
