// widget-registry.js — 弈沐资本数据看板 v2.0 组件注册表
// 25 组件元数据 + 动态加载 + 按类型分组
'use strict';

const WidgetRegistry = (function() {
  var registry = {};

  // === 25 组件元数据 ===
  var widgets = [
    // 工具类
    { id:'W01', type:'timeline',      title:'时段时间线',   category:'tool',     tier:'slow',   defaultSize:{w:12,h:2},  dataPaths:[], priority:'P0', usageRole:'hidden_eval', usageLabel:'隐藏' },
    // 决策类
    { id:'W02', type:'style-detect',  title:'风格检测卡',   category:'decision', tier:'daily',  defaultSize:{w:4,h:6},   dataPaths:['style.总分','style.风格','style.连板占比','style.趋势占比','style.连板信号强度','style.趋势信号强度','style.dim1_量能','style.dim2_连板生态','style.dim3_趋势','style.dim4_情绪广度','style.一进二晋级率','style.二进三晋级率','style.三进四晋级率','style.预警','style.持续天数','style.实际执行'], priority:'P0', usageRole:'hidden_eval', usageLabel:'隐藏' },
    { id:'W03', type:'position-calc', title:'三层仓位计',   category:'decision', tier:'tick',defaultSize:{w:6,h:6},  dataPaths:['style.总仓位上限','style.连板占比','style.趋势占比','style.实际执行.连板实际','style.实际执行.趋势实际','style.实际执行.首笔上限','risk.熔断触发','risk.连亏天数','positions','live_quotes','pnl_live','rule_state'], priority:'P0', usageRole:'hidden_eval', usageLabel:'隐藏' },
    { id:'W06', type:'auction-5d',    title:'竞价5维面板',  category:'decision', tier:'manual', defaultSize:{w:12,h:6},  dataPaths:['auction_snapshot','sentiment.情绪值','sentiment.昨日涨停收益','sentiment.昨日炸板收益','sentiment.连板收益','sentiment.连板风险值','sentiment.赚钱效应','sentiment.晋级率','sentiment.最高板','sentiment.封板率','style.一进二晋级率','style.二进三晋级率','style.三进四晋级率','style.趋势走强板块数'], priority:'P1', usageRole:'secondary_evidence', usageLabel:'侧屏' },
    { id:'W07', type:'climax-guard',  title:'高潮保护',     category:'decision', tier:'manual', defaultSize:{w:3,h:2},  dataPaths:['sentiment.竞价情绪值','rule_state'], priority:'P1', usageRole:'hidden_eval', usageLabel:'隐藏' },
    { id:'W08', type:'w1-check',      title:'W1早盘确认',   category:'decision', tier:'tick',   defaultSize:{w:4,h:6},  dataPaths:['decision.早盘','lianban_pool','live_quotes','rule_state'], priority:'P1', usageRole:'secondary_evidence', usageLabel:'侧屏' },
    { id:'W09', type:'w2-check',      title:'W2实时观察',   category:'decision',tier:'tick',   defaultSize:{w:10,h:7},  dataPaths:['sentiment_nodes','sentiment.情绪值','sentiment.昨日涨停收益','trend_pool','live_quotes','live_index','rule_state'], priority:'P1', usageRole:'secondary_evidence', usageLabel:'侧屏' },
    // 数据类
    { id:'W04', type:'market-overview',title:'市场全景',    category:'data',     tier:'tick',   defaultSize:{w:6,h:3},  dataPaths:['live_index','market.涨跌比','market.涨停家数','market.跌停家数','iwencai.昨日涨停收益','iwencai.连板收益','iwencai.炸板收益','iwencai.涨停家数','iwencai.跌停家数'], priority:'P0', usageRole:'first_screen', usageLabel:'首屏' },
    { id:'W05', type:'sentiment-dash',title:'情绪节点对比', category:'data',     tier:'manual', defaultSize:{w:8,h:5},  dataPaths:['sentiment_nodes','live_index','iwencai.涨停家数','iwencai.跌停家数','iwencai.昨日涨停收益','iwencai.连板收益','iwencai.炸板收益'], priority:'P0', usageRole:'review_low', usageLabel:'复盘' },
    { id:'W10', type:'sector-heat',   title:'板块热力图',   category:'data',     tier:'fast',   defaultSize:{w:8,h:6},  dataPaths:['sectors','sector_inflow','live_sectors','lianban_pool','trend_pool','live_quotes','decision.锚定股状态'], priority:'P1', usageRole:'secondary_evidence', usageLabel:'侧屏' },
    { id:'W11', type:'volume-bars',   title:'15min量价图', category:'data',     tier:'slow',   defaultSize:{w:10,h:6}, dataPaths:['上证15min','深证15min','创业15min'], priority:'P1', usageRole:'review_low', usageLabel:'复盘' },
    { id:'W12', type:'lianban-pool',  title:'连板自选池',   category:'data',     tier:'tick',   defaultSize:{w:12,h:4}, dataPaths:['lianban_pool','live_quotes'], priority:'P1', usageRole:'secondary_evidence', usageLabel:'侧屏' },
    { id:'W13', type:'trend-pool',    title:'趋势自选池',   category:'data',     tier:'tick',   defaultSize:{w:12,h:4}, dataPaths:['trend_pool','live_quotes'], priority:'P1', usageRole:'secondary_evidence', usageLabel:'侧屏' },
    // 风控类
    { id:'W14', type:'risk-panel',    title:'账户风控',     category:'risk',     tier:'tick', defaultSize:{w:4,h:5}, dataPaths:['risk.单日熔断线','risk.周累计回撤','risk.月累计回撤','risk.连亏天数','positions','live_quotes','pnl_live','rule_state'], priority:'P0', usageRole:'first_screen', usageLabel:'首屏' },
    { id:'W15', type:'positions',     title:'持仓快照',       category:'risk',     tier:'tick',defaultSize:{w:12,h:6}, dataPaths:['positions','decision.今日操作','live_quotes','pnl_live'], priority:'P0', usageRole:'first_screen', usageLabel:'首屏' },
    // 工具类
    { id:'W16', type:'input-panel',   title:'报数面板',     category:'tool',     tier:'manual', defaultSize:{w:12,h:2}, dataPaths:[], priority:'P1', usageRole:'hidden_eval', usageLabel:'隐藏' },
    // 决策类（v2.1 新增）
    { id:'W17', type:'today-ops',     title:'今日操作',     category:'decision', tier:'manual', defaultSize:{w:6,h:3}, dataPaths:['decision.今日操作','pnl_live'], priority:'P1', usageRole:'review_low', usageLabel:'复盘' },
    { id:'W18', type:'anchor-stocks', title:'锚定股状态',   category:'decision', tier:'tick',   defaultSize:{w:6,h:3}, dataPaths:['decision.锚定股状态','live_quotes'], priority:'P1', usageRole:'review_low', usageLabel:'复盘' },
    { id:'W19', type:'midday-review',title:'午盘复核',     category:'decision', tier:'manual', defaultSize:{w:4,h:4}, dataPaths:['decision.盘中','rule_state'], priority:'P1', usageRole:'review_low', usageLabel:'复盘' },
    { id:'W20', type:'llm-monitor',  title:'研判摘要',     category:'decision', tier:'manual', defaultSize:{w:8,h:6}, dataPaths:[], priority:'P1', usageRole:'review_low', usageLabel:'复盘' },
    { id:'W21', type:'zt-echelon',  title:'涨停梯队',   category:'data',     tier:'tick',   defaultSize:{w:8,h:7}, dataPaths:['hot_list','iwencai.连板股列表'], priority:'P1', usageRole:'secondary_evidence', usageLabel:'侧屏' },
    { id:'W22', type:'pnl-curve',   title:'账户收益曲线', category:'data',     tier:'fast',   defaultSize:{w:12,h:10}, dataPaths:['live_quotes','pnl_live'], priority:'P1', usageRole:'first_screen', usageLabel:'首屏' },
    { id:'W23', type:'trade-review',title:'逐笔复盘',     category:'data',     tier:'manual', defaultSize:{w:12,h:5},  dataPaths:[], priority:'P1', usageRole:'review_low', usageLabel:'复盘' },
    { id:'W24', type:'trade-tickets',title:'交易票据',     category:'risk',     tier:'manual', defaultSize:{w:12,h:5},  dataPaths:['trade_tickets'], priority:'P0', usageRole:'first_screen', usageLabel:'首屏' },
    { id:'W25', type:'evidence-board',title:'作战态势',     category:'decision', tier:'tick',   defaultSize:{w:12,h:5},  dataPaths:['pnl_live','trade_tickets','sentiment','iwencai','rule_state','live_index'], priority:'P0', usageRole:'first_screen', usageLabel:'首屏' },
  ];

  // 注册组件 class
  function register(id, WidgetClass) {
    var meta = widgets.find(function(w) { return w.id === id; });
    if (!meta) { console.error('WidgetRegistry: unknown id ' + id); return; }
    registry[id] = { meta: meta, Class: WidgetClass };
  }

  // 获取全部元数据
  function list() {
    return widgets.map(function(w) { return Object.assign({}, w); });
  }

  // 按类型分组
  function listByCategory() {
    return {
      decision: widgets.filter(function(w) { return w.category === 'decision'; }),
      data:     widgets.filter(function(w) { return w.category === 'data'; }),
      risk:     widgets.filter(function(w) { return w.category === 'risk'; }),
      tool:     widgets.filter(function(w) { return w.category === 'tool'; }),
    };
  }

  // 按 Dashboard 3.0 使用位置分组
  function listByUsageRole() {
    return {
      first_screen: widgets.filter(function(w) { return w.usageRole === 'first_screen'; }),
      secondary_evidence: widgets.filter(function(w) { return w.usageRole === 'secondary_evidence'; }),
      review_low: widgets.filter(function(w) { return w.usageRole === 'review_low'; }),
      hidden_eval: widgets.filter(function(w) { return w.usageRole === 'hidden_eval'; }),
    };
  }

  function isFirstScreen(id) {
    var w = widgets.find(function(w) { return w.id === id; });
    return !!(w && w.usageRole === 'first_screen');
  }

  // 获取单个组件的注册信息
  function get(id) {
    return registry[id] || null;
  }

  // 获取元数据
  function getMeta(id) {
    var w = widgets.find(function(w) { return w.id === id; });
    return w ? Object.assign({}, w) : null;
  }

  return {
    register: register,
    list: list,
    listByCategory: listByCategory,
    listByUsageRole: listByUsageRole,
    isFirstScreen: isFirstScreen,
    get: get,
    getMeta: getMeta,
  };
})();
