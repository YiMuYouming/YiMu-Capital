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
    var iw = (data && data.iwencai) || {};  // T2 iwencai 2min实时，优先
    var li = (data && data.live_index) || {};
    var liveQ = (data && data.live_quotes) || {};
    var lbPoolAll = (data && data.lianban_pool) || [];
    var trPoolAll = (data && data.trend_pool) || [];
    var sectors = (data && data.sectors) || [];

    var lbPool = lbPoolAll.filter(function(s){ var w=s['窗口']||''; return !w||w==='W1'; });
    var trPool = trPoolAll.filter(function(s){ var w=s['窗口']||''; return !w||w==='W1'; });

    function todayRole(s) {
      if (!s) return '';
      return String(s['今日定位'] || (legacyOnly(s) ? '观察标' : s['角色']) || '');
    }
    function todayTrigger(s) {
      if (!s) return '';
      return String(s['触发/失效'] || s['触发失效'] || s['操作'] || '');
    }
    function legacyOnly(s) {
      if (!s) return false;
      var hasLegacy = !!(s['角色'] || s['操作']);
      var hasTodayRole = !!s['今日定位'];
      var hasTrigger = !!(s['触发/失效'] || s['触发失效']);
      return !!s['derived_from_legacy_fields'] || (hasLegacy && (!hasTodayRole || !hasTrigger));
    }
    function observationOnly(s) {
      var trigger = todayTrigger(s);
      return legacyOnly(s) || !String(s && (s['触发/失效'] || s['触发失效']) || '').trim() ||
        trigger.indexOf('只观察') >= 0 || trigger.indexOf('不授权') >= 0 ||
        trigger.indexOf('只盯') >= 0 || trigger.indexOf('不买') >= 0;
    }

    var initBase = DataStore.getInitialBase();
    var closeS = (initBase && initBase.sentiment) || {};

    var now = new Date();
    var hour = now.getHours(), min = now.getMinutes();
    var inW1 = hour === 9 && min >= 30 && min <= 59 || hour === 10 && min === 0;
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

    // ===== 数值：T2 iwencai 实时优先，baseline 回退 =====
    var qx = parseFloat(S['情绪值']) || 0;
    var yestQx = parseFloat(closeS['情绪值']) || 0;
    var ztProfit = parseFloat(String(iw['昨日涨停收益'] != null ? iw['昨日涨停收益'] : S['昨日涨停收益']||'0').replace('%','').replace('+','')) || 0;
    var fbRate = 0;
    if (iw['炸板率'] != null) {
      fbRate = parseFloat(iw['炸板率']) * 100;  // iwencai存小数
    } else if (M['炸板率'] != null) {
      fbRate = parseFloat(String(M['炸板率']).replace('%','')) || 0;
    }
    var ztCount = parseInt(iw['涨停家数'] != null ? iw['涨停家数'] : M['涨停家数']) || 0;
    var topBoard = iw['最高板'] != null ? iw['最高板'] : parseInt(String(S['最高板']||'').replace('板','')) || 0;
    var topName = iw['最高板'] ? iw['最高板']+'板' : String(S['最高板']||'');
    // 晋级率：iwencai实时优先（iwencai存小数0.38=38%，需×100对齐baseline的百分数格式）
    function _pct(iwVal, sVal) {
      if (iwVal != null) return Math.round(parseFloat(iwVal) * 100);
      if (sVal != null) return parseFloat(String(sVal).replace('%',''));
      return null;
    }
    var jjl1 = _pct(iw['一进二晋级率'], S['一进二晋级率']);
    var jjl2 = _pct(iw['二进三晋级率'], S['二进三晋级率']);
    var jjl3 = _pct(iw['三进四晋级率'], S['三进四晋级率']);
    // 赚钱效应
    var profitEffect = iw['赚钱效应'] || S['赚钱效应'] || '—';

    // ===== rule_state 实时规则引擎（Gate 1A 唯一权威结论）=====
    var RS = (data && data.rule_state) || null;
    var rsW1 = (RS && RS.windows && RS.windows.w1) || {};
    var rsBlocks = (RS && RS.blocks) || [];
    var rsMissing = !RS;

    function ruleLabel(code) {
      var labels = {
        LOSS_STREAK: '连亏保护',
        DOUBLE_ICE: '连续冰点',
        LIANBAN_SIDE_CLOSED: '连板侧关闭',
        'WIN-ICE-W1-001': '冰点W1关闭',
        'WIN-ICE-POLAR-MAINLINE-001': '极化主线人工复核',
        W1_EMOTION: '情绪不足',
        W1_LIMIT_UP_PROFIT: '涨停收益不足',
        W1_PROMOTION: '晋级率不足',
        W2_ICE: '冰点关闭',
        W2_ICE_RISK: '冰点风险'
      };
      return labels[code] || code;
    }

    function scopeLabel(scope) {
      return scope === 'all' ? '全局' : scope === 'w1' ? 'W1' : scope === 'w2' ? 'W2' : scope === 'lianban' ? '连板' : scope || '规则';
    }

    // Phase 4: 健康门禁 — trade_entry_allowed=false 时整版关闭
    if (data && data.trade_entry_allowed === false) {
      var reason = data.trade_entry_reason || '系统健康检查未通过';
      body.innerHTML = '<div class="ui-degraded"><strong>交易入口已关闭</strong><span>' + reason + '</span></div>';
      this.updateTimestamp();
      return;
    }

    if (rsMissing) {
      body.innerHTML = '<div class="ui-degraded"><strong>规则状态不可用</strong><span>后端 rule_state 未生成，W1 结论暂停显示。</span></div>';
      this.updateTimestamp();
      return;
    }

    var w1BuyAllowed = rsW1.buy_allowed;
    var w1ManualReview = !!rsW1.manual_review_allowed;
    var w1Blocks = rsW1.blocks || [];

    // ===== 环境阻断（展示 rule_state blocks + 本地详情补充，结论一律服从 buy_allowed）=====
    var blocks = [];
    rsBlocks.forEach(function(b) {
      if (b.scope !== 'w1' && b.scope !== 'all') return;
      blocks.push({label: ruleLabel(b.code), detail: b.message, scope: scopeLabel(b.scope)});
    });

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
    var w1CandidateCount = lbPool.length + trPool.length;
    var w1RuleState = w1BuyAllowed ? (rsW1.in_session ? '允许' : '待开') : (w1ManualReview ? '黄灯' : '关闭');
    var w1WindowLabel = rsW1.in_session ? '09:30-10:00' : '非W1时段';
    var w1CommandClass = w1BuyAllowed ? (rsW1.in_session ? 'is-ready' : 'is-watch') : (w1ManualReview ? 'is-watch' : 'is-blocked');

    function windowCommandHtml(title, cls, state, windowLabel, candidateCount, blockCount, detail) {
      return '<div class="window-command ' + cls + '">' +
        '<div class="window-command-head"><span><i>' + title + '</i>窗口验收</span><b>' + state + '</b></div>' +
        '<div class="window-command-grid">' +
          '<div><span>当前窗口</span><b>' + windowLabel + '</b><em>' + detail + '</em></div>' +
          '<div><span>规则状态</span><b>' + state + '</b><em>阻断 ' + blockCount + ' / rule_state</em></div>' +
          '<div><span>候选</span><b>' + candidateCount + '</b><em>连板 ' + lbPool.length + ' / 趋势 ' + trPool.length + '</em></div>' +
        '</div>' +
      '</div>';
    }

    // rule_state 结论：W1 不允许买入时展示阻断原因
    if (!w1BuyAllowed) {
      var blockedDetail = w1ManualReview ? '极化主线需人工复核' : '早盘追涨入口暂不可用';
      html += windowCommandHtml('W1验收', w1CommandClass, w1RuleState, w1WindowLabel, w1CandidateCount, blocks.length, blockedDetail);
      html += '<div style="height:100%;display:flex;flex-direction:column;justify-content:center;padding:14px 18px">'+
        '<div style="display:flex;align-items:center;gap:12px;justify-content:center;margin-bottom:12px">'+
          '<div style="width:42px;height:42px;border-radius:50%;background:' + (w1ManualReview ? 'var(--warn)' : 'var(--danger)') + ';box-shadow:0 8px 22px ' + (w1ManualReview ? 'rgba(245,158,11,0.22)' : 'rgba(220,38,38,0.22)') + ';line-height:42px;font-size:22px;color:var(--text-inverse);text-align:center">' + (w1ManualReview ? '!' : '✕') + '</div>'+
          '<div style="text-align:left">'+
            '<div style="font-size:15px;font-weight:800;color:' + (w1ManualReview ? 'var(--warn)' : 'var(--danger)') + '">' + (w1ManualReview ? 'W1 黄灯 · 极化主线需人工复核' : ('W1 关闭' + (rsW1.in_session ? '' : ' · 非W1时段'))) + '</div>'+
            '<div style="font-size:11px;color:var(--text-secondary);margin-top:2px">' + (w1ManualReview ? 'manual_review，不等于买入授权' : '早盘追涨入口暂不可用') + '</div>'+
          '</div>'+
        '</div>'+
        '<div style="max-width:280px;margin:0 auto;display:flex;flex-direction:column;gap:5px">';
      blocks.forEach(function(b){
        html += '<div style="display:flex;align-items:flex-start;gap:8px;text-align:left;padding:6px 8px;border-radius:6px;background:var(--bg-base);border:1px solid var(--border-light)">'+
          '<span style="flex:0 0 auto;font-size:10px;font-weight:700;color:var(--danger);background:rgba(220,38,38,0.08);padding:1px 5px;border-radius:999px">'+b.scope+'</span>'+
          '<div style="min-width:0">'+
            '<div style="font-size:12px;font-weight:700;color:var(--text-primary)">'+b.label+'</div>'+
            '<div style="font-size:11px;color:var(--text-secondary);line-height:1.35">'+b.detail+'</div>'+
          '</div>'+
          '</div>';
      });
      if (!blocks.length) html += '<div style="font-size:12px;color:var(--text-secondary);text-align:center">后端规则引擎判定不可交易</div>';
      html += '</div></div>';
      body.innerHTML = html;
      this.updateTimestamp();
      return;
    }

    html += windowCommandHtml('W1验收', w1CommandClass, w1RuleState, w1WindowLabel, w1CandidateCount, 0, rsW1.in_session ? '早盘窗口可按三件套继续核对' : '未到窗口，仅看预案');

    // ===== 信号灯样式函数 =====
    function signalDot(ok, size) {
      var s = size || 48;
      var color, glow;
      if (ok === true)  { color = 'var(--down)'; glow = '0 0 20px rgba(5,150,105,0.4)'; }
      else if (ok === false) { color = 'var(--danger)'; glow = '0 0 20px rgba(220,38,38,0.35)'; }
      else              { color = 'var(--text-disabled)'; glow = 'none'; }
      return '<span style="display:inline-block;width:'+s+'px;height:'+s+'px;border-radius:50%;'+
        'background:'+color+';box-shadow:'+glow+';'+
        'line-height:'+s+'px;text-align:center;font-size:'+Math.floor(s*0.5)+'px;font-weight:700;color:#fff;'+
        'transition:all 0.5s">'+
        (ok===true?'✓':ok===false?'✕':'—')+'</span>';
    }

    function miniDot(ok) {
      var color = ok===true ? 'var(--down)' : ok===false ? 'var(--danger)' : 'var(--text-disabled)';
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
      signalDot(piece1_ok, 40)+
      '<div style="font-size:12px;font-weight:600;color:var(--text-primary);margin-top:5px">情绪≥60%</div>'+
      '<div style="font-size:15px;font-weight:700;color:'+(piece1_ok?'var(--up)':'var(--danger)')+'">'+qx+'%</div>'+
      '<div style="font-size:10px;color:var(--text-disabled)">昨日 '+yestQx+'%</div>'+
      '</div>';

    // 灯2: 涨停收益
    html += '<div style="text-align:center">'+
      signalDot(piece2_ok, 40)+
      '<div style="font-size:12px;font-weight:600;color:var(--text-primary);margin-top:5px">涨停收益>2%</div>'+
      '<div style="font-size:15px;font-weight:700;color:'+(piece2_ok?'var(--up)':'var(--danger)')+'">'+ztProfit.toFixed(1)+'%</div>'+
      '<div style="font-size:10px;color:var(--text-disabled)">炸板率 '+fbRate.toFixed(1)+'%</div>'+
      '</div>';

    // 灯3: 标的高开
    html += '<div style="text-align:center">'+
      signalDot(piece3_ok, 40)+
      '<div style="font-size:12px;font-weight:600;color:var(--text-primary);margin-top:5px">标的高开3-7%</div>'+
      '<div style="font-size:15px;font-weight:700;color:'+(piece3_ok?'var(--up)':'var(--danger)')+'">'+
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
      sigColor = 'var(--down)';
      sigGlow = '0 0 32px rgba(34,197,94,0.4)';
    } else if (piece1_ok && piece2_ok) {
      sigText = '等 待 信 号';
      sigBg = 'rgba(245,158,11,0.1)';
      sigColor = 'var(--warn)';
      sigGlow = '0 0 16px rgba(245,158,11,0.25)';
    } else {
      sigText = '降级 · 1进2或空仓';
      sigBg = 'rgba(239,68,68,0.08)';
      sigColor = 'var(--danger)';
      sigGlow = 'none';
    }

    html += '<div style="display:inline-block;padding:10px 36px;border-radius:8px;'+
      'background:'+sigBg+';box-shadow:'+sigGlow+';'+
      'border:2px solid '+sigColor+';margin:0 auto">'+
      '<div style="font-size:16px;font-weight:800;color:'+sigColor+';letter-spacing:3px">'+sigText+'</div>'+
      '<div style="font-size:11px;color:var(--text-secondary);margin-top:2px">'+
        '涨停'+ztCount+'家 | 最高'+topBoard+'板 | 晋级1进2:'+fmtPct(jjl1)+' 2进3:'+fmtPct(jjl2)+' 3进4:'+fmtPct(jjl3)+
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
      return {ok:count>=2, val:count+'只>3%'+(names.length>0?' ('+names.join(' ')+')':'')};
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
        var role = todayRole(s);
        var op = todayTrigger(s);
        var sector = s['板块'] || '';

        var isObservation = observationOnly(s);
        var isWatch = isObservation || role.indexOf('情绪标')>=0 || role.indexOf('龙头')>=0 || op.indexOf('只盯')>=0;
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
        if (isObservation) { stockStatus = '只观察'; stColor = 'var(--text-secondary)'; }
        else if (isSkip)       { stockStatus = '不碰'; stColor = 'var(--text-disabled)'; }
        else if (isWatch) { stockStatus = '只盯不买'; stColor = 'var(--text-secondary)'; }
        else if (stockOk) { stockStatus = '追涨'; stColor = 'var(--down)'; }
        else if (stockWait) { stockStatus = '待确认'; stColor = 'var(--warn)'; }
        else              { stockStatus = '条件不足'; stColor = 'var(--danger)'; }

        // 标的行
        html += '<div style="padding:8px 4px;border-bottom:1px solid var(--border-light);display:flex;align-items:center;gap:10px">';

        // 左侧：状态灯 + 名称
        html += '<div style="flex:0 0 auto;text-align:center;min-width:44px">'+
          signalDot((isWatch||isSkip)?null:stockOk?true:stockFail?false:null, 28)+
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
          '<div style="font-size:15px;font-weight:700;color:'+(chg>=0?'var(--up)':'var(--down)')+'">'+(chg>=0?'+':'')+chg.toFixed(1)+'%</div>'+
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
        var holding = !observationOnly(s) && (todayRole(s).indexOf('持仓')>=0 || todayTrigger(s).indexOf('持有')>=0);

        var ok = chg >= 0;
        var dotOk = ok;  // 绿涨红跌
        var nameColor = holding ? 'var(--warn)' : 'var(--text-secondary)';
        html += '<div style="display:flex;align-items:center;gap:8px;padding:3px 0;font-size:12px">'+
          miniDot(dotOk)+
          '<span style="font-weight:'+(holding?'700':'400')+';color:'+nameColor+'">'+s['标的']+'</span>'+
          '<span style="font-size:10px;color:var(--text-disabled)">'+code+'</span>'+
          '<span style="flex:1"></span>'+
          '<span style="font-weight:600;color:'+(chg>=0?'var(--up)':'var(--down)')+'">'+(chg>=0?'+':'')+chg.toFixed(1)+'%</span>'+
          (distMA5!==null?'<span style="font-size:10px;color:var(--text-disabled)">MA5 '+(distMA5>=0?'+':'')+distMA5.toFixed(1)+'%</span>':'<span style="font-size:10px;color:var(--text-disabled)">MA5 —</span>')+
          (s['止损']?'<span style="font-size:10px;color:var(--danger)">止损'+s['止损']+'</span>':'')+
          ((typeof window === 'undefined' || !window._healthCritical) && !observationOnly(s) && w1BuyAllowed && dotOk ? '<button onclick="event.stopPropagation();_prefillW15(\''+(s['标的']||'').replace(/'/g,"\\'")+'\',\''+code+'\',\'W1\',\'W1买入信号：涨幅'+chg.toFixed(1)+'%\')" style="margin-left:4px;background:var(--info);color:#fff;border:none;padding:1px 6px;border-radius:3px;cursor:pointer;font-size:10px;white-space:nowrap">录入</button>' : '')+
          '</div>';
      });
      html += '</div>';
    }

    // ===== 外部研判信号 =====
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
            '<span style="font-size:11px;font-weight:700;color:var(--info)">研判信号</span>'+
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
      ' | 赚钱效应 '+profitEffect+
      ' | 上证 '+(li['上证指数涨幅']||'—')+
      '</div>';

    body.innerHTML = html;
    this.updateTimestamp();

    function fmtPct(v) { var s=String(v||''); return s?parseFloat(s.replace('%','')).toFixed(0)+'%':'—'; }
    function zoneName(v) { return v<20?'冰点':v<40?'低迷':v<60?'主升':v<80?'强势':'高潮'; }
  }
}

WidgetRegistry.register('W08', W1CheckWidget);
