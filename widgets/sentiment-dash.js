// widgets/sentiment-dash.js — W05 情绪仪表盘 (v2.0: 冰点=橙, 高潮=红)
'use strict';

class SentimentDashWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var S = (data && data.sentiment) || {};
    var M = (data && data.market) || {};

    // v2.0: 冰点→warn(橙), 高潮→danger(红)
    function zoneColor(zone) {
      if (zone === '冰点') return 'warn';
      if (zone === '低迷') return 'warn';
      if (zone === '主升') return 'info';
      if (zone === '强势') return 'info';
      if (zone === '高潮') return 'danger';
      return '';
    }

    var kpis = [
      {label:'情绪值',   val:(S['情绪值']!=null?S['情绪值']+'%':'—'), cls:zoneColor(S['情绪区间']), verdict:S['情绪区间']||''},
      {label:'上涨家数', val:S['上涨家数']||'—'},
      {label:'下跌家数', val:S['下跌家数']||'—'},
      {label:'涨停收益', val:S['昨日涨停收益']||'—'},
      {label:'连板收益', val:S['连板收益']||'—'},
      {label:'炸板收益', val:S['昨日炸板收益']||'—'},
      {label:'风险值',   val:(S['连板风险值']!=null?S['连板风险值']:'—')},
      {label:'晋级率',   val:S['晋级率']||'—'},
      {label:'封板率',   val:M['封板率']||'—'},
      {label:'赚钱效应', val:S['赚钱效应']||'—', verdict:(S['赚钱效应']==='好'?'info':S['赚钱效应']==='差'?'danger':'warn')},
      {label:'最高板',   val:S['最高板']||'—'},
      {label:'次高板',   val:S['次高板']||'—'},
      {label:'连板梯队', val:S['连板梯队']||'—'},
    ];

    var html = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(90px,1fr));gap:var(--sp-sm)">';
    kpis.forEach(function(k) {
      html += '<div class="kpi-card">' +
        '<div class="kpi-label">' + k.label + '</div>' +
        '<div class="kpi-value ' + (k.cls||'') + '" style="font-size:16px">' + k.val + '</div>' +
        (k.verdict ? '<div class="kpi-verdict ' + (k.cls||'') + '">' + k.verdict + '</div>' : '') +
        '</div>';
    });
    html += '</div>';

    // Alert bar
    var alerts = [];
    var qx = S['情绪值'];
    if (qx != null) {
      if (qx < 20) alerts.push('冰点预警('+qx+'%)');
      if (qx > 80) alerts.push('高潮警报('+qx+'%)');
    }
    if (S['情绪变化'] != null && S['情绪变化'] <= -20) alerts.push('情绪急降('+S['情绪变化']+'pp)');

    if (alerts.length) {
      html += '<div style="margin-top:var(--sp-sm);padding:var(--sp-sm);background:var(--danger-bg);border-radius:var(--radius-sm);font-size:var(--fs-body);color:var(--danger)">' +
        alerts.join(' | ') + '</div>';
    }

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W05', SentimentDashWidget);
