// widgets/trend-pool.js — W13 趋势自选池
'use strict';

class TrendPoolWidget extends YiMuWidget {
  constructor(config) {
    super(config);
    this._sortDir = null;
  }

  render(data) {
    var body = this.getBody();
    if (!body) return;
    var pool = (data && data.trend_pool) || [];

    if (!pool.length) {
      body.innerHTML = '<div style="padding:var(--sp-lg);text-align:center;color:var(--text-disabled)">趋势池数据未录入</div>';
      return;
    }

    var quotes = (data && data.live_quotes) || {};
    var self = this;

    var cols = ['标的','板块','涨幅','最新价','量比','换手','MA10(60m)','MA5','角色','操作','备注'];

    var rows = pool.map(function(s) {
      var code = s['代码'] || '';
      var live = quotes[code] || {};
      var chg = live['涨幅'] || s['涨幅'] || '—';
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
          '角色':   s['角色'] || '—',
          '操作':   s['操作'] || '—',
          '备注':   s['备注'] || '—'
        },
        _chgNum: parseFloat(String(chg).replace('%','')) || 0
      };
    });

    if (self._sortDir) {
      rows.sort(function(a, b) {
        return self._sortDir === 'asc' ? a._chgNum - b._chgNum : b._chgNum - a._chgNum;
      });
    }

    var sortArrow = self._sortDir === 'asc' ? ' ▲' : (self._sortDir === 'desc' ? ' ▼' : '');

    var html = '<table class="data-table" style="font-size:13px"><thead><tr>';
    cols.forEach(function(c) {
      if (c === '涨幅') {
        html += '<th class="sortable" data-sort="chg" style="cursor:pointer;user-select:none">涨幅' + sortArrow + '</th>';
      } else {
        html += '<th>' + c + '</th>';
      }
    });
    html += '</tr></thead><tbody>';

    rows.forEach(function(r) {
      html += '<tr>';
      cols.forEach(function(key) {
        var val = r.cells[key] != null ? r.cells[key] : '—';
        var cls = '';
        if (key === '涨幅') {
          var str = String(val);
          cls = str.charAt(0) === '+' ? 'up' : str.charAt(0) === '-' ? 'down' : '';
        }
        if (key === '操作') {
          if (String(val).indexOf('买入') >= 0) cls = 'down';
        }
        html += '<td class="' + cls + '">' + val + '</td>';
      });
      html = html.replace('<td class="">' + r.cells['标的'] + '</td>',
        '<td>' + r.cells['标的'] + ' <span style="font-size:var(--fs-label);color:var(--text-disabled)">' + (r.code||'') + '</span></td>');
      html += '</tr>';
    });

    html += '</tbody></table>';
    body.innerHTML = html;

    var th = body.querySelector('.sortable');
    if (th) {
      th.addEventListener('click', function() {
        if (!self._sortDir) self._sortDir = 'desc';
        else if (self._sortDir === 'desc') self._sortDir = 'asc';
        else self._sortDir = null;
        self._renderBody();
      });
    }

    this.updateTimestamp();
  }
}

WidgetRegistry.register('W13', TrendPoolWidget);
