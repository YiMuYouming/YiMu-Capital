// widgets/volume-bars.js — W11 15min量价图（上证/深证/创业）
'use strict';

class VolumeBarsWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;

    var SLOTS = ['09:45','10:00','10:15','10:30','10:45','11:00','11:15','11:30',
                 '13:00','13:15','13:30','13:45','14:00','14:15','14:30','14:45','15:00'];
    var N = SLOTS.length;

    var indexes = [
      {key:'上证15min', label:'上证', data:(data||{})['上证15min']||[]},
      {key:'深证15min', label:'深证', data:(data||{})['深证15min']||[]},
      {key:'创业15min', label:'创业', data:(data||{})['创业15min']||[]}
    ];

    var now = new Date();
    var nowMin = now.getHours()*60 + now.getMinutes();
    var currentIdx = -1;
    for (var i=0;i<N;i++){var p=SLOTS[i].split(':');if(nowMin>=parseInt(p[0])*60+parseInt(p[1]))currentIdx=i;else break;}

    var barW = Math.max(2.5, (100/N)-2.8);
    var BASELINE=32, MAX_BAR=26, ROW_H=62;
    var lunchX=(8/N)*100;

    var html = '';

    // tooltip
    html += '<div id="w11tip" style="display:none;position:fixed;background:rgba(0,0,0,0.85);color:#fff;padding:3px 9px;border-radius:5px;font-size:11px;white-space:nowrap;z-index:9999;pointer-events:none"></div>';

    indexes.forEach(function(idx, rowI) {
      var bars = idx.data;
      var barMap = {};
      bars.forEach(function(b){barMap[b.t]=b;});

      var maxR=1.3, minR=0.7;
      bars.forEach(function(b){if(b.volRatio>maxR)maxR=Math.min(3,b.volRatio);if(b.volRatio<minR)minR=Math.max(0.2,b.volRatio);});
      var range=Math.max(maxR-1,1-minR,0.15);

      // 行
      html += '<div style="display:flex;align-items:stretch;gap:var(--sp-xs);margin-bottom:'+(rowI<2?'4px':'0')+'">';
      // 标签
      html += '<div style="width:24px;font-size:10px;font-weight:700;color:var(--text-primary);writing-mode:vertical-lr;text-align:center;flex-shrink:0;letter-spacing:2px">'+idx.label+'</div>';
      // 图+标尺
      html += '<div style="flex:1;min-width:0">';
      html += '<div id="w11r'+rowI+'" style="position:relative;height:'+ROW_H+'px">';
      // 基线
      html += '<div style="position:absolute;left:0;right:0;top:'+BASELINE+'px;border-top:1px solid var(--border-light)"></div>';
      // 午休
      html += '<div style="position:absolute;left:'+lunchX+'%;top:0;bottom:0;width:1px;background:var(--border-light);opacity:0.3"></div>';

      SLOTS.forEach(function(slot, i){
        var b=barMap[slot];
        var isPast=b!=null;
        var isCurrent=i===currentIdx;
        var left=(i/N)*100;

        if(isPast&&b){
          var ratio=Math.max(0.2,Math.min(3,b.volRatio||1));
          var chg=b.chg||0;
          var dev=Math.abs(ratio-1);
          var barH=Math.max(3,Math.min(MAX_BAR,dev/range*MAX_BAR));
          var top=ratio>=1?(BASELINE-barH):BASELINE;
          var color=(chg>=0)?'var(--up)':'var(--down)';
          var alpha=isCurrent?1:0.7;
          var tip=idx.label+' '+slot+'  涨跌'+(chg>=0?'+':'')+chg.toFixed(2)+'%  较昨日'+ratio.toFixed(2)+'x';
          html += '<div class="w11b" data-tip="'+tip.replace(/"/g,'&quot;')+'" style="position:absolute;left:'+left+'%;width:'+barW+'%;top:'+top+'px;height:'+barH+'px;background:'+color+';opacity:'+alpha+';border-radius:1px 1px 0 0;cursor:pointer"></div>';
        } else {
          html += '<div style="position:absolute;left:'+left+'%;width:'+barW+'%;top:'+(BASELINE-1)+'px;height:2px;background:var(--border-light);border-radius:1px;opacity:0.15"></div>';
        }
      });

      html += '</div>'; // end chart
      html += '</div></div>'; // end row
    });

    // 底部时间标签
    html += '<div style="position:relative;height:12px;margin:2px 0 0 28px;font-size:7px;color:var(--text-disabled)">';
    SLOTS.forEach(function(l,i){
      var isCur=i===currentIdx;
      var left=(i/N)*100;
      html += '<span style="position:absolute;left:'+left+'%;width:'+barW+'%;text-align:center;'+(isCur?'color:var(--text-primary);font-weight:700':'')+'">'+l+'</span>';
    });
    html += '</div>';

    // 底部三卡标尺（最新时段）
    html += '<div style="display:flex;gap:var(--sp-sm);margin-top:var(--sp-sm)">';
    indexes.forEach(function(idx){
      var bars=idx.data;
      // 找非累计的最后一条
      var normalBars=bars.filter(function(b){return !b._cum;});
      var last=normalBars.length>0?normalBars[normalBars.length-1]:null;
      html += '<div style="flex:1;padding:var(--sp-xs) var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-sm);font-size:11px;line-height:1.6">';
      html += '<span style="font-weight:700;color:var(--text-primary);margin-right:var(--sp-sm)">'+idx.label+'</span>';
      if(last){
        var dw=last.chg>0?'涨':(last.chg<0?'跌':'平');
        var amtYi=(last.amount||0)/1e8;
        var yesterdayAmt=(last.yesterdayAmt||0)/1e8;
        var amtDiff=amtYi-yesterdayAmt;
        var vsign=amtDiff>=0?'+':'';
        var vcolor=amtDiff>=0?'var(--up)':'var(--down)';
        var vword=amtDiff>=1?'放量':(amtDiff<=-1?'缩量':'平量');
        html += '<span style="color:var(--text-disabled)">'+last.t+'</span> '+
          '<span style="color:var(--'+(last.chg>=0?'up':'down')+');font-weight:600">'+dw+Math.abs(last.chg).toFixed(2)+'%</span> '+
          '<span style="color:var(--text-secondary)">'+amtYi.toFixed(0)+'亿</span> '+
          '<span style="color:'+vcolor+';font-weight:600">'+vsign+amtDiff.toFixed(0)+'亿 '+vword+'</span>';
      } else {html+='<span style="color:var(--text-disabled)">—</span>';}
      html += '</div>';
    });
    html += '</div>';

    // 累计行（日涨跌 + 全日成交额，全市场量对比）
    html += '<div style="display:flex;gap:var(--sp-sm);margin-top:4px">';
    var li = (data||{}).live_index||{};
    // 全市场量差：用 bar 累计反推（上证+深证，不含创业）
    var cumTotal = 0, cumYesterdayTotal = 0;
    ['上证15min','深证15min'].forEach(function(k){
      var bd=(data||{})[k]||[];
      for(var j=0;j<bd.length;j++){if(bd[j]._cum){cumTotal+=bd[j].amount||0;cumYesterdayTotal+=bd[j].cumYesterdayAmt||0;break;}}
    });
    var cumIndexes = [
      {label:'上证', chg:(li['上证指数涨幅']||'—'), amt:(li['上证指数成交额']||'—')},
      {label:'深证', chg:(li['深证指数涨幅']||'—'), amt:(li['深证指数成交额']||'—')},
      {label:'创业', chg:(li['创业指数涨幅']||'—'), amt:(li['创业指数成交额']||'—')}
    ];
    cumIndexes.forEach(function(ci){
      var isUp = String(ci.chg).charAt(0)==='+';
      html += '<div style="flex:1;padding:var(--sp-xs) var(--sp-sm);background:var(--bg-base);border-radius:var(--radius-sm);font-size:11px;line-height:1.6;border-left:2px solid var(--info)">';
      html += '<span style="font-weight:700;color:var(--text-primary);margin-right:var(--sp-sm)">'+ci.label+' 全日</span>';
      html += '<span style="color:var(--'+(isUp?'up':'down')+');font-weight:600">'+ci.chg+'</span> ';
      html += '<span style="color:var(--text-secondary)">'+ci.amt+'</span>';
      html += '</div>';
    });
    html += '</div>';

    // 全市场量对比
    if (cumTotal > 0 && cumYesterdayTotal > 0) {
      var totalYi = cumTotal/1e8;
      var yesYi = cumYesterdayTotal/1e8;
      var diffYi = totalYi - yesYi;
      var vs = diffYi>=0?'+':'';
      var vc = diffYi>=0?'var(--up)':'var(--down)';
      var vw = diffYi>0?'放量':'缩量';
      html += '<div style="margin-top:2px;font-size:11px;color:var(--text-secondary);text-align:center">'+
        '全市场累计 <span style="font-weight:600;color:var(--text-primary)">'+totalYi.toFixed(0)+'亿</span> '+
        '<span style="color:'+vc+';font-weight:600">较昨日 '+vs+diffYi.toFixed(0)+'亿 '+vw+'</span></div>';
    }

    body.innerHTML = html;

    // hover
    var tipEl = body.querySelector('#w11tip');
    [0,1,2].forEach(function(ri){
      var rowEl = body.querySelector('#w11r'+ri);
      if(rowEl&&tipEl){
        rowEl.addEventListener('mouseover',function(e){
          var t=e.target;
          if(t&&t.classList.contains('w11b')){
            tipEl.textContent=t.getAttribute('data-tip')||'';
            tipEl.style.display='block';
            tipEl.style.left=(e.clientX+12)+'px';
            tipEl.style.top=(e.clientY-28)+'px';
          }
        });
        rowEl.addEventListener('mouseout',function(e){
          if(e.target&&e.target.classList.contains('w11b'))tipEl.style.display='none';
        });
      }
    });

    this.updateTimestamp();
  }
}

WidgetRegistry.register('W11', VolumeBarsWidget);
