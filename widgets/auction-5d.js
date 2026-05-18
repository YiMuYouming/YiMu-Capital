// widgets/auction-5d.js — W06 竞价5维面板 v3.0 (竞价快照 + SSOT情绪指标)
'use strict';

class Auction5DWidget extends YiMuWidget {
  constructor(config) {
    super(config);
    this._snapshot = null;
  }

  render(data) {
    var body = this.getBody();
    if (!body) return;

    var snap = this._snapshot;
    var sent = (snap && snap['情绪指标']) || {};  // 9:25 实时 THS 数据
    var sty = (data && data.style) || {};
    var mkt = (data && data.market) || {};
    var sen = (data && data.sentiment) || {};     // 复盘笔记 baseline 兜底

    // 首次加载：异步获取竞价快照
    if (!snap) {
      this._loadSnapshot(body);
      this._renderPlaceholder(body, sent, sty, mkt, sen);
      return;
    }

    // 合并渲染
    this._renderFull(body, snap, sent, sty, mkt, sen);
  }

  _loadSnapshot(body) {
    var self = this;
    fetch('data/auction_snapshot.json?t=' + Date.now())
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(snap) {
        if (snap && snap['指数竞价']) {
          self._snapshot = snap;
          self._renderBody();
        }
      })
      .catch(function() {});
  }

  _renderPlaceholder(body, sent, sty, mkt, sen) {
    var html = '<div style="font-size:var(--fs-label);color:var(--text-disabled);text-align:center;padding:var(--sp-md)">加载竞价数据...</div>';
    html += this._renderSentiment(sent, sty, mkt, sen);
    body.innerHTML = html;
    this.updateTimestamp();
  }

  _renderFull(body, snap, sent, sty, mkt, sen) {
    var lights = snap['信号灯'] || {};
    var overall = lights['综合'] || {};
    var lightColors = {green:'var(--info)', orange:'var(--warn)', red:'var(--danger)'};
    var lightDots = {green:'🟢', orange:'🟠', red:'🔴'};
    var lightBg = {green:'rgba(59,130,246,0.06)', orange:'rgba(255,149,0,0.05)', red:'rgba(255,59,48,0.05)'};

    var html = '';

    // === 顶部综合条 ===
    var oc = overall['灯'] || 'orange';
    html += '<div style="display:flex;align-items:center;gap:var(--sp-sm);padding:var(--sp-xs) var(--sp-md);margin-bottom:var(--sp-sm);background:'+(lightBg[oc]||lightBg.orange)+';border-radius:var(--radius-md);border-left:3px solid '+(lightColors[oc]||lightColors.orange)+'">' +
      '<span style="font-size:16px">'+(lightDots[oc]||'🟠')+'</span>' +
      '<span style="font-weight:700;font-size:var(--fs-subtitle);color:'+(lightColors[oc]||lightColors.orange)+'">'+(overall['label']||'—')+'</span>' +
      '<span style="font-size:var(--fs-body);color:var(--text-secondary)">强势'+(snap['竞价强势家数']||0)+'只</span>' +
      '<span style="font-size:var(--fs-body);color:var(--text-secondary)">涨'+(snap['涨跌家数']['上涨']||0)+'/跌'+(snap['涨跌家数']['下跌']||0)+'</span>' +
      '<span style="margin-left:auto;font-size:var(--fs-label);color:var(--text-disabled)">'+(snap['time']||'')+'</span>' +
      '</div>';

    // === 上排：指数 | 情绪(宽,两列内排) ===
    html += '<div style="display:grid;grid-template-columns:1fr 1.8fr;gap:var(--sp-sm);margin-bottom:var(--sp-sm)">';

    html += this._card('指数竞价', function() {
      var h = '';
      (snap['指数竞价']||[]).forEach(function(idx) {
        var chg = idx['竞价涨幅'] || 0;
        var cls = chg >= 0 ? 'up' : 'down';
        var sign = chg >= 0 ? '+' : '';
        h += '<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:var(--fs-body)">' +
          '<span style="font-weight:600">' + idx['名称'] + '</span>' +
          '<span class="' + cls + '" style="font-family:var(--font-mono);font-weight:600">' + sign + chg.toFixed(2) + '%</span></div>';
      });
      var ud = snap['涨跌家数'] || {};
      h += '<div style="margin-top:var(--sp-xs);padding-top:var(--sp-xs);border-top:1px solid var(--border-light);font-size:var(--fs-body)">' +
        '<span style="color:var(--text-disabled)">涨跌比 </span>' +
        '<span style="font-weight:600;color:var(--up)">'+(ud['上涨']||0)+'</span>/' +
        '<span style="font-weight:600;color:var(--down)">'+(ud['下跌']||0)+'</span>' +
        '<span style="color:var(--text-disabled);margin-left:var(--sp-xs)">('+(ud['涨跌比']||'—')+')</span></div>';
      return h;
    }());

    html += this._renderSentiment(sent, sty, mkt, sen);
    html += '</div>';

    // === 下排：高标 | 自选 ===
    html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--sp-sm);margin-bottom:var(--sp-sm)">';

    html += this._card('高标竞价', function() {
      var h = '';
      var highs = snap['高标竞价'] || [];
      highs.slice(0, 8).forEach(function(hi) {
        var chg = hi['竞价涨幅'] || 0;
        var cls = chg >= 5 ? 'up' : chg >= 0 ? '' : 'down';
        var sign = chg >= 0 ? '+' : '';
        var anomaly = hi['异动'] || '';
        var aCls = anomaly.indexOf('砸盘')>=0 ? 'down' : anomaly.indexOf('抢筹')>=0 ? 'up' : '';
        h += '<div style="display:flex;align-items:center;gap:2px;padding:1px 0;font-size:var(--fs-body)">' +
          '<span style="font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0">'+hi['名称']+'</span>' +
          '<span style="font-size:9px;color:var(--text-disabled);flex-shrink:0">'+hi['板数']+'板</span>' +
          '<span class="'+cls+'" style="font-family:var(--font-mono);font-weight:600;margin-left:auto;flex-shrink:0;font-size:var(--fs-body)">'+sign+chg.toFixed(1)+'%</span>' +
          (anomaly?'<span class="'+aCls+'" style="font-size:8px;flex-shrink:0">'+anomaly.substring(0,4)+'</span>':'') +
          '</div>';
      });
      return h;
    }());

    html += this._card('自选池', function() {
      var h = '';
      var pools = snap['自选池竞价'] || [];
		pools.forEach(function(s) {
		  var chg = s['竞价涨幅'];
		  var hasData = chg != null && chg !== '';
		  var cls = hasData ? (chg >= 3 ? 'up' : chg <= -3 ? 'down' : '') : '';
		  var sign = hasData && chg >= 0 ? '+' : '';
		  var display = hasData ? sign + chg.toFixed(2) + '%' : '—';
		  var src = s['来源'] || '';
		  var srcCls = src=='连板'?'up':src=='趋势'?'down':'info';
		  h += '<div style="display:flex;align-items:center;gap:2px;padding:1px 0;font-size:var(--fs-body)">' +
		    '<span style="font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0">'+s['名称']+'</span>' +
		    (src?'<span style="font-size:8px;padding:0 3px;border-radius:2px;background:var(--'+srcCls+');color:var(--text-inverse);flex-shrink:0">'+src+'</span>':'') +
		    '<span class="'+cls+'" style="font-family:var(--font-mono);font-weight:600;margin-left:auto;flex-shrink:0;font-size:var(--fs-body)">'+display+'</span>' +
		    '</div>';
		});
      return h;
    }());

    html += '</div>';

    html += '</div>'; // end grid

    // === 信号灯 + 板块竞价 ===
    html += '<div style="display:flex;gap:var(--sp-sm);align-items:center;flex-wrap:wrap;font-size:var(--fs-body)">';
    ['涨跌','强势','高标'].forEach(function(k) {
      var l = lights[k] || {};
      var c = l['灯'] || 'orange';
      html += '<span style="padding:1px 6px;border-radius:3px;background:'+(lightBg[c]||'')+';color:'+(lightColors[c]||'')+'">'+(lightDots[c]||'')+' '+k+':'+(l['label']||'—')+'</span>';
    });
    var sectors = snap['板块竞价'] || [];
    sectors.forEach(function(sec) {
      var chg = sec['竞价涨幅'] || 0;
      var cls = chg >= 0 ? 'up' : 'down';
      var sign = chg >= 0 ? '+' : '';
      html += '<span style="font-size:var(--fs-body);padding:0 6px;background:var(--bg-hover);border-radius:3px">' +
        '<span style="font-weight:600">'+sec['板块']+'</span> ' +
        '<span class="'+cls+'" style="font-family:var(--font-mono)">'+sign+chg.toFixed(2)+'%</span></span>';
    });
    html += '</div>';

    body.innerHTML = html;
    this.updateTimestamp();
  }

  // === 情绪指标卡片 (SSOT from 复盘笔记) ===
  _renderSentiment(sent, sty, mkt, sen) {
    function kv(label, value, cls) {
      if (value == null || value === '') return '';
      return '<div style="display:flex;justify-content:space-between;gap:var(--sp-xs)">' +
        '<span style="color:var(--text-secondary);white-space:nowrap">'+label+'</span>' +
        '<span class="'+(cls||'')+'" style="font-family:var(--font-mono);font-weight:600;text-align:right">'+value+'</span></div>';
    }
    function pctV(label, val) {
      if (val == null) return '';
      var num = parseFloat(String(val).replace('%','').replace('（',''));
      var cls = isNaN(num) ? '' : num >= 2 ? 'up' : num >= 0 ? '' : 'down';
      return kv(label, val+'%', cls);
    }
    function cleanBoard(s) {
      if (!s) return '';
      var m = String(s).match(/^(\d+)/);
      return m ? m[1]+'板' : s;
    }

    var h = '<div style="background:var(--bg-base);border-radius:var(--radius-md);padding:var(--sp-xs) var(--sp-sm)">' +
      '<div style="font-size:var(--fs-label);font-weight:600;color:var(--text-primary);margin-bottom:var(--sp-xs);padding-bottom:2px;border-bottom:1px solid var(--border-light)">情绪指标 9:25</div>';

	    // fallback: 快照情绪为空时用 baseline sentiment（复盘笔记 frontmatter）
	    sen = sen || {};
	    if (sent['情绪值'] == null && sen['情绪值'] != null) sent['情绪值'] = sen['情绪值'];
	    if (!sent['赚钱效应'] && sen['赚钱效应']) sent['赚钱效应'] = sen['赚钱效应'];
	    if (!sent['昨日涨停收益'] && !sent['涨停收益'] && sen['昨日涨停收益'] != null) sent['昨日涨停收益'] = sen['昨日涨停收益'];
	    if (!sent['昨日连板收益'] && !sent['连板收益'] && sen['连板收益'] != null) sent['连板收益'] = sen['连板收益'];
	    if (!sent['昨日炸板收益'] && sen['昨日炸板收益'] != null) sent['昨日炸板收益'] = sen['昨日炸板收益'];
	    if (sent['连板风险值'] == null && sen['连板风险值'] != null) sent['连板风险值'] = sen['连板风险值'];
	    if (!sent['最高板'] && sen['最高板']) sent['最高板'] = sen['最高板'];

    h += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:2px var(--sp-md);font-size:var(--fs-body)">';

    // 左列
    var left = '';

    var qx = sent['情绪值'];
    if (qx != null) {
      var qxNum = parseFloat(String(qx).replace('%',''));
      var qxLabel = qxNum < 20 ? '冰点' : qxNum < 40 ? '低迷' : qxNum < 60 ? '主升' : qxNum < 80 ? '强势' : '高潮';
      var qxCls = qxNum >= 40 && qxNum <= 60 ? 'up' : qxNum >= 20 && qxNum < 40 ? 'warn' : '';
      left += kv('情绪值', qx+'% '+qxLabel, qxCls);
    }
    if (sent['赚钱效应']) left += kv('赚钱效应', sent['赚钱效应']);
    left += pctV('涨停收益', sent['昨日涨停收益']||sent['涨停收益']);
    left += pctV('连板收益', sent['昨日连板收益']||sent['连板收益']);

    // 右列
    var right = '';
    right += pctV('炸板收益', sent['昨日炸板收益']);

    var risk = sent['连板风险值'];
    if (risk != null) {
      var riskNum = parseFloat(String(risk));
      var riskCls = !isNaN(riskNum) ? (riskNum < 0.5 ? 'up' : riskNum < 1 ? '' : 'down') : '';
      right += kv('连板风险值', risk, riskCls);
    }

    var maxB = sent['最高板'];
    if (maxB) right += kv('最高板', cleanBoard(maxB));

    h += '<div>' + left + '</div>';
    h += '<div>' + right + '</div>';
    h += '</div>';
    h += '</div>';
    return h;
  }

  _card(title, body) {
    return '<div style="background:var(--bg-base);border-radius:var(--radius-md);padding:var(--sp-xs) var(--sp-sm)">' +
      '<div style="font-size:var(--fs-label);font-weight:600;color:var(--text-primary);margin-bottom:var(--sp-xs);padding-bottom:2px;border-bottom:1px solid var(--border-light)">'+title+'</div>' +
      body + '</div>';
  }
}

WidgetRegistry.register('W06', Auction5DWidget);
