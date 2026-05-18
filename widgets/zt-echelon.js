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
    this._insights = null;
  }

  render(data) {
    var self = this;
    var body = this.getBody();
    if (!body) return;

    var hotList = (data && data.hot_list) || {};
    var reasonStats = hotList.reason_stats || {};
    var ztStocks = hotList.zt_stocks || [];
    var ztHistory = hotList.zt_history || {};

    // Build date list
    var dates = this._buildDateList(ztStocks, ztHistory);
    if (!this._selectedDate || dates.indexOf(this._selectedDate) < 0) {
      this._selectedDate = dates[0];
    }

    // Get stocks for selected date
    var stocks = this._getStocksForDate(this._selectedDate, ztStocks, ztHistory);
    var isToday = (this._selectedDate === new Date().toISOString().substring(0, 10));

    // Compute 连板性质
    stocks.forEach(function(s) {
      s._nature = self._computeNature(s.code, self._selectedDate, ztHistory);
      s._natureRank = self._natureRank(s._nature);
    });

    // === Concept tag stats (normalized + merged) ===
    var conceptStats = _buildConceptStats(reasonStats);
    var conceptKeys = Object.keys(conceptStats).sort(function(a, b) {
      if (a === '其他') return 1;
      if (b === '其他') return -1;
      return conceptStats[b] - conceptStats[a];
    });
    var top5Keys = conceptKeys.filter(function(k) { return k !== '其他'; }).slice(0, 5);
    var top5Counts = top5Keys.map(function(k) { return conceptStats[k]; });
    var fireThreshold = top5Counts.length >= 5 ? top5Counts[top5Counts.length - 1]
      : (top5Counts.length > 0 ? top5Counts[top5Counts.length - 1] : 999);

    // Filter by selected concepts (normalize both sides)
    if (this._selectedConcepts.length > 0) {
      stocks = stocks.filter(function(s) {
        var tags = (s.reason || '').split('+');
        var normTags = tags.map(function(t) { return _normalizeConcept(t.trim()); });
        return self._selectedConcepts.some(function(c) {
          return normTags.indexOf(c) >= 0;
        });
      });
    }

    // Sort
    if (this._sortKey === 'nature') {
      stocks.sort(function(a, b) { return b._natureRank - a._natureRank; });
    } else if (this._sortKey === 'reason') {
      stocks.sort(function(a, b) { return (a.reason || '').localeCompare(b.reason || ''); });
    }

    // Stats
    var natureCount = {};
    stocks.forEach(function(s) {
      var n = s._nature || '首板';
      natureCount[n] = (natureCount[n] || 0) + 1;
    });
    var maxBoard = 0;
    Object.keys(natureCount).forEach(function(k) {
      var m = k.match(/^(\d+)连板/);
      if (m) maxBoard = Math.max(maxBoard, parseInt(m[1]));
    });

    var stats_首板 = natureCount['首板'] || 0;
    var stats_二连 = 0, stats_三连 = 0, stats_四板 = 0;
    Object.keys(natureCount).forEach(function(k) {
      if (k === '首板') return;
      var m = k.match(/^(\d+)连板/);
      if (m) {
        var v = parseInt(m[1]);
        if (v >= 4) stats_四板 += natureCount[k];
        else if (v === 3) stats_三连 += natureCount[k];
        else if (v === 2) stats_二连 += natureCount[k];
      }
    });
    var statsHtml = '<div class="zt-stats">';
    statsHtml += '最高板: <b>' + (maxBoard > 0 ? maxBoard + '连板' : '—') + '</b>';
    statsHtml += ' | 首板:' + stats_首板;
    statsHtml += ' 二连:' + stats_二连;
    statsHtml += ' 三连:' + stats_三连;
    statsHtml += ' 四板:' + stats_四板;
    statsHtml += ' | 共' + stocks.length + '只';
    statsHtml += '</div>';

    // === Render ===
    var html = '';

    // Row 1: Date tabs
    html += '<div class="zt-date-row">';
    dates.forEach(function(d) {
      var label = d.substring(5);
      var active = d === self._selectedDate ? ' active' : '';
      html += '<span class="zt-date-tab' + active + '" data-date="' + d + '">' + label + '</span>';
    });
    html += '</div>';

    // Row 2: Concept tags (merged)
    if (conceptKeys.length > 0) {
      html += '<div class="zt-concept-row">';
      conceptKeys.forEach(function(c) {
        var count = conceptStats[c];
        var isOther = (c === '其他');
        var isFire = (!isOther && count >= fireThreshold) ? ' fire' : '';
        var isSel = self._selectedConcepts.indexOf(c) >= 0 ? ' active' : '';
        var mutedCls = isOther ? ' zt-muted' : '';
        html += '<span class="zt-concept-tag' + isFire + isSel + mutedCls + '" data-concept="' + c + '">';
        if (!isOther && count >= fireThreshold) html += '🔥 ';
        html += c + ' <b>' + count + '</b></span>';
      });
      html += '</div>';
    }

    // Stats bar (between concepts and table)
    if (stocks.length > 0) {
      html += statsHtml;
    }

    // No data state
    if (stocks.length === 0) {
      html += '<div class="zt-empty">';
      if (isToday && ztStocks.length === 0) {
        html += '⏳ 等待开盘（今日数据尚未更新，切换日期Tab可看历史）';
      } else {
        html += '当日无涨停数据';
      }
      html += '</div>';
    } else {
      // Table header
      html += '<div class="zt-table-header">';
      html += '<span class="zt-col-name">名称</span>';
      html += '<span class="zt-col-chg">涨幅</span>';
      html += '<span class="zt-col-hs">换手</span>';
      html += '<span class="zt-col-amt">成交额</span>';
      var natureCls = self._sortKey === 'nature' ? ' zt-sortable zt-sorted' : ' zt-sortable';
      html += '<span class="zt-col-nature' + natureCls + '" data-sort="nature">性质</span>';
      var reasonCls = self._sortKey === 'reason' ? ' zt-sortable zt-sorted' : ' zt-sortable';
      html += '<span class="zt-col-reason' + reasonCls + '" data-sort="reason">板块</span>';
      html += '</div>';

      // Stock list
      html += '<div class="zt-stock-list">';
      stocks.forEach(function(s) {
        var natureCls = '';
        if (s._nature === '首板') natureCls = ' zt-nature-1';
        else if (s._nature === '二连板') natureCls = ' zt-nature-2';
        else natureCls = ' zt-nature-3';

        var hs = s.huanshou != null ? s.huanshou.toFixed(1) + '%' : '—';
        var amt = s.chengjiaoe != null ? self._fmtAmt(s.chengjiaoe) : '—';
        var chg = s.zhangfu != null ? (s.zhangfu >= 0 ? '+' : '') + s.zhangfu.toFixed(2) + '%' : '—';
        var chgCls = s.zhangfu > 0 ? 'up' : (s.zhangfu < 0 ? 'down' : '');

        html += '<div class="zt-stock-row">';
        html += '<span class="zt-col-name">' + s.name + '</span>';
        html += '<span class="zt-col-chg ' + chgCls + '">' + chg + '</span>';
        html += '<span class="zt-col-hs">' + hs + '</span>';
        html += '<span class="zt-col-amt">' + amt + '</span>';
        html += '<span class="zt-col-nature' + natureCls + '">' + s._nature + '</span>';
        html += '<span class="zt-col-reason">' + (s.reason || '—') + '</span>';
        html += '</div>';
      });
      html += '</div>';
    }

    // LLM slot
    html += this._renderLLMSlot();

    // Debug line

    body.innerHTML = html;

    // Bind events
    this._bindEvents(body, dates);
    this.updateTimestamp();
  }

  // === Internal methods ===

  _buildDateList(ztStocks, ztHistory) {
    var dates = [];
    var today = new Date().toISOString().substring(0, 10);
    ztStocks = ztStocks || [];
    ztHistory = ztHistory || {};

    // Today always first if we have today's data
    var allDates = Object.keys(ztHistory).concat([today]);
    allDates.sort().reverse();
    // Deduplicate
    var seen = {};
    var result = [];
    allDates.forEach(function(d) {
      if (!seen[d]) { seen[d] = true; result.push(d); }
    });
    return result.slice(0, 5);
  }

  _getStocksForDate(dateStr, ztStocks, ztHistory) {
    if (!dateStr) return [];
    var today = new Date().toISOString().substring(0, 10);
    if (dateStr === today) return ztStocks || [];
    return (ztHistory && ztHistory[dateStr]) || [];
  }

  _computeNature(code, dateStr, ztHistory) {
    ztHistory = ztHistory || {};
    var today = new Date().toISOString().substring(0, 10);
    var isToday = (dateStr === today);

    var dates = Object.keys(ztHistory).sort().reverse();
    if (isToday && dates.indexOf(today) < 0) dates.unshift(today);

    var startIdx = dates.indexOf(dateStr);
    if (startIdx < 0) return '首板';

    // Count consecutive streak: today always counts (stock is in live ztStocks)
    var consecutive = 0;
    for (var i = startIdx; i < dates.length; i++) {
      var d = dates[i];
      var stocks = ztHistory[d] || [];
      var found = (isToday && i === startIdx) ? true : stocks.some(function(s) { return s.code === code; });
      if (found) consecutive++; else break;
    }

    var totalApps = 0, firstApp = null, lastApp = null;
    for (var j = dates.length - 1; j >= 0; j--) {
      var day = dates[j];
      var dayStocks = ztHistory[day] || [];
      var inDay = (isToday && j === startIdx) ? true : dayStocks.some(function(s) { return s.code === code; });
      if (inDay) {
        totalApps++;
        if (firstApp === null) firstApp = day;
        lastApp = day;
      }
    }

    if (consecutive >= 2) {
      return consecutive + '连板';
    } else if (consecutive === 1 && totalApps >= 2) {
      var firstIdx = dates.indexOf(firstApp);
      var lastIdx = dates.indexOf(lastApp);
      var daySpan = lastIdx >= 0 && firstIdx >= 0 ? firstIdx - lastIdx + 1 : totalApps;
      return daySpan + '天' + totalApps + '板';
    }
    return '首板';
  }

  _natureRank(nature) {
    if (!nature) return 0;
    var m = nature.match(/^(\d+)连板/);
    if (m) return parseInt(m[1]) * 100;
    var m2 = nature.match(/^(\d+)天(\d+)板/);
    if (m2) return parseInt(m2[1]) * 10 + parseInt(m2[2]);
    if (nature === '首板') return 1;
    return 0;
  }

  _fmtAmt(val) {
    // val is in 万元 from ths_hot API
    if (!val || val === 0) return '—';
    var yi = val / 10000;
    if (yi >= 10000) return (yi / 10000).toFixed(2) + '万亿';
    if (yi >= 1) return yi.toFixed(1) + '亿';
    return val + '万';
  }

  _renderLLMSlot() {
    var self = this;
    if (!this._insights) {
      this._loadInsights();
      return '<div class="zt-llm">🤖 LLM研判加载中...</div>';
    }

    var today = new Date().toISOString().substring(0, 10);
    var todayData = this._insights[today] || {};
    var text = '';

    // Search for matching keywords
    var keywords = ['涨停梯队', '连板', '涨停', '梯队'];
    var keys = Object.keys(todayData);
    for (var i = 0; i < keywords.length && !text; i++) {
      for (var j = 0; j < keys.length && !text; j++) {
        var entry = todayData[keys[j]] || {};
        var t = entry.text || '';
        if (t.indexOf(keywords[i]) >= 0 || keys[j].indexOf(keywords[i]) >= 0) {
          text = t;
          break;
        }
      }
    }

    // Fallback: latest global insight
    if (!text && keys.length > 0) {
      text = todayData[keys[0]].text || '';
    }

    // Try other dates
    if (!text) {
      var allDates = Object.keys(this._insights).sort().reverse();
      for (var d = 0; d < allDates.length && !text; d++) {
        var dd = this._insights[allDates[d]] || {};
        var dk = Object.keys(dd);
        if (dk.length > 0) {
          text = dd[dk[0]].text || '';
        }
      }
    }

    if (text) {
      var short = text.length > 100 ? text.substring(0, 100) + '...' : text;
      return '<div class="zt-llm">🤖 ' + short + '</div>';
    }
    return '';
  }

  _loadInsights() {
    var self = this;
    fetch('data/llm_insights.json?t=' + Date.now())
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(data) {
        if (data) { self._insights = data; self._renderBody(); }
      })
      .catch(function() {});
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
