// widgets/sentiment-dash.js — W05 情绪仪表盘 (v2.2 实时涨跌家数/情绪变化/昨日基线)
'use strict';

class SentimentDashWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var S = (data && data.sentiment) || {};
    var M = (data && data.market) || {};
    var li = (data && data.live_index) || {};

    var initBase = DataStore.getInitialBase();
    var closeS = (initBase && initBase.sentiment) || {};
    var closeM = (initBase && initBase.market) || {};

    // 情绪区间
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

    // 风险值
    var risk = parseFloat(S['连板风险值']);
    var riskLabel = isNaN(risk) ? '' : risk < 0.4 ? '安全' : risk < 0.5 ? '关注' : '退潮';
    var riskCls = isNaN(risk) ? '' : risk < 0.4 ? 'info' : risk < 0.5 ? 'warn' : 'danger';

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

    // 情绪变化 = 今日情绪值 - 昨日情绪值
    var yestQx = parseFloat(closeS['情绪值']) || 0;
    var ecNum = qxNum - yestQx;
    var ecStr = (!isNaN(ecNum) && yestQx > 0) ? (ecNum > 0 ? '+' : '') + ecNum.toFixed(0) + 'pp' : '—';

    // 涨跌家数（从 live_index 实时数据）
    var liveUp = li['上涨家数'];
    var liveDn = li['下跌家数'];

    var kpis = [
      {label:'情绪值', val:(qx!=null?qx+'%':'—'), cls:zoneColor(zone), verdict:zone, verdictCls:zoneColor(zone)},
      {label:'情绪变化', val:ecStr, cls:ecNum>0?'up':ecNum<0?'down':'', extra:(yestQx>0?'较昨日'+(ecNum>0?'+':'')+ecNum.toFixed(0)+'pp':'')},
      {label:'涨/跌家数', val:'', html:'<span class="up">'+(liveUp||'—')+'</span><span style="color:var(--text-secondary)">/</span><span class="down">'+(liveDn||'—')+'</span>'},
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
        html += '<div class="kpi-verdict ' + (k.cls||'') + '" style="font-size:var(--fs-label)">' + k.extra + '</div>';
      }
      if (k.verdict) {
        html += '<div class="kpi-verdict ' + (k.verdictCls||k.cls||'') + '">' + k.verdict + '</div>';
      }
      html += '</div>';
    });
    html += '</div>';

    // Alert bar
    var alerts = [];
    if (qxNum < 20) alerts.push('<span>情绪值 ' + qxNum + '% &lt; 20%，冰点预警</span>');
    if (qxNum > 80) alerts.push('<span>情绪值 ' + qxNum + '% &gt; 80%，高潮警报，只卖不买</span>');
    if (!isNaN(ecNum) && ecNum <= -20) alerts.push('<span>情绪急降 ' + Math.abs(ecNum) + 'pp，可能触发止盈</span>');

    alerts.forEach(function(alert) {
      html += '<div style="margin-top:var(--sp-sm);padding:var(--sp-sm) var(--sp-md);background:var(--danger-bg);border-radius:var(--radius-sm);font-size:12px;color:var(--danger)">' + alert + '</div>';
    });

    // 昨日收盘基线
    html += '<div style="margin-top:var(--sp-md);padding-top:var(--sp-sm);border-top:1px solid var(--border-light)">' +
      '<div class="kpi-label" style="margin-bottom:var(--sp-xs);color:var(--text-secondary);font-size:12px">昨日收盘基线</div>' +
      '<div style="display:flex;flex-wrap:wrap;gap:2px 16px;font-size:12px">';
    var baseItems = [
      {t:'情绪', v:(closeS['情绪值']!=null?closeS['情绪值']+'%':'—') + ' ' + (closeS['情绪区间']||'')},
      {t:'赚钱效应', v:closeS['赚钱效应']||'—'},
      {t:'涨停收益', v:closeS['昨日涨停收益']||'—'},
      {t:'连板收益', v:closeS['连板收益']||'—'},
      {t:'晋级率', v:closeS['晋级率']||'—'},
      {t:'最高板', v:closeS['最高板']||'—'},
      {t:'次高板', v:closeS['次高板']||'—'},
      {t:'涨跌停', v:'<span style=\"color:var(--up)\">'+(closeM['涨停家数']||'—')+'</span>/<span style=\"color:var(--down)\">'+(closeM['跌停家数']||'—')+'</span>'},
    ];
    baseItems.forEach(function(item) {
      html += '<span><span style="color:var(--text-disabled)">' + item.t + '</span> <strong style="color:var(--text-primary)">' + item.v + '</strong></span>';
    });
    html += '</div></div>';

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W05', SentimentDashWidget);
