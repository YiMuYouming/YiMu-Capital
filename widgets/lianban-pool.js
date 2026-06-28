// widgets/lianban-pool.js — W12 连板自选池
'use strict';

function _lbEsc(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function _lbCleanText(s, fallback) {
  if (s == null || s === '') return fallback || '';
  var text = String(s);
  if (/[<>]/.test(text) || /alert\s*\(/i.test(text)) return fallback || '—';
  return text;
}

function _lbChgNum(v) {
  return parseFloat(String(v || '').replace('%','').replace('+','')) || 0;
}

function _lbContract(s) {
  var todayRole = s['今日定位'];
  var todayCheck = s['今日检查'];
  var triggerInvalid = s['触发/失效'] || s['触发失效'];
  var legacyRole = s['角色'];
  var legacyAction = s['操作'];
  var hasLegacy = !!(legacyRole || legacyAction);
  var hasTodayContract = !!(todayRole || todayCheck || triggerInvalid);
  if (!hasTodayContract && hasLegacy) {
    return {
      role: '观察标',
      check: '旧字段兼容：需补今日检查',
      trigger: '缺少新版触发/失效；只观察，不授权买卖',
      note: (s['备注'] || '') + ' 旧字段：角色=' + (legacyRole || '—') + '；操作=' + (legacyAction || '—')
    };
  }
  return {
    role: todayRole || legacyRole || '—',
    check: todayCheck || '—',
    trigger: triggerInvalid || '缺少触发/失效；只观察，不授权买卖',
    note: s['备注'] || '—'
  };
}

class LianbanPoolWidget extends YiMuWidget {
  constructor(config) {
    super(config);
    this._sortDir = null;
    this._sortBound = false;
  }

  unmount() {
    this._sortBound = false;
    super.unmount();
  }

  render(data) {
    var body = this.getBody();
    if (!body) return;
    var pool = (data && data.lianban_pool) || [];

    if (!pool.length) {
      body.innerHTML = '<div class="ui-empty"><div class="ui-empty-title">连板池数据未录入</div><div class="ui-empty-detail">等待复盘基线或实时自选池同步。</div></div>';
      return;
    }

    var quotes = (data && data.live_quotes) || {};
    var self = this;

    var cols = ['标的','板块','涨幅','最新价','量比','换手','MA10(60m)','MA5','今日定位','窗口','今日检查','触发/失效','备注'];
    var w1Count = pool.filter(function(s){ return (s['窗口'] || '') === 'W1'; }).length;
    var w2Count = pool.filter(function(s){ return (s['窗口'] || '') === 'W2'; }).length;
    var watchCount = pool.filter(function(s){
      var c = _lbContract(s);
      var role = String(c.role || '');
      var check = String(c.check || '');
      return check.indexOf('只盯') >= 0 || role.indexOf('观察') >= 0 || role.indexOf('温度') >= 0;
    }).length;

    // 构建行数据
    var rows = pool.map(function(s) {
      var code = _lbCleanText(s['代码'], '');
      var live = quotes[code] || {};
      var chg = live['涨幅'] || s['涨幅'] || '—';
      var contract = _lbContract(s);
      return {
        code: code,
        cells: {
          '标的':   s['标的'] || '—',
          '板块':   s['板块'] || '—',
          '涨幅':   chg,
          '最新价':  live['最新价'] || s['收盘价'] || s['最新价'] || '—',
          '量比':   live['量比'] || s['量比'] || '—',
          '换手':   live['换手'] || s['换手'] || '—',
          'MA10(60m)': (live['MA10_60m']||s['MA10_60m']) || '—',
          'MA5':   s['MA5'] || '—',
          '今日定位': contract.role,
          '窗口':   s['窗口'] || '—',
          '今日检查': contract.check,
          '触发/失效': contract.trigger,
          '备注':   contract.note
        },
        _chgNum: _lbChgNum(chg)
      };
    });

    // 排序
    if (self._sortDir) {
      rows.sort(function(a, b) {
        return self._sortDir === 'asc' ? a._chgNum - b._chgNum : b._chgNum - a._chgNum;
      });
    }

    var sortArrow = self._sortDir === 'asc' ? ' ▲' : (self._sortDir === 'desc' ? ' ▼' : '');

    var html = '<div class="candidate-brief candidate-brief-lianban">' +
      '<div class="candidate-brief-main"><span class="evidence-inline-ref">W12</span><span class="candidate-brief-title">连板池验收</span><em>按今日定位、触发/失效和实时涨幅核对。</em></div>' +
      '<div class="candidate-brief-grid">' +
        '<div><span>总数</span><b>' + rows.length + '</b></div>' +
        '<div><span>W1</span><b>' + w1Count + '</b></div>' +
        '<div><span>W2</span><b>' + w2Count + '</b></div>' +
        '<div><span>观察</span><b>' + watchCount + '</b></div>' +
      '</div>' +
    '</div>';

    html += '<div class="candidate-table-wrap"><table class="data-table candidate-table"><thead><tr>';
    cols.forEach(function(c) {
      if (c === '涨幅') {
        html += '<th class="sortable" data-sort="chg" style="cursor:pointer;user-select:none">涨幅' + sortArrow + '</th>';
      } else {
        html += '<th>' + _lbEsc(c) + '</th>';
      }
    });
    html += '</tr></thead><tbody>';

    rows.forEach(function(r) {
      html += '<tr>';
      cols.forEach(function(key) {
        var val = r.cells[key] != null ? r.cells[key] : '—';
        var displayVal = _lbCleanText(val, '—');
        var cls = '';
        if (key === '涨幅') {
          var str = String(val);
          cls = str.charAt(0) === '+' ? 'up' : str.charAt(0) === '-' ? 'down' : '';
        }
        if (key === '今日检查') {
          if (String(val).indexOf('追') >= 0) cls = 'up';
          else if (String(val).indexOf('只盯') >= 0) cls = 'warn';
        }
        if (key === '标的') {
          html += '<td>' + _lbEsc(displayVal) + ' <span class="candidate-code">' + _lbEsc(r.code || '') + '</span></td>';
        } else {
          html += '<td class="' + cls + '">' + _lbEsc(displayVal) + '</td>';
        }
      });
      html += '</tr>';
    });

    html += '</tbody></table></div>';
    body.innerHTML = html;

    // 排序：事件代理在 body，仅首次 render 绑定
    if (!this._sortBound) {
      this._sortBound = true;
      this._on = this._on || function(el, evt, fn){ if (el && el.addEventListener) el.addEventListener(evt, fn); };
      this._on(body, 'click', function(e) {
        if (e.target && e.target.classList.contains('sortable')) {
          if (!self._sortDir) self._sortDir = 'desc';
          else if (self._sortDir === 'desc') self._sortDir = 'asc';
          else self._sortDir = null;
          self._renderBody();
        }
      });
    }

    this.updateTimestamp();
  }
}

WidgetRegistry.register('W12', LianbanPoolWidget);
