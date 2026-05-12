// widgets/w1-check.js — W08 W1早盘确认 (v3.1 共用窗口+连板+趋势三区)
'use strict';

class W1CheckWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var S = (data && data.sentiment) || {};
    var M = (data && data.market) || {};
    var li = (data && data.live_index) || {};
    var liveQ = (data && data.live_quotes) || {};
    var lbPoolAll = (data && data.lianban_pool) || [];
    var trPoolAll = (data && data.trend_pool) || [];
    // 按窗口过滤：W1只显示标记为W1的（向后兼容：无窗口标记的也显示）
    var lbPool = lbPoolAll.filter(function(s){ var w=s['窗口']||''; return !w||w==='W1'; });
    var trPool = trPoolAll.filter(function(s){ var w=s['窗口']||''; return !w||w==='W1'; });
    var sectors = (data && data.sectors) || [];
    var decision = (data && data.decision) || {};
    var auction = decision['竞价'] || {};

    var initBase = DataStore.getInitialBase();
    var closeS = (initBase && initBase.sentiment) || {};

    var now = new Date();
    var weekday = now.getDay();
    var isFriday = weekday === 5;
    var hour = now.getHours(), min = now.getMinutes();
    var inW1 = (hour === 9 && min >= 30) || (hour === 9 && min <= 59) || (hour === 10 && min === 0);
    var w1Phase = inW1 ? (min < 45 ? '前半段(9:30-9:45)' : '后半段(9:45-10:00)') : '';

    // ===== 数值提取 =====
    var qx = parseFloat(S['情绪值']) || 0;
    var yestQx = parseFloat(closeS['情绪值']) || 0;
    var jjl1to2 = parseFloat(String(S['一进二晋级率']||S['晋级率']||'0').replace('%','')) || 0;
    var jjl2to3 = parseFloat(String(S['二进三晋级率']||'0').replace('%','')) || 0;
    var jjl3to4 = parseFloat(String(S['三进四晋级率']||'0').replace('%','')) || 0;
    var ztProfit = parseFloat(String(S['昨日涨停收益']||'0').replace('%','').replace('+','')) || 0;
    var fbRate = parseFloat(String(M['炸板率']||'0').replace('%','')) || 0;
    var ztCount = parseInt(M['涨停家数']) || 0;
    var topBoard = String(S['最高板']||'').replace('板','');
    var topN = parseInt(topBoard) || 0;
    var szChg = parseFloat(String(li['上证指数涨幅']||'0').replace('%','').replace('+','')) || 0;
    var zone = qx < 20 ? '冰点' : qx < 40 ? '低迷' : qx < 60 ? '主升' : qx < 80 ? '强势' : '高潮';
    var isDb = qx < 20 && yestQx < 20;

    // ===== 共用窗口条件 =====
    var sharedItems = [];
    // 时间
    sharedItems.push({ok: inW1, label: '时间窗口',
      detail: inW1 ? '9:30-10:00 '+w1Phase : '当前非W1时段', hard: true});
    // 周五
    sharedItems.push({ok: !isFriday, label: '周五',
      detail: isFriday ? '周五W1关闭' : '非周五', hard: true});
    // 双冰
    sharedItems.push({ok: !isDb, label: '双冰',
      detail: isDb ? '连续两日<20%' : '无双冰', hard: true});

    var sharedAllOk = sharedItems.every(function(x){return x.ok;});

    // ===== 连板W1 专属条件 =====
    var lbItems = [];
    // 高潮保护（连板更敏感）
    var lbClimax = qx >= 80 ? (qx >= 85 ? 'fail' : 'half') : 'ok';
    lbItems.push({ok: lbClimax !== 'fail', label: '高潮保护',
      detail: qx >= 85 ? '全关' : qx >= 80 ? '降半仓' : '正常', hard: true});

    // 赚钱效应
    var lbProfit = ztProfit >= 1.5 && fbRate < 30;
    lbItems.push({ok: lbProfit, label: '赚钱效应',
      detail: '涨停收益'+ztProfit.toFixed(1)+'%'+(ztProfit>=1.5?'≥1.5%':'<1.5%')+' 炸板'+fbRate+'%'+(fbRate<30?'<30%':'≥30%'), hard: true});

    // 情绪区间→打法
    var styleText = {'冰点':'空仓','低迷':'1进2·7折','主升':'1进2','强势':'2进3/3进4','高潮':'不买'}[zone];
    var canPlay = zone !== '冰点' && zone !== '高潮';
    lbItems.push({ok: canPlay, label: '情绪:'+zone,
      detail: canPlay ? styleText : styleText, hard: zone==='高潮'});

    // 晋级率
    var jjlOk = true, jjlText = '';
    if (zone === '低迷' || zone === '主升') {
      jjlOk = jjl1to2 >= 15; jjlText = '1进2≥15%:'+jjl1to2+'%'+(jjlOk?'✅':'❌');
    } else if (zone === '强势') {
      jjlOk = jjl2to3 >= 25 || jjl3to4 >= 35;
      jjlText = '2进3≥25%:'+jjl2to3+'%|3进4≥35%:'+jjl3to4+'%'+(jjlOk?'✅':'❌');
    } else { jjlText = '不适用('+zone+')'; }
    lbItems.push({ok: jjlOk, label: '晋级率',
      detail: jjlText, hard: false});

    // 竞价AB
    var aucAB = auction['结论'] || '';
    var aucOk = aucAB.indexOf('偏多') >= 0 || aucAB.indexOf('A好+B好') >= 0;
    var aucHalf = aucAB.indexOf('降级') >= 0 || aucAB.indexOf('A好+B差') >= 0;
    lbItems.push({ok: aucOk || aucHalf, label: '竞价AB',
      detail: aucAB || '未录入', hard: !aucHalf});

    var lbHardOk = lbItems.filter(function(x){return x.hard;}).every(function(x){return x.ok;});
    var lbAllOk = lbItems.every(function(x){return x.ok;});

    // ===== 连板W1 板块方向确认 =====
    var lbSectors = [];
    sectors.forEach(function(sec) {
      var name = sec['板块'] || '';
      var type = sec['类型'] || '';
      if (type.indexOf('退潮') >= 0) return;
      var isZx = type.indexOf('主线') >= 0;

      // 龙头封板
      var leader = sec['龙头'] || '';
      var leaderCode = '';
      lbPool.forEach(function(s) {
        if (s['标的'] === leader || leader.indexOf(s['标的']) >= 0) leaderCode = s['代码'] || '';
      });
      var lq = liveQ[leaderCode] || {};
      var ldrChg = parseFloat(String(lq['涨幅']||'0').replace('%','').replace('+','')) || 0;
      var ldrOk = ldrChg >= 9.5;

      // 跟风同步 ≥3只涨幅>3%
      var followCount = 0;
      lbPool.forEach(function(s) {
        if (s['板块'] === name || (s['板块']||'').indexOf(name) >= 0) {
          var fq = liveQ[s['代码']] || {};
          var fchg = parseFloat(String(fq['涨幅']||s['涨幅']||'0').replace('%','').replace('+','')) || 0;
          if (fchg > 3) followCount++;
        }
      });
      var followOk = followCount >= 3;

      // 集中度 ≥8只
      var ztOk = (parseInt(sec['涨停数']) || 0) >= 8;

      // 中军不弱
      var midOk = false;
      trPool.forEach(function(s) {
        if (s['板块'] === name || (s['板块']||'').indexOf(name) >= 0) {
          var mq = liveQ[s['代码']] || {};
          var mchg = parseFloat(String(mq['涨幅']||s['涨幅']||'0').replace('%','').replace('+','')) || 0;
          if (mchg > 0) midOk = true;
        }
      });

      var score = (ldrOk?1:0)+(followOk?1:0)+(ztOk?1:0)+(midOk?1:0);
      lbSectors.push({
        name: name, isZx: isZx, score: score, doable: score>=3,
        detail: '龙头'+(ldrOk?'✅':'❌')+' 跟风'+followCount+'只'+(followOk?'✅':'❌')+
                ' 集中'+(sec['涨停数']||0)+'只'+(ztOk?'✅':'❌')+' 中军'+(midOk?'✅':'❌')
      });
    });

    // 连板候选标的
    var lbCandidates = [];
    lbPool.forEach(function(s) {
      var code = s['代码'] || '';
      var q = liveQ[code] || {};
      var chg = parseFloat(String(q['涨幅']||s['涨幅']||'0').replace('%','').replace('+','')) || 0;
      var vr = parseFloat(q['量比']||s['量比']) || 0;
      var op = s['操作'] || '';
      if (chg >= 3 && chg <= 7 && vr >= 3 && op.indexOf('追') >= 0) {
        lbCandidates.push({name:s['标的'],code:code,chg:chg,vr:vr, strategy:'A 竞价确认型·直接追',strong:true});
      } else if (chg >= 3 && chg <= 7 && vr >= 3) {
        lbCandidates.push({name:s['标的'],code:code,chg:chg,vr:vr, strategy:'B 开盘确认型·观察',strong:false});
      } else if (op.indexOf('追') >= 0 && chg > 0) {
        lbCandidates.push({name:s['标的'],code:code,chg:chg,vr:vr, strategy:'⏳ '+(chg<3?'高开不足':'量比低'),strong:false});
      }
    });

    // ===== 趋势W1 回踩检测（按板块分组）=====
    var trendBySector = {}; // {sectorName: [{name,code,status,...}]}
    trPool.forEach(function(s) {
      var code = s['代码'] || '';
      var q = liveQ[code] || {};
      var price = parseFloat(q['最新价']) || parseFloat(s['收盘价']||s['最新价']) || 0;
      var ma5 = parseFloat(s['MA5']) || 0;
      var volRatio = parseFloat(q['量比']||s['量比']) || 1;
      var chg = parseFloat(String(q['涨幅']||s['涨幅']||'0').replace('%','').replace('+','')) || 0;
      if (!price || !ma5) return;
      var dist5 = (price - ma5) / ma5 * 100;
      var nearMA5 = Math.abs(price - ma5) <= ma5 * 0.005;
      var shrinking = volRatio < 0.8;
      var notCrashing = chg > -5;
      var qualify = nearMA5 && shrinking && notCrashing;

      var status, sc;
      if (qualify)      { status = '🟢 可买'; sc = 'var(--down)'; }
      else if (nearMA5) { status = '🟡 等缩量'; sc = 'var(--warn)'; }
      else if (shrinking && notCrashing) { status = '⏳ 等回踩'; sc = 'var(--text-secondary)'; }
      else              { status = '—'; sc = 'var(--text-disabled)'; }

      var sector = s['板块'] || '其他';
      // 归入大板块
      var bigS = (sectors.find(function(sec){return sec['板块']===sector;})||{}).板块;
      if (!bigS) {
        var idx = sector.indexOf('/');
        bigS = idx >= 0 ? sector.substring(0, idx) : sector;
      }
      if (!trendBySector[bigS]) trendBySector[bigS] = [];
      trendBySector[bigS].push({
        name: s['标的'], code: code,
        status: status, sc: sc, qualify: qualify,
        nearMA5: nearMA5, shrinking: shrinking, notCrashing: notCrashing,
        dist5: dist5.toFixed(1), volRatio: volRatio.toFixed(2), chg: chg.toFixed(1)
      });
    });
    var allTrendEvals = [];
    Object.keys(trendBySector).forEach(function(k) { allTrendEvals = allTrendEvals.concat(trendBySector[k]); });
    var trBuy = allTrendEvals.filter(function(t){return t.qualify;}).length;
    var trWaitShrink = allTrendEvals.filter(function(t){return t.nearMA5 && !t.shrinking && t.notCrashing;}).length;
    var trWaitPull = allTrendEvals.filter(function(t){return !t.nearMA5 && t.shrinking && t.notCrashing;}).length;

    // ===== 趋势W1 T4.2 突破确认（强势不回调时）=====
    var trendBrkBySector = {};
    trPool.forEach(function(s) {
      var code = s['代码'] || '';
      var q = liveQ[code] || {};
      var price = parseFloat(q['最新价']) || parseFloat(s['收盘价']||s['最新价']) || 0;
      var ma5 = parseFloat(s['MA5']) || 0;
      var volRatio = parseFloat(q['量比']||s['量比']) || 1;
      var chg = parseFloat(String(q['涨幅']||s['涨幅']||'0').replace('%','').replace('+','')) || 0;
      if (!price || !ma5) return;
      var dist5 = (price - ma5) / ma5 * 100;
      // 突破条件：站上MA5(距>+0.5%且<+8%) + 涨 + 量健康(0.8-2.0)
      var aboveMA5 = dist5 > 0.5 && dist5 < 8;
      var upToday = chg > 0;
      var volHealthy = volRatio >= 0.8 && volRatio <= 2.0;
      var brkQualify = aboveMA5 && upToday && volHealthy;
      if (!brkQualify) return;

      var sector = s['板块'] || '其他';
      var bigS = (sectors.find(function(sec){return sec['板块']===sector;})||{}).板块;
      if (!bigS) { var idx = sector.indexOf('/'); bigS = idx >= 0 ? sector.substring(0, idx) : sector; }
      if (!trendBrkBySector[bigS]) trendBrkBySector[bigS] = [];
      trendBrkBySector[bigS].push({
        name: s['标的'], code: code,
        dist5: dist5.toFixed(1), volRatio: volRatio.toFixed(2), chg: chg.toFixed(1)
      });
    });
    var allBrkEvals = [];
    Object.keys(trendBrkBySector).forEach(function(k) { allBrkEvals = allBrkEvals.concat(trendBrkBySector[k]); });

    // ===== 渲染 =====
    function itemHtml(items) {
      var h = '';
      items.forEach(function(x) {
        var icon = x.ok ? '✅' : '❌';
        var c = x.ok ? 'var(--up)' : 'var(--danger)';
        if (x.hard === false && !x.ok) { icon = '⚠️'; c = 'var(--warn)'; }
        h += '<span style="font-size:12px;white-space:nowrap"><span style="color:'+c+'">'+icon+'</span> '+
          x.label+(x.ok?'':x.hard?' ✗':'')+' <span style="color:var(--text-secondary);font-size:11px">'+x.detail+'</span></span>';
      });
      return h;
    }

    // 计数
    var lbPass = lbItems.filter(function(x){return x.ok;}).length;
    var lbHardPass = lbItems.filter(function(x){return x.hard !== false && x.ok;}).length;
    var lbHardTotal = lbItems.filter(function(x){return x.hard !== false;}).length;
    var lbDirPass = lbSectors.filter(function(v){return v.doable;}).length;

    var html = '';

    // ===== 一、W1 共用窗口 =====
    var sharedVerdict = sharedAllOk ? (inW1 ? '✅ W1开启' : '⏳ 等待9:30开盘') : '❌ W1关闭';
    var sharedColor = sharedAllOk ? (inW1 ? 'var(--up)' : 'var(--text-secondary)') : 'var(--danger)';
    html += '<div style="padding:var(--sp-sm) var(--sp-md);margin-bottom:var(--sp-md);background:var(--bg-base);border-radius:var(--radius-md);border-left:4px solid '+sharedColor+'">'+
      '<div style="display:flex;align-items:baseline;justify-content:space-between;margin-bottom:var(--sp-xs)">'+
        '<span style="font-size:15px;font-weight:700;color:'+sharedColor+'">'+sharedVerdict+'</span>'+
        '<span style="font-size:11px;color:var(--text-secondary)">情绪'+qx+'% '+zone+' | 上证'+li['上证指数涨幅']+' | 涨停'+ztCount+'家</span>'+
      '</div>'+
      '<div style="display:flex;flex-wrap:wrap;gap:4px 16px">'+itemHtml(sharedItems)+'</div>'+
      '</div>';

    // ===== 二、左右双栏：连板 W1 | 趋势 W1 =====
    html += '<div style="display:flex;gap:var(--sp-md)">';

    // 左栏：连板 W1
    html += '<div style="flex:1;min-width:0">';
    var lbVerdict = lbHardOk ? (lbAllOk ? '✅ 可追涨' : '⚠️ 降级观望') : '❌ 不追';
    var lbColor = lbHardOk ? (lbAllOk ? 'var(--up)' : 'var(--warn)') : 'var(--danger)';

    html += '<div style="padding:var(--sp-sm) var(--sp-md);margin-bottom:var(--sp-md);background:var(--bg-base);border-radius:var(--radius-md);border-left:4px solid '+lbColor+'">'+
      '<div style="font-size:14px;font-weight:700;color:'+lbColor+';margin-bottom:var(--sp-xs)">连板 W1 '+lbVerdict+'</div>'+
      '<div style="display:flex;flex-wrap:wrap;gap:4px 16px;margin-bottom:var(--sp-sm)">'+itemHtml(lbItems)+'</div>';

    // 按板块分组的个股（连板W1 方向+标的）
    if (lbSectors.length > 0) {
      html += '<div style="font-size:12px;color:var(--text-secondary);margin-bottom:2px">方向确认 + 候选标的：</div>';
      lbSectors.forEach(function(v) {
        var c = v.doable ? 'var(--up)' : 'var(--text-disabled)';
        html += '<div style="font-size:12px;padding:1px 0;color:'+c+';margin-bottom:2px">'+
          (v.doable?'✅':'—')+' <strong>'+v.name+'</strong> '+v.score+'/4</div>';
        // 该板块下的候选个股
        var stocks = lbCandidates.filter(function(s) {
          return (lbPool.find(function(p){return p['代码']===s.code;})||{})['板块'] === v.name ||
                 ((lbPool.find(function(p){return p['代码']===s.code;})||{})['板块']||'').indexOf(v.name) >= 0;
        });
        if (stocks.length === 0) {
          // 找该板块所有连板池标的
          stocks = lbPool.filter(function(p) {
            return (p['板块'] === v.name || (p['板块']||'').indexOf(v.name) >= 0);
          }).map(function(p) {
            var q = liveQ[p['代码']] || {};
            var chg = parseFloat(String(q['涨幅']||p['涨幅']||'0').replace('%','').replace('+','')) || 0;
            var vr = parseFloat(q['量比']||p['量比']) || 0;
            return {name:p['标的'],code:p['代码'],chg:chg,vr:vr};
          });
        }
        stocks.forEach(function(s) {
          var q = liveQ[s.code] || {};
          var chg = parseFloat(String(q['涨幅']||s['涨幅']||'0').replace('%','').replace('+','')) || 0;
          var vr = parseFloat(q['量比']||s['量比']) || 0;
          // 判断是否符合追涨条件
          var qualify = chg >= 3 && chg <= 7 && vr >= 3;
          var tag = qualify ? '🟢追' : (chg > 0 ? '⏳等' : '—');
          var tc = qualify ? 'var(--up)' : 'var(--text-disabled)';
          html += '<div style="font-size:11px;padding:1px 0 1px 16px;display:flex;justify-content:space-between;color:var(--text-secondary)">'+
            '<span><span style="color:'+tc+'">'+tag+'</span> '+s.name+
              (s.code?' <span style="font-size:10px;color:var(--text-disabled)">'+s.code+'</span>':'')+'</span>'+
            '<span>+'+(chg||0).toFixed(1)+'% 量比'+(vr||0).toFixed(1)+'</span></div>';
        });
      });
    }

    // 连板总结
    var lbQualifyLbl = lbHardOk && lbDirPass > 0 ? '→ 可追涨，关注'+lbSectors.filter(function(v){return v.doable;}).map(function(v){return v.name;}).join('、') : '';
    if (!lbQualifyLbl && lbHardOk) lbQualifyLbl = '→ 等方向确认达标';
    if (!lbHardOk) lbQualifyLbl = '→ 条件不足，不操作';
    html += '<div style="margin-top:var(--sp-sm);padding-top:var(--sp-xs);border-top:1px solid var(--border-light);font-size:12px;font-weight:600;color:'+lbColor+'">'+
      lbPass+'/'+lbItems.length+' 条件通过，'+lbDirPass+' 板块达标 '+lbQualifyLbl+'</div>';
    html += '</div>'; // 连板卡片
    html += '</div>'; // 左栏

    // 右栏：趋势 W1
    html += '<div style="flex:1;min-width:0">';
    var trColor = 'var(--info)';

    html += '<div style="padding:var(--sp-sm) var(--sp-md);margin-bottom:var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-md);border-left:4px solid '+trColor+'">'+
      '<div style="font-size:14px;font-weight:700;color:'+trColor+';margin-bottom:var(--sp-xs)">趋势 W1</div>'+
      '<div style="font-size:11px;color:var(--text-secondary);margin-bottom:var(--sp-sm)">不追高·不等W1·不靠情绪。买入唯一时机=回踩支撑位+缩量+未大跌</div>';

    Object.keys(trendBySector).sort().forEach(function(sectorName) {
      var stocks = trendBySector[sectorName];
      var buyCnt = stocks.filter(function(t){return t.qualify;}).length;
      var scColor = buyCnt > 0 ? 'var(--up)' : 'var(--text-secondary)';
      html += '<div style="font-size:12px;font-weight:600;color:'+scColor+';margin-top:3px;padding-top:2px;border-top:1px solid var(--border-light)">'+
        sectorName+' <span style="font-weight:400;font-size:11px">('+buyCnt+'只可买)</span></div>';
      stocks.forEach(function(t) {
        function cond(ok, label, val, unit) {
          var c = ok ? 'var(--up)' : 'var(--text-disabled)';
          return '<span style="color:'+c+';white-space:nowrap">'+(ok?'✅':'❌')+' '+label+' <b>'+val+'</b>'+unit+'</span>';
        }
        var d = (t.dist5.charAt(0)==='-'?'':'+')+t.dist5;
        var line = cond(t.nearMA5, '触及MA5', d, '%')+'  '+
                   cond(t.shrinking, '缩量', t.volRatio, '')+'  '+
                   cond(t.notCrashing, '未大跌', (t.chg.charAt(0)==='-'?'':'+')+t.chg, '%');
        html += '<div style="font-size:11px;padding:1px 0 1px 16px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--border-light)">'+
          '<span><span style="color:'+t.sc+';font-weight:600">'+t.status+'</span> <strong>'+t.name+'</strong>'+
            (t.code?' <span style="font-size:10px;color:var(--text-disabled)">'+t.code+'</span>':'')+'</span>'+
          '<span style="font-size:11px">'+line+'</span></div>';
      });
    });

    // 回踩总结
    var trSummary = '';
    if (trBuy > 0) trSummary = '→ 🟢 '+trBuy+'只可买，重点看：'+allTrendEvals.filter(function(t){return t.qualify;}).map(function(t){return t.name;}).join('、');
    else if (trWaitShrink > 0) trSummary = '→ 🟡 '+trWaitShrink+'只等缩量，关注：'+allTrendEvals.filter(function(t){return t.nearMA5;}).map(function(t){return t.name;}).join('、');
    else if (trWaitPull > 0) trSummary = '→ ⏳ '+trWaitPull+'只等回踩到位';
    else trSummary = '→ 暂无标的满足回踩条件，继续等待';
    html += '<div style="margin-top:var(--sp-sm);padding-top:var(--sp-xs);border-top:1px solid var(--border-light);font-size:12px;font-weight:600;color:var(--info)">'+
      '🟢'+trBuy+'可买 🟡'+trWaitShrink+'等缩量 ⏳'+trWaitPull+'等回踩 '+trSummary+'</div>';

    // 突破确认（备选）
    if (allBrkEvals.length > 0) {
      html += '<div style="margin-top:var(--sp-sm);padding-top:var(--sp-xs);border-top:1px solid var(--border-light)">'+
        '<div style="font-size:12px;font-weight:700;color:var(--special);margin-bottom:2px">T4.2 突破确认备选（强势不回调·站上MA5+涨+量健康）</div>';
      Object.keys(trendBrkBySector).sort().forEach(function(sectorName) {
        var stocks = trendBrkBySector[sectorName];
        html += '<div style="font-size:12px;font-weight:600;color:var(--text-secondary);margin-top:2px">'+sectorName+'</div>';
        stocks.forEach(function(b) {
          html += '<div style="font-size:11px;padding:1px 0 1px 16px;display:flex;justify-content:space-between;color:var(--text-secondary)">'+
            '<span>🚀 <strong>'+b.name+'</strong> <span style="font-size:10px;color:var(--text-disabled)">'+b.code+'</span></span>'+
            '<span>距MA5 +'+b.dist5+'% 量比'+b.volRatio+' +'+b.chg+'%</span></div>';
        });
      });
      html += '<div style="font-size:11px;color:var(--text-disabled);margin-top:2px">突破买入=等创新高后回踩分时均线企稳再介入，不追正在拉升的阳线</div>';
    }
    html += '</div>'; // 趋势卡片
    html += '</div>'; // 右栏
    html += '</div>'; // 双栏容器

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W08', W1CheckWidget);
