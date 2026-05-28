#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
市场风格检测脚本 v0.3 — 四维度概率化风格判定 + 复盘数据集成 + 状态持续性

用法:
  python3 style_detect.py                        # 纯iwencai模式
  python3 style_detect.py --review <复盘笔记.md>  # 复盘数据增强模式（推荐）
  python3 style_detect.py --json                 # JSON输出
  python3 style_detect.py --json --review <...>  # JSON+复盘增强

改进（v0.3 vs v0.2）:
  维度一 量能环境 25分: 成交额+5日均量比+CV波动率+量能趋势方向
  维度二 连板生态 35分: 最高板+涨停收益+炸板收益🆕+连板风险值🆕+晋级率
  维度三 趋势赚钱效应 25分: 沪深300+趋势板块+大市值赚钱比例🆕+TOP50涨跌
  维度四 情绪广度 15分🆕: 情绪值+涨跌比+赚钱效应定性
  输出: 风格+连板/趋势占比+置信度+状态持续性+过渡预警

数据源优先级: 复盘笔记 frontmatter > iwencai 实时查询
"""

import sys, os, json, re
from datetime import datetime, timedelta
from pathlib import Path

# === ym_stock_data 延迟导入 ===
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
    default = Path(__file__).resolve().parent.parent.parent / "YM-data-pipeline"
    return default

_pip_path = None

def _ensure_pipeline():
    """确保 ym_stock_data 在 sys.path 中（延迟导入）"""
    global _pip_path
    if _pip_path is not None:
        return _pip_path
    p = _load_pipeline_path()
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
    _pip_path = p
    return p

def _iwencai_query(*args, **kwargs):
    """延迟导入 iwencai 查询"""
    _ensure_pipeline()
    from ym_stock_data.sources.iwencai import query as _q
    return _q(*args, **kwargs)

# === 状态持续性追踪文件 ===
REGIME_STATE_FILE = Path(__file__).parent / ".style_regime_state.json"


def q(query, limit=2000):
    """调用 ym_stock_data 问财查询，返回解析结果"""
    try:
        return _iwencai_query(query, limit=limit)
    except Exception:
        return {}


def find_field(fields, keyword):
    """在字段列表中查找包含关键字的字段（优先无日期后缀，否则取最新日期）"""
    exact = [f for f in fields if f == keyword]
    if exact:
        return exact[0]
    dated = [f for f in fields if keyword in f and "[" in f]
    if dated:
        dated.sort(reverse=True)
        return dated[0]
    return None


def val(row, field, default=0):
    """安全取值"""
    v = row.get(field, default) if field else default
    return float(v) if v else 0


def parse_review_frontmatter(filepath):
    """解析复盘笔记 YAML frontmatter，提取风格相关字段"""
    data = {}
    if not filepath or not os.path.exists(filepath):
        return data
    try:
        with open(filepath) as f:
            content = f.read()
    except Exception:
        return data

    m = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if not m:
        return data
    fm = m.group(1)

    for line in fm.split('\n'):
        line = line.rstrip()
        if not line or line.startswith('#'):
            continue
        m2 = re.match(r'^([\w一-鿿]+):\s*(.*)', line)
        if not m2:
            continue
        key, raw_val = m2.group(1), m2.group(2).strip()
        if raw_val.startswith('"') and raw_val.endswith('"'):
            raw_val = raw_val[1:-1]
        if raw_val.startswith("'") and raw_val.endswith("'"):
            raw_val = raw_val[1:-1]
        data[key] = raw_val

    return data


def parse_tiered_jjl(filepath):
    """从复盘笔记解析分层晋级率（FM 优先，正文表格兜底）"""
    result = {}
    if not filepath or not os.path.exists(filepath):
        return result

    # 1. 先读 FM（稳米填的值，优先级最高）
    fm = parse_review_frontmatter(filepath)
    for fm_key in ['一进二晋级率', '二进三晋级率', '三进四晋级率']:
        val = _parse_pct(fm.get(fm_key))
        if val is not None:
            result[fm_key] = val

    if result:
        return result

    # 2. FM 没有的再从正文表格解析
    try:
        with open(filepath) as f:
            content = f.read()
    except Exception:
        return result

    for line in content.split('\n'):
        line = line.strip()
        if not line.startswith('|') or '---' in line:
            continue
        cells = [c.strip() for c in line.split('|')[1:-1]]

        # 匹配: | 一进二 | 8.77% | ... |（只在首次匹配时写入，防止后续非数据行覆盖）
        for i, cell in enumerate(cells):
            if '一进二' in cell and len(cells) > i + 1:
                val = _parse_pct(cells[i + 1])
                if val is not None and '一进二晋级率' not in result:
                    result['一进二晋级率'] = val
            if '二进三' in cell and len(cells) > i + 1:
                val = _parse_pct(cells[i + 1])
                if val is not None and '二进三晋级率' not in result:
                    result['二进三晋级率'] = val
            if '三进四' in cell and len(cells) > i + 1:
                val = _parse_pct(cells[i + 1])
                if val is not None and '三进四晋级率' not in result:
                    result['三进四晋级率'] = val

    return result


def compute_allocation(total_score, lianban_conf=None):
    """按 Vault `references/量能风格切换.md` 插值表分配连板/趋势资金。"""
    score = _number(total_score) if "_number" in globals() else None
    if score is None:
        try:
            score = float(total_score)
        except (TypeError, ValueError):
            score = 50
    anchors = [
        (40, 0),
        (45, 30),
        (50, 50),
        (60, 60),
        (75, 80),
        (80, 100),
    ]
    if score <= anchors[0][0]:
        lb = anchors[0][1]
    elif score >= anchors[-1][0]:
        lb = anchors[-1][1]
    else:
        lb = 50
        for (s0, lb0), (s1, lb1) in zip(anchors, anchors[1:]):
            if s0 <= score <= s1:
                t = (score - s0) / (s1 - s0)
                lb = round(lb0 + t * (lb1 - lb0))
                break
    return {'连板资金占比': lb, '趋势资金占比': 100 - lb}


def _clean_val(s):
    """清洗值：去括号注释、去%、去首尾空白"""
    if s is None:
        return None
    s = str(s).strip()
    # 去掉中文括号注释: "2.41%（低）" → "2.41%"
    s = re.sub(r'（[^）]*）', '', s)
    # 去掉英文括号注释: "2.41%(low)" → "2.41%"
    s = re.sub(r'\([^)]*\)', '', s)
    return s.strip()


def _parse_pct(s):
    """安全解析百分比字符串 → float"""
    if s is None:
        return None
    s = _clean_val(s).replace('%', '').strip()
    try:
        return float(s)
    except ValueError:
        return None


def _parse_num(s):
    """安全解析数值字符串 → float"""
    if s is None:
        return None
    cleaned = _clean_val(s)
    m = re.search(r'[+-]?\d+(?:\.\d+)?', str(cleaned))
    if m:
        return float(m.group(0))
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_market_volume_yi(value):
    """解析复盘笔记市场量能为亿元。

    复盘笔记常写 3.24 表示 3.24万亿；若写 32400 或 3.24万亿也兼容。
    """
    if value is None:
        return None
    raw = str(value).strip()
    num = _parse_num(raw.replace('万亿', '').replace('亿', ''))
    if num is None:
        return None
    if '万亿' in raw or num < 100:
        return num * 10000
    return num


def _parse_style_score_validation(review=None):
    """解析 frontmatter 的风格分数验证。

    支持格式：
    42分(维度一17+维度二9+维度三9+维度四7)
    """
    raw = (review or {}).get("风格分数验证")
    if not raw:
        return None
    text = str(raw)
    total_m = re.search(r'(\d+(?:\.\d+)?)\s*分', text)
    dim_map = {"一": "dim1", "二": "dim2", "三": "dim3", "四": "dim4"}
    parsed = {}
    if total_m:
        parsed["total"] = int(float(total_m.group(1)))
    for cn, key in dim_map.items():
        m = re.search(r'维度%s\s*(\d+(?:\.\d+)?)' % cn, text)
        if m:
            parsed[key] = int(float(m.group(1)))
    return parsed if parsed else None


def apply_review_score_validation(review, s1, s2, s3, s4):
    """用复盘笔记的人工校验分覆盖算法维度分。

    W02 是每日风格基线，复盘笔记 frontmatter 是盘后人工确认口径；
    style_detect 的实时/默认查询只做缺字段时的辅助计算。
    """
    parsed = _parse_style_score_validation(review)
    if not parsed:
        return None
    targets = [
        ("dim1", s1),
        ("dim2", s2),
        ("dim3", s3),
        ("dim4", s4),
    ]
    for key, score_obj in targets:
        if key not in parsed:
            continue
        old = score_obj.get("score")
        new = parsed[key]
        score_obj["score"] = new
        score_obj.setdefault("details", {})["复盘校验"] = f"{old}→{new}" if old != new else f"{new}"
    return parsed


# ========== 维度一：量能环境（25分）==========

def score_dim1(review=None):
    """维度一：量能环境 — 成交额+均量比+波动率+趋势方向"""
    r = {"score": 0, "details": {}, "max": 25}

    d = q("全市场成交额 近5日成交额")
    fields = d.get("fields", [])
    datas = d.get("datas", [])

    vol_fields = sorted([f for f in fields if "成交额[" in f])
    volumes = []
    for row in datas:
        for vf in vol_fields:
            v = val(row, vf)
            if v > 0:
                volumes.append(v / 1e8)
        if volumes:
            break

    latest_vol = volumes[-1] if volumes else 0
    avg_5 = sum(volumes) / len(volumes) if volumes else 0

    review_vol = _parse_market_volume_yi(review.get("市场量能")) if review else None
    if latest_vol <= 0 and review_vol:
        latest_vol = review_vol
        volumes = [review_vol]

    vol_ratio = latest_vol / avg_5 if avg_5 > 0 else 1.0

    r["details"]["全市场成交额"] = f"{latest_vol:.0f}亿"
    r["details"]["5日均量"] = f"{avg_5:.0f}亿"
    r["details"]["量比(vs5日均)"] = f"{vol_ratio:.2f}x"

    # 1. 成交额绝对值 (0-8分)
    if latest_vol > 25000:
        vol_score = 8
    elif latest_vol > 20000:
        vol_score = 6
    elif latest_vol > 15000:
        vol_score = 4
    elif latest_vol > 10000:
        vol_score = 2
    else:
        vol_score = 1
    r["details"]["成交额评分"] = f"{vol_score}/8"
    r["score"] += vol_score

    # 2. 5日均量比 (0-8分) — 放量才有行情
    if vol_ratio > 1.15:
        ratio_score = 8
        ratio_desc = "显著放量↑↑"
    elif vol_ratio > 1.05:
        ratio_score = 6
        ratio_desc = "温和放量↑"
    elif vol_ratio > 0.95:
        ratio_score = 4
        ratio_desc = "持平→"
    elif vol_ratio > 0.85:
        ratio_score = 2
        ratio_desc = "缩量↓"
    else:
        ratio_score = 1
        ratio_desc = "显著缩量↓↓"
    r["details"]["量比评分"] = f"{ratio_score}/8 ({ratio_desc})"
    r["score"] += ratio_score

    # 3. 量能波动率CV (0-5分)
    if len(volumes) >= 3:
        mean_v = sum(volumes) / len(volumes)
        var_v = sum((v - mean_v)**2 for v in volumes) / len(volumes)
        cv = (var_v**0.5) / mean_v if mean_v > 0 else 0
        if cv < 0.15:
            cv_score = 5
        elif cv < 0.25:
            cv_score = 4
        elif cv < 0.4:
            cv_score = 2
        else:
            cv_score = 1
        r["details"]["量能波动率"] = f"{cv:.1%}CV → {cv_score}/5"
        r["score"] += cv_score
    else:
        r["details"]["量能波动率"] = "数据不足（默认3分）"
        r["score"] += 3

    # 4. 量能趋势方向 (0-4分) — 连续放量/缩量天数
    if len(volumes) >= 4:
        ups = sum(1 for i in range(1, len(volumes)) if volumes[i] > volumes[i-1])
        downs = len(volumes) - 1 - ups
        if ups >= 3:
            trend_score = 4
            trend_desc = f"连续{ups}日放量"
        elif ups > downs:
            trend_score = 3
            trend_desc = "偏放量"
        elif downs >= 3:
            trend_score = 1
            trend_desc = f"连续{downs}日缩量"
        else:
            trend_score = 2
            trend_desc = "偏缩量"
        r["details"]["量能方向"] = f"{trend_desc} → {trend_score}/4"
        r["score"] += trend_score
    else:
        r["details"]["量能方向"] = "数据不足（默认2分）"
        r["score"] += 2

    return r


# ========== 维度二：连板生态（35分）==========

def score_dim2(review=None):
    """维度二：连板生态 — 最高板+涨停收益+炸板收益+连板风险值+晋级率"""
    r = {"score": 0, "details": {}, "max": 35}

    # --- 数据获取 ---
    # 优先从复盘笔记取值，iwencai兜底
    review_zt_ret = _parse_pct(review.get("昨日涨停收益")) if review else None
    review_zb_ret = _parse_pct(review.get("昨日炸板收益")) if review else None
    review_lb_ret = _parse_pct(review.get("昨日连板收益")) if review else None
    review_risk = _parse_num(review.get("连板风险值")) if review else None
    review_jjl = _parse_pct(review.get("整体晋级率") or review.get("晋级率")) if review else None
    review_max_board_raw = review.get("最高板", "") if review else ""
    review_fb_rate = _parse_pct(review.get("封板率")) if review else None
    review_zb_rate = _parse_pct(review.get("炸板率")) if review else None

    # 最高板: 从复盘笔记解析 "5板（大唐发电）" → 5
    review_max_board = None
    if review_max_board_raw:
        m = re.search(r'(\d+)', str(review_max_board_raw))
        if m:
            review_max_board = int(m.group(1))

    # iwencai 连板查询
    d_board = q("连续涨停天数 股票简称 非st 非退市")
    board_fields = d_board.get("fields", [])
    board_field = find_field(board_fields, "连续涨停天数")

    max_board = review_max_board or 0
    if not max_board and d_board.get("datas"):
        for row in d_board.get("datas"):
            b = int(val(row, board_field))
            name = row.get("股票简称", "")
            if b > max_board and "ST" not in name and "退" not in name:
                max_board = b

    # --- 1. 最高连板高度 (0-8分) ---
    r["details"]["最高板"] = f"{max_board}板"
    if max_board >= 7:
        h_score = 8
    elif max_board >= 5:
        h_score = 6
    elif max_board >= 4:
        h_score = 4
    elif max_board >= 3:
        h_score = 2
    else:
        h_score = 1
    r["details"]["高度评分"] = f"{h_score}/8"
    r["score"] += h_score

    # --- 2. 涨停收益 (0-8分) ---
    zt_ret = review_zt_ret
    if zt_ret is None:
        d = q("昨涨停股今日涨幅 平均值 涨停收益")
        zt_field = find_field(d.get("fields", []), "涨停收益")
        if zt_field and d.get("datas"):
            zt_ret = float(d["datas"][0].get(zt_field, 0) or 0)
        else:
            zt_ret = 0
    r["details"]["涨停收益"] = f"{zt_ret:.2f}%"
    if zt_ret > 5:
        zt_score = 8
    elif zt_ret > 3:
        zt_score = 6
    elif zt_ret > 2:
        zt_score = 4
    elif zt_ret > 1:
        zt_score = 2
    else:
        zt_score = 0
    r["details"]["收益评分"] = f"{zt_score}/8"
    r["score"] += zt_score

    # --- 3. 炸板收益 (0-8分) 🆕 ---
    zb_ret = review_zb_ret
    if zb_ret is None:
        zb_ret = 0
    r["details"]["炸板收益"] = f"{zb_ret:.2f}%"
    if zb_ret > 2:
        zb_score = 8  # 炸板都能赚钱→极强
    elif zb_ret > 0:
        zb_score = 6  # 炸板不亏钱→强
    elif zb_ret > -2:
        zb_score = 4  # 炸板小亏→正常
    elif zb_ret > -5:
        zb_score = 2  # 炸板亏钱→弱
    else:
        zb_score = 0  # 炸板大亏→极弱
    r["details"]["炸板评分"] = f"{zb_score}/8"
    r["score"] += zb_score

    # --- 4. 连板风险值 (0-6分，反向) 🆕 ---
    risk_val = review_risk
    if risk_val is None:
        risk_val = 5.0  # 无数据时默认中等风险
    r["details"]["连板风险值"] = f"{risk_val:.1f}"
    if risk_val < 0.3:
        risk_score = 6  # 几乎无风险
    elif risk_val < 0.5:
        risk_score = 5
    elif risk_val < 1.0:
        risk_score = 4  # 低风险
    elif risk_val < 2.0:
        risk_score = 3
    elif risk_val < 3.0:
        risk_score = 2
    else:
        risk_score = 1  # 高风险
    r["details"]["风险评分"] = f"{risk_score}/6"
    r["score"] += risk_score

    # --- 5. 晋级率 (0-5分) ---
    jjl = review_jjl
    if jjl is None:
        # iwencai 推算晋级率
        lianban_today = 0
        for row in d_board.get("datas", []):
            if int(val(row, board_field)) >= 2:
                lianban_today += 1
        d_zt_yes = q("昨日涨停 非st", limit=500)
        zt_yes = len(d_zt_yes.get("datas", []))
        if zt_yes == 0:
            qty_field = find_field(d_zt_yes.get("fields", []), "数量[")
            for row in d_zt_yes.get("datas", []):
                c = int(val(row, qty_field))
                if c > zt_yes:
                    zt_yes = c
        jjl = round(lianban_today / zt_yes * 100, 1) if zt_yes > 0 else 0
    r["details"]["晋级率"] = f"{jjl}%"
    if jjl > 35:
        j_score = 5
    elif jjl > 25:
        j_score = 4
    elif jjl > 18:
        j_score = 3
    elif jjl > 10:
        j_score = 2
    else:
        j_score = 1
    r["details"]["晋级评分"] = f"{j_score}/5"
    r["score"] += j_score

    # --- 附加记录：封板率/炸板率（不计分，供参考）---
    if review_fb_rate is not None:
        r["details"]["封板率"] = f"{review_fb_rate:.1f}%"
    if review_zb_rate is not None:
        r["details"]["炸板率"] = f"{review_zb_rate:.1f}%"

    return r


# ========== 维度三：趋势赚钱效应（25分）==========

def score_dim3(review=None):
    """维度三：趋势赚钱效应 — 沪深300+趋势板块+大市值赚钱+TOP50分布"""
    r = {"score": 0, "details": {}, "max": 25}

    review_trend_sectors = _parse_num(review.get("趋势走强板块数")) if review else None
    review_bigcap_pct = _parse_pct(review.get("大市值赚钱比例")) if review else None

    # --- 1. 沪深300方向 (0-8分) ---
    d = q("沪深300 涨跌幅")
    hs300 = 0
    for row in d.get("datas", []):
        chg = row.get("最新涨跌幅:前复权", 0) or 0
        hs300 = float(str(chg).replace("%", ""))
        break
    r["details"]["沪深300涨跌幅"] = f"{hs300:.2f}%"
    if hs300 > 1.0:
        hs_score = 8
    elif hs300 > 0.5:
        hs_score = 6
    elif hs300 > 0:
        hs_score = 4
    elif hs300 > -0.5:
        hs_score = 2
    else:
        hs_score = 0
    r["details"]["方向评分"] = f"{hs_score}/8"
    r["score"] += hs_score

    # --- 2. 趋势板块 (0-8分) ---
    # iwencai 查板块站上20日线+放量
    d = q("板块指数站上20日线 近5日成交额放量")
    iwencai_sectors = len(d.get("datas", []))
    # 复盘笔记的趋势走强板块数优先
    trend_sectors = review_trend_sectors if review_trend_sectors is not None else iwencai_sectors
    # 取两者中更有信息量的（大的那个通常更准确）
    if review_trend_sectors is not None and iwencai_sectors > 0:
        trend_sectors = max(trend_sectors, iwencai_sectors) if abs(trend_sectors - iwencai_sectors) < 5 else trend_sectors

    r["details"]["趋势板块数"] = f"{trend_sectors}个"
    if trend_sectors >= 8:
        ts_score = 8
    elif trend_sectors >= 5:
        ts_score = 6
    elif trend_sectors >= 3:
        ts_score = 4
    elif trend_sectors >= 1:
        ts_score = 2
    else:
        ts_score = 0
    r["details"]["板块评分"] = f"{ts_score}/8"
    r["score"] += ts_score

    # --- 3. 大市值赚钱比例 (0-5分) 🆕 ---
    bigcap_pct = review_bigcap_pct
    if bigcap_pct is None:
        # iwencai 推算：成交额TOP50上涨比例
        d = q("成交额排名前50 今日涨幅")
        up_count = 0
        total_count = 0
        for row in d.get("datas", []):
            total_count += 1
            chg = str(row.get("最新涨跌幅", "0") or "0").replace("%", "")
            if float(chg) > 0:
                up_count += 1
        bigcap_pct = round(up_count / total_count * 100, 1) if total_count > 0 else 0
    r["details"]["大市值赚钱比例"] = f"{bigcap_pct}%"
    if bigcap_pct > 60:
        bc_score = 5
    elif bigcap_pct > 45:
        bc_score = 4
    elif bigcap_pct > 35:
        bc_score = 3
    elif bigcap_pct > 25:
        bc_score = 2
    else:
        bc_score = 1
    r["details"]["市值评分"] = f"{bc_score}/5"
    r["score"] += bc_score

    # --- 4. 新高新低比 (0-4分) ---
    d = q("创60日新高 非st 非新股 前复权")
    new_high = len(d.get("datas", []))
    d = q("创60日新低 非st 非新股 前复权")
    new_low = len(d.get("datas", []))
    hl_ratio = new_high / max(new_low, 1)
    r["details"]["60日新高/新低"] = f"{new_high}/{new_low} (比{hl_ratio:.1f})"
    if hl_ratio > 3:
        hl_score = 4
    elif hl_ratio > 1.5:
        hl_score = 3
    elif hl_ratio > 0.7:
        hl_score = 2
    else:
        hl_score = 1
    r["details"]["新高评分"] = f"{hl_score}/4"
    r["score"] += hl_score

    return r


# ========== 维度四：情绪与广度（15分）🆕 ==========

def score_dim4(review=None):
    """维度四：情绪与广度 — 情绪值+涨跌比+赚钱效应定性"""
    r = {"score": 0, "details": {}, "max": 15}

    review_qx = _parse_pct(review.get("情绪值")) if review else None
    review_ud_raw = review.get("涨跌比", "") if review else ""
    review_profit = review.get("赚钱效应", "") if review else ""

    # --- 1. 情绪值 (0-5分) ---
    qx = review_qx
    if qx is None:
        qx = 50  # 无数据默认中性
    r["details"]["情绪值"] = f"{qx:.0f}%"

    if 40 <= qx <= 60:
        qx_score = 5  # 主升区最佳
        qx_desc = "主升区间（最佳）"
    elif 60 < qx <= 80:
        qx_score = 4  # 强势但可能过热
        qx_desc = "强势区间"
    elif 20 <= qx < 40:
        qx_score = 3  # 低迷但可能转暖
        qx_desc = "低迷区间"
    elif qx < 20:
        qx_score = 1  # 冰点
        qx_desc = "冰点（极端）"
    else:
        qx_score = 2  # 高潮>80
        qx_desc = "高潮（警惕反转）"
    r["details"]["情绪评分"] = f"{qx_score}/5 ({qx_desc})"
    r["score"] += qx_score

    # --- 2. 涨跌比 (0-5分) ---
    up_n, dn_n = 0, 0
    if review_ud_raw:
        m = re.match(r'(\d+)\s*/\s*(\d+)', str(review_ud_raw))
        if m:
            up_n, dn_n = int(m.group(1)), int(m.group(2))
    if up_n + dn_n > 0:
        ud_ratio = up_n / max(dn_n, 1)
        r["details"]["涨跌比"] = f"{up_n}/{dn_n} ({ud_ratio:.2f})"
        if ud_ratio > 1.5:
            ud_score = 5
            ud_desc = "普涨"
        elif ud_ratio > 1.0:
            ud_score = 4
            ud_desc = "偏涨"
        elif ud_ratio > 0.6:
            ud_score = 3
            ud_desc = "分化"
        elif ud_ratio > 0.3:
            ud_score = 2
            ud_desc = "偏跌"
        else:
            ud_score = 1
            ud_desc = "普跌"
        r["details"]["涨跌评分"] = f"{ud_score}/5 ({ud_desc})"
        r["score"] += ud_score
    else:
        r["details"]["涨跌比"] = "—"
        r["details"]["涨跌评分"] = "默认3分"
        r["score"] += 3

    # --- 3. 赚钱效应定性 (0-5分) ---
    profit = str(review_profit).strip() if review_profit else "一般"
    r["details"]["赚钱效应"] = profit
    if profit in ("好", "极好"):
        pf_score = 5
    elif profit in ("较好",):
        pf_score = 4
    elif profit in ("一般",):
        pf_score = 3
    elif profit in ("较差",):
        pf_score = 2
    else:  # 差
        pf_score = 1
    r["details"]["效应评分"] = f"{pf_score}/5"
    r["score"] += pf_score

    return r


# ========== 风格判定（概率化 + 状态持续性）==========

def _load_regime_state():
    """加载历史状态"""
    if REGIME_STATE_FILE.exists():
        try:
            with open(REGIME_STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"history": [], "current_regime": None, "days_in_regime": 0}


def _save_regime_state(state):
    """保存状态"""
    REGIME_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(REGIME_STATE_FILE, 'w') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _regime_base(style):
    return (style or "").split("（")[0]


def _dedup_history_by_date(history):
    """同一日期只保留最后一次记录，避免重复 gen 放大持续天数。"""
    by_date = {}
    for item in history or []:
        date = item.get("date")
        if not date:
            continue
        by_date[date] = item
    return [by_date[d] for d in sorted(by_date)]


def _count_regime_days(history, style):
    base = _regime_base(style)
    if not base:
        return 0
    count = 0
    for item in reversed(_dedup_history_by_date(history)):
        if _regime_base(item.get("style")) != base:
            break
        count += 1
    return count


def determine_style(s1, s2, s3, s4, date_str=None):
    """概率化风格判定 + 状态持续性

    逻辑：
    - 连板信号 = dim2 (连板生态) + dim4 (情绪，连板更依赖情绪)
    - 趋势信号 = dim3 (趋势赚钱效应) + dim1 (量能，趋势需要量)
    - 两条线独立打分，不互斥
    - 持续性：昨日风格不轻易翻转，需显著信号
    """
    dim1_pct = s1["score"] / s1["max"]  # 量能
    dim2_pct = s2["score"] / s2["max"]  # 连板生态
    dim3_pct = s3["score"] / s3["max"]  # 趋势赚钱效应
    dim4_pct = s4["score"] / s4["max"]  # 情绪广度

    # 连板综合信号：连板生态 55% + 情绪 30% + 量能 15%
    lianban_signal = dim2_pct * 0.55 + dim4_pct * 0.30 + dim1_pct * 0.15
    # 趋势综合信号：趋势赚钱效应 55% + 量能 30% + 情绪 15%
    trend_signal = dim3_pct * 0.55 + dim1_pct * 0.30 + dim4_pct * 0.15

    # 归一化：两者之和可能不为1
    total_signal = lianban_signal + trend_signal
    if total_signal > 0:
        lianban_conf = round(lianban_signal / total_signal * 100)
        trend_conf = round(trend_signal / total_signal * 100)
    else:
        lianban_conf = 50
        trend_conf = 50

    # 总分
    total = s1["score"] + s2["score"] + s3["score"] + s4["score"]

    # === 风格判定 ===
    gap = abs(lianban_conf - trend_conf)

    if lianban_conf >= 65 or (lianban_conf >= 60 and gap >= 20):
        style = "连板行情"
        confidence = min(90, lianban_conf + gap // 2)
    elif trend_conf >= 65 or (trend_conf >= 60 and gap >= 20):
        style = "趋势行情"
        confidence = min(90, trend_conf + gap // 2)
    elif gap <= 10:
        style = "混合（均衡）"
        confidence = max(lianban_conf, trend_conf)
    elif lianban_conf > trend_conf:
        style = "混合（偏连板）"
        confidence = lianban_conf - 5
    else:
        style = "混合（偏趋势）"
        confidence = trend_conf - 5

    # === 细化信号 ===
    if dim2_pct < 0.25:
        lianban_detail = "连板极弱（考虑不开连板仓）"
    elif dim2_pct < 0.40:
        lianban_detail = "连板偏弱（谨慎开仓）"
    elif dim2_pct < 0.60:
        lianban_detail = "连板正常"
    else:
        lianban_detail = "连板强势"

    if dim3_pct < 0.25:
        trend_detail = "趋势极弱（不追趋势）"
    elif dim3_pct < 0.40:
        trend_detail = "趋势偏弱（等回踩确认）"
    elif dim3_pct < 0.60:
        trend_detail = "趋势正常"
    else:
        trend_detail = "趋势强势"

    # === 状态持续性 ===
    state = _load_regime_state()
    prev_regime = state.get("current_regime")
    prev_days = state.get("days_in_regime", 0)

    # 判断是否翻转
    regime_base = _regime_base(style)  # "连板行情" or "趋势行情" or "混合"
    prev_base = _regime_base(prev_regime) if prev_regime else ""

    flipped = False
    if prev_base and regime_base != prev_base:
        # 不同大类，检查gap是否够大
        if gap >= 25 and confidence >= 70:
            flipped = True
        elif lianban_conf >= 70 and prev_base == "趋势":
            flipped = True
        elif trend_conf >= 70 and prev_base == "连板":
            flipped = True
        else:
            # 信号不够强，维持昨日判定但降置信度
            style = prev_regime
            confidence = max(40, confidence - 20)
            flipped = False

    today = date_str or datetime.now().strftime("%Y-%m-%d")
    # 保留最近30天历史
    history = state.get("history", [])
    history.append({
        "date": today,
        "style": style,
        "total": total,
        "lianban_conf": lianban_conf,
        "trend_conf": trend_conf,
        "confidence": confidence,
    })
    history = _dedup_history_by_date(history)
    if len(history) > 30:
        history = history[-30:]

    new_days = _count_regime_days(history, style) or 1
    new_state = {
        "current_regime": style,
        "days_in_regime": new_days,
        "last_update": today,
    }
    new_state["history"] = history
    _save_regime_state(new_state)

    # === 过渡预警 ===
    warnings = []
    if new_days >= 5 and style.startswith("连板"):
        warnings.append(f"连板行情已持续{new_days}天，关注高潮转弱信号")
    if new_days >= 5 and style.startswith("趋势"):
        warnings.append(f"趋势行情已持续{new_days}天，关注放量滞涨信号")
    if dim2_pct < 0.30 and dim3_pct > 0.50:
        warnings.append("连板退潮中，趋势可能接棒")
    if dim3_pct < 0.30 and dim2_pct > 0.50:
        warnings.append("趋势走弱中，连板可能接棒")
    if dim4_pct < 0.30:
        warnings.append("整体情绪低迷，仓位从严")

    return {
        "style": style,
        "total": total,
        "confidence": confidence,
        "lianban_conf": lianban_conf,
        "trend_conf": trend_conf,
        "lianban_signal_pct": round(lianban_signal * 100),
        "trend_signal_pct": round(trend_signal * 100),
        "lianban_detail": lianban_detail,
        "trend_detail": trend_detail,
        "days_in_regime": new_days,
        "flipped": flipped,
        "warnings": warnings,
    }


# ========== 主入口 ==========

def main():
    import argparse
    parser = argparse.ArgumentParser(description="市场风格检测 v0.3")
    parser.add_argument("--date", help="回测日期")
    parser.add_argument("--json", action="store_true", help="JSON输出")
    parser.add_argument("--review", help="复盘笔记路径（数据增强）")
    parser.add_argument("--no-save", action="store_true", help="不保存状态")
    args = parser.parse_args()

    date_str = args.date or datetime.now().strftime("%Y-%m-%d")

    # 解析复盘笔记
    review = {}
    if args.review:
        review = parse_review_frontmatter(args.review)
        if review:
            print(f"📋 复盘数据加载: {args.review}", file=sys.stderr)

    print(f"📊 风格检测 {date_str}", file=sys.stderr)
    print("=" * 55, file=sys.stderr)

    s1 = score_dim1(review)
    s2 = score_dim2(review)
    s3 = score_dim3(review)
    s4 = score_dim4(review)
    apply_review_score_validation(review, s1, s2, s3, s4)

    dims = [
        ("维度一 · 量能环境", s1),
        ("维度二 · 连板生态", s2),
        ("维度三 · 趋势赚钱效应", s3),
        ("维度四 · 情绪广度", s4),
    ]
    for label, sd in dims:
        print(f"\n{label}: {sd['score']}/{sd['max']}", file=sys.stderr)
        for k, v in sd["details"].items():
            print(f"  {k}: {v}", file=sys.stderr)

    result = determine_style(s1, s2, s3, s4, date_str)

    # 分层晋级率（供 trading-core 硬卡判定用）
    tiered_jjl = {}
    if args.review:
        tiered_jjl = parse_tiered_jjl(args.review)

    # 资金分配（根据 trading-core 分配插值表）
    alloc = compute_allocation(result["total"], result.get("lianban_conf"))

    print(f"\n{'=' * 55}", file=sys.stderr)
    print(f"风格: {result['style']} (置信度 {result['confidence']}%)", file=sys.stderr)
    print(f"信号强度 — 连板: {result['lianban_signal_pct']}% ({result['lianban_detail']}) | 趋势: {result['trend_signal_pct']}% ({result['trend_detail']})", file=sys.stderr)
    print(f"资金分配 — 连板: {alloc['连板资金占比']}% | 趋势: {alloc['趋势资金占比']}%", file=sys.stderr)
    if tiered_jjl:
        print(f"分层晋级率 — 一进二: {tiered_jjl.get('一进二晋级率', '?')}% | 二进三: {tiered_jjl.get('二进三晋级率', '?')}% | 三进四+: {tiered_jjl.get('三进四晋级率', '?')}%", file=sys.stderr)
    print(f"持续天数: {result['days_in_regime']}天", file=sys.stderr)
    if result['flipped']:
        print(f"⚠️ 风格翻转！", file=sys.stderr)
    for w in result['warnings']:
        print(f"⚠️ {w}", file=sys.stderr)
    print(f"{'=' * 55}", file=sys.stderr)

    if args.json:
        output = {
            "date": date_str,
            "dim1": {"score": s1["score"], "max": s1["max"], "details": s1["details"]},
            "dim2": {"score": s2["score"], "max": s2["max"], "details": s2["details"]},
            "dim3": {"score": s3["score"], "max": s3["max"], "details": s3["details"]},
            "dim4": {"score": s4["score"], "max": s4["max"], "details": s4["details"]},
            "total": result["total"],
            "style": result["style"],
            "confidence": result["confidence"],
            "lianban_conf": result["lianban_conf"],
            "trend_conf": result["trend_conf"],
            "lianban_signal_pct": result["lianban_signal_pct"],
            "trend_signal_pct": result["trend_signal_pct"],
            "lianban_detail": result["lianban_detail"],
            "trend_detail": result["trend_detail"],
            "tiered_jjl": tiered_jjl if tiered_jjl else None,
            "allocation": alloc,
            "days_in_regime": result["days_in_regime"],
            "warnings": result["warnings"],
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
