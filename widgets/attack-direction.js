// widgets/attack-direction.js — W26 主攻方向 v1.0
'use strict';

class AttackDirectionWidget extends YiMuWidget {
  render(data) {
    var body = this.getBody();
    if (!body) return;

    var payload = (data && data.attack_direction) || null;
    if (!payload || !payload.summary || payload.source_status === 'missing_source') {
      body.innerHTML =
          '<div class="ui-empty attack-empty">' +
            '<div class="ui-empty-title">今日确认涨停源暂不可用</div>' +
          '<div class="ui-empty-detail">等待交易时段涨停明细或题材归因源更新后输出主攻方向。</div>' +
        '</div>';
      this.updateTimestamp();
      return;
    }

    var summary = payload.summary || {};
    var sectors = payload.sectors || [];
    var leader = sectors[0] || {};
    var status = payload.source_status || '';
    var leaderName = summary.leader_sector || leader.sector || '未形成';
    var conclusion = summary.conclusion || '观察';
    var statusText = this._statusText(status);
    var statusCls = this._statusClass(status, conclusion);
    var updated = this._formatUpdated(payload._updated);
    var warnings = payload.warnings || [];
    var freshness = payload.source_freshness || {};
    var freshnessLabel = freshness.label || updated && ('更新 ' + updated) || '';
    var freshnessCls = this._freshnessClass(freshness.level || '');

    var html = '';
    html += '<div class="attack-board">';
    html += '<div class="attack-hero ' + statusCls + '">';
    html += '<div class="attack-hero-copy">';
    html += '<span class="attack-label">W26 早封首板</span>';
    html += '<div class="attack-title"><span>' + this._esc(conclusion) + '</span><b>' + this._esc(leaderName) + '</b></div>';
    html += '<div class="attack-sub">' + this._esc(this._heroLine(payload, leader)) + '</div>';
    html += '</div>';
    html += '<div class="attack-confidence"><span>置信</span><b>' + this._fmtInt(summary.confidence) + '</b></div>';
    html += '</div>';

    html += '<div class="attack-source-row">';
    html += '<span class="attack-source-chip primary">' + this._esc(statusText) + '</span>';
    html += '<span class="attack-source-chip">窗口 ' + this._esc(payload.window || '09:30-09:45') + '</span>';
    html += '<span class="attack-source-chip compact-stat">' + this._esc(this._summaryChip(summary)) + '</span>';
    if (freshnessLabel) html += '<span class="attack-source-chip ' + freshnessCls + '">' + this._esc(freshnessLabel) + '</span>';
    html += '<span class="attack-source-chip muted">' + this._esc(payload.source || 'hot_list + sector_inflow') + '</span>';
    html += '</div>';

    if (warnings.length) {
      html += '<div class="attack-warning">' + warnings.map(this._esc.bind(this)).join('；') + '</div>';
    }

    if (!sectors.length) {
      html += '<div class="ui-empty attack-empty compact"><div class="ui-empty-title">暂无可归因方向</div></div>';
    } else {
      html += '<div class="attack-sector-grid">';
      for (var i = 0; i < Math.min(sectors.length, 3); i++) {
        html += this._renderSector(sectors[i], i);
      }
      html += '</div>';
    }

    html += '</div>';
    body.innerHTML = html;
    this.updateTimestamp();
  }

  _renderSector(row, idx) {
    var score = Math.max(0, Math.min(100, parseInt(row.score || 0, 10)));
    var cls = idx === 0 ? ' leader' : '';
    var samples = row.sample || [];
    var html = '<div class="attack-sector' + cls + '">';
    html += '<div class="attack-sector-head">';
    html += '<div><b>' + this._esc(row.sector || '未归因') + '</b><span>' + this._esc(row.conclusion || '观察') + '</span></div>';
    html += '<strong><small>强度</small>' + score + '</strong>';
    html += '</div>';
    html += '<div class="attack-score-bar"><i style="width:' + score + '%"></i></div>';
    html += '<div class="attack-sector-metrics">';
    html += '<span>早封 <b>' + this._fmtInt(row.early_first_count) + '</b></span>';
    html += '<span>跟随 <b>' + this._fmtInt(row.follow_count) + '</b></span>';
    html += '<span>全板 <b>' + this._fmtInt(row.all_limit_count) + '</b></span>';
    html += '</div>';
    if (samples.length) {
      html += '<div class="attack-samples">';
      samples.slice(0, 2).forEach(function(s) {
        var title = (s.seal_time ? s.seal_time + ' ' : '') + (s.reason || '');
        html += '<span title="' + this._esc(title) + '">' + this._esc(s.name || s.code || '—') + '<small>' + this._esc(s.seal_time || '') + '</small></span>';
      }, this);
      html += '</div>';
    }
    html += '</div>';
    return html;
  }

  _freshnessClass(level) {
    if (level === 'live') return 'fresh-live';
    if (level === 'delayed') return 'fresh-delayed';
    if (level === 'stale') return 'fresh-stale';
    return 'muted';
  }

  _heroLine(payload, leader) {
    var status = payload.source_status || '';
    if (status === 'missing_time') {
      return '确认涨停有数据，但封板时间缺失，暂不确认09:30-09:45早封强度。';
    }
    if (status === 'partial_reason_stats') {
      return '确认涨停名单缺失，仅按题材归因观察方向，不能验收早封首板。';
    }
    if (!leader || !leader.sector) {
      return '早封首板尚未形成集中方向。';
    }
    return '早封首板' + (leader.early_first_count || 0) + '只，跟随封板' + (leader.follow_count || 0) + '只，全板' + (leader.all_limit_count || 0) + '只。';
  }

  _kpi(label, value, unit) {
    return '<div class="attack-kpi"><span>' + this._esc(label) + '</span><b>' + this._esc(value) + '</b><em>' + this._esc(unit) + '</em></div>';
  }

  _summaryChip(summary) {
    return '早' + this._fmtInt(summary.early_first_count) +
      ' 首' + this._fmtInt(summary.first_count) +
      ' 全' + this._fmtInt(summary.all_limit_count) +
      ' 向' + this._fmtInt(summary.sector_count);
  }

  _statusText(status) {
    if (status === 'confirmed') return '早封可验收';
    if (status === 'partial_reason_stats') return '名单缺失';
    if (status === 'missing_time') return '封板时间缺失';
    if (status === 'missing_source') return '涨停源缺失';
    return '观察源';
  }

  _statusClass(status, conclusion) {
    if (status === 'missing_time' || status === 'missing_source' || status === 'partial_reason_stats') return 'source-limited';
    if (conclusion === '主攻确认') return 'confirmed';
    if (conclusion === '主攻观察') return 'watch';
    return 'neutral';
  }

  _formatUpdated(raw) {
    if (!raw) return '';
    var m = String(raw).match(/T(\d{2}:\d{2})/);
    return m ? m[1] : String(raw).slice(0, 16);
  }

  _fmtInt(v) {
    var n = parseInt(v == null ? 0 : v, 10);
    return isNaN(n) ? '0' : String(n);
  }

  _fmtPct(v) {
    if (v == null || v === '') return '—';
    var n = parseFloat(v);
    return isNaN(n) ? '—' : (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
  }

  _fmtFlow(v) {
    if (v == null || v === '') return '—';
    var n = parseFloat(v);
    return isNaN(n) ? '—' : (n >= 0 ? '+' : '') + n.toFixed(1) + '亿';
  }

  _esc(v) {
    return this._clean(v)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  _clean(v) {
    return String(v == null ? '' : v)
      .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '')
      .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, '')
      .replace(/<[^>]+>/g, '')
      .replace(/\bon\w+\s*=\s*[^ ]+/gi, '')
      .replace(/javascript:/gi, '')
      .trim();
  }
}

WidgetRegistry.register('W26', AttackDirectionWidget);
