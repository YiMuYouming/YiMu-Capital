// store.js — 弈沐资本数据看板 v2.0 数据中枢
// DataStore: 订阅-发布 + 分层刷新 + SSOT 溯源 + dataAdapter 抽象
'use strict';

/** localStorage key 集中声明 */
const STORAGE_KEYS = {
  inputs: 'dash_inputs',        // 报数面板 15 字段
  panelOpen: 'dash_panel_open', // 报数面板折叠状态
  layout: 'dash_layout_v2',    // 画板布局 JSON (v2.1 新 key)
};

const DataStore = (function() {
  // === 数据池 ===
  var baseData = null;         // dashboard_data.json（Layer 1）
  var liveData = null;         // dashboard_live.json（Layer 2）
  var manualData = {};         // 手工录入数据（Layer 3，W16 输入事件驱动）
  var merged = null;           // mergeData() 三层合并结果
  var initialBase = null;      // baseData 首次加载快照（昨日收盘基线）
  var fallback = (typeof EMBEDDED_DATA !== 'undefined') ? EMBEDDED_DATA : null;  // 兜底数据

  // === 刷新层级（v2.0 多源实时：PyTDX + 东方财富 + easyquotation）===
  var tiers = {
    tick:    { interval: 5000,   sources: ['live_index', 'live_quotes'], label: '5秒' },
    fast:    { interval: 30000,  sources: ['live_sectors'],               label: '30秒' },
    slow:    { interval: null,   sources: ['上证15min', 'market'],        label: '已停用' },
    manual:  { interval: null,   sources: ['sentiment', 'decision'],      label: '手工' },
    daily:   { interval: null,   sources: ['style', 'sectors', 'lianban_pool', 'trend_pool'], label: '每日' },
  };

  // === 订阅中心 ===
  // subscribers[dataPath] = [{ id, callback }]
  var subscribers = {};
  var subIdCounter = 0;

  // === 连接状态 ===
  var connectionStatus = 'polling'; // 'live' | 'polling' | 'dead'
  var errors = [];

  // === 数据适配器（v3.0: API 优先 + file:// 降级 + SSE）===
  var _isFileProtocol = (typeof location !== 'undefined' && location.protocol === 'file:');
  var _sseClient = null;

  var adapter = {
    fetchBase: function() {
      if (_isFileProtocol) {
        return fetch('data/dashboard_data.json?t=' + Date.now() + Math.random())
          .then(function(r) { if (!r.ok) throw new Error('base fetch failed'); return r.json(); });
      }
      return fetch('/api/baseline')
        .then(function(r) { if (!r.ok) throw new Error('base fetch failed'); return r.json(); })
        .catch(function() {
          // API 失败降级到直接读文件
          return fetch('data/dashboard_data.json?t=' + Date.now() + Math.random())
            .then(function(r) { return r.ok ? r.json() : null; });
        });
    },
    fetchLive: function() {
      if (_isFileProtocol) {
        return fetch('data/dashboard_live.json?t=' + Date.now() + Math.random())
          .then(function(r) { return r.ok ? r.json() : null; })
          .catch(function() { return null; });
      }
      return fetch('/api/live/quotes')
        .then(function(r) { return r.ok ? r.json() : null; })
        .catch(function() {
          // API 失败降级到直接读文件
          return fetch('data/dashboard_live.json?t=' + Date.now() + Math.random())
            .then(function(r) { return r.ok ? r.json() : null; })
            .catch(function() { return null; });
        });
    }
  };

  /** SSE 实时推送（降级到 fetch 轮询） */
  function connectSSE() {
    if (_isFileProtocol || typeof EventSource === 'undefined') return;
    try {
      _sseClient = new EventSource('/api/live/stream');
      _sseClient.onmessage = function(e) {
        try {
          var live = JSON.parse(e.data);
          if (live) liveData = live;
          merge();
          notifyAll();
          connectionStatus = 'live';
          notifyConnListeners();
        } catch (ex) {}
      };
      _sseClient.onerror = function() {
        connectionStatus = 'polling';
        notifyConnListeners();
        // SSE 断开则降级到 fetch 轮询（由 refresh() 的 tick 驱动）
      };
    } catch (e) {
      connectionStatus = 'polling';
    }
  }

  // === 工具函数 ===
  function deepClone(obj) {
    return JSON.parse(JSON.stringify(obj));
  }

  function setByPath(obj, path, value) {
    var keys = path.split('.');
    var target = obj;
    for (var i = 0; i < keys.length - 1; i++) {
      if (!target[keys[i]]) target[keys[i]] = {};
      target = target[keys[i]];
    }
    target[keys[keys.length - 1]] = value;
  }

  function getByPath(obj, path) {
    if (!obj) return undefined;
    var keys = path.split('.');
    var target = obj;
    for (var i = 0; i < keys.length; i++) {
      if (target == null) return undefined;
      target = target[keys[i]];
    }
    return target;
  }

  function notifyPath(path) {
    var subs = subscribers[path];
    if (!subs || !subs.length) return;
    var val = getByPath(merged, path);
    for (var i = 0; i < subs.length; i++) {
      try { subs[i].callback(val, path); } catch(e) {
        errors.push({ path: path, error: e, time: new Date() });
        console.error('DataStore notify error [' + path + ']:', e);
      }
    }
  }

  function notifyAll() {
    Object.keys(subscribers).forEach(function(path) {
      notifyPath(path);
    });
  }

  // === 核心：三层合并 ===
  function merge() {
    // Step 1: 从 baseData 或 fallback 开始
    var src = baseData || fallback || {};
    var d = deepClone(src);

    // Step 2: manualData 覆盖（报数面板手动录入）
    // 注：情绪值/涨跌家数的优先级逻辑已移至 Step 3 之后（T3实时→T2校验→T4覆盖）
    if (manualData) {
      // 涨停收益 → 赚钱效应判定
      var zsStr = manualData['涨停收益'] || '';
      if (zsStr) {
        d.sentiment = d.sentiment || {};
        d.sentiment['昨日涨停收益'] = zsStr.indexOf('%') >= 0 ? zsStr : zsStr + '%';
        var zs = parseFloat(zsStr);
        var lb = parseFloat(d.sentiment['连板收益']) || 0;
        var fz = parseFloat(d.sentiment['连板风险值']) || 999;
        var zb = parseFloat(d.sentiment['昨日炸板收益']) || -999;
        if (zs > 3 && lb > 0 && fz < 0.5 && zb > 0) d.sentiment['赚钱效应'] = '好';
        else if (zs < 2) d.sentiment['赚钱效应'] = '差';
        else d.sentiment['赚钱效应'] = '一般';
      }

      var lbStr = manualData['连板收益'] || '';
      if (lbStr) { d.sentiment = d.sentiment || {}; d.sentiment['连板收益'] = lbStr.indexOf('%') >= 0 ? lbStr : lbStr + '%'; }
      var zbStr = manualData['炸板收益'] || '';
      if (zbStr) { d.sentiment = d.sentiment || {}; d.sentiment['昨日炸板收益'] = zbStr.indexOf('%') >= 0 ? zbStr : zbStr + '%'; }
      var fzVal = manualData['风险值'] || '';
      if (fzVal) { d.sentiment = d.sentiment || {}; d.sentiment['连板风险值'] = parseFloat(fzVal); }
      var jjStr = manualData['晋级率'] || '';
      if (jjStr) { d.sentiment = d.sentiment || {}; d.sentiment['晋级率'] = jjStr.indexOf('%') >= 0 ? jjStr : jjStr + '%'; }
      var fbStr = manualData['封板率'] || '';
      if (fbStr) { d.market = d.market || {}; d.market['封板率'] = fbStr.indexOf('%') >= 0 ? fbStr : fbStr + '%'; }
      var zqStr = manualData['赚钱效应'] || '';
      if (zqStr) { d.sentiment = d.sentiment || {}; d.sentiment['赚钱效应'] = zqStr; }
      var ztVal = manualData['涨停家数'] || '';
      if (ztVal) { d.market = d.market || {}; d.market['涨停家数'] = parseInt(ztVal); }
      var dtVal = manualData['跌停家数'] || '';
      if (dtVal) { d.market = d.market || {}; d.market['跌停家数'] = parseInt(dtVal); }
      var zgVal = manualData['最高板'] || '';
      if (zgVal) { d.sentiment = d.sentiment || {}; d.sentiment['最高板'] = zgVal; }
      var cgVal = manualData['次高板'] || '';
      if (cgVal) { d.sentiment = d.sentiment || {}; d.sentiment['次高板'] = cgVal; }
      var tdVal = manualData['梯队'] || '';
      if (tdVal) { d.sentiment = d.sentiment || {}; d.sentiment['连板梯队'] = tdVal; }
      // 账户头寸 → d.pnl（W22 收益曲线依赖）
      var zcVal = parseFloat(manualData['总资产']) || 0;
      if (zcVal > 0) { d.pnl = d.pnl || {}; d.pnl['总资产'] = zcVal; }
      var rjVal = manualData['可用资金'] || '';
      if (rjVal) { d.pnl = d.pnl || {}; d.pnl['可用资金'] = parseFloat(rjVal) || 0; }
      var ykVal = manualData['总盈亏'] || '';
      if (ykVal) { d.pnl = d.pnl || {}; d.pnl['总盈亏'] = parseFloat(ykVal) || 0; }
    }

    // Step 3: liveData 覆盖（实时报价 + 15min量价 + 板块）
    if (liveData) {
      ['上证15min','深证15min','创业15min'].forEach(function(k) {
        if (liveData[k] && liveData[k].length) d[k] = liveData[k];
      });
      if (liveData.live_index) {
        d.live_index = d.live_index || {};
        for (var k in liveData.live_index) { d.live_index[k] = liveData.live_index[k]; }
      }
      if (liveData.live_sectors) {
        d.live_sectors = d.live_sectors || {};
        for (var k in liveData.live_sectors) { d.live_sectors[k] = liveData.live_sectors[k]; }
      }
      if (liveData.live_breadth) {
        d.live_breadth = d.live_breadth || {};
        for (var k in liveData.live_breadth) { d.live_breadth[k] = liveData.live_breadth[k]; }
      }
      // iwencai 实时情绪数据（供 W04 等组件）
      if (liveData.iwencai) {
        d.iwencai = d.iwencai || {};
        for (var k in liveData.iwencai) { d.iwencai[k] = liveData.iwencai[k]; }
      }
      // ym-stock-data 新增字段
      if (liveData.sector_inflow) { d.sector_inflow = liveData.sector_inflow; }
      if (liveData.northbound) { d.northbound = liveData.northbound; }
      if (liveData.hot_list) { d.hot_list = liveData.hot_list; }
      if (liveData.yesterday_baseline) {
        d.yesterday_baseline = d.yesterday_baseline || {};
        for (var k in liveData.yesterday_baseline) { d.yesterday_baseline[k] = liveData.yesterday_baseline[k]; }
      }
      if (liveData.live_quotes) {
        d.live_quotes = d.live_quotes || {};
        for (var c in liveData.live_quotes) { d.live_quotes[c] = liveData.live_quotes[c]; }
        [d.lianban_pool, d.trend_pool].forEach(function(pool) {
          (pool || []).forEach(function(s) {
            var q = liveData.live_quotes[s['代码']];
            if (q) {
              if (q['最新价'] != null && q['最新价'] !== '—') { s['最新价'] = q['最新价']; s['收盘价'] = q['最新价']; }
              if (q['涨幅'] != null && q['涨幅'] !== '—') s['涨幅'] = q['涨幅'];
              if (q['量比'] != null && q['量比'] !== '—') s['量比'] = q['量比'];
              if (q['换手'] != null && q['换手'] !== '—') s['换手'] = q['换手'];
            }
          });
        });
      }
    }

    // === Step 4: 情绪值优先级 T3 实时 > T2 校验 > T4 手工覆盖 ===
    var autoEmotion = null;
    var emotionSource = 'none';

    // T3 优先：实时涨跌家数比（来自 live_index 或 manualData）
    var upAdv = (manualData && parseInt(manualData['上涨'])) || (d.live_index && d.live_index['上涨家数']) || 0;
    var dnAdv = (manualData && parseInt(manualData['下跌'])) || (d.live_index && d.live_index['下跌家数']) || 0;
    if (upAdv + dnAdv > 0) {
      autoEmotion = Math.round(upAdv / (upAdv + dnAdv) * 100);
      emotionSource = 'T3:live_breadth';
    }

    // T2 校验：iwencai 情绪值（来自 liveData 或 baseData）
    var iwencaiEmotion = (liveData && liveData._iwencai_情绪值) || (d.sentiment && d.sentiment['_iwencai_情绪值']);
    if (iwencaiEmotion != null && (autoEmotion == null || Math.abs(autoEmotion - parseFloat(iwencaiEmotion)) > 15)) {
      // iwencai 与 T3 偏差 >15% 时记录，但不覆盖 T3（T3 主源更实时）
      if (autoEmotion == null) {
        autoEmotion = parseFloat(iwencaiEmotion);
        emotionSource = 'T2:iwencai(fallback)';
      }
    }

    // T4 覆盖：仅当手工明确录入且勾选了手动覆盖 checkbox
    var manualEmotion = manualData && manualData['情绪值'] || '';
    var isManualOverride = manualEmotion && manualData && manualData['_情绪值_手动覆盖'] === 'true';

    var finalEmotion = isManualOverride ? parseFloat(manualEmotion)
      : autoEmotion != null ? autoEmotion
      : iwencaiEmotion != null ? parseFloat(iwencaiEmotion)
      : (d.sentiment && d.sentiment['情绪值']) || 0;

    if (isManualOverride) emotionSource = 'T4:manual_override';

    d.sentiment = d.sentiment || {};
    d.sentiment['情绪值'] = finalEmotion;
    d.sentiment['情绪区间'] = finalEmotion < 20 ? '冰点' : finalEmotion < 40 ? '低迷'
      : finalEmotion < 60 ? '主升' : finalEmotion < 80 ? '强势' : '高潮';
    d.sentiment['_emotion_source'] = emotionSource;

    // 保留 API 响应的 _freshness（优先 liveData 实时源，其次 baseData 基线源）
    d._freshness = (liveData && liveData._freshness) || d._freshness || null;

    // 注入 PnL 实时总资产（每 tick 从 bridge /api/pnl/summary 拉取）
    if (_pnlLive) {
      d.pnl_live = _pnlLive;
    }

    setMerged(d);
    return d;
  }

  var _pnlLive = null;

  function _fetchPnlSummary() {
    if (location.protocol === 'file:') return Promise.resolve(null);
    return fetch('/api/pnl/summary').then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; });
  }

  // === 刷新数据（v2.0 多源实时管线）===
  var _refreshCount = 0;
  function refresh(tier) {
    if (tier === 'manual' || tier === 'daily' || tier === 'slow') return;

    connectionStatus = 'polling';
    notifyConnListeners();

    if (tier === 'tick' || tier === 'fast') {
      // 每 12 次 tick（~60s）重拉 base 数据（gen 脚本可能更新了文件）
      if (tier === 'tick') _refreshCount++;
      var reloadBase = (_refreshCount % 12 === 0);
      var chain = reloadBase ? adapter.fetchBase() : new Promise(function(r){r(baseData);});
      // SSE 连接时跳过 fetchLive（SSE 推送接管实时数据）
      if (_sseClient && _sseClient.readyState === EventSource.OPEN) {
        chain.then(function(base) {
          if (reloadBase && base) baseData = base;
          merge();
          notifyAll();
          notifyConnListeners();
        });
      } else {
        chain.then(function(base) {
          if (reloadBase && base) baseData = base;
          return adapter.fetchLive();
        }).then(function(live) {
          if (live) { liveData = live; connectionStatus = 'live'; }
          return _fetchPnlSummary().then(function(pnlLive) {
            if (pnlLive) _pnlLive = pnlLive;
          });
        }).then(function() {
          merge();
          notifyAll();
          notifyConnListeners();
        }).catch(function() {
          connectionStatus = 'dead';
          if (!baseData && fallback) {
            setMerged(deepClone(fallback));
            notifyAll();
          }
          notifyConnListeners();
        });
      }
    }
  }

  function init() {
    // 立即用 EMBEDDED_DATA 渲染，保证 file:// 协议下不白屏
    if (fallback) {
              setMerged(deepClone(fallback));
    }
    // 启动 SSE 实时推送（非 file:// 协议）
    connectSSE();
  }

  function fetchAll() {
    // 先确保有兜底数据可用
    if (!merged && fallback) {
              setMerged(deepClone(fallback));
    }

    connectionStatus = 'polling';
    notifyConnListeners();

    adapter.fetchBase().then(function(base) {
      baseData = base;
      if (!initialBase && base.market) {
        initialBase = { market: deepClone(base.market), sentiment: deepClone(base.sentiment) };
      }
      return adapter.fetchLive();
    }).then(function(live) {
      if (live) { liveData = live; connectionStatus = 'live'; }
      return _fetchPnlSummary().then(function(pnlLive) {
        if (pnlLive) _pnlLive = pnlLive;
      });
    }).then(function() {
      merge();
      notifyAll();
      notifyConnListeners();
    }).catch(function(err) {
      // 即使 live 拉取失败，baseData 已更新 → 合并 baseData 保证最新
      connectionStatus = 'dead';
      if (baseData) {
        merge();
        notifyAll();
      } else if (fallback) {
        setMerged(deepClone(fallback));
        notifyAll();
      }
      notifyConnListeners();
    });
  }

  // === 连接状态监听 ===
  var connListeners = [];
  function onConnChange(fn) { connListeners.push(fn); }
  function notifyConnListeners() {
    connListeners.forEach(function(fn) { try { fn(connectionStatus); } catch(e) {} });
  }

  // 保持 exports.merged 与内部 merged 同步
  function syncMerged() { exports.merged = merged; }
  function setMerged(val) { merged = val; exports.merged = val; }

  // === 公共 API ===
  var exports = {
    // 数据池状态（widget 渲染时直接读取）
    merged: null,  // 由 init/fetchAll/merge 更新

    // 数据读取
    get: function(path) { return getByPath(merged, path); },
    getInitialBase: function() { return initialBase; },
    getConnectionStatus: function() { return connectionStatus; },

    // 初始化（立即加载兜底数据，避免白屏）
    init: function() {
      init();
      // 把 merged 暴露为直接可读属性
      this.merged = merged;
    },

    // 订阅
    subscribe: function(paths, callback) {
      if (typeof paths === 'string') paths = [paths];
      var id = ++subIdCounter;
      var debounced = debounce(callback, 100);
      paths.forEach(function(p) {
        if (!subscribers[p]) subscribers[p] = [];
        // 去重：同一 callback 不重复注册
        var exists = subscribers[p].some(function(s) { return s.callback === callback; });
        if (!exists) subscribers[p].push({ id: id, callback: debounced });
      });
      return function unsubscribe() {
        paths.forEach(function(p) {
          if (subscribers[p]) {
            subscribers[p] = subscribers[p].filter(function(s) { return s.id !== id; });
          }
        });
      };
    },

    // 手工数据（由 W16 报数面板调用）
    manualData: {
      set: function(key, value) {
        manualData[key] = value;
        try { localStorage.setItem(STORAGE_KEYS.inputs, JSON.stringify(manualData)); } catch(e) {}
      },
      get: function(key) { return key ? manualData[key] : undefined; },
      getAll: function() { return deepClone(manualData); },
      load: function() {
        try {
          manualData = JSON.parse(localStorage.getItem(STORAGE_KEYS.inputs) || '{}');
        } catch(e) { manualData = {}; }
        delete manualData['总资产'];
        ['可用资金','总盈亏'].forEach(function(k) {
          var v = manualData[k];
          if (v === '0' || v === 0 || v === '' || v == null) delete manualData[k];
        });
      },
      clear: function() {
        manualData = {};
        try { localStorage.removeItem(STORAGE_KEYS.inputs); } catch(e) {}
      }
    },

    // 数据刷新
    refresh: refresh,
    fetchAll: fetchAll,
    merge: merge,
    notifyAll: notifyAll,
    // 强制刷新 base 数据（gen 运行后调用）
    refreshBase: function() {
      adapter.fetchBase().then(function(base) {
        if (base) baseData = base;
        return adapter.fetchLive();
      }).then(function(live) {
        if (live) liveData = live;
        merge();
        notifyAll();
        notifyConnListeners();
      }).catch(function() {
        if (baseData) { merge(); notifyAll(); }
      });
    },

    // 适配器（可替换为 Dify）
    adapter: adapter,

    // SSOT 溯源
    getSSOT: function(path) {
      var map = {
        // === T1 实时（秒级，YM-data-pipeline → bridge APScheduler） ===
        'live_index.*':           { source: 'YM-data-pipeline fetch(index) → collectors/quotes.py → bridge CACHE', freq: '5s', owner: 'bridge APScheduler' },
        'live_quotes.*':          { source: 'YM-data-pipeline fetch(quotes) → collectors/quotes.py → bridge CACHE', freq: '5s', owner: 'bridge APScheduler' },
        'live_breadth.*':         { source: 'YM-data-pipeline fetch(breadth) → collectors/quotes.py → bridge CACHE', freq: '30s', owner: 'bridge APScheduler' },
        'live_sectors.*':         { source: 'YM-data-pipeline fetch(sector_index) → collectors/quotes.py → bridge CACHE', freq: '30s', owner: 'bridge APScheduler' },
        '上证15min.*':             { source: 'PyTDX 5分钟K线 → poll_live.py (待迁入 quotes.py)', freq: '5min', owner: 'bridge APScheduler' },
        '深证15min.*':             { source: 'PyTDX 5分钟K线 → poll_live.py (待迁入 quotes.py)', freq: '5min', owner: 'bridge APScheduler' },
        '创业15min.*':             { source: 'PyTDX 5分钟K线 → poll_live.py (待迁入 quotes.py)', freq: '5min', owner: 'bridge APScheduler' },
        'northbound.*':           { source: 'YM-data-pipeline fetch(northbound) → collectors/quotes.py → bridge CACHE', freq: '60s', owner: 'bridge APScheduler' },
        // === T2 阶段（分钟/日级，iwencai/同花顺） ===
        'sentiment.涨停收益':       { source: 'iwencai 2min轮询 → CACHE[iwencai] → /api/live/iwencai', freq: '2min', owner: 'collectors/iwencai_poll.py' },
        'sentiment.连板收益':       { source: 'iwencai 2min轮询 → CACHE[iwencai]', freq: '2min', owner: 'collectors/iwencai_poll.py' },
        'sentiment.昨日炸板收益':    { source: 'iwencai 2min轮询 → CACHE[iwencai]', freq: '2min', owner: 'collectors/iwencai_poll.py' },
        'sentiment.封板率':         { source: 'iwencai 2min轮询 → CACHE[iwencai]', freq: '2min', owner: 'collectors/iwencai_poll.py' },
        'sentiment.炸板率':         { source: 'iwencai 2min轮询 → CACHE[iwencai]', freq: '2min', owner: 'collectors/iwencai_poll.py' },
        'sentiment.晋级率':         { source: 'iwencai 2min轮询 → CACHE[iwencai]', freq: '2min', owner: 'collectors/iwencai_poll.py' },
        'sentiment.最高板':         { source: 'iwencai 2min轮询（连板个股取max）→ CACHE[iwencai]', freq: '2min', owner: 'collectors/iwencai_poll.py' },
        'sentiment.连板风险值':      { source: 'iwencai 2min轮询（从晋级率反推）→ CACHE[iwencai]', freq: '2min', owner: 'collectors/iwencai_poll.py' },
        'sentiment.连板股数':       { source: 'iwencai 2min轮询 → CACHE[iwencai]', freq: '2min', owner: 'collectors/iwencai_poll.py' },
        'sentiment.涨停溢价率':      { source: 'iwencai 2min轮询（昨日涨停今日涨幅均值）→ CACHE[iwencai]', freq: '2min', owner: 'collectors/iwencai_poll.py' },
        'market.涨停家数':          { source: 'T1 breadth → bridge CACHE', freq: '30s', owner: 'collectors/quotes.py' },
        'market.跌停家数':          { source: 'T1 breadth → bridge CACHE', freq: '30s', owner: 'collectors/quotes.py' },
        'market.炸板率':            { source: 'T2 iwencai → CACHE[iwencai]', freq: '2min', owner: 'collectors/iwencai_poll.py' },
        'market.封板率':            { source: 'T2 iwencai → CACHE[iwencai]', freq: '2min', owner: 'collectors/iwencai_poll.py' },
        'sector_inflow.*':        { source: 'YM-data-pipeline fetch(sector_inflow) → collectors/market_data.py → bridge CACHE', freq: '5min', owner: 'bridge APScheduler' },
        'hot_list.*':             { source: 'YM-data-pipeline fetch(ths_hot) → collectors/quotes.py → bridge CACHE', freq: '5min', owner: 'bridge APScheduler' },
        'news.*':                 { source: 'YM-data-pipeline fetch(news) → collectors/market_data.py → bridge CACHE', freq: '5min', owner: 'bridge APScheduler' },
        'decision.竞价.*':         { source: 'snapshot_auction.py 9:25快照 → auction_snapshot.json', freq: '9:25', owner: 'bridge APScheduler' },
        'sentiment_nodes.*':      { source: 'sentiment_snapshot.py 30min自动快照 → sentiment_auto.json', freq: '30min', owner: 'bridge APScheduler' },
        // === T3 实时计算（从 T1+T2 逻辑推导） ===
        'sentiment.情绪值':         { source: 'T3涨跌家数比(主) / T2 iwencai(校验) / T4手工覆盖(需checkbox)', freq: '5s/2min/随录', owner: 'store.js merge() Step4' },
        'sentiment.情绪区间':       { source: 'T3计算: 情绪值阈值判定(<20冰点 <40低迷 <60主升 <80强势 ≥80高潮)', freq: '实时', owner: 'store.js merge() Step4' },
        'sentiment.竞价情绪值':     { source: 'T3计算: 竞价涨跌比 / T2 iwencai / snapshot_auction 高潮保护', freq: '9:25', owner: 'snapshot_auction.py' },
        'sentiment.赚钱效应':       { source: 'T3计算: 昨日涨停收益阈值(>2%好 <0差 其余一般)', freq: '2min', owner: 'collectors/iwencai_poll.py' },
        'pnl.*':                  { source: 'T3计算: P&L链(NAV连乘) / T2存储: pnl.db daily_summary', freq: '5min/每日', owner: 'bridge APScheduler + pnl_calc.py' },
        'market.赚钱效应':          { source: 'T3计算: 涨停收益阈值判定', freq: '2min', owner: 'store.js merge()' },
        // === T4 人工/复盘笔记（策略决策类字段） ===
        'style.*':                { source: 'style_detect.py → gen_dashboard_data.py → dashboard_data.json', freq: '每日盘前', owner: '稳米 + gen脚本' },
        'lianban_pool.*':         { source: '复盘笔记附录A → pools.json / 数据附录 → dashboard_data.json', freq: '每日盘前', owner: '稳米 + gen脚本' },
        'trend_pool.*':           { source: '复盘笔记附录A → pools.json / 数据附录 → dashboard_data.json', freq: '每日盘前', owner: '稳米 + gen脚本' },
        'sectors.*':              { source: '复盘笔记数据附录 → dashboard_data.json', freq: '每日盘前', owner: '稳米 + gen脚本' },
        'anchor_stocks.*':        { source: '复盘笔记附录A → pools.json', freq: '每日盘前', owner: '稳米 + gen脚本' },
        'positions.*':            { source: 'W16输入面板/W15记流水 → pnl.db + localStorage', freq: '随录', owner: '弈沐哥' },
        'decision.今日操作.*':      { source: 'W17自助录入 → pnl.db trade_records', freq: '随录', owner: '弈沐哥' },
        'decision.锚定股状态.*':    { source: '复盘笔记数据附录 → dashboard_data.json', freq: '每日盘前', owner: '稳米 + gen脚本' },
        'decision.早盘.*':         { source: '复盘笔记数据附录 W1早盘确认 → dashboard_data.json', freq: '每日盘前', owner: '稳米 + gen脚本' },
        'decision.盘中.*':         { source: '复盘笔记数据附录 W2盘中跟踪 → dashboard_data.json', freq: '每日盘前', owner: '稳米 + gen脚本' },
        'risk.当日盈亏':           { source: 'T4人工: 复盘笔记 frontmatter → gen脚本校验 vs T3计算', freq: '每日', owner: '弈沐哥 + gen脚本' },
        'risk.熔断触发':           { source: 'T4人工: 复盘笔记 frontmatter', freq: '每日', owner: '弈沐哥' },
        'risk.周回撤触发':          { source: 'T4人工: 复盘笔记 frontmatter', freq: '每日', owner: '弈沐哥' },
        'risk.*':                 { source: 'T4人工: 复盘笔记 frontmatter → dashboard_data.json', freq: '每日', owner: '弈沐哥 + gen脚本' },
        'time_window.*':          { source: 'T1系统时钟 / T4人工: frontmatter W1/W2状态', freq: '实时/每日', owner: 'bridge + 弈沐哥' },
        'market.上证指数':          { source: 'T1实时: fetch(index) → bridge CACHE / T4回退: frontmatter', freq: '5s/每日', owner: 'bridge APScheduler' },
        'market.上证涨幅':          { source: 'T1实时: fetch(index) → bridge CACHE / T4回退: frontmatter', freq: '5s/每日', owner: 'bridge APScheduler' },
        'market.市场量能':          { source: 'T1实时: fetch(index) → bridge CACHE / T4回退: frontmatter', freq: '5s/每日', owner: 'bridge APScheduler' },
        'market.涨跌比':            { source: 'T1实时: fetch(breadth) → bridge CACHE', freq: '30s', owner: 'bridge APScheduler' },
        // === 其他 ===
        'yesterday_baseline.*':   { source: 'pools.json + dashboard_data.json 前日快照', freq: '每日', owner: 'gen脚本' },
        '_freshness.*':           { source: 'bridge.py _add_freshness() 辅助函数', freq: '实时', owner: 'bridge API' },
        'meta.*':                 { source: 'gen_dashboard_data.py → dashboard_data.json', freq: '每日', owner: 'gen脚本' },
      };
      // 前缀匹配：先精确匹配，再按前缀最长匹配
      if (map[path]) return map[path];
      var best = null;
      Object.keys(map).forEach(function(key) {
        if (key.endsWith('.*')) {
          var prefix = key.slice(0, -2);
          if (path.indexOf(prefix) === 0) {
            if (!best || prefix.length > best.prefixLen) {
              best = { val: map[key], prefixLen: prefix.length };
            }
          }
        }
      });
      return (best && best.val) || { source: '— (未映射，需补充)', freq: '—', owner: '—' };
    },

    // 连接状态
    onConnChange: onConnChange,
    getErrors: function() { return errors; },

    // 常量
    STORAGE_KEYS: STORAGE_KEYS,
    tiers: tiers,
  };

  syncMerged();
  return exports;
})();

// === 工具：debounce ===
function debounce(fn, delay) {
  var timer = null;
  return function() {
    var ctx = this, args = arguments;
    clearTimeout(timer);
    timer = setTimeout(function() { fn.apply(ctx, args); }, delay);
  };
}
