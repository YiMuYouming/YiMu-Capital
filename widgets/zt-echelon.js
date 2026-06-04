// widgets/zt-echelon.js — W21 涨停梯队 v1.1
// 标签合并 → 未来可切 SSOT（涨停日志 JSON），输出结构不变
'use strict';

// === 板块归一化 → 涨停日志 SSOT 口径 ===
// 64种板块变体 → 22个标准板块。后续切 SSOT 时替换此层即可。
var CONCEPT_MERGE = {
  // 算力/半导体
  '算力':'算力/半导体', '算力产业链':'算力/半导体', '算力合同':'算力/半导体',
  '算力/光通信/PCB':'算力/半导体', '算力/半导体产业链':'算力/半导体',
  '半导体':'算力/半导体', '半导体产业链':'算力/半导体', '半导体材料':'算力/半导体',
  '半导体封装':'算力/半导体', '半导体/存储':'算力/半导体', '第三代半导体':'算力/半导体',
  '存储芯片':'算力/半导体', '存储上游':'算力/半导体', '芯片概念':'算力/半导体',
  '先进封装':'算力/半导体', '碳化硅':'算力/半导体', 'AI服务器':'算力/半导体',
  '东数西算':'算力/半导体', '电子特气':'算力/半导体', '电子特气/化工':'算力/半导体',
  '氢氟酸涨价':'算力/半导体', '800G交换机':'算力/半导体',
  // 算力租赁
  '算力租赁':'算力租赁',
  // 电力
  '电力':'电力', '绿色电力':'电力', '算电协同':'电力', '电力改革':'电力',
  '电力/储能':'电力', '电力/燃气轮机':'电力', '电力/燃气':'电力',
  '电力/电缆':'电力', '电力/算电':'电力', '电力(退潮)':'电力',
  '燃气轮机':'电力', '储能':'电力', '数据中心供电':'电力',
  '风光火储':'电力', '绿电转型':'电力',
  // 光通信/CPO
  '光通信':'光通信/CPO', '光通信/光纤':'光通信/CPO', '光通信/CPO':'光通信/CPO',
  'CPO':'光通信/CPO', 'CPO概念':'光通信/CPO', 'CPO/光通信':'光通信/CPO',
  '光模块':'光通信/CPO', '硅光芯片':'光通信/CPO', '光纤':'光通信/CPO',
  '光纤涨价':'光通信/CPO', '光电/LED':'光通信/CPO',
  // 机器人
  '机器人':'机器人', '人形机器人':'机器人', '机器人概念':'机器人',
  '机器人🆕':'机器人', '机器人/无人驾驶':'机器人', '机器人代工':'机器人',
  // PCB链
  'PCB':'PCB链', 'PCB链':'PCB链', '覆铜板':'PCB链', 'PCB/电子':'PCB链',
  'PCB链/铜箔':'PCB链',
  // 航天/军工
  '航天':'航天/军工', '航天/军工':'航天/军工', '航天/光伏':'航天/军工',
  '商业航天':'航天/军工', '军工':'航天/军工', '低空经济':'航天/军工',
  // 锂电池
  '锂电池':'锂电池', '锂电':'锂电池', '电池':'锂电池',
  // 光伏
  '光伏':'光伏', '光伏🆕':'光伏', 'TOPCon':'光伏',
  '光伏建筑一体化':'光伏', '光伏储能':'光伏',
  // 并购重组/股权
  '并购重组':'并购重组/股权', '股权转让':'并购重组/股权', '并购重组/股权':'并购重组/股权',
  '股份转让':'并购重组/股权',
  // 其他标准板块
  '地产':'地产产业链', '地产产业链':'地产产业链', '房地产':'地产产业链',
  '大消费':'大消费', '医药':'医药',
  '液冷':'液冷', '液冷服务器':'液冷', '液冷并购':'液冷',
  '有色金属':'有色/稀土', '稀土永磁':'有色/稀土', '有色/钨/稀土':'有色/稀土', '钨':'有色/稀土',
  '建筑装饰':'建筑/装饰', '建筑':'建筑/装饰', '基建/建筑':'建筑/装饰',
  '汽车零部件':'汽车零部件',
  '环保':'环保/水利', '环保/水利':'环保/水利', '水利':'环保/水利',
  '化工':'化工/新材料', '化工/新材料':'化工/新材料',
  'AI应用':'AI应用', 'AI':'AI应用',
  // 摘帽/ST → 归入其他（不独立显示）
  'ST板块':'摘帽', 'ST摘帽预期':'摘帽', '摘帽预期':'摘帽',
  '摘帽申请':'摘帽', '申请摘帽':'摘帽', 'ST反弹':'摘帽', '摘帽':'摘帽',
  '控制权变更':'摘帽',
};
// 不显示的概念标签（过滤掉）
var CONCEPT_FILTER = ['央企','央企背景','国企','国企改革','国资','国资背景',
  '新疆国资','厦门国资','湖南国资','北京国资','地方国资','唐山国资','淄博国资入主',
  '复牌','股东转让','控制权变更',
  '大单','亿大单','订单','出口','出口增长','涨价',
  '新股','次新','超跌','超跌反弹','扭亏','拟收购','机构','询价',
  '苹果概念','华为合作','OLED','超级电容','世界杯','短剧',
  '一季报','年报','一季报增长','一季报扭亏','股权激励','特斯拉','马斯克',
  '创新药','检测','CRO','宠物','保健品','猪肉','猪周期',
  '连续涨停','涨停','更名','债务延期','重整预期',
  '虫草龙头','酒水高增','智能制造','涂装业务','小家电','露营经济',
  '墙布','瓶盖龙头','北美客户','牛散举牌','跨境电商','流通盘小',
  '天然气','油气服务','环氧丙烷','特种线缆','消费电子',
  '业绩增长','华为合作',
];
// 涨停日志每日常见 7-10 个板块。概念行最多显示 TOP_N，其余归「其他」
var CONCEPT_TOP_N = 8;

function _normalizeConcept(raw) {
  var clean = String(raw||'').replace(/🆕|⬇️|🔄|✅|❌|🔥/g, '').trim();
  if (CONCEPT_MERGE[clean]) return CONCEPT_MERGE[clean];
  // 模糊匹配：长标签包含短key
  for (var k in CONCEPT_MERGE) {
    if (clean.indexOf(k) >= 0) return CONCEPT_MERGE[k];
  }
  return clean;
}

function _isConceptTag(tag) {
  for (var i = 0; i < CONCEPT_FILTER.length; i++) {
    if (tag.indexOf(CONCEPT_FILTER[i]) >= 0) return false;
  }
  return true;
}

function _buildConceptStats(reasonStats) {
  // Normalize and merge concept counts
  var merged = {};
  var keys = Object.keys(reasonStats || {});
  for (var i = 0; i < keys.length; i++) {
    var raw = keys[i];
    var norm = _normalizeConcept(raw);
    if (!_isConceptTag(raw) || !_isConceptTag(norm)) continue;
    merged[norm] = (merged[norm] || 0) + (reasonStats[raw] || 0);
  }
  // Sort by count desc, keep top N, rest → 其他
  var sorted = Object.keys(merged).sort(function(a, b) { return merged[b] - merged[a]; });
  var result = {};
  var otherCount = 0;
  for (var i = 0; i < sorted.length; i++) {
    var k = sorted[i];
    // 摘帽永远归入其他
    if (k === '摘帽') { otherCount += merged[k]; continue; }
    if (i < CONCEPT_TOP_N) {
      result[k] = merged[k];
    } else {
      otherCount += merged[k];
    }
  }
  if (otherCount > 0) result['其他'] = otherCount;
  return result;
}

class ZtEchelonWidget extends YiMuWidget {
  constructor(config) {
    super(config);
    this._selectedConcepts = [];
    this._selectedDate = null;
    this._sortKey = null;
  }

  render(data) {
    var self = this;
    var body = this.getBody();
    if (!body) return;

    var hotList = (data && data.hot_list) || {};
    var reasonStats = hotList.reason_stats || {};
    var today = this._today();
    var confirmedZt = this._normalizeHotStocks(hotList.zt_stocks || [], 'ths');
    var hotStocks = this._normalizeHotStocks(hotList.stocks || [], 'hot');
    var iwencaiStocks = this._normalizeIwencaiStocks((data && data.iwencai && data.iwencai['连板股列表']) || []);
    var ztHistory = hotList.zt_history || {};
    if (confirmedZt.length > 0) self._saveLocalHistory(confirmedZt);

    // Build date list
    var dates = this._buildDateList(confirmedZt, ztHistory, iwencaiStocks);
    if (!this._selectedDate || dates.indexOf(this._selectedDate) < 0) {
      this._selectedDate = dates[0];
    }

    var isToday = (this._selectedDate === today);
    var displayStocks = this._getConfirmedStocksForDate(
      this._selectedDate, confirmedZt, iwencaiStocks, ztHistory
    );
    displayStocks.forEach(function(s) {
      var computed = s._boardLevel > 0 ? s._boardLevel + '板' : self._computeNature(s.code, self._selectedDate, ztHistory);
      s._nature = computed === '首板' ? '首板' : computed;
      s._natureRank = self._natureRank(s._nature);
    });

    var conceptStats = _buildConceptStats(reasonStats);
    var conceptKeys = Object.keys(conceptStats).sort(function(a, b) {
      if (a === '其他') return 1;
      if (b === '其他') return -1;
      return conceptStats[b] - conceptStats[a];
    });

    if (this._selectedConcepts.length > 0) {
      displayStocks = displayStocks.filter(function(s) {
        var tags = (s.reason || '').split('+');
        var normTags = tags.map(function(t) { return _normalizeConcept(t.trim()); });
        return self._selectedConcepts.some(function(c) {
          return normTags.indexOf(c) >= 0;
        });
      });
    }

    if (this._sortKey === 'nature') {
      displayStocks.sort(function(a, b) { return b._natureRank - a._natureRank; });
    } else if (this._sortKey === 'reason') {
      displayStocks.sort(function(a, b) { return (a.reason || '').localeCompare(b.reason || ''); });
    } else {
      displayStocks.sort(function(a, b) { return b._natureRank - a._natureRank; });
    }

    var confirmedCodes = {};
    displayStocks.forEach(function(s) { if (s.code) confirmedCodes[s.code] = true; });
    var hotObserve = hotStocks.filter(function(s) { return !confirmedCodes[s.code]; }).slice(0, 12);
    if (this._selectedConcepts.length > 0) {
      hotObserve = hotObserve.filter(function(s) {
        var tags = (s.reason || '').split('+');
        var normTags = tags.map(function(t) { return _normalizeConcept(t.trim()); });
        return self._selectedConcepts.some(function(c) { return normTags.indexOf(c) >= 0; });
      });
    }

    var stats = this._buildStats(displayStocks);
    var hasFullZtSource = confirmedZt.length > 0;
    var hasIwcSource = iwencaiStocks.length > 0;
    var sourceLabel = isToday
      ? (hasIwcSource ? '问财连板' : (hasFullZtSource ? '同花顺涨停' : '涨停源待确认'))
      : '历史快照';
    var updated = this._formatUpdated(hotList._updated);

    // === Render ===
    var html = '';
    html += '<div class="zt-source-row">';
    html += '<span class="zt-source-chip primary">' + this._esc(sourceLabel) + '</span>';
    html += '<span class="zt-source-chip">热榜实时 ' + (hotList.total || hotStocks.length || 0) + '只</span>';
    if (updated) html += '<span class="zt-source-chip muted">更新 ' + this._esc(updated) + '</span>';
    if (isToday && !hasFullZtSource) {
      html += '<span class="zt-source-chip warn">首板源未确认</span>';
    }
    html += '</div>';

    html += '<div class="zt-date-row">';
    dates.forEach(function(d) {
      var label = d.substring(5);
      var active = d === self._selectedDate ? ' active' : '';
      html += '<span class="zt-date-tab' + active + '" data-date="' + d + '">' + label + '</span>';
    });
    html += '</div>';

    html += '<div class="zt-stats">';
    html += '<span>最高 <b>' + (stats.maxBoard > 0 ? stats.maxBoard + '板' : '—') + '</b></span>';
    html += '<span>次高 <b>' + (stats.secondBoard > 0 ? stats.secondBoard + '板' : '—') + '</b></span>';
    html += '<span>连板 <b>' + stats.linkedCount + '</b></span>';
    html += '<span>首板 <b>' + stats.firstCount + '</b></span>';
    html += '<span>确认 <b>' + displayStocks.length + '</b>只</span>';
    html += '</div>';

    if (displayStocks.length > 0) {
      html += this._renderBoardLanes(displayStocks);
    }

    if (conceptKeys.length > 0) {
      html += '<div class="zt-concept-row">';
      conceptKeys.forEach(function(c) {
        var count = conceptStats[c];
        var isOther = (c === '其他');
        var isSel = self._selectedConcepts.indexOf(c) >= 0 ? ' active' : '';
        var mutedCls = isOther ? ' zt-muted' : '';
        html += '<span class="zt-concept-tag' + isSel + mutedCls + '" data-concept="' + self._esc(c) + '">';
        html += self._esc(c) + ' <b>' + count + '</b></span>';
      });
      html += '</div>';
    }

    if (displayStocks.length === 0) {
      html += '<div class="zt-empty">';
      if (isToday) {
        html += '今日确认涨停源暂不可用，可先看热榜观察和历史日期。';
      } else {
        html += '该日期暂无涨停历史快照。';
      }
      html += '</div>';
    } else {
      html += this._renderStockTable('确认梯队', displayStocks, true);
    }

    if (isToday && hotObserve.length > 0) {
      html += this._renderHotObserve(hotObserve);
    }

    body.innerHTML = html;

    this._bindEvents(body, dates);
    this.updateTimestamp();
  }

  // === Internal methods ===

  _today() {
    var d = new Date();
    var m = String(d.getMonth() + 1).padStart(2, '0');
    var day = String(d.getDate()).padStart(2, '0');
    return d.getFullYear() + '-' + m + '-' + day;
  }

  _esc(v) {
    return String(v == null ? '' : v)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  _toNum(v) {
    if (v == null || v === '') return null;
    var n = parseFloat(String(v).replace('%', '').replace('+', ''));
    return isNaN(n) ? null : n;
  }

  _normalizeHotStocks(list, source) {
    var self = this;
    return (list || []).filter(function(s) {
      var name = s.name || s['名称'] || '';
      return !/ST/.test(name);
    }).map(function(s) {
      return {
        code: String(s.code || s['代码'] || ''),
        name: s.name || s['名称'] || '—',
        zhangfu: self._toNum(s.zhangfu != null ? s.zhangfu : s['涨幅']),
        huanshou: self._toNum(s.huanshou != null ? s.huanshou : s['换手率']),
        chengjiaoe: self._toNum(s.chengjiaoe != null ? s.chengjiaoe : s['成交额']),
        reason: s.reason || s['所属概念'] || s['概念'] || '',
        _source: source,
        _boardLevel: 0,
      };
    });
  }

  _normalizeIwencaiStocks(list) {
    var self = this;
    return (list || []).filter(function(s) {
      var name = s['名称'] || s.name || s['股票简称'] || '';
      return !/ST/.test(name);
    }).map(function(s) {
      var board = parseInt(s['连板数'] || s.board_count || s['连续涨停天数'] || 1, 10);
      if (!board || board < 1) board = 1;
      return {
        code: String(s['代码'] || s.code || ''),
        name: s['名称'] || s.name || s['股票简称'] || '—',
        zhangfu: self._toNum(s['涨幅'] || s.zhangfu),
        huanshou: self._toNum(s['换手率'] || s.huanshou),
        chengjiaoe: self._toNum(s['成交额'] || s.chengjiaoe),
        reason: s['所属概念'] || s['概念'] || s.reason || '',
        _source: 'iwencai',
        _boardLevel: board,
      };
    });
  }

  _buildDateList(ztStocks, ztHistory, iwencaiStocks) {
    var today = this._today();
    ztStocks = ztStocks || [];
    iwencaiStocks = iwencaiStocks || [];
    ztHistory = ztHistory || {};

    var allDates = Object.keys(ztHistory);
    if (ztStocks.length > 0 || iwencaiStocks.length > 0 || allDates.length === 0) {
      allDates.push(today);
    }
    allDates.sort().reverse();
    var seen = {};
    var result = [];
    allDates.forEach(function(d) {
      if (!seen[d]) { seen[d] = true; result.push(d); }
    });
    return result.slice(0, 5);
  }

  _getConfirmedStocksForDate(dateStr, ztStocks, iwencaiStocks, ztHistory) {
    if (!dateStr) return [];
    var today = this._today();
    var merged = [];
    var seen = {};
    function add(s) {
      if (!s || !s.code || seen[s.code]) return;
      seen[s.code] = true;
      merged.push(s);
    }
    if (dateStr === today) {
      (iwencaiStocks || []).forEach(add);
      (ztStocks || []).forEach(add);
      return merged;
    }
    return this._normalizeHotStocks((ztHistory && ztHistory[dateStr]) || [], 'history');
  }

  _computeNature(code, dateStr, ztHistory) {
    ztHistory = ztHistory || {};
    var today = this._today();
    var isToday = (dateStr === today);

    var dates = Object.keys(ztHistory).sort().reverse();
    if (isToday && dates.indexOf(today) < 0) dates.unshift(today);

    var startIdx = dates.indexOf(dateStr);
    if (startIdx < 0) return '首板';

    // 检查某日期是否包含该股票：兼容对象数组 [{code}] 和字符串数组 ["code"]
    function _hasCode(dayData, c) {
      if (!dayData || !dayData.length) return false;
      return dayData.some(function(s) {
        return (typeof s === 'string') ? s === c : s.code === c;
      });
    }

    // Count consecutive streak backwards from dateStr
    var consecutive = 0;
    for (var i = startIdx; i < dates.length; i++) {
      var d = dates[i];
      var found = (isToday && i === startIdx) ? true : _hasCode(ztHistory[d], code);
      if (found) consecutive++; else break;
    }

    // Count total appearances
    var totalApps = 0;
    for (var j = 0; j < dates.length; j++) {
      var day = dates[j];
      var inDay = (isToday && j === startIdx) ? true : _hasCode(ztHistory[day], code);
      if (inDay) totalApps++;
    }

    if (consecutive >= 2) {
      return consecutive + '板';
    }
    return '首板';
  }

  _natureRank(nature) {
    if (!nature) return 0;
    var m = nature.match(/^(\d+)板/);
    if (m) return parseInt(m[1]) * 100;
    if (nature === '首板') return 1;
    return 0;
  }

  _buildStats(stocks) {
    var boards = [];
    var firstCount = 0;
    stocks.forEach(function(s) {
      var level = s._natureRank >= 100 ? Math.floor(s._natureRank / 100) : 1;
      if (level > 1) boards.push(level);
      else firstCount++;
    });
    boards.sort(function(a, b) { return b - a; });
    return {
      maxBoard: boards[0] || 0,
      secondBoard: boards[1] || 0,
      linkedCount: boards.length,
      firstCount: firstCount,
    };
  }

  _renderBoardLanes(stocks) {
    var self = this;
    var groups = {};
    stocks.forEach(function(s) {
      var level = s._natureRank >= 100 ? Math.floor(s._natureRank / 100) : 1;
      var key = level > 1 ? level + '板' : '首板';
      if (!groups[key]) groups[key] = [];
      groups[key].push(s);
    });
    var keys = Object.keys(groups).sort(function(a, b) {
      var av = a === '首板' ? 1 : parseInt(a, 10);
      var bv = b === '首板' ? 1 : parseInt(b, 10);
      return bv - av;
    });
    var html = '<div class="zt-lanes">';
    keys.forEach(function(k) {
      html += '<div class="zt-lane">';
      html += '<div class="zt-lane-head"><b>' + self._esc(k) + '</b><span>' + groups[k].length + '只</span></div>';
      html += '<div class="zt-lane-stocks">';
      groups[k].slice(0, 8).forEach(function(s) {
        html += '<span title="' + self._esc(s.reason || '') + '">' + self._esc(s.name) + '</span>';
      });
      if (groups[k].length > 8) html += '<em>+' + (groups[k].length - 8) + '</em>';
      html += '</div></div>';
    });
    html += '</div>';
    return html;
  }

  _renderStockTable(title, stocks, sortable) {
    var self = this;
    var natureCls = this._sortKey === 'nature' ? ' zt-sortable zt-sorted' : ' zt-sortable';
    var reasonCls = this._sortKey === 'reason' ? ' zt-sortable zt-sorted' : ' zt-sortable';
    var html = '<div class="zt-section-title">' + this._esc(title) + '</div>';
    html += '<div class="zt-table-header">';
    html += '<span class="zt-col-name">名称</span>';
    html += '<span class="zt-col-chg">涨幅</span>';
    html += '<span class="zt-col-hs">换手</span>';
    html += '<span class="zt-col-amt">成交额</span>';
    html += '<span class="zt-col-nature' + (sortable ? natureCls : '') + '" data-sort="nature">性质</span>';
    html += '<span class="zt-col-reason' + (sortable ? reasonCls : '') + '" data-sort="reason">板块</span>';
    html += '</div>';
    html += '<div class="zt-stock-list">';
    stocks.forEach(function(s) { html += self._renderStockRow(s, true); });
    html += '</div>';
    return html;
  }

  _renderStockRow(s, showNature) {
    var level = s._natureRank >= 100 ? Math.floor(s._natureRank / 100) : 1;
    var natureCls = level <= 1 ? ' zt-nature-1' : (level === 2 ? ' zt-nature-2' : ' zt-nature-3');
    var hs = s.huanshou != null ? s.huanshou.toFixed(1) + '%' : '—';
    var amt = s.chengjiaoe != null ? this._fmtAmt(s.chengjiaoe) : '—';
    var chg = s.zhangfu != null ? (s.zhangfu >= 0 ? '+' : '') + s.zhangfu.toFixed(2) + '%' : '—';
    var chgCls = s.zhangfu > 0 ? 'up' : (s.zhangfu < 0 ? 'down' : '');
    var html = '<div class="zt-stock-row">';
    html += '<span class="zt-col-name">' + this._esc(s.name) + '</span>';
    html += '<span class="zt-col-chg ' + chgCls + '">' + chg + '</span>';
    html += '<span class="zt-col-hs">' + hs + '</span>';
    html += '<span class="zt-col-amt">' + amt + '</span>';
    html += '<span class="zt-col-nature' + natureCls + '">' + (showNature ? this._esc(s._nature || '首板') : '观察') + '</span>';
    html += '<span class="zt-col-reason">' + this._esc(s.reason || '—') + '</span>';
    html += '</div>';
    return html;
  }

  _renderHotObserve(stocks) {
    var self = this;
    var html = '<div class="zt-hot-observe">';
    html += '<div class="zt-section-title">热榜观察 <span>同花顺实时热榜，未计入确认涨停</span></div>';
    html += '<div class="zt-hot-grid">';
    stocks.forEach(function(s) {
      html += '<div class="zt-hot-card">';
      html += '<b>' + self._esc(s.name) + '</b>';
      html += '<span>' + self._esc(s.reason || '—') + '</span>';
      html += '</div>';
    });
    html += '</div></div>';
    return html;
  }

  _formatUpdated(raw) {
    if (!raw) return '';
    var m = String(raw).match(/T(\d{2}:\d{2})/);
    return m ? m[1] : String(raw).slice(0, 16);
  }

  // === 客户端涨停历史缓存（跨日连板判定用）===

  _historyKey() {
    return 'zt_history_cache_v2';
  }

  _loadLocalHistory() {
    try {
      return JSON.parse(localStorage.getItem(this._historyKey()) || '{}');
    } catch(e) { return {}; }
  }

  _saveLocalHistory(ztStocks) {
    if (!ztStocks || ztStocks.length === 0) return;
    var today = new Date().toISOString().substring(0, 10);
    var hist = this._loadLocalHistory();
    // 保存今日出现的涨停股票 code
    hist[today] = ztStocks.map(function(s) { return s.code; });
    // 保留最近 30 天
    var keys = Object.keys(hist).sort().reverse();
    if (keys.length > 30) {
      var trimmed = {};
      keys.slice(0, 30).forEach(function(k) { trimmed[k] = hist[k]; });
      hist = trimmed;
    }
    try {
      localStorage.setItem(this._historyKey(), JSON.stringify(hist));
    } catch(e) {}
  }

  _fmtAmt(val) {
    // val is in 万元 from ths_hot API
    if (!val || val === 0) return '—';
    var yi = val / 10000;
    if (yi >= 10000) return (yi / 10000).toFixed(2) + '万亿';
    if (yi >= 1) return yi.toFixed(1) + '亿';
    return val + '万';
  }

  _bindEvents(body, dates) {
    var self = this;

    // Date tabs
    var dateTabs = body.querySelectorAll('.zt-date-tab');
    dateTabs.forEach(function(tab) {
      tab.addEventListener('click', function() {
        self._selectedDate = this.dataset.date;
        self._renderBody();
      });
    });

    // Concept tags (multi-select)
    var conceptTags = body.querySelectorAll('.zt-concept-tag');
    conceptTags.forEach(function(tag) {
      tag.addEventListener('click', function() {
        var c = this.dataset.concept;
        var idx = self._selectedConcepts.indexOf(c);
        if (idx >= 0) {
          self._selectedConcepts.splice(idx, 1);
        } else {
          self._selectedConcepts.push(c);
        }
        self._renderBody();
      });
    });

    // Sort headers
    var sortHeaders = body.querySelectorAll('.zt-sortable');
    sortHeaders.forEach(function(h) {
      h.addEventListener('click', function() {
        var key = this.dataset.sort;
        self._sortKey = (self._sortKey === key) ? null : key;
        self._renderBody();
      });
    });
  }
}

WidgetRegistry.register('W21', ZtEchelonWidget);
