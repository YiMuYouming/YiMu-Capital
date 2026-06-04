// widgets/sector-heat.js — W10 板块热力 v4.0 (复盘SSOT + 盘中校验)
'use strict';

function _w10CleanText(value) {
  return String(value == null ? '' : value)
    .replace(/[\u{1F300}-\u{1FAFF}\u2600-\u27BF]/gu, '')
    .replace(/[★☆⭐✅❌⚠️🔥🆕🚨🔴🟡🔵🟢⚫⚪🥇🥈🥉📶🔬📱🔌]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function _w10Norm(value) {
  var s = _w10CleanText(value).replace(/[（）()【】\[\]\s]/g, '').toLowerCase();
  var aliases = [
    ['半导体产业链', '半导体'], ['半导体存储', '半导体'], ['半导体/存储', '半导体'],
    ['先进封装', '半导体'], ['元件pcb', 'pcb'], ['元件/pcb', 'pcb'], ['pcb链', 'pcb'],
    ['通信设备', '通信设备'], ['cpo光通信', '通信设备'], ['cpo/光通信', '通信设备'], ['光通信', '通信设备'],
    ['消费电子', '消费电子'], ['电力改革', '电力'], ['电力储能', '电力'], ['电力', '电力']
  ];
  for (var i = 0; i < aliases.length; i++) {
    if (s.indexOf(aliases[i][0]) >= 0) return aliases[i][1];
  }
  return s;
}

function _w10Num(value) {
  if (value == null || value === '' || value === '—') return null;
  var m = String(value).replace(/,/g, '').match(/[+-]?\d+(?:\.\d+)?/);
  return m ? parseFloat(m[0]) : null;
}

function _w10Pct(value) {
  var n = _w10Num(value);
  return n == null ? '—' : (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
}

function _w10Yi(value) {
  var n = _w10Num(value);
  return n == null ? '—' : (n >= 0 ? '+' : '') + n.toFixed(1) + '亿';
}

function _w10Class(n) {
  n = _w10Num(n);
  return n == null ? 'muted' : n > 0 ? 'up' : n < 0 ? 'down' : 'muted';
}

function _w10ExtractStatus(sec) {
  var status = String(sec && sec['状态'] || '');
  var pct = sec && (sec['涨跌幅'] != null ? sec['涨跌幅'] : sec['板块涨跌幅']);
  var flow = sec && (sec['主力净流入'] != null ? sec['主力净流入'] : sec['净流入']);
  var ma = sec && (sec['5日线位置'] || sec['MA5位置'] || sec['均线']);

  if (pct == null) {
    var pm = status.match(/[+-]?\d+(?:\.\d+)?%/);
    if (pm) pct = pm[0];
  }
  if (flow == null) {
    var fm = status.match(/(?:主力)?([+-]\d+(?:\.\d+)?)\s*亿/);
    if (fm) flow = fm[1];
  }
  if (!ma) {
    if (/站上|均线上升|多头/.test(status)) ma = '站上';
    else if (/跌破|破5日|破MA5/.test(status)) ma = '跌破';
  }

  return {
    pct: _w10Num(pct),
    flow: _w10Num(flow),
    ma: ma ? _w10CleanText(ma) : '',
    note: _w10CleanText(status)
  };
}

class SectorHeatWidget extends YiMuWidget {
  constructor(config) {
    super(config);
    this._sectorInflow = null;
    this._sectorInflowLoading = false;
  }

  render(data) {
    var body = this.getBody();
    if (!body) return;

    var sectors = (data && data.sectors) || [];
    var liveQ = (data && data.live_quotes) || {};
    var lbPool = (data && data.lianban_pool) || [];
    var trPool = (data && data.trend_pool) || [];
    var liveSectors = (data && data.live_sectors) || {};
    var inflowRaw = (data && data.sector_inflow) || this._sectorInflow || [];
    var inflow = Array.isArray(inflowRaw) ? inflowRaw : (inflowRaw.data || []);
    if (!inflow.length) this._loadSectorInflow();

    if (!sectors.length) {
      body.innerHTML = '<div class="w10-empty">板块状态未录入</div>';
      this.updateTimestamp();
      return;
    }

    function liveBySector(name) {
      var target = _w10Norm(name);
      if (liveSectors[name]) return liveSectors[name];
      for (var k in liveSectors) {
        if (_w10Norm(k) === target) return liveSectors[k];
      }
      for (var i = 0; i < inflow.length; i++) {
        if (_w10Norm(inflow[i].name) === target) return inflow[i];
      }
      for (var j = 0; j < inflow.length; j++) {
        var n = _w10Norm(inflow[j].name);
        if (target && n && (target.indexOf(n) >= 0 || n.indexOf(target) >= 0)) return inflow[j];
      }
      return null;
    }

    function stockChange(row) {
      var code = row['代码'] || '';
      var q = liveQ[code] || {};
      var n = _w10Num(q['涨幅']);
      if (n == null) n = _w10Num(row['涨幅']);
      return n;
    }

    function stockRank(row) {
      var role = row['角色'] || '';
      var action = row['操作'] || '';
      if (/持仓|主趋势/.test(role + action)) return 0;
      if (/买入|回踩|操作/.test(action)) return 1;
      if (/候选|观察/.test(role + action)) return 2;
      return 3;
    }

    function sectorStocks(name, limit) {
      var target = _w10Norm(name);
      var rows = lbPool.concat(trPool).filter(function(row) {
        return _w10Norm(row['板块']) === target;
      });
      rows.sort(function(a, b) {
        var r = stockRank(a) - stockRank(b);
        if (r !== 0) return r;
        return Math.abs(stockChange(b) || 0) - Math.abs(stockChange(a) || 0);
      });
      return limit == null ? rows : rows.slice(0, limit);
    }

    function averageStockChange(rows) {
      var vals = rows.map(stockChange).filter(function(v) { return v != null && !isNaN(v); });
      if (!vals.length) return null;
      return vals.reduce(function(a, b) { return a + b; }, 0) / vals.length;
    }

    function typeTone(type) {
      type = _w10CleanText(type);
      if (/分歧|退潮|风险|背离/.test(type)) return 'risk';
      if (/防守|观察|候选/.test(type)) return 'watch';
      if (/主线|强/.test(type)) return 'main';
      return 'neutral';
    }

    var html = '<div class="w10-board">';
    html += '<div class="w10-header"><span>复盘板块</span><span>盘中校验</span></div>';

    sectors.forEach(function(sec) {
      var name = sec['板块'] || '—';
      var cleanName = _w10CleanText(name) || '—';
      var type = _w10CleanText(sec['类型'] || '未分类');
      var tone = typeTone(type + ' ' + (sec['状态'] || ''));
      var live = liveBySector(name) || {};
      var statusInfo = _w10ExtractStatus(sec);
      var pct = _w10Num(live.change_pct != null ? live.change_pct : live['涨跌幅']);
      if (pct == null) pct = statusInfo.pct;
      var flow = _w10Num(live.net_inflow_yi != null ? live.net_inflow_yi : live['主力净流入']);
      if (flow == null) flow = statusInfo.flow;
      var up = live.up_count;
      var down = live.down_count;
      var leader = _w10CleanText(live.leader || sec['龙头'] || '');
      var leaderChg = _w10Num(live.leader_change_pct);
      var ma = statusInfo.ma || _w10CleanText(live['MA5方向'] || live['5日线位置'] || '');
      var source = live && Object.keys(live).length ? '实时' : '复盘';
      var allStocks = sectorStocks(name);
      var stocks = allStocks.slice(0, 3);
      var avgStockPct = averageStockChange(allStocks);
      if (pct == null && avgStockPct != null) {
        pct = avgStockPct;
        source = '池均';
      }

      html += '<article class="w10-row w10-' + tone + '">';
      html += '<div class="w10-main">';
      html += '<div class="w10-title"><b>' + cleanName + '</b><span>' + type + '</span></div>';
      html += '<div class="w10-meta">' +
        '<span>涨停 ' + _w10CleanText(sec['涨停数'] || '—') + '</span>' +
        '<span>梯队 ' + _w10CleanText(sec['梯队'] || '—') + '</span>' +
        (ma ? '<span>MA5 ' + ma + '</span>' : '') +
        '</div>';
      html += '<div class="w10-note">' + (statusInfo.note || '复盘未写状态') + '</div>';
      html += '</div>';

      html += '<div class="w10-live">';
      html += '<div class="w10-live-top">' +
        '<span class="' + _w10Class(pct) + '">' + _w10Pct(pct) + '</span>' +
        '<span class="' + _w10Class(flow) + '">' + _w10Yi(flow) + '</span>' +
        '<em>' + source + '</em>' +
        '</div>';
      html += '<div class="w10-live-sub">' +
        (up != null || down != null ? '<span>涨跌 ' + (up != null ? up : '—') + ':' + (down != null ? down : '—') + '</span>' : '<span>涨跌 —</span>') +
        (leader ? '<span>领涨 ' + leader + (leaderChg != null ? ' ' + _w10Pct(leaderChg) : '') + '</span>' : '<span>龙头 ' + _w10CleanText(sec['龙头'] || '—') + '</span>') +
        '</div>';
      if (stocks.length) {
        html += '<div class="w10-stocks">';
        stocks.forEach(function(s) {
          var chg = stockChange(s);
          html += '<span><b>' + _w10CleanText(s['标的'] || '') + '</b><i class="' + _w10Class(chg) + '">' + _w10Pct(chg) + '</i></span>';
        });
        html += '</div>';
      } else {
        html += '<div class="w10-stocks muted">自选池暂无匹配标的</div>';
      }
      html += '</div>';
      html += '</article>';
    });

    html += '</div>';
    body.innerHTML = html;
    this.updateTimestamp();
  }

  _loadSectorInflow() {
    if (this._sectorInflowLoading || typeof fetch !== 'function') return;
    var self = this;
    this._sectorInflowLoading = true;
    fetch('/api/live/sectors?t=' + Date.now())
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(data) {
        if (data && (Array.isArray(data) || data.data)) {
          self._sectorInflow = data;
          self._renderBody();
        }
      })
      .catch(function() {})
      .finally(function() { self._sectorInflowLoading = false; });
  }
}

WidgetRegistry.register('W10', SectorHeatWidget);
