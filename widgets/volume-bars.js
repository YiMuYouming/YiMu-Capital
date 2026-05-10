// widgets/volume-bars.js — W11 上证15min量价
// 设计偏好：量大柱向下、量小柱向上（弈沐哥个人偏好，非A股常规）
'use strict';

class VolumeBarsWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;
    var bars = (data && data['上证15min']) || [];

    if (!bars.length) {
      body.innerHTML = '<div style="padding:var(--sp-lg);text-align:center;color:var(--text-disabled)">量价数据未录入</div>';
      return;
    }

    var maxVol = Math.max.apply(null, bars.map(function(b) { return b.vol || 0; }));
    var maxHeight = 100;

    var html = '<div style="display:flex;align-items:flex-end;gap:2px;height:120px;margin-bottom:var(--sp-sm)">';
    bars.forEach(function(b) {
      var h = maxVol > 0 ? Math.max(4, (b.vol / maxVol) * maxHeight) : 4;
      var dir = (b.chg || 0) >= 0 ? 'up' : 'down';
      var ratio = b.volRatio || 1;
      var opacity = ratio > 2 ? 1 : ratio > 1 ? 0.7 : 0.4;

      html += '<div class="vol-bar ' + dir + '" style="height:'+h+'px;opacity:'+opacity+'" title="'+b.t+' 涨跌:'+(b.chg||0)+'% 量比:'+ratio.toFixed(1)+'x"></div>';
    });
    html += '</div>';

    // Time labels
    html += '<div style="display:flex;justify-content:space-between;font-size:var(--fs-label);color:var(--text-disabled)">';
    var labels = ['9:30','10:00','10:30','11:00','13:00','13:30','14:00','14:30'];
    labels.forEach(function(l) {
      html += '<span>'+l+'</span>';
    });
    html += '</div>';

    // Legend
    html += '<div style="margin-top:var(--sp-xs);font-size:var(--fs-label);color:var(--text-disabled);text-align:center">' +
      '↑缩量(量比<1) · ↓放量(量比>1) · 红涨绿跌 · 柱向=弈沐哥偏好</div>';

    body.innerHTML = html;
    this.updateTimestamp();
  }
}

WidgetRegistry.register('W11', VolumeBarsWidget);
