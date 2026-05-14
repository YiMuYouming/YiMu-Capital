// widgets/w1-check.js — W08 W1早盘确认 (v5.0 信号灯系统)
'use strict';

class W1CheckWidget extends YiMuWidget {
  constructor(config) {
    super(config);
    this._aiInsights = null;
    this._aiLoaded = false;
    this._openSnapshot = null;  // 9:25 开盘快照，锁住高开+合力判定
  }

  _loadAI() {
    if (this._aiLoaded) return;
    this._aiLoaded = true;
    var self = this;
    fetch('data/llm_insights.json?t=' + Date.now())
      .then(function(r){ return r.json(); })
      .then(function(d){ self._aiInsights = d; self._renderBody(); })
      .catch(function(){});
  }

  render(data) {
    var body = this.getBody();
    if (!body) return;
    var S = (data && data.sentiment) || {};
    var M = (data && data.market) || {};
    var li = (data && data.live_index) || {};
    var liveQ = (data && data.live_quotes) || {};
    var lbPoolAll = (data && data.lianban_pool) || [];
    var trPoolAll = (data && data.trend_pool) || [];
    var sectors = (data && data.sectors) || [];

    var lbPool = lbPoolAll.filter(function(s){ var w=s['窗口']||''; return !w||w==='W1'; });
    var trPool = trPoolAll.filter(function(s){ var w=s['窗口']||''; return !w||w==='W1'; });

    var initBase = DataStore.getInitialBase();
    var closeS = (initBase && initBase.sentiment) || {};

    var now = new Date();
    var hour = now.getHours(), min = now.getMinutes();
    var inW1 = (hour === 9 && min >= 30) || (hour === 9 && min <= 59) || (hour === 10 && min === 0);
    var isFriday = now.getDay() === 5;

    // ===== 开盘快照：W1 首次有数据时定格，用于高开/合力判定 =====
    if (inW1 && !this._openSnapshot && Object.keys(liveQ).length > 0) {
      var hasValidData = Object.values(liveQ).some(function(q){ return parseFloat(String(q['涨幅']||'0').replace('%','').replace('+','')) > 0; });
      if (hasValidData) {
        this._openSnapshot = {};
        Object.keys(liveQ).forEach(function(k){
          this._openSnapshot[k] = {
            涨幅: liveQ[k]['涨幅'],
            量比: liveQ[k]['量比'],
            最新价: liveQ[k]['最新价']
          };
        }, this);
      }
    }
    var openQ = this._openSnapshot || liveQ;  // 开盘数据优先，无快照时用实时

    // ===== 数值 =====
    var qx = parseFloat(S['情绪值']) || 0;
    var yestQx = parseFloat(closeS['情绪值']) || 0;
    var ztProfit = parseFloat(String(S['昨日涨停收益']||'0').replace('%','').replace('+','')) || 0;
    var fbRate = parseFloat(String(M['炸板率']||'0').replace('%','')) || 0;
    var ztCount = parseInt(M['涨停家数']) || 0;
    var topN = parseInt(String(S['最高板']||'').replace('板','')) || 0;
    var topName = String(S['最高板']||'');

    // ===== 环境阻断 =====
    var blocks = [];
    if (isFriday) blocks.push({label:'周五休战', detail:'周五W1关闭'});
    if (qx < 20 && yestQx < 20) blocks.push({label:'双冰', detail:'连续两日情绪<20%'});
    if (qx >= 85) blocks.push({label:'高潮保护', detail:'情绪≥85%极端高潮'});
    var blocked = blocks.length > 0;

    // ===== 三件套 =====
    var piece1_ok = qx >= 60;
    var piece3_stocks = [];
    lbPool.forEach(function(s){
      var code = s['代码'] || '';
      var oq = openQ[code] || liveQ[code] || {};
      var ochg = parseFloat(String(oq['涨幅']||s['涨幅']||'0').replace('%','').replace('+','')) || 0;
      if (ochg >= 3 && ochg <= 9.5) piece3_stocks.push({name:s['标的'], code:code, chg:ochg});
    });
    var piece2_ok = ztProfit > 2;
    var piece3_ok = piece3_stocks.length > 0;
    var threePass = piece1_ok && piece2_ok && piece3_ok;

    // ===== 渲染 =====
    var html = '';

    // 环境阻断
    if (blocked) {
      html += '<div style="text-align:center;padding:20px">'+
        '<div style="display:inline-block;width:64px;height:64px;border-radius:50%;background:var(--danger);'+
          'box-shadow:0 0 24px var(--danger);line-height:64px;font-size:28px;color:#fff;margin-bottom:12px">✕</div>'+
        '<div style="font-size:16px;font-weight:700;color:var(--danger);margin-bottom:8px">W1 关闭</div>';
      blocks.forEach(function(b){
        html += '<div style="font-size:12px;color:var(--text-secondary)">'+b.label+': '+b.detail+'</div>';
      });
      html += '</div>';
      body.innerHTML = html;
      this.updateTimestamp();
      return;
    }

    // ===== 信号灯样式函数 =====
    function signalDot(ok, size) {
      var s = size || 48;
      var color, glow;
      if (ok === true)  { color = '#22c55e'; glow = '0 0 20px rgba(34,197,94,0.6)'; }
      else if (ok === false) { color = '#ef4444'; glow = '0 0 20px rgba(239,68,68,0.5)'; }
      else              { color = '#6b7280'; glow = 'none'; }
      return '<span style="display:inline-block;width:'+s+'px;height:'+s+'px;border-radius:50%;'+
        'background:'+color+';box-shadow:'+glow+';'+
        'line-height:'+s+'px;text-align:center;font-size:'+Math.floor(s*0.45)+'px;color:#fff;'+
        'transition:all 0.5s">'+
        (ok===true?'✓':ok===false?'✕':'—')+'</span>';
    }

    function miniDot(ok) {
      var color = ok===true ? '#22c55e' : ok===false ? '#ef4444' : '#4b5563';
      var glow = ok===true ? '0 0 6px rgba(34,197,94,0.5)' : 'none';
      return '<span style="display:inline-block;width:14px;height:14px;border-radius:50%;'+
        'background:'+color+';box-shadow:'+glow+';vertical-align:middle;margin-right:2px;transition:all 0.4s"></span>';
    }

    // ===== 三件套信号灯（三盏大圆灯）=====
    html += '<div style="text-align:center;padding:6px 0 12px">';

    // 三盏灯横排
    html += '<div style="display:flex;justify-content:center;gap:28px;margin-bottom:6px">';

    // 灯1: 情绪
    html += '<div style="text-align:center">'+
      signalDot(piece1_ok, 50)+
      '<div style="font-size:12px;font-weight:600;color:var(--text-primary);margin-top:6px">情绪≥60%</div>'+
      '<div style="font-size:18px;font-weight:700;color:'+(piece1_ok?'var(--up)':'var(--danger)')+'">'+qx+'%</div>'+
      '<div style="font-size:10px;color:var(--text-disabled)">昨日 '+yestQx+'%</div>'+
      '</div>';

    // 灯2: 涨停收益
    html += '<div style="text-align:center">'+
      signalDot(piece2_ok, 50)+
      '<div style="font-size:12px;font-weight:600;color:var(--text-primary);margin-top:6px">涨停收益>2%</div>'+
      '<div style="font-size:18px;font-weight:700;color:'+(piece2_ok?'var(--up)':'var(--danger)')+'">'+ztProfit.toFixed(1)+'%</div>'+
      '<div style="font-size:10px;color:var(--text-disabled)">炸板率 '+fbRate.toFixed(1)+'%</div>'+
      '</div>';

    // 灯3: 标的高开
    html += '<div style="text-align:center">'+
      signalDot(piece3_ok, 50)+
      '<div style="font-size:12px;font-weight:600;color:var(--text-primary);margin-top:6px">标的高开3-7%</div>'+
      '<div style="font-size:18px;font-weight:700;color:'+(piece3_ok?'var(--up)':'var(--danger)')+'">'+
        (piece3_ok ? piece3_stocks.length+'只' : '0只')+'</div>'+
      '<div style="font-size:10px;color:var(--text-disabled)">'+
        (piece3_ok ? piece3_stocks.map(function(s){return s.name+'+'+s.chg.toFixed(1)+'%';}).join(' ') : '标的未达区间')+'</div>'+
      '</div>';

    html += '</div>'; // 三盏灯

    // ===== 总信号 =====
    var sigText, sigBg, sigColor, sigGlow;
    if (threePass) {
      sigText = '买 入 信 号';
      sigBg = 'rgba(34,197,94,0.12)';
      sigColor = '#22c55e';
      sigGlow = '0 0 32px rgba(34,197,94,0.4)';
    } else if (piece1_ok && piece2_ok) {
      sigText = '等 待 信 号';
      sigBg = 'rgba(245,158,11,0.1)';
      sigColor = '#f59e0b';
      sigGlow = '0 0 16px rgba(245,158,11,0.25)';
    } else {
      sigText = '降级 · 1进2或空仓';
      sigBg = 'rgba(239,68,68,0.08)';
      sigColor = '#ef4444';
      sigGlow = 'none';
    }

    html += '<div style="display:inline-block;padding:10px 36px;border-radius:8px;'+
      'background:'+sigBg+';box-shadow:'+sigGlow+';'+
      'border:2px solid '+sigColor+';margin:0 auto">'+
      '<div style="font-size:20px;font-weight:800;color:'+sigColor+';letter-spacing:6px">'+sigText+'</div>'+
      '<div style="font-size:11px;color:var(--text-secondary);margin-top:2px">'+
        '涨停'+ztCount+'家 | 最高'+topN+'板'+topName+' | 晋级1进2:'+fmtPct(S['一进二晋级率']||S['晋级率'])+' 2进3:'+fmtPct(S['二进三晋级率'])+' 3进4:'+fmtPct(S['三进四晋级率'])+
      '</div>'+
      '</div>';

    html += '</div>'; // 三件套区域

    // ===== 分隔 =====
    html += '<div style="border-top:1px solid var(--border-light);margin:4px 0"></div>';

    // ===== 龙头+合力 预计算 =====
    function findLeader(sectorName) {
      var sec = sectors.find(function(x){ return x['板块']===sectorName || (x['板块']||'').indexOf(sectorName)>=0 || (sectorName||'').indexOf(x['板块'])>=0; });
      if (!sec) return null;
      var leaderRaw = sec['龙头'] || '';
      var leaderClean = leaderRaw.replace(/\d+板.*$/, '').trim();
      if (!leaderClean) return null;
      var ls = lbPoolAll.find(function(x){ return x['标的']===leaderClean || leaderRaw.indexOf(x['标的'])>=0; });
      return ls || null;
    }
    function checkLeader(leaderStock) {
      if (!leaderStock) return {ok:null, val:'无龙头数据'};
      var lq = liveQ[leaderStock['代码']] || {};
      var lchg = parseFloat(String(lq['涨幅']||leaderStock['涨幅']||'0').replace('%','').replace('+','')) || 0;
      var alive = lchg >= 9.5;
      return {ok:alive, val:leaderStock['标的']+(alive?' 封板':' +'+lchg.toFixed(1)+'%')};
    }
    function checkSynergy(sectorName) {
      var count=0, names=[];
      lbPoolAll.forEach(function(x){
        var xs = x['板块']||'';
        if (xs===sectorName || xs.indexOf(sectorName)>=0 || (sectorName||'').indexOf(xs)>=0) {
          var oq = openQ[x['代码']] || liveQ[x['代码']] || {};
          var xchg = parseFloat(String(oq['涨幅']||x['涨幅']||'0').replace('%','').replace('+','')) || 0;
          if (xchg > 3) { count++; if (names.length<3) names.push(x['标的']+'+'+xchg.toFixed(1)+'%'); }
        }
      });
      return {ok:count>=3, val:count+'只>3%'+(names.length>0?' ('+names.join(' ')+')':'')};
    }

    // ===== 标的信号卡 =====
    if (lbPool.length > 0) {
      html += '<div style="padding:0">';

      lbPool.forEach(function(s){
        var code = s['代码'] || '';
        var name = s['标的'] || '';
        var q = liveQ[code] || {};
        var chg = parseFloat(String(q['涨幅']||s['涨幅']||'0').replace('%','').replace('+','')) || 0;
        var vr = parseFloat(q['量比']||s['量比']) || 0;
        // 开盘涨幅（定格），用于高开条件判定
        var oq = openQ[code] || liveQ[code] || {};
        var ochg = parseFloat(String(oq['涨幅']||s['涨幅']||'0').replace('%','').replace('+','')) || 0;
        var role = s['角色'] || '';
        var op = s['操作'] || '';
        var sector = s['板块'] || '';

        var isWatch = role.indexOf('情绪标')>=0 || role.indexOf('龙头')>=0 || op.indexOf('只盯')>=0;
        var isSkip = role.indexOf('移除')>=0 || op.indexOf('不碰')>=0;
        var is3jin4 = !isWatch && !isSkip && (role.indexOf('3进4')>=0 || name.indexOf('华电')>=0);
        var is2jin3 = !isWatch && !isSkip && (role.indexOf('2进3')>=0 || name.indexOf('万控')>=0);
        var is1jin2 = !isWatch && !isSkip && (role.indexOf('1进2')>=0 || name.indexOf('韶能')>=0);

        // 预计算龙头+合力（标的本身是龙头则跳过龙头检查）
        var leaderStock = findLeader(sector);
        var selfIsLeader = leaderStock && leaderStock['代码'] === code;
        var leaderCheck = selfIsLeader ? {ok:null, val:'自身为龙头', _skip:true} : checkLeader(leaderStock);
        var synergyCheck = checkSynergy(sector);

        var conds = [];
        if (is3jin4 || is2jin3) {
          var gapOk = ochg>=3 && ochg<=9.5;
          var gapLabel = ochg>7 ? '高开偏高' : '高开3-7%';
          conds.push({label: gapLabel, ok: gapOk, val:'开盘+'+ochg.toFixed(1)+'%'});
          conds.push({label:'量比>1.5', ok: vr>=1.5, val:vr.toFixed(1)});
          conds.push({label:'龙头存活', ok: leaderCheck.ok, val: leaderCheck.val});
          if (is3jin4) conds.push({label:'板块合力', ok: synergyCheck.ok, val: synergyCheck.val});
        } else if (is1jin2) {
          conds.push({label:'高开>0%', ok: ochg>0, val:'开盘+'+ochg.toFixed(1)+'%'});
          conds.push({label:'板块合力', ok: synergyCheck.ok, val: synergyCheck.val});
          conds.push({label:'龙头存活', ok: leaderCheck.ok, val: leaderCheck.val});
        } else if (isSkip) {
          // 不碰标的：不显示条件
        } else if (!isWatch) {
          var gapOk2 = ochg>=3 && ochg<=9.5;
          var gapLabel2 = ochg>7 ? '高开偏高' : '高开3-7%';
          conds.push({label: gapLabel2, ok: gapOk2, val:'开盘+'+ochg.toFixed(1)+'%'});
          conds.push({label:'量比>1.5', ok: vr>=1.5, val:vr.toFixed(1)});
        }

        var activeConds = conds.filter(function(c){return !c._skip;});
        var failCount = activeConds.filter(function(c){return c.ok===false;}).length;
        var pendCount = activeConds.filter(function(c){return c.ok===null;}).length;
        var stockOk = failCount===0 && pendCount===0;
        var stockWait = failCount===0 && pendCount>0;
        var stockFail = failCount>0;

        var stockStatus, stColor;
        if (isSkip)       { stockStatus = '不碰'; stColor = 'var(--text-disabled)'; }
        else if (isWatch) { stockStatus = '只盯不买'; stColor = 'var(--text-secondary)'; }
        else if (stockOk) { stockStatus = '追涨'; stColor = '#22c55e'; }
        else if (stockWait) { stockStatus = '待确认'; stColor = '#f59e0b'; }
        else              { stockStatus = '条件不足'; stColor = '#ef4444'; }

        // 标的行
        html += '<div style="padding:8px 4px;border-bottom:1px solid var(--border-light);display:flex;align-items:center;gap:10px">';

        // 左侧：状态灯 + 名称
        html += '<div style="flex:0 0 auto;text-align:center;min-width:44px">'+
          signalDot((isWatch||isSkip)?null:stockOk?true:stockFail?false:null, 36)+
          '<div style="font-size:10px;font-weight:600;color:'+stColor+';margin-top:2px">'+stockStatus+'</div>'+
          '</div>';

        // 中间：名称+板块+条件灯
        html += '<div style="flex:1;min-width:0">'+
          '<div style="display:flex;align-items:baseline;gap:6px;margin-bottom:3px">'+
            '<span style="font-size:14px;font-weight:700;color:var(--text-primary)">'+name+'</span>'+
            '<span style="font-size:10px;color:var(--text-disabled)">'+code+'</span>'+
            (role?'<span style="font-size:10px;color:var(--special);background:rgba(139,92,246,0.12);padding:0 5px;border-radius:3px">'+role+'</span>':'')+
          '</div>';
        if (!isWatch && conds.length > 0) {
          html += '<div style="display:flex;gap:10px;flex-wrap:wrap">';
          conds.forEach(function(c){
            html += '<span style="font-size:11px;white-space:nowrap">'+
              miniDot(c.ok)+c.label+' <span style="color:var(--text-secondary)">'+c.val+'</span></span>';
          });
          html += '</div>';
        }
        html += '</div>';

        // 右侧：开盘+实时涨幅+量比
        var hasOpenData = openQ[code] && ochg !== chg;
        html += '<div style="flex:0 0 auto;text-align:right;font-size:11px;color:var(--text-secondary)">'+
          '<div style="font-size:15px;font-weight:700;color:'+(chg>=0?'var(--up)':'var(--danger)')+'">'+(chg>=0?'+':'')+chg.toFixed(1)+'%</div>'+
          (hasOpenData?'<div style="font-size:10px;color:var(--text-disabled)">开盘'+(ochg>=0?'+':'')+ochg.toFixed(1)+'%</div>':'')+
          '<div>量比 '+vr.toFixed(1)+'</div>'+
          '<div style="font-size:10px;color:var(--text-disabled)">'+sector+'</div>'+
          '</div>';

        html += '</div>'; // 标的行
      });

      html += '</div>';
    }

    // ===== 趋势持仓（简化信号灯）=====
    if (trPool.length > 0) {
      html += '<div style="border-top:1px solid var(--border-light);margin-top:4px;padding-top:6px">'+
        '<div style="font-size:11px;color:var(--text-disabled);margin-bottom:4px">趋势 W1</div>';

      trPool.forEach(function(s){
        var code = s['代码'] || '';
        var q = liveQ[code] || {};
        var chg = parseFloat(String(q['涨幅']||s['涨幅']||'0').replace('%','').replace('+','')) || 0;
        var price = parseFloat(q['最新价']) || parseFloat(s['收盘价']||s['最新价']) || 0;
        var ma5 = parseFloat(s['MA5']) || 0;
        var distMA5 = ma5>0 ? ((price-ma5)/ma5*100) : null;
        var holding = (s['角色']||'').indexOf('持仓')>=0 || (s['操作']||'').indexOf('持有')>=0;

        var ok = chg > -3;
        html += '<div style="display:flex;align-items:center;gap:8px;padding:3px 0;font-size:12px">'+
          miniDot(ok)+
          '<span style="font-weight:'+(holding?'700':'400')+';color:'+(holding?'var(--warn)':'var(--text-secondary)')+'">'+s['标的']+'</span>'+
          '<span style="font-size:10px;color:var(--text-disabled)">'+code+'</span>'+
          '<span style="flex:1"></span>'+
          '<span style="font-weight:600;color:'+(chg>=0?'var(--up)':'var(--danger)')+'">'+(chg>=0?'+':'')+chg.toFixed(1)+'%</span>'+
          (distMA5!==null?'<span style="font-size:10px;color:var(--text-disabled)">MA5 '+(distMA5>=0?'+':'')+distMA5.toFixed(1)+'%</span>':'')+
          (s['止损']?'<span style="font-size:10px;color:var(--danger)">止损'+s['止损']+'</span>':'')+
          '</div>';
      });
      html += '</div>';
    }

    // ===== AI 盯盘信号 =====
    this._loadAI();
    if (this._aiInsights) {
      var today = new Date().toISOString().slice(0,10);
      var todayData = this._aiInsights[today] || {};
      var aiNodes = Object.keys(todayData).sort().reverse();
      if (aiNodes.length > 0) {
        var latestAi = todayData[aiNodes[0]];
        var aiText = (latestAi.text||'').substring(0, 120);
        var aiSignals = latestAi.signals || [];
        var buyCount = aiSignals.filter(function(s){return s.type==='BUY'&&s.status==='✅';}).length;
        var watchCount = aiSignals.filter(function(s){return s.type==='WATCH';}).length;
        html += '<div style="padding:6px 8px;margin-top:4px;background:rgba(59,130,246,0.06);border-radius:6px;border-left:3px solid var(--info)">'+
          '<div style="display:flex;align-items:center;gap:6px;margin-bottom:2px">'+
            '<span style="font-size:11px;font-weight:700;color:var(--info)">AI 盯盘</span>'+
            '<span style="font-size:10px;color:var(--text-disabled)">'+aiNodes[0]+'</span>'+
            (buyCount>0?'<span style="font-size:10px;color:var(--up)">'+buyCount+' BUY</span>':'')+
            (watchCount>0?'<span style="font-size:10px;color:var(--info)">'+watchCount+' WATCH</span>':'')+
          '</div>'+
          '<div style="font-size:11px;color:var(--text-secondary);line-height:1.5">'+aiText+'...</div>'+
          '</div>';
      }
    }

    // ===== 底部环境条 =====
    html += '<div style="font-size:10px;color:var(--text-disabled);padding:4px 0;text-align:center;border-top:1px solid var(--border-light);margin-top:4px">'+
      (inW1?'W1 '+(min<45?'前半段 9:30-9:45':'后半段 9:45-10:00'):'非W1时段')+
      ' | 情绪区间 '+zoneName(qx)+
      ' | 赚钱效应 '+(S['赚钱效应']||'—')+
      ' | 上证 '+(li['上证指数涨幅']||'—')+
      '</div>';

    body.innerHTML = html;
    this.updateTimestamp();

    function fmtPct(v) { var s=String(v||''); return s?parseFloat(s.replace('%','')).toFixed(0)+'%':'—'; }
    function zoneName(v) { return v<20?'冰点':v<40?'低迷':v<60?'主升':v<80?'强势':'高潮'; }
  }
}

WidgetRegistry.register('W08', W1CheckWidget);
