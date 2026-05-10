// widgets/sentiment-dash.js — W05 情绪仪表盘 (v2.1 补全字段)
'use strict';

class SentimentDashWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var S = (data && data.sentiment) || {};
    var M = (data && data.market) || {};

    // 情绪区间自动判定（兼容数据中无此字段的情况）
    var qx = S['情绪值'];
    var qxNum = parseFloat(qx) || 0;
    var zone = S['情绪区间'];
    if (!zone || zone === 'null' || zone === 'undefined') {
      zone = qxNum < 20 ? '冰点' : qxNum < 40 ? '低迷' : qxNum < 60 ? '主升' : qxNum < 80 ? '强势' : '高潮';
    }

    function zoneColor(z) {
      if (z === '冰点') return 'warn';
      if (z === '低迷') return 'warn';
      if (z === '主升') return 'info';
      if (z === '强势') return 'info';
      if (z === '高潮') return 'danger';
      return '';
    }

    // 风险值判定
    var risk = parseFloat(S['连板风险值']);
    var riskLabel = isNaN(risk) ? '' : risk < 0.4 ? '安全' : risk < 0.5 ? '关注' : '退潮';
    var riskCls = isNaN(risk) ? '' : risk < 0.4 ? 'info' : risk < 0.5 ? 'warn' : 'danger';

    // 涨跌方向色
    function dirCls(val) {
      var n = parseFloat(val);
      if (isNaN(n)) return '';
      return n > 0 ? 'up' : n < 0 ? 'down' : '';
    }
    function dirArrow(val) {
      var n = parseFloat(val);
      if (isNaN(n)) return '';
      return n > 0 ? '▲ ' : n < 0 ? '▼ ' : '';
    }

    // 情绪变化
    var ec = S['情绪变化'];
    var ecNum = parseFloat(ec);

    var kpis = [
      {label:'情绪值', val:(qx!=null?qx+'%':'—'), cls:zoneColor(zone), verdict:zone, verdictCls:zoneColor(zone)},
      {label:'情绪变化', val:(!isNaN(ecNum)?(ecNum>0?'+':'')+ecNum+'pp':'—'), cls:ecNum>0?'up':ecNum<0?'down':'', extra: ecNum>0?'较昨日↑':ecNum<0?'较昨日↓':''},
      {label:'涨/跌家数', val:'', html:'<span class="up">'+(S['上涨家数']||'—')+'</span><span style="color:var(--text-secondary)">/</span><span class="down">'+(S['下跌家数']||'—')+'</span>'},
      {label:'涨停收益', val:dirArrow(S['昨日涨停收益'])+(S['昨日涨停收益']||'—'), cls:dirCls(S['昨日涨停收益'])},
      {label:'连板收益', val:dirArrow(S['连板收益'])+(S['连板收益']||'—'), cls:dirCls(S['连板收益'])},
      {label:'炸板收益', val:(S['昨日炸板收益']||'—'), cls:dirCls(S['昨日炸板收益'])},
      {label:'风险值', val:(!isNaN(risk)?risk:'—'), cls:riskCls, verdict:riskLabel, verdictCls:riskCls},
      {label:'晋级率', val:S['晋级率']||'—', cls:'info'},
      {label:'封板率', val:M['封板率']||'—'},
      {label:'涨/跌停', val:'', html:'<span class="up">'+(M['涨停家数']||'—')+'</span><span style="color:var(--text-secondary)">/</span><span class="down">'+(M['跌停家数']||'—')+'</span>'},
      {label:'赚钱效应', val:S['赚钱效应']||'—', cls:S['赚钱效应']==='好'?'info':S['赚钱效应']==='差'?'danger':'warn'},
      {label:'最高板', val:S['最高板']||'—'},
      {label:'次高板', val:S['次高板']||'—'},
      {label:'连板梯队', val:S['连板梯队']||'—'},
    ];

    var html = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(100px,1fr));gap:var(--sp-sm)">';
    kpis.forEach(function(k) {
      html += '<div class="kpi-card">' +
        '<div class="kpi-label">' + k.label + '</div>';
      if (k.html) {
        html += '<div class="kpi-value" style="font-size:14px">' + k.html + '</div>';
      } else {
        html += '<div class="kpi-value ' + (k.cls||'') + '" style="font-size:15px">' + k.val + '</div>';
      }
      if (k.extra) {
        html += '<div class="kpi-verdict ' + (k.cls||'') + '" style="font-size:var(--fs-micro)">' + k.extra + '</div>';
      }
      if (k.verdict) {
        html += '<div class="kpi-verdict ' + (k.verdictCls||k.cls||'') + '">' + k.verdict + '</div>';
      }
      html += '</div>';
    });
    html += '</div>';

    // Alert bar
    var alerts = [];
    if (qxNum < 20) alerts.push('<span style="font-weight:600">🔴 冰点预警</span>：情绪值 ' + qxNum + '% < 20%，极度恐慌');
    if (qxNum > 80) alerts.push('<span style="font-weight:600">🔴 高潮警报</span>：情绪值 ' + qxNum + '% > 80%，只卖不买');
    if (!isNaN(ecNum) && ecNum <= -20) alerts.push('<span style="font-weight:600">⚠️ 情绪急降</span>：' + Math.abs(ecNum) + 'pp，可能触发止盈信号');

    alerts.forEach(function(alert) {
      html += '<div style="margin-top:var(--sp-sm);padding:var(--sp-sm) var(--sp-md);background:var(--danger-bg);border-radius:var(--radius-sm);font-size:var(--fs-body);color:var(--danger)">' + alert + '</div>';
    });

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W05', SentimentDashWidget);
