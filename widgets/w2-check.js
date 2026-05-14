// widgets/w2-check.js — W09 W2尾盘确认 v6.0 (信号灯系统)
'use strict';

class W2CheckWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var S = (data && data.sentiment) || {};
    var li = (data && data.live_index) || {};
    var liveQ = (data && data.live_quotes) || {};
    var trPool = (data && data.trend_pool) || [];
    var lbPool = (data && data.lianban_pool) || [];

    var now = new Date();
    var hour = now.getHours(), min = now.getMinutes();
    var inW2 = hour === 14 && min >= 0 && min <= 50;
    var w2Label = inW2 ? (min < 30 ? '14:00-14:30 核心' : '14:30-14:50 确认') : '非W2时段';

    function p(v) { return parseFloat(String(v).replace('%','').replace('+','')) || 0; }

    var qx = p(S['情绪值']);
    var ztProfit = p(S['昨日涨停收益']);
    var profitFx = S['赚钱效应'] || '—';
    var szChg = li['上证指数涨幅'] || '—';
    var upCnt = li['上涨家数'] || '—';
    var dnCnt = li['下跌家数'] || '—';
    var zone = qx < 20 ? '冰点' : qx < 40 ? '低迷' : qx < 60 ? '主升' : qx < 80 ? '强势' : '高潮';

    // ===== 信号灯 =====
    function signalDot(ok, size) {
      var s = size || 32;
      var color = ok===true ? '#22c55e' : ok===false ? '#ef4444' : '#6b7280';
      var glow = ok===true ? '0 0 12px rgba(34,197,94,0.5)' : 'none';
      return '<span style="display:inline-block;width:'+s+'px;height:'+s+'px;border-radius:50%;'+
        'background:'+color+';box-shadow:'+glow+';line-height:'+s+'px;text-align:center;'+
        'font-size:'+Math.floor(s*0.4)+'px;color:#fff;transition:all 0.5s">'+
        (ok===true?'✓':ok===false?'✕':'—')+'</span>';
    }
    function miniDot(ok) {
      var color = ok===true?'#22c55e':ok===false?'#ef4444':'#4b5563';
      return '<span style="display:inline-block;width:12px;height:12px;border-radius:50%;'+
        'background:'+color+';vertical-align:middle;margin-right:2px"></span>';
    }

    var html = '';

    // ===== 顶栏 =====
    var envOk = qx >= 20 && ztProfit >= 2;
    var topColor = inW2 ? (envOk ? 'var(--down)' : 'var(--warn)') : 'var(--text-disabled)';
    html += '<div style="display:flex;align-items:center;gap:8px;padding:6px 10px;margin-bottom:8px;'+
      'background:var(--bg-base);border-radius:6px;border-left:3px solid '+topColor+'">'+
      '<span style="font-weight:700;font-size:13px;color:'+topColor+'">'+(inW2?'W2 '+w2Label:w2Label)+'</span>'+
      '<span style="font-size:11px;color:var(--text-secondary)">'+
        '情绪'+qx+'%'+zone+' | 涨停收益'+ztProfit.toFixed(1)+'% | 赚钱'+profitFx+
        ' | 涨'+upCnt+'跌'+dnCnt+' | 上证'+szChg+
      '</span></div>';

    // ===== 趋势 W2 标的信号卡 =====
    var trW2 = trPool.filter(function(s){ var w=s['窗口']||''; return !w||w==='W2'; });
    if (trW2.length === 0) trW2 = trPool; // 向后兼容：无窗口标记的也显示

    html += '<div style="font-size:12px;font-weight:700;color:var(--text-primary);margin-bottom:4px">趋势 W2</div>';

    var trendEvals = [];
    trW2.forEach(function(s) {
      var code = s['代码'] || '';
      var q = liveQ[code] || {};
      var price = parseFloat(q['最新价']) || parseFloat(s['收盘价']||s['最新价']) || 0;
      if (!price) return;
      var ma10_60m = q['MA10_60m'];
      var dir60 = q['MA10_60m_dir'] || '—';
      var volRatio = parseFloat(q['量比']||s['量比']) || 1;
      var chg = p(q['涨幅']||s['涨幅']);
      var ma5 = parseFloat(s['MA5']) || 0;

      var anchor = ma10_60m;
      var dist = anchor ? ((price - anchor) / anchor * 100) : 999;

      // 60分钟MA10回踩
      var dirUp = dir60 === '向上';
      var near60m = dirUp && dist >= -1.5 && dist <= 1.0;
      // 缩量
      var shrink = volRatio < 0.8;
      // 未大跌
      var notCrash = chg > -5;
      // 日线MA5支撑
      var nearMA5 = ma5 > 0 && Math.abs(price - ma5) / ma5 <= 0.02;

      var hardMet = (near60m?1:0) + (shrink?1:0) + (notCrash?1:0);

      var signal, sigColor;
      if (hardMet >= 3)      { signal = '买入'; sigColor = '#22c55e'; }
      else if (hardMet >= 2) { signal = '接近'; sigColor = '#f59e0b'; }
      else                   { signal = '—'; sigColor = '#6b7280'; }

      var holding = (s['角色']||'').indexOf('持仓')>=0 || (s['操作']||'').indexOf('持有')>=0;

      trendEvals.push({
        name:s['标的'], code:code, holding:holding,
        price:price, ma10_60m:ma10_60m, dist:dist, dir60:dir60,
        volRatio:volRatio, chg:chg, ma5:ma5,
        near60m:near60m, shrink:shrink, notCrash:notCrash, nearMA5:nearMA5,
        hardMet:hardMet, signal:signal, sigColor:sigColor
      });
    });
    trendEvals.sort(function(a,b){ return b.hardMet - a.hardMet || a.dist - b.dist; });

    if (trendEvals.length > 0) {
      trendEvals.forEach(function(t) {
        var stockOk = t.hardMet >= 3;
        var stockWait = t.hardMet >= 2 && t.hardMet < 3;
        var stockFail = t.hardMet < 2;

        html += '<div style="padding:6px 4px;border-bottom:1px solid var(--border-light);display:flex;align-items:center;gap:8px">';

        // 左：信号灯 + 信号
        html += '<div style="flex:0 0 auto;text-align:center;min-width:36px">'+
          signalDot(stockOk?true:stockFail?false:null, 28)+
          '<div style="font-size:9px;font-weight:600;color:'+t.sigColor+';margin-top:1px">'+t.signal+'</div></div>';

        // 中：名称 + 条件
        html += '<div style="flex:1;min-width:0">'+
          '<div style="display:flex;align-items:baseline;gap:4px;margin-bottom:2px">'+
            (t.holding?'<span style="font-size:9px;color:var(--warn)">持仓</span>':'')+
            '<span style="font-size:13px;font-weight:700;color:var(--text-primary)">'+t.name+'</span>'+
            '<span style="font-size:9px;color:var(--text-disabled)">'+t.code+'</span></div>'+
          '<div style="display:flex;gap:8px;flex-wrap:wrap;font-size:10px">'+
            '<span>'+miniDot(t.near60m)+'60mMA10回踩 <span style="color:var(--text-secondary)">'+
              t.dir60+' 距'+(t.dist>=0?'+':'')+(Math.abs(t.dist)<100?t.dist.toFixed(1)+'%':'—')+'</span></span>'+
            '<span>'+miniDot(t.shrink)+'缩量 <span style="color:var(--text-secondary)">'+t.volRatio.toFixed(2)+'</span></span>'+
            '<span>'+miniDot(t.notCrash)+'未大跌 <span style="color:var(--text-secondary)">'+(t.chg>=0?'+':'')+t.chg.toFixed(1)+'%</span></span>'+
            (t.ma5>0?'<span>'+miniDot(t.nearMA5)+'近MA5 <span style="color:var(--text-secondary)">'+(t.price-t.ma5>=0?'+':'')+(t.price-t.ma5).toFixed(1)+'</span></span>':'')+
          '</div>';

        // 止损线
        if (t.hardMet >= 2 && !stockOk) {
          var stopPx = t.dist <= 0 ? (t.price*0.93) : (t.price*0.95);
          html += '<div style="font-size:9px;color:var(--text-disabled);margin-top:1px">止损参考 '+
            '<span style="color:var(--danger)">'+stopPx.toFixed(1)+'</span> 仓位20%</div>';
        }
        html += '</div>';

        // 右：现价 + MA10
        html += '<div style="flex:0 0 auto;text-align:right;font-size:11px;color:var(--text-secondary)">'+
          '<div style="font-size:14px;font-weight:700;color:'+(t.chg>=0?'var(--up)':'var(--down)')+'">'+
            (t.chg>=0?'+':'')+t.chg.toFixed(1)+'%</div>'+
          '<div style="font-size:10px">'+(t.price?t.price.toFixed(2):'—')+'</div>'+
          '<div style="font-size:9px;color:var(--text-disabled)">MA10 '+(t.ma10_60m?t.ma10_60m.toFixed(2):'—')+'</div>'+
          '</div>';

        html += '</div>';
      });
    } else {
      html += '<div style="text-align:center;padding:8px;color:var(--text-disabled);font-size:12px">趋势池无数据</div>';
    }

    // ===== 连板 W2 候选 =====
    var lbW2 = lbPool.filter(function(s){ var w=s['窗口']||''; return w==='W2'; });
    var lbDown = lbW2.filter(function(s){
      var chg = p((liveQ[s['代码']]||{})['涨幅']||s['涨幅']);
      return chg < 0 && chg > -7;
    });
    if (lbDown.length > 0) {
      html += '<div style="margin-top:6px;padding:6px 8px;background:var(--bg-base);border-radius:6px;border-left:3px solid var(--warn)">'+
        '<span style="font-size:12px;font-weight:700;color:var(--warn)">连板 W2</span>';
      lbDown.forEach(function(s){
        var code = s['代码']||'';
        var chg = p((liveQ[code]||{})['涨幅']||s['涨幅']);
        var vr = parseFloat((liveQ[code]||{})['量比']||s['量比'])||1;
        html += '<span style="margin-left:8px;font-size:11px">'+s['标的']+
          ' <span style="color:var(--down);font-weight:600">'+(chg>=0?'+':'')+chg.toFixed(1)+'%</span>'+
          ' <span style="font-size:9px;color:var(--text-disabled)">量'+vr.toFixed(1)+'</span></span>';
      });
      html += '</div>';
    }

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W09', W2CheckWidget);
