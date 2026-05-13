// widgets/w2-check.js — W09 W2实时评估 v5.0 (60分钟MA10核心锚点 + 强势/普通分类)
'use strict';

class W2CheckWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var nodes = (data && data.sentiment_nodes) || {};
    var S = (data && data.sentiment) || {};
    var li = (data && data.live_index) || {};
    var liveQ = (data && data.live_quotes) || {};
    var trPool = (data && data.trend_pool) || [];
    var lbPool = (data && data.lianban_pool) || [];

    var NODE_ORDER = ['竞价','早盘','午盘','尾盘','收盘'];
    var _placeholder = function(v) {
      if (!v) return true;
      v = String(v);
      if (v === '—' || v === '%' || v === '亿' || v === '操作' || v === '板') return true;
      if (v.indexOf('点位') >= 0 || v.indexOf('(%)') >= 0) return true;
      if (/^(好|一般|差)(\/(好|一般|差))+$/.test(v)) return true;
      if (/^(完整|断层)(\/(完整|断层))+$/.test(v)) return true;
      if (/^(竞价|早盘|午盘|尾盘|收盘)$/.test(v)) return true;
      return false;
    };
    // 逐指标从最新节点往前找第一个有效值
    function latestVal(key, fallback) {
      for (var i = NODE_ORDER.length-1; i >= 0; i--) {
        var v = (nodes[NODE_ORDER[i]] || {})[key];
        if (v != null && !_placeholder(v)) return {val: v, node: NODE_ORDER[i]};
      }
      return {val: fallback, node: '基线'};
    }

    var now = new Date();
    var hour = now.getHours(), min = now.getMinutes();
    var inW2 = (hour === 14 && min >= 0 && min <= 50);
    var w2Label = inW2 ? (min < 30 ? '14:00-14:30 核心' : '14:30-14:50 确认') : '非W2';

    function p(v) { return parseFloat(String(v).replace('%','').replace('+','')) || 0; }

    // === 市场条件（逐指标独立取最新值）===
    var qxR = latestVal('情绪', S['情绪值']);
    var ztR = latestVal('涨停收益', S['昨日涨停收益']);
    var pfR = latestVal('赚钱效应', S['赚钱效应']);
    var qx = p(qxR.val); var ztProfit = p(ztR.val); var profitSrc = pfR.val;
    var zone = qx < 20 ? '冰点' : qx < 40 ? '低迷' : qx < 60 ? '主升' : qx < 80 ? '强势' : '高潮';
    var srcTag = '📋' + (qxR.node === ztR.node ? qxR.node : qxR.node + '/' + ztR.node);

    var mktItems = [
      {label:'情绪', val:qx+'% '+zone, ok:qx>=20, rule:'≥20%', src:srcTag},
      {label:'涨停收益', val:ztProfit.toFixed(1)+'%', ok:ztProfit>=2, rule:'≥2%', src:srcTag},
      {label:'赚钱效应', val:profitSrc||'—', ok:profitSrc==='好'||profitSrc==='较好', rule:'好/较好', src:srcTag},
      {label:'涨跌', val:'涨'+(li['上涨家数']||'—')+' 跌'+(li['下跌家数']||'—'), ok:true, rule:'', src:'⚡'},
      {label:'上证', val:li['上证指数涨幅']||'—', ok:true, rule:'', src:'⚡'},
    ];
    var mktOk = mktItems.filter(function(x){return !x.ok;}).length === 0;

    // === 个股实时评估 ===
    var trendEvals = [];
    trPool.forEach(function(s) {
      var code = s['代码'] || '';
      var q = liveQ[code] || {};
      var price = parseFloat(q['最新价']) || 0;
      if (!price) return;

      var ma5_d = q['MA5_d'];           // 日线MA5（方向/强弱参考）
      var ma10_d = q['MA10_d'];         // 日线MA10
      var ma20_d = q['MA20_d'];         // 日线MA20
      var ma10_60m = q['MA10_60m'];     // 60分钟MA10（核心回踩锚点）
      var dir60 = q['MA10_60m_dir'] || '—';
      var volRatio = parseFloat(q['量比']) || 1;
      var chg = p(q['涨幅']);

      var anchor = ma10_60m;
      var dist = anchor ? ((price - anchor) / anchor * 100) : 999;

      // 日线多头排列（方向/强弱）
      var dailyAlign = ma5_d && ma10_d && ma20_d && ma5_d > ma10_d && ma10_d > ma20_d;

      var conditions = [];

      // 1. 60分钟MA10回踩（核心）：方向向上 + 距MA10在-1%~+0.5%
      var dirUp = dir60 === '向上';
      var near60m = dirUp && dist >= -1 && dist <= 0.5;
      conditions.push({ok: near60m, label: '60mMA10↑回踩',
        detail: dir60+' 距'+(dist>=0?'+':'')+dist.toFixed(1)+'%'});

      // 2. 日线多头（方向/强弱参考，不硬卡但条件不足时示警）
      conditions.push({ok: dailyAlign, label: '日线多头',
        detail: dailyAlign ? 'MA5>MA10>MA20' : '排列不佳'});

      // 3. 缩量：量比<0.8
      var shrink = volRatio < 0.8;
      conditions.push({ok: shrink, label: '缩量',
        detail: '量比'+volRatio.toFixed(2)+'<0.8'});

      // 4. 未大跌：涨幅>-5%
      var notCrash = chg > -5;
      conditions.push({ok: notCrash, label: '未大跌',
        detail: (chg>=0?'+':'')+chg.toFixed(1)+'%'});

      // 5. 龙头存活
      var sec = s['板块'] || '';
      var leaderAlive = false;
      trPool.forEach(function(ts) {
        if (ts === s) return;
        if ((ts['板块']||'').indexOf(sec.split('/')[0])>=0 || sec.indexOf((ts['板块']||'').split('/')[0])>=0) {
          if (p((liveQ[ts['代码']]||{})['涨幅']) > 0) leaderAlive = true;
        }
      });
      conditions.push({ok: leaderAlive, label: '龙头活', detail: leaderAlive?'✓':'—'});

      var met = conditions.filter(function(c){return c.ok;}).length;
      var total = conditions.length;

      // 核心条件：60分钟MA10回踩 + 缩量 + 未大跌 = 3个硬条件
      var hardMet = (near60m?1:0) + (shrink?1:0) + (notCrash?1:0);

      var signal, signalCls;
      if (hardMet >= 3 && leaderAlive) { signal = '🟢 买入'; signalCls = 'var(--down)'; }
      else if (hardMet >= 2)           { signal = '🟡 接近'; signalCls = 'var(--warn)'; }
      else                             { signal = '—'; signalCls = 'var(--text-disabled)'; }

      trendEvals.push({
        name:s['标的'], code:code,
        price:price, anchor:ma10_60m,
        dist:dist, dir60:dir60, volRatio:volRatio, chg:chg,
        ma5_d:ma5_d, conditions:conditions, met:met, total:total,
        hardMet:hardMet, signal:signal, signalCls:signalCls
      });
    });

    trendEvals.sort(function(a,b){ return b.met - a.met || a.dist - b.dist; });

    // === 渲染 ===
    var html = '';

    var topColor = inW2 ? (mktOk ? 'var(--down)' : 'var(--warn)') : 'var(--text-disabled)';
    html += '<div style="display:flex;align-items:center;gap:var(--sp-sm);padding:var(--sp-xs) var(--sp-md);margin-bottom:var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-md);border-left:3px solid '+topColor+'">'+
      '<span style="font-weight:700;color:'+topColor+'">'+(inW2?'✅ W2 '+w2Label:'⏳ '+w2Label)+'</span>'+
      '<span style="margin-left:auto;font-size:var(--fs-body);color:var(--text-secondary)">'+srcTag+' + ⚡实时</span></div>';

    // 市场条件
    html += '<div style="display:flex;flex-wrap:wrap;gap:4px 12px;padding:var(--sp-xs) var(--sp-sm);margin-bottom:var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-sm);font-size:var(--fs-body)">'+
      '<span style="color:var(--text-disabled);font-weight:600;margin-right:4px">市场</span>';
    mktItems.forEach(function(item) {
      var valHtml;
      if (item.label === '涨跌') {
        var parts = String(item.val).split(' ');
        valHtml = parts.map(function(p) {
          if (p.indexOf('涨')===0) return '<span class="up" style="font-weight:600">'+p+'</span>';
          if (p.indexOf('跌')===0) return '<span class="down" style="font-weight:600">'+p+'</span>';
          return p;
        }).join(' ');
      } else {
        valHtml = '<b>'+item.val+'</b>';
      }
      html += '<span style="white-space:nowrap">'+
        '<span style="color:'+(item.ok?'var(--up)':'var(--danger)')+'">'+(item.ok?'✅':'❌')+'</span> '+
        item.label+' '+valHtml+
        (item.rule ? '<span style="font-size:8px;color:var(--text-disabled)"> ('+item.rule+')</span>' : '')+
        '<span style="font-size:8px;color:var(--text-disabled);margin-left:1px">'+item.src+'</span></span>';
    });
    html += '</div>';

    // 趋势 W2 表
    html += '<div style="font-size:var(--fs-label);font-weight:600;margin-bottom:2px">趋势 W2 弱回踩</div>';
    html += '<div style="font-size:10px;color:var(--text-secondary);margin-bottom:var(--sp-sm)">'+
      '核心:60分钟MA10回踩(方向↑,距MA10≤1%) + 缩量(量比<0.8) + 未大跌(>-5%) | 日线多头=方向参考</div>';

    html += '<table style="width:100%;border-collapse:collapse;font-size:var(--fs-body)">';
    html += '<thead><tr style="border-bottom:1px solid var(--border)">'+
      '<th style="text-align:left;padding:2px 4px;color:var(--text-disabled);font-weight:400">标的</th>'+
      '<th style="text-align:right;padding:2px 4px;color:var(--text-disabled);font-weight:400">现价</th>'+
      '<th style="text-align:right;padding:2px 4px;color:var(--text-disabled);font-weight:400">MA10(60m)</th>'+
      '<th style="text-align:right;padding:2px 4px;color:var(--text-disabled);font-weight:400">距</th>'+
      '<th style="text-align:center;padding:2px 2px;color:var(--text-disabled);font-weight:400;font-size:10px">方向</th>'+
      '<th style="text-align:right;padding:2px 4px;color:var(--text-disabled);font-weight:400">量比</th>'+
      '<th style="text-align:right;padding:2px 4px;color:var(--text-disabled);font-weight:400">涨跌</th>'+
      '<th style="text-align:center;padding:2px 4px;color:var(--text-disabled);font-weight:400">条件</th>'+
      '<th style="text-align:center;padding:2px 4px;color:var(--text-disabled);font-weight:400">信号</th>'+
      '</tr></thead><tbody>';

    trendEvals.forEach(function(t) {
      var distStr = (Math.abs(t.dist) < 100) ? (t.dist>=0?'+':'')+t.dist.toFixed(1)+'%' : '—';
      var distCls = t.dist >= -1 && t.dist <= 0.5 ? 'down' : t.dist < -3 ? 'up' : '';
      var dirCls = t.dir60==='向上'?'up':t.dir60==='向下'?'down':'';
      var chgCls = t.chg>0?'up':'down';

      html += '<tr style="border-bottom:1px solid var(--border-light)">'+
        '<td style="padding:2px 4px"><b>'+t.name+'</b><span style="font-size:9px;color:var(--text-disabled)"> '+t.code+'</span></td>'+
        '<td style="text-align:right;padding:2px 4px;font-family:var(--font-mono)">'+t.price.toFixed(2)+'</td>'+
        '<td style="text-align:right;padding:2px 4px;font-family:var(--font-mono);font-size:10px;color:var(--text-disabled)">'+(t.anchor?t.anchor.toFixed(2):'—')+'</td>'+
        '<td style="text-align:right;padding:2px 4px;font-family:var(--font-mono);color:var(--'+distCls+');font-weight:600">'+distStr+'</td>'+
        '<td style="text-align:center;padding:2px 2px;font-family:var(--font-mono);font-size:10px;color:var(--'+dirCls+')">'+t.dir60+'</td>'+
        '<td style="text-align:right;padding:2px 4px;font-family:var(--font-mono);color:'+(t.volRatio<0.8?'var(--down)':'')+'">'+t.volRatio.toFixed(2)+'</td>'+
        '<td style="text-align:right;padding:2px 4px;font-family:var(--font-mono);color:var(--'+chgCls+')">'+(t.chg>=0?'+':'')+t.chg.toFixed(1)+'%</td>'+
        '<td style="text-align:center;padding:2px 2px;font-size:12px">'+
          t.conditions.map(function(c){return '<span title="'+c.label+':'+c.detail+'">'+(c.ok?'🟢':'🔴')+'</span>';}).join('')+
          '<span style="font-size:9px;color:var(--text-secondary)"> '+t.hardMet+'/3</span></td>'+
        '<td style="text-align:center;padding:2px 4px;font-weight:700;color:'+t.signalCls+';white-space:nowrap">'+t.signal+'</td></tr>';

      if (t.hardMet >= 2) {
        var stopPrice = t.dist <= 0 ? (t.price*0.93).toFixed(1)+'(-7%)' : (t.price*0.95).toFixed(1)+'(-5%)';
        html += '<tr><td colspan="10" style="padding:1px 4px 3px 16px;font-size:10px">'+
          t.conditions.map(function(c){return '<span style="margin-right:8px">'+(c.ok?'🟢':'🔴')+' '+c.label+':'+c.detail+'</span>';}).join('')+
          '<span style="color:var(--down);font-weight:700"> → 止损'+stopPrice+' 仓位20%</span></td></tr>';
      }
    });

    html += '</tbody></table>';

    if (trendEvals.length === 0) {
      html += '<div style="text-align:center;padding:var(--sp-md);color:var(--text-disabled)">趋势池无数据</div>';
    }

    // 连板 W2 简化
    var lbCandidates = lbPool.filter(function(s) {
      var chg = p((liveQ[s['代码']]||{})['涨幅']);
      return chg < 0 && chg > -5;
    });
    if (lbCandidates.length > 0) {
      html += '<div style="margin-top:var(--sp-sm);padding:var(--sp-xs) var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-sm);font-size:var(--fs-body)">'+
        '<span style="color:var(--warn);font-weight:600">连板 W2 候选: </span>';
      lbCandidates.forEach(function(s) {
        var code = s['代码']||'';
        var chg = p((liveQ[code]||{})['涨幅']);
        var vr = parseFloat((liveQ[code]||{})['量比'])||1;
        html += '<span style="margin-left:6px">'+s['标的']+' <span style="color:var(--down)">'+chg.toFixed(1)+'%</span> v'+vr.toFixed(1)+'</span>';
      });
      html += '</div>';
    }

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W09', W2CheckWidget);
