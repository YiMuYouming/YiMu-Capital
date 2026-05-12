// widgets/w2-check.js — W09 W2尾盘确认 (v3.0 规则引擎·低吸三策略+弱回踩)
'use strict';

class W2CheckWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var S = (data && data.sentiment) || {};
    var M = (data && data.market) || {};
    var li = (data && data.live_index) || {};
    var liveQ = (data && data.live_quotes) || {};
    var lbPoolAll = (data && data.lianban_pool) || [];
    var trPoolAll = (data && data.trend_pool) || [];
    // 按窗口过滤：W2只显示标记为W2的（向后兼容：无窗口标记的也显示）
    var lbPool = lbPoolAll.filter(function(s){ var w=s['窗口']||''; return !w||w==='W2'; });
    var trPool = trPoolAll.filter(function(s){ var w=s['窗口']||''; return !w||w==='W2'; });
    var sectors = (data && data.sectors) || [];

    var initBase = DataStore.getInitialBase();
    var closeS = (initBase && initBase.sentiment) || {};

    var now = new Date();
    var weekday = now.getDay();
    var isFriday = weekday === 5;
    var hour = now.getHours(), min = now.getMinutes();
    var inW2 = (hour === 14 && min >= 0 && min <= 50);
    var w2Phase = inW2 ? (min < 30 ? '核心时段(14:00-14:30)' : '确认段(14:30-14:50)') : '';

    // ===== 数值提取 =====
    var qx = parseFloat(S['情绪值']) || 0;
    var yestQx = parseFloat(closeS['情绪值']) || 0;
    var ztProfit = parseFloat(String(S['昨日涨停收益']||'0').replace('%','').replace('+','')) || 0;
    var fbRate = parseFloat(String(M['炸板率']||'0').replace('%','')) || 0;
    var ztCount = parseInt(M['涨停家数']) || 0;
    var szChg = parseFloat(String(li['上证指数涨幅']||'0').replace('%','').replace('+','')) || 0;
    var zone = qx < 20 ? '冰点' : qx < 40 ? '低迷' : qx < 60 ? '主升' : qx < 80 ? '强势' : '高潮';
    var isDb = qx < 20 && yestQx < 20;

    // ===== 一、共用窗口 =====
    var sharedItems = [];
    // 时间
    sharedItems.push({ok: inW2, label: '时间窗口',
      detail: inW2 ? '14:00-14:50 '+w2Phase : '当前非W2时段', hard: true});
    // 周五 → W2正常开
    sharedItems.push({ok: true, label: '周五',
      detail: isFriday ? 'W2正常（低吸仓位小）' : '非周五', hard: false});
    // 双冰 → W2可开但门槛提高
    sharedItems.push({ok: true, label: '双冰',
      detail: isDb ? 'W2可开·门槛涨停≥10' : '无双冰', hard: false});
    // 高潮保护
    var climaxOk = qx < 90;
    sharedItems.push({ok: climaxOk, label: '高潮保护',
      detail: qx >= 90 ? '全关' : qx >= 85 ? '降半仓' : '正常', hard: qx >= 90});

    var sharedAllOk = sharedItems.filter(function(x){return x.hard;}).every(function(x){return x.ok;});

    // ===== 二、连板 W2 =====
    // 三个子策略
    var lbStrategies = [];
    // 龙头首阴：最高板首次断板+非放量+跟风封板+回踩5日线
    var topBoardName = String(S['最高板']||'');
    var topLeader = lbPool.find(function(s){return s['标的']===topBoardName;}) || {};
    var tlCode = topLeader['代码'] || '';
    var tlQ = liveQ[tlCode] || {};
    var tlChg = parseFloat(String(tlQ['涨幅']||topLeader['涨幅']||'0').replace('%','').replace('+','')) || 0;
    var tlVr = parseFloat(tlQ['量比']||topLeader['量比']) || 0;
    var lbFollowCount = 0;
    lbPool.forEach(function(s){
      var q = liveQ[s['代码']] || {};
      var c = parseFloat(String(q['涨幅']||s['涨幅']||'0').replace('%','').replace('+','')) || 0;
      if (c > 3) lbFollowCount++;
    });
    var firstBreak = tlChg < 0 && tlVr < 1.5; // 断板收阴+非放量崩盘
    var hasFollow = lbFollowCount >= 1;
    lbStrategies.push({
      name: '龙头首阴', ok: firstBreak && hasFollow,
      detail: tlChg.toFixed(1)+'%'+(firstBreak?' 首阴':'')+(hasFollow?' 跟风'+lbFollowCount+'只':' 无跟风×'),
      pos: '10%', stop: '-5%'
    });

    // 分歧转一致：炸板率30-40%+核心标的回踩5日线不破+14:30后有放量回拉
    var diverge = fbRate >= 30 && fbRate <= 40;
    var dipOk = false; // 需要更细的分时数据，先标记
    lbStrategies.push({
      name: '分歧转一致', ok: diverge,
      detail: '炸板率'+(fbRate||'—')+'%'+((diverge&&fbRate)?' 分歧':'')+' 待确认',
      pos: '10%', stop: '-5%'
    });

    // 双冰试错：双冰+合力3/3+标的限龙头/中军
    var dbTryOk = isDb; // 简化：双冰时开放，实际需合力3/3
    lbStrategies.push({
      name: '双冰试错', ok: dbTryOk,
      detail: isDb ? '双冰W2试错·止损-3%' : '无双冰',
      pos: '10%', stop: '-3%'
    });

    // 方向确认（W2门槛：双冰时涨停≥10）
    var lbSectors = [];
    sectors.forEach(function(sec) {
      var name = sec['板块'] || '';
      var type = sec['类型'] || '';
      if (type.indexOf('退潮') >= 0) return;
      var ztThreshold = isDb ? 10 : 8;
      var ztCnt = parseInt(sec['涨停数']) || 0;
      var ztOk = ztCnt >= ztThreshold;

      var leader = sec['龙头'] || '';
      var leaderCode = '';
      lbPool.forEach(function(s){if(s['标的']===leader||leader.indexOf(s['标的'])>=0)leaderCode=s['代码']||'';});
      var lq = liveQ[leaderCode] || {};
      var ldrChg = parseFloat(String(lq['涨幅']||'0').replace('%','').replace('+','')) || 0;
      var ldrOk = ldrChg >= 9.5;

      var followCount = 0;
      lbPool.forEach(function(s){
        if(s['板块']===name||(s['板块']||'').indexOf(name)>=0){
          var fq=liveQ[s['代码']]||{};var fc=parseFloat(String(fq['涨幅']||s['涨幅']||'0').replace('%','').replace('+',''))||0;
          if(fc>3)followCount++;
        }
      });
      var followOk = followCount >= 3;

      var midOk = false;
      trPool.forEach(function(s){
        if(s['板块']===name||(s['板块']||'').indexOf(name)>=0){
          var mq=liveQ[s['代码']]||{};var mc=parseFloat(String(mq['涨幅']||s['涨幅']||'0').replace('%','').replace('+',''))||0;
          if(mc>0)midOk=true;
        }
      });

      var score = (ldrOk?1:0)+(followOk?1:0)+(ztOk?1:0)+(midOk?1:0);
      lbSectors.push({
        name:name, score:score, doable:score>=3,
        detail:'龙头'+(ldrOk?'✅':'❌')+' 跟风'+followCount+'只 集中'+ztCnt+'/'+ztThreshold+(ztOk?'✅':'❌')+' 中军'+(midOk?'✅':'❌')
      });
    });

    // ===== 三、趋势 W2 弱回踩（深回踩，区别于W1强回踩）=====
    var trendBySector = {};
    trPool.forEach(function(s) {
      var code = s['代码'] || '';
      var q = liveQ[code] || {};
      var price = parseFloat(q['最新价']) || parseFloat(s['收盘价']||s['最新价']) || 0;
      var ma5 = parseFloat(s['MA5']) || 0;
      var ma20 = parseFloat(s['MA20']) || 0;
      var volRatio = parseFloat(q['量比']||s['量比']) || 1;
      var chg = parseFloat(String(q['涨幅']||s['涨幅']||'0').replace('%','').replace('+','')) || 0;
      if (!price || !ma5) return;
      var dist5 = (price - ma5) / ma5 * 100;
      var dist20 = ma20 ? (price - ma20) / ma20 * 100 : 999;
      // W2弱回踩 ≠ W1强回踩：聚焦深回踩（接近10/20日线）或弱势缩量
      var nearMA20 = ma20 && dist20 <= 0 && dist20 >= -3; // 接近或跌破20日线
      var deepPull = dist5 <= -1 && dist5 >= -5; // 深回踩到5日线下方1-5%
      var nearBuyZone = nearMA20 || deepPull;
      var shrinking = volRatio < 0.8;
      var notCrashing = chg > -5;
      var qualify = nearBuyZone && shrinking && notCrashing;

      var status, sc;
      if (qualify)      { status = '🟢 可吸'; sc = 'var(--down)'; }
      else if (nearBuyZone) { status = '🟡 等缩量'; sc = 'var(--warn)'; }
      else if (shrinking && notCrashing) { status = '⏳ 等深回踩'; sc = 'var(--text-secondary)'; }
      else              { status = '—'; sc = 'var(--text-disabled)'; }

      var sector = s['板块'] || '其他';
      var bigS = (sectors.find(function(sec){return sec['板块']===sector;})||{}).板块;
      if (!bigS) { var idx = sector.indexOf('/'); bigS = idx >= 0 ? sector.substring(0, idx) : sector; }
      if (!trendBySector[bigS]) trendBySector[bigS] = [];
      trendBySector[bigS].push({
        name:s['标的'],code:code,status:status,sc:sc,qualify:qualify,
        nearBuyZone:nearBuyZone,shrinking:shrinking,notCrashing:notCrashing,deepPull:deepPull,nearMA20:nearMA20,
        dist5:dist5.toFixed(1),volRatio:volRatio.toFixed(2),chg:chg.toFixed(1)
      });
    });
    var allTrendEvals = [];
    Object.keys(trendBySector).forEach(function(k){allTrendEvals=allTrendEvals.concat(trendBySector[k]);});
    var trBuy = allTrendEvals.filter(function(t){return t.qualify;}).length;
    var trWaitShrink = allTrendEvals.filter(function(t){return t.nearBuyZone&&!t.shrinking&&t.notCrashing;}).length;
    var trWaitPull = allTrendEvals.filter(function(t){return !t.nearBuyZone&&t.shrinking&&t.notCrashing;}).length;

    // V反检测
    var vRev = (yestQx < 30 && yestQx > 0) && qx >= 60 && ztProfit >= 2;
    var vRevOpen = vRev && !isFriday;

    // ===== 渲染 =====
    function itemHtml(items) {
      var h = '';
      items.forEach(function(x) {
        var icon = x.ok ? '✅' : '❌';
        var c = x.ok ? 'var(--up)' : 'var(--danger)';
        if (x.hard === false && !x.ok) { icon = '⚠️'; c = 'var(--warn)'; }
        h += '<span style="font-size:12px;white-space:nowrap"><span style="color:'+c+'">'+icon+'</span> '+
          x.label+' <span style="color:var(--text-secondary);font-size:11px">'+x.detail+'</span></span>';
      });
      return h;
    }

    var html = '';

    // ===== 一、共用窗口 =====
    var sharedVerdict = sharedAllOk ? (inW2 ? '✅ W2开启' : '⏳ 等待14:00') : '❌ W2关闭';
    var sharedColor = sharedAllOk ? (inW2 ? 'var(--up)' : 'var(--text-secondary)') : 'var(--danger)';
    html += '<div style="padding:var(--sp-sm) var(--sp-md);margin-bottom:var(--sp-md);background:var(--bg-base);border-radius:var(--radius-md);border-left:4px solid '+sharedColor+'">'+
      '<div style="display:flex;align-items:baseline;justify-content:space-between;margin-bottom:var(--sp-xs)">'+
        '<span style="font-size:15px;font-weight:700;color:'+sharedColor+'">'+sharedVerdict+'</span>'+
        '<span style="font-size:11px;color:var(--text-secondary)">情绪'+qx+'% '+zone+' | 上证'+li['上证指数涨幅']+' | 涨停'+ztCount+'家'+
          (vRevOpen?' | 🔥V反开放':'')+'</span>'+
      '</div>'+
      '<div style="display:flex;flex-wrap:wrap;gap:4px 16px">'+itemHtml(sharedItems)+'</div>'+
      (vRevOpen ? '<div style="font-size:12px;color:var(--special);margin-top:var(--sp-xs);font-weight:600">🔥 V反信号：昨冰'+yestQx+'%→今'+qx+'% 赚钱效应'+ztProfit.toFixed(1)+'%≥2% 仓位上限40%(×0.5半仓)→约10-14%</div>' : '')+
      '</div>';

    // ===== 左右双栏 =====
    html += '<div style="display:flex;gap:var(--sp-md)">';

    // 左：连板 W2
    html += '<div style="flex:1;min-width:0">';
    var lbVerdict = sharedAllOk ? '低吸博弈' : '—';
    html += '<div style="padding:var(--sp-sm) var(--sp-md);margin-bottom:var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-md);border-left:4px solid var(--warn)">'+
      '<div style="font-size:14px;font-weight:700;color:var(--warn);margin-bottom:var(--sp-xs)">连板 W2 '+lbVerdict+'</div>'+
      '<div style="font-size:11px;color:var(--text-secondary);margin-bottom:var(--sp-sm)">逆向博弈·低吸不追高。企稳三阶段(止跌→横住→拐头)全部完成才出手</div>';

    // 三个子策略
    html += '<div style="font-size:12px;color:var(--text-secondary);margin-bottom:2px">子策略：</div>';
    lbStrategies.forEach(function(s) {
      var c = s.ok ? 'var(--up)' : 'var(--text-disabled)';
      html += '<div style="font-size:11px;padding:1px 0;color:'+c+'">'+
        (s.ok?'🟢':'—')+' <strong>'+s.name+'</strong> '+s.detail+' | 仓位'+s.pos+' 止损'+s.stop+'</div>';
    });

    // 方向确认 + 板块个股
    if (lbSectors.length > 0) {
      html += '<div style="font-size:12px;color:var(--text-secondary);margin-top:var(--sp-sm);margin-bottom:2px">方向确认 + 候选（需≥3/4'+(isDb?'·双冰≥10只涨停':'')+'）：</div>';
      lbSectors.forEach(function(v) {
        var c = v.doable ? 'var(--up)' : 'var(--text-disabled)';
        html += '<div style="font-size:11px;padding:1px 0;color:'+c+';margin-bottom:1px">'+
          (v.doable?'✅':'—')+' <strong>'+v.name+'</strong> '+v.score+'/4</div>';
        // 该板块连板池个股
        var stocks = lbPool.filter(function(p){return p['板块']===v.name||(p['板块']||'').indexOf(v.name)>=0;});
        stocks.forEach(function(p) {
          var q = liveQ[p['代码']] || {};
          var chg = parseFloat(String(q['涨幅']||p['涨幅']||'0').replace('%','').replace('+','')) || 0;
          var vr = parseFloat(q['量比']||p['量比']) || 0;
          var lowBuy = chg < 0 && vr < 1.2; // 低吸条件：收跌+不放量
          var tag = lowBuy ? '🟢低吸' : (chg < 0 ? '🟡观察' : '—');
          var tc = lowBuy ? 'var(--down)' : 'var(--text-disabled)';
          html += '<div style="font-size:10px;padding:1px 0 1px 16px;display:flex;justify-content:space-between;color:var(--text-secondary)">'+
            '<span><span style="color:'+tc+'">'+tag+'</span> '+p['标的']+' <span style="color:var(--text-disabled)">'+p['代码']+'</span></span>'+
            '<span>'+chg.toFixed(1)+'% 量比'+vr.toFixed(1)+'</span></div>';
        });
      });
    }

    // 企稳三阶段提示
    html += '<div style="font-size:11px;color:var(--text-disabled);margin-top:var(--sp-sm);padding-top:var(--sp-xs);border-top:1px solid var(--border-light)">'+
      '⚠️ 所有W2低吸必须过企稳三阶段：<br>止跌(不创新低)→横住(窄幅)→拐头(阳线+温和放量)</div>';
    html += '</div></div>'; // 左栏

    // 右：趋势 W2
    html += '<div style="flex:1;min-width:0">';
    html += '<div style="padding:var(--sp-sm) var(--sp-md);margin-bottom:var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-md);border-left:4px solid var(--info)">'+
      '<div style="font-size:14px;font-weight:700;color:var(--info);margin-bottom:var(--sp-xs)">趋势 W2 弱回踩</div>'+
      '<div style="font-size:11px;color:var(--text-secondary);margin-bottom:var(--sp-sm)">弱回踩≠W1强回踩。聚焦深回踩(近10/20日线或跌破5日线1-5%)+全天缩量+尾盘企稳。不追高·不等W1·回踩即买</div>';

    Object.keys(trendBySector).sort().forEach(function(sectorName) {
      var stocks = trendBySector[sectorName];
      var buyCnt = stocks.filter(function(t){return t.qualify;}).length;
      var scColor = buyCnt > 0 ? 'var(--up)' : 'var(--text-secondary)';
      html += '<div style="font-size:12px;font-weight:600;color:'+scColor+';margin-top:2px;padding-top:2px;border-top:1px solid var(--border-light)">'+
        sectorName+' (低吸'+buyCnt+'只)</div>';
      stocks.forEach(function(t) {
        function cond(ok,label,val,unit){
          var c=ok?'var(--up)':'var(--text-disabled)';
          return '<span style="color:'+c+';white-space:nowrap">'+(ok?'✅':'❌')+' '+label+' <b>'+val+'</b>'+unit+'</span>';
        }
        var d=(t.dist5.charAt(0)==='-'?'':'+')+t.dist5;
        // W2特有：深回踩(近10/20日线或跌破MA5) + 缩量 + 未大跌
        var reason = t.nearMA20 ? '近20日线' : (t.deepPull ? '破5日线'+d+'%' : '未到位');
        var line=cond(t.nearBuyZone, reason, '', '')+'  '+
                 cond(t.shrinking, '缩量', t.volRatio, '')+'  '+
                 cond(t.notCrashing, '未大跌', (t.chg.charAt(0)==='-'?'':'+')+t.chg, '%');
        html += '<div style="font-size:11px;padding:1px 0 1px 16px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--border-light)">'+
          '<span><span style="color:'+t.sc+';font-weight:600">'+t.status+'</span> <strong>'+t.name+'</strong>'+
            (t.code?' <span style="font-size:10px;color:var(--text-disabled)">'+t.code+'</span>':'')+'</span>'+
          '<span style="font-size:11px">'+line+'</span></div>';
      });
    });

    // 趋势总结
    var trSummary='';
    if(trBuy>0)trSummary='→ 🟢 '+trBuy+'只可低吸，重点看：'+allTrendEvals.filter(function(t){return t.qualify;}).map(function(t){return t.name;}).join('、');
    else if(trWaitShrink>0)trSummary='→ 🟡 '+trWaitShrink+'只等缩量';
    else if(trWaitPull>0)trSummary='→ ⏳ '+trWaitPull+'只等深回踩';
    else trSummary='→ 暂无标的满足深回踩条件（W2看近10/20日线或破MA5 1-5%）';
    html += '<div style="margin-top:var(--sp-sm);padding-top:var(--sp-xs);border-top:1px solid var(--border-light);font-size:12px;font-weight:600;color:var(--info)">'+
      '🟢'+trBuy+'可吸 🟡'+trWaitShrink+'等缩量 ⏳'+trWaitPull+'等深回踩 '+trSummary+'</div>';

    html += '<div style="font-size:11px;color:var(--text-disabled);margin-top:var(--sp-sm);padding-top:var(--sp-xs);border-top:1px solid var(--border-light)">'+
      '止损：回踩5日线-7% | 回踩10日线-5% | 总账户该股-10%</div>';
    html += '</div></div>'; // 右栏

    html += '</div>'; // 双栏容器

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W09', W2CheckWidget);
