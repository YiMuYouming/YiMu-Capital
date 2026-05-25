// widgets/today-ops.js — W17 今日操作（只读展示，编辑入口在 W15 记流水）
'use strict';

class TodayOpsWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;

    var manual = DataStore.manualData.getAll();
    var opsJson = manual['_今日操作'];
    var ops = [];
    if (opsJson) {
      try { ops = JSON.parse(opsJson); } catch(e) { ops = []; }
    }
    // fallback: baseline decision.今日操作（W15 记流水未录入时）
    if (!ops || !ops.length) {
      ops = (data && data.decision && data.decision['今日操作']) || [];
    }

    var html = '';

    if (!ops.length) {
      html += '<div style="padding:var(--sp-lg);text-align:center;color:var(--text-disabled);font-size:var(--fs-body)">今日无操作（请在 W15 持仓组件中记流水）</div>';
      body.innerHTML = html;
      this.updateTimestamp();
      return;
    }

    html += '<table class="data-table"><thead><tr>' +
      '<th>时间</th><th>动作</th><th>标的</th><th>代码</th><th>价格</th><th>数量</th><th>窗口</th><th>原因</th>' +
      '</tr></thead><tbody>';

    ops.forEach(function(o, idx) {
      var act = o['动作'] || '—';
      var isBuy = act.indexOf('买入') >= 0 || act.indexOf('追') >= 0;
      html += '<tr>' +
        '<td style="font-size:var(--fs-body)">'+(o['时间']||'—')+'</td>' +
        '<td><span class="tag" style="font-size:var(--fs-body);background:var(--'+(isBuy?'up-bg':'down-bg')+');color:var(--'+(isBuy?'up':'down')+')">'+act+'</span></td>' +
        '<td style="font-size:var(--fs-body);font-weight:600">'+(o['标的']||'—')+'</td>' +
        '<td style="font-size:var(--fs-body);font-family:var(--font-mono);color:var(--text-secondary)">'+(o['代码']||'—')+'</td>' +
        '<td style="font-size:var(--fs-body);font-family:var(--font-mono)">'+(o['价格']||'—')+'</td>' +
        '<td style="font-size:var(--fs-body);font-family:var(--font-mono)">'+(o['数量']||'—')+'</td>' +
        '<td style="font-size:var(--fs-body)">'+(o['窗口']||'—')+'</td>' +
        '<td style="font-size:var(--fs-body);color:var(--text-secondary);max-width:120px;white-space:normal">'+(o['原因']||'')+'</td>' +
        '</tr>';
    });

    html += '</tbody></table>';

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W17', TodayOpsWidget);
