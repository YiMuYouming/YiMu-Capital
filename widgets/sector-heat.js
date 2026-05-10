// widgets/sector-heat.js — W10 板块热力图
'use strict';

class SectorHeatWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var sectors = (data && data.sectors) || [];
    var live = (data && data.live_sectors) || {};

    if (!sectors.length) {
      body.innerHTML = '<div style="padding:var(--sp-lg);text-align:center;color:var(--text-disabled)">板块数据未录入</div>';
      return;
    }

    var html = '';
    sectors.forEach(function(s) {
      var liveS = live[s['板块']] || {};
      var isDead = s['类型'] === '退潮';
      var opacity = isDead ? 'opacity:0.5' : '';

      html += '<div class="sector-card type-'+s['类型']+'" style="'+opacity+'">' +
        '<div style="flex:1;min-width:0">' +
        '<div style="font-weight:600;font-size:var(--fs-body)">'+s['板块']+' <span class="tag" style="font-size:var(--fs-label)">'+s['类型']+'</span></div>' +
        '<div style="font-size:var(--fs-label);color:var(--text-secondary)">'+s['梯队']+' | 龙头:'+s['龙头']+'</div>' +
        '</div>' +
        '<div style="display:flex;gap:var(--sp-md);text-align:right">' +
        '<div><div class="kpi-label">涨跌</div><div class="'+(parseFloat(liveS['涨跌幅']||0)>=0?'up':'down')+'" style="font-family:var(--font-mono);font-size:var(--fs-body)">'+(liveS['涨跌幅']!=null?liveS['涨跌幅']+'%':'—')+'</div></div>' +
        '<div><div class="kpi-label">主力</div><div style="font-family:var(--font-mono);font-size:var(--fs-body)">'+(liveS['主力净流入']||'—')+'</div></div>' +
        '<div><div class="kpi-label">5日线</div><div style="font-family:var(--font-mono);font-size:var(--fs-body)">'+(liveS['5日线']||'—')+'</div></div>' +
        '<div><div class="kpi-label">涨停</div><div style="font-family:var(--font-mono);font-size:var(--fs-body)">'+(liveS['今日涨停数']!=null?liveS['今日涨停数']:'—')+'</div></div>' +
        '</div>' +
        '</div>';
    });

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W10', SectorHeatWidget);
