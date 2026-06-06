// widgets/lianban-pool.js — W12 连板自选池
'use strict';

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

    var cols = ['标的','板块','涨幅','最新价','量比','换手','MA10(60m)','MA5','角色','操作','备注'];

    // 构建行数据
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

    // 排序
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
          if (String(val).indexOf('追') >= 0) cls = 'up';
          else if (String(val).indexOf('只盯') >= 0) cls = 'warn';
        }
        html += '<td class="' + cls + '">' + val + '</td>';
      });
      // 代码小字附在标的后
      html = html.replace('<td class="">' + r.cells['标的'] + '</td>',
        '<td>' + r.cells['标的'] + ' <span style="font-size:var(--fs-label);color:var(--text-disabled)">' + (r.code||'') + '</span></td>');
      html += '</tr>';
    });

    html += '</tbody></table>';
    body.innerHTML = html;

    // 排序：事件代理在 body，仅首次 render 绑定
    if (!this._sortBound) {
      this._sortBound = true;
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
