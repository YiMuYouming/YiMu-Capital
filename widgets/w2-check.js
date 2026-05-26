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
      var color = ok===true ? 'var(--down)' : ok===false ? 'var(--danger)' : 'var(--text-disabled)';
      var glow = ok===true ? '0 0 12px rgba(5,150,105,0.4)' : 'none';
      return '<span style="display:inline-block;width:'+s+'px;height:'+s+'px;border-radius:50%;'+
        'background:'+color+';box-shadow:'+glow+';line-height:'+s+'px;text-align:center;'+
        'font-size:'+Math.floor(s*0.48)+'px;font-weight:700;color:#fff;transition:all 0.5s">'+
        (ok===true?'✓':ok===false?'✕':'—')+'</span>';
    }
    function miniDot(ok) {
      var color = ok===true?'var(--down)':ok===false?'var(--danger)':'var(--text-disabled)';
      return '<span style="display:inline-block;width:12px;height:12px;border-radius:50%;'+
        'background:'+color+';vertical-align:middle;margin-right:2px"></span>';
    }

    // ===== rule_state 实时规则引擎（Gate 1A 唯一权威结论）=====
    var RS = (data && data.rule_state) || null;
    var rsW2 = (RS && RS.windows && RS.windows.w2) || {};
    var rsBlocks = (RS && RS.blocks) || [];
    var rsMissing = !RS;

    if (rsMissing) {
      body.innerHTML = '<div style="text-align:center;padding:20px;color:var(--danger);font-weight:600">规则状态不可用</div>'
        +'<div style="font-size:12px;color:var(--text-disabled);text-align:center">后端 rule_state 未生成</div>';
      this.updateTimestamp();
      return;
    }

    var w2BuyAllowed = rsW2.buy_allowed;
    var html = '';

    // ===== 顶栏：rule_state 结论 + 本地三条件详情 =====
    var c1 = qx >= 20;
    var c2 = ztProfit >= 2;
    var c3 = profitFx === '好' || profitFx === '较好' || profitFx === '很好' || profitFx === '非常好';
    function dot(ok) {
      return '<span style="display:inline-block;width:14px;height:14px;border-radius:50%;'+
        'background:'+(ok===true?'var(--down)':(ok===false?'var(--danger)':'var(--text-disabled)'))+';'+
        'box-shadow:'+(ok===true?'0 0 6px rgba(5,150,105,0.4)':'none')+';'+
        'vertical-align:middle;margin:0 2px"></span>';
    }
    var overallColor = w2BuyAllowed ? 'var(--down)' : 'var(--danger)';
    var overallLabel = w2BuyAllowed ? '✅ W2 允许买入' : '⚠️ W2 关闭' + (rsW2.in_session ? '' : '（非W2时段）');
    html += '<div style="padding:6px 10px;background:var(--bg-base);border-radius:6px;'+
      'border-left:3px solid '+overallColor+';margin-bottom:6px">'+
      '<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">'+
        '<span style="font-weight:700;font-size:13px;color:'+overallColor+'">'+overallLabel+'</span>'+
        '<span style="flex:1"></span>'+
        '<span style="font-size:11px;color:var(--text-secondary)">'+(inW2?w2Label:'非W2时段')+'</span>'+
      '</div>'+
      '<div style="display:flex;gap:10px;font-size:11px">'+
        '<span>'+dot(c1)+'情绪≥20 <span style="color:'+(c1?'var(--down)':'var(--danger)')+'">'+qx+'%</span></span>'+
        '<span>'+dot(c2)+'涨停收益≥2 <span style="color:'+(c2?'var(--down)':'var(--danger)')+'">'+ztProfit.toFixed(1)+'%</span></span>'+
        '<span>'+dot(c3)+'赚钱效应好 <span style="color:'+(c3?'var(--down)':'var(--danger)')+'">'+profitFx+'</span></span>'+
      '</div>'+
      '<div style="font-size:10px;color:var(--text-disabled);margin-top:3px">'+
        '涨'+upCnt+'跌'+dnCnt+' | 上证'+szChg+' | 情绪区：'+qx.toFixed(0)+'% '+zone+
      '</div>';

    // W2 阻断展示（rule_state blocks 中 scope=w2 或 scope=all 的项）
    var w2ScopeCodes = rsBlocks.filter(function(b){ return b.scope === 'w2' || b.scope === 'all'; });
    if (w2ScopeCodes.length) {
      html += '<div style="margin-top:4px;padding:3px 6px;background:rgba(220,38,38,0.08);border-radius:4px;font-size:10px">';
      w2ScopeCodes.forEach(function(b){ html += '<div style="color:var(--danger)">✕ '+b.code+': '+b.message+'</div>'; });
      html += '</div>';
    }
    html += '</div>';

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
      if (!w2BuyAllowed) {
        // rule_state 判定 W2 不可交易，所有候选统一降级
        signal = '关闭'; sigColor = 'var(--text-disabled)';
      } else if (hardMet >= 3)      { signal = '买入'; sigColor = 'var(--down)'; }
      else if (hardMet >= 2) { signal = '接近'; sigColor = 'var(--warn)'; }
      else                   { signal = '—'; sigColor = 'var(--text-disabled)'; }

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
        var stockOk = t.hardMet >= 3 && w2BuyAllowed;
        var stockWait = t.hardMet >= 2 && t.hardMet < 3 && w2BuyAllowed;
        var stockFail = !w2BuyAllowed || t.hardMet < 2;

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
        if (t.hardMet >= 2 && !stockOk && w2BuyAllowed) {
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
          (!window._healthCritical && stockOk?'<button onclick="event.stopPropagation();_prefillW15(\''+t.name.replace(/'/g,"\\'")+'\',\''+t.code+'\',\'W2\',\'趋势W2买入:MA回踩+缩量+未大跌\')" style="margin-top:2px;background:var(--down);color:#fff;border:none;padding:1px 6px;border-radius:3px;cursor:pointer;font-size:9px;white-space:nowrap">录入</button>':'')+
          '</div>';

        html += '</div>';
      });
    } else {
      html += '<div style="text-align:center;padding:8px;color:var(--text-disabled);font-size:12px">趋势池无数据</div>';
    }

    // ===== 连板 W2 低吸候选（信号灯）=====
    var lbW2 = lbPool.filter(function(s){ var w=s['窗口']||''; return w==='W2'; });
    if (lbW2.length === 0) lbW2 = lbPool.filter(function(s){
      var op=s['操作']||''; return op.indexOf('低吸')>=0 || op.indexOf('W2')>=0;
    });
    if (lbW2.length > 0) {
      html += '<div style="font-size:12px;font-weight:700;color:var(--text-primary);margin:8px 0 4px;padding-top:4px;border-top:1px solid var(--border-light)">连板 W2' + (w2BuyAllowed ? ' 低吸' : ' 关闭') + '</div>';

      lbW2.forEach(function(s){
        var code = s['代码'] || '';
        var name = s['标的'] || '';
        var q = liveQ[code] || {};
        var chg = p(q['涨幅']||s['涨幅']);
        var vr = parseFloat(q['量比']||s['量比'])||1;
        var sector = s['板块'] || '';
        var isSkip = (s['角色']||'').indexOf('移除')>=0 || (s['操作']||'').indexOf('不碰')>=0;
        if (isSkip) return;

        // 连板W2条件: 分歧回落 + 缩量 + 龙头存活 + 非冰点
        var diverge = chg < 0 && chg > -7;  // 分歧回落（非崩盘）
        var shrink2 = vr < 0.8;
        var leaderAlive = false;
        // 找板块龙头（从lbPool中找情绪标的）
        lbPool.forEach(function(ls){
          if ((ls['角色']||'').indexOf('情绪标')>=0 && (ls['板块']||'')===sector) {
            var lchg = p((liveQ[ls['代码']]||{})['涨幅']||ls['涨幅']);
            if (lchg >= 3) leaderAlive = true;
          }
        });
        if (!leaderAlive) leaderAlive = true; // 找不到明确龙头时放行
        var notIce = qx >= 20;

        var hardMet = (diverge?1:0) + (shrink2?1:0) + (leaderAlive?1:0) + (notIce?1:0);

        // rule_state W2 关闭时连板候选统一降级
        var stockOk, stockWait, stockFail;
        if (!w2BuyAllowed) {
          stockOk = false; stockWait = false; stockFail = true;
        } else {
          stockOk = hardMet >= 3;
          stockWait = hardMet >= 2 && hardMet < 3;
          stockFail = hardMet < 2;
        }

        var stockStatus, stColor;
        if (!w2BuyAllowed) { stockStatus = '关闭'; stColor = 'var(--text-disabled)'; }
        else if (stockOk)      { stockStatus = '低吸'; stColor = 'var(--down)'; }
        else if (stockWait) { stockStatus = '观察'; stColor = 'var(--warn)'; }
        else              { stockStatus = '—'; stColor = 'var(--text-disabled)'; }

        html += '<div style="padding:6px 4px;border-bottom:1px solid var(--border-light);display:flex;align-items:center;gap:8px">'+
          '<div style="flex:0 0 auto;text-align:center;min-width:36px">'+
            signalDot(stockOk?true:stockFail?false:null, 28)+
            '<div style="font-size:9px;font-weight:600;color:'+stColor+';margin-top:1px">'+stockStatus+'</div></div>'+
          '<div style="flex:1;min-width:0">'+
            '<div style="display:flex;align-items:baseline;gap:4px;margin-bottom:2px">'+
              '<span style="font-size:13px;font-weight:700;color:var(--text-primary)">'+name+'</span>'+
              '<span style="font-size:9px;color:var(--text-disabled)">'+code+' '+sector+'</span></div>'+
            '<div style="display:flex;gap:8px;flex-wrap:wrap;font-size:10px">'+
              '<span>'+miniDot(diverge)+'分歧回落 <span style="color:var(--text-secondary)">'+(chg>=0?'+':'')+chg.toFixed(1)+'%</span></span>'+
              '<span>'+miniDot(shrink2)+'缩量 <span style="color:var(--text-secondary)">'+vr.toFixed(2)+'</span></span>'+
              '<span>'+miniDot(leaderAlive)+'龙头活 <span style="color:var(--text-secondary)">'+sector+'</span></span>'+
              '<span>'+miniDot(notIce)+'非冰点 <span style="color:var(--text-secondary)">'+qx+'%</span></span>'+
            '</div>'+
            (stockWait?'<div style="font-size:9px;color:var(--text-disabled);margin-top:1px">仓位≤10% 等缩量+分时企稳</div>':'')+
          '</div>'+
          '<div style="flex:0 0 auto;text-align:right;font-size:11px;color:var(--text-secondary)">'+
            '<div style="font-size:14px;font-weight:700;color:'+(chg>=0?'var(--up)':'var(--down)')+'">'+(chg>=0?'+':'')+chg.toFixed(1)+'%</div>'+
            '<div style="font-size:9px">量'+vr.toFixed(1)+'</div></div>'+
          '</div>';
      });
    }

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W09', W2CheckWidget);
