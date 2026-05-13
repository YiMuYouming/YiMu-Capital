// widgets/sector-heat.js — W10 板块热力 v3.3 (三行结构·角色分层)
'use strict';

class SectorHeatWidget extends YiMuWidget {
  constructor(config) {
    super(config);
    this._insights = null;
  }

  render(data) {
    // 异步加载 LLM 研判
    if (!this._insights) this._loadInsights();
    var body = this.getBody();
    if (!body) return;
    var sectors = (data && data.sectors) || [];
    var liveQ = (data && data.live_quotes) || {};
    var lbPool = (data && data.lianban_pool) || [];
    var trPool = (data && data.trend_pool) || [];
    var liveSectors = (data && data.live_sectors) || {};

    if (!sectors.length) {
      body.innerHTML = '<div style="padding:var(--sp-lg);text-align:center;color:var(--text-disabled)">板块数据未录入</div>';
      this.updateTimestamp();
      return;
    }

    var ALIAS = {
      'CPO':'CPO/光通信','光通信':'CPO/光通信','光纤/光通信':'CPO/光通信','CPO/光通信':'CPO/光通信',
      '半导体':'半导体','半导体产业链':'半导体','半导体/存储':'半导体','半导体材料':'半导体',
      '电力':'电力','电力/算电':'电力','电力改革':'电力','电力/储能':'电力',
      '数据中心':'数据中心','数据中心供电':'数据中心',
      'PCB':'PCB','PCB链':'PCB',
      '机器人':'机器人','机器人🆕':'机器人',
      '光伏':'光伏','光伏🆕':'光伏',
      '算力租赁':'算力租赁','算力':'算力租赁',
      '存储芯片':'存储芯片',
    };
    function norm(n) {
      // 去掉emoji后缀再匹配
      var clean = String(n||'').replace(/🆕|⬇️|🔄|✅|❌/g, '').trim();
      return ALIAS[clean] || ALIAS[n] || n;
    }
    function matchLive(name) {
      var n = norm(name);
      if (liveSectors[n]) return liveSectors[n];
      for (var k in liveSectors) { if (n.indexOf(k)>=0||k.indexOf(n)>=0) return liveSectors[k]; }
      return null;
    }

    // 获取板块关联的所有标的，按角色分组
    function sectorRoles(sectorName) {
      var result = {龙头:[], 中军:[], 跟风:[], 高度板:[], 趋势:[], 锚定:[]};
      lbPool.concat(trPool).forEach(function(s) {
        if (norm(s['板块']||'') !== norm(sectorName)) return;
        var role = s['角色']||'';
        var code = s['代码']||'';
        var q = liveQ[code]||{};
        var chg = parseFloat(q['涨幅']||s['涨幅']||0)||0;
        var cls = chg>0?'up':chg<0?'down':'';
        var tag = '<span style="white-space:nowrap">'+
          '<span style="color:var(--text-primary)">'+s['标的']+'</span> '+
          '<span class="'+cls+'" style="font-family:var(--font-mono)">'+(chg>=0?'+':'')+chg.toFixed(1)+'%</span></span>';

        if (role.indexOf('龙头')>=0) result['龙头'].push(tag);
        else if (role.indexOf('中军')>=0) result['中军'].push(tag);
        else if (role.indexOf('跟风')>=0) result['跟风'].push(tag);
        else if (role.indexOf('高度板')>=0) result['高度板'].push(tag);
        else if (role.indexOf('趋势')>=0) result['趋势'].push(tag);
        else result['跟风'].push(tag); // 兜底
      });
      return result;
    }

    // === 分组 ===
    var groups = [
      {key:'主线', label:'主线', icon:'🔴', color:'var(--up)', sectors:[]},
      {key:'趋势主线', label:'趋势主线', icon:'🔵', color:'var(--info)', sectors:[]},
      {key:'强支线', label:'强支线', icon:'🟠', color:'var(--warn)', sectors:[]},
      {key:'观察', label:'观察/候选', icon:'⚪', color:'var(--text-secondary)', sectors:[]},
      {key:'退潮', label:'退潮', icon:'⚫', color:'var(--text-disabled)', sectors:[]},
    ];

    sectors.forEach(function(sec) {
      var type = sec['类型']||'';
      var placed = false;
      if (type.indexOf('退潮')>=0) { groups[4].sectors.push(sec); placed=true; }
      else if (type.indexOf('主线')>=0 && type.indexOf('趋势')>=0) { groups[1].sectors.push(sec); placed=true; }
      else if (type.indexOf('主线')>=0) { groups[0].sectors.push(sec); placed=true; }
      else if (type.indexOf('支线')>=0) { groups[2].sectors.push(sec); placed=true; }
      else { groups[3].sectors.push(sec); }
    });

    var html = '';

    groups.forEach(function(g) {
      if (!g.sectors.length) return;

      html += '<div style="margin-bottom:var(--sp-sm)">'+
        '<div style="display:flex;align-items:center;gap:6px;margin-bottom:1px;padding:2px var(--sp-sm)">'+
          '<span style="font-size:15px">'+g.icon+'</span>'+
          '<span style="font-weight:700;font-size:13px;color:'+g.color+'">'+g.label+'</span>'+
          '<span style="font-size:var(--fs-label);color:var(--text-disabled)">'+g.sectors.length+'</span>'+
        '</div>';

      g.sectors.forEach(function(sec) {
        var name = sec['板块']||'—';
        var live = matchLive(name) || {};
        var chgNum = parseFloat(live['涨跌幅']);
        var chgStr = !isNaN(chgNum) ? (chgNum>=0?'+':'')+chgNum.toFixed(2)+'%' : '—';
        var chgCls = chgNum>=0?'up':'down';
        var leader = sec['龙头']||'';
        var roles = sectorRoles(name);

        // 卡片开始
        html += '<div style="margin:3px 0 3px 8px;padding:4px var(--sp-sm);background:var(--bg-base);border:1px solid var(--border-light);border-radius:var(--radius-md);border-left:3px solid '+g.color+'">';

        // === 行1：板块数据（TDX实时）===
        var amtTrend = live['成交额趋势']||'';
        var amtCls = amtTrend==='放量'?'up':amtTrend==='缩量'?'down':'';
        var distMA5 = live['距MA5'];
        var distStr = (distMA5 != null) ? ((distMA5>=0?'+':'')+distMA5.toFixed(1)+'%') : '';
        var distCls = (distMA5 != null) ? (distMA5>=0?'up':'down') : '';
        html += '<div style="font-size:13px;padding-bottom:3px">'+
          '<span style="font-weight:700;color:var(--text-primary)">'+name+'</span>'+
          '<span class="'+chgCls+'" style="font-family:var(--font-mono);font-weight:700;font-size:14px;margin-left:var(--sp-sm)">'+chgStr+'</span>'+
          (distStr ? '<span class="'+distCls+'" style="font-family:var(--font-mono);font-size:11px;margin-left:4px">距MA5 '+distStr+'</span>' : '')+
          (amtTrend ? '<span class="'+amtCls+'" style="font-size:11px;margin-left:4px">'+amtTrend+'</span>' : '')+
          '<span style="font-size:9px;color:var(--text-disabled);margin-left:2px">⚡</span>'+
          '</div>';

        // === 行2：个股（带角色标签）===
        var roleOrder = [
          {key:'高度板', label:'高', color:'var(--warn)'},
          {key:'龙头', label:'龙头', color:'var(--up)'},
          {key:'中军', label:'中军', color:'var(--info)'},
          {key:'趋势', label:'趋势', color:'var(--down)'},
          {key:'跟风', label:'跟风', color:'var(--text-secondary)'},
        ];
        var stockRows = [];
        roleOrder.forEach(function(r) {
          if (roles[r.key].length) {
            stockRows.push('<span style="font-size:9px;padding:1px 4px;border-radius:2px;background:'+r.color+'18;color:'+r.color+';margin-right:4px;white-space:nowrap">'+r.label+'</span>'+
              roles[r.key].join(' '));
          }
        });
        if (stockRows.length) {
          html += '<div style="font-size:var(--fs-body);padding:2px 0">'+stockRows.join('  ')+'</div>';
        } else {
          html += '<div style="font-size:var(--fs-body);color:var(--text-disabled);padding:2px 0">自选池无此板块标的</div>';
        }

        // === 行3：LLM（从 llm_insights 读取最新研判）===
        var llmText = '';
        if (this._insights) {
          // 取今天最新一条研判中匹配此板块的内容
          var today = new Date().toISOString().slice(0,10);
          var todayData = this._insights[today] || {};
          var keys = Object.keys(todayData).sort().reverse();
          for (var ki = 0; ki < keys.length; ki++) {
            var text = todayData[keys[ki]].text || '';
            if (text.indexOf(name) >= 0 || text.indexOf(norm(name)) >= 0) {
              llmText = text; break;
            }
          }
          // 无板块匹配→取最新一条全文
          if (!llmText && keys.length > 0) {
            llmText = todayData[keys[0]].text || '';
          }
        }
        html += '<div style="font-size:11px;color:var(--text-secondary)">';
        if (llmText) {
          var short = llmText.length > 120 ? llmText.substring(0, 120) + '...' : llmText;
          html += '<span style="border-left:2px solid var(--info);padding-left:6px">🤖 '+short+'</span>';
        } else {
          html += '<span style="border:1px dashed var(--border-light);padding:1px 6px;border-radius:3px;color:var(--text-disabled)">🤖 待分析</span>';
        }
        html += '</div>';

        html += '</div>'; // 卡片结束
      });

      html += '</div>';
    });

    body.innerHTML = html;
    this.updateTimestamp();
  }

  _loadInsights() {
    var self = this;
    fetch('data/llm_insights.json?t=' + Date.now())
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(data) {
        if (data) { self._insights = data; self._renderBody(); }
      })
      .catch(function() {});
  }
}

WidgetRegistry.register('W10', SectorHeatWidget);
