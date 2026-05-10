// widget-base.js — 弈沐资本数据看板 v2.0 组件基类
// 生命周期：register → instantiate → mount → (resize/refresh repeat) → unmount
// v2.0: try-catch 错误隔离 + 拖拽期间暂停刷新
'use strict';

var isDragging = false;  // GridStack 拖拽状态（跨组件共享）

class YiMuWidget {
  constructor(config) {
    this.id = config.id;           // 'W03'
    this.type = config.type;       // 'position-calc'
    this.title = config.title;     // '三层仓位计'
    this.category = config.category; // 'decision' | 'data' | 'risk' | 'tool'
    this.tier = config.tier;       // 'tick'|'fast'|'slow'|'manual'|'daily'
    this.dataPaths = config.dataPaths || [];
    this.defaultSize = config.defaultSize || { w: 4, h: 4 };

    this._container = null;    // GridStack 分配的 DOM 容器
    this._unsubscribers = [];  // DataStore 订阅清理函数
    this._timers = [];          // setInterval/setTimeout 清理
    this._lastRender = null;   // 上次渲染时间戳
  }

  // === 生命周期 ===

  /** GridStack 挂载：创建容器 → 渲染 → 订阅数据 → 启动定时器 */
  mount(container) {
    this._container = container;
    this._renderShell();   // 标题栏 + body 骨架
    this._renderBody();    // 内容（try-catch 隔离）
    this._subscribe();     // DataStore 订阅
    this._startTimers();   // 定时刷新
  }

  /** GridStack 尺寸变化 */
  resize(w, h) {
    // 子类可覆盖 onResize(w, h)
    if (typeof this.onResize === 'function') {
      try { this.onResize(w, h); } catch(e) {
        console.error('[' + this.id + '] onResize error:', e);
      }
    }
  }

  /** GridStack 卸载：取消订阅 → 清除定时器 */
  unmount() {
    this._unsubscribers.forEach(function(fn) { if (typeof fn === 'function') fn(); });
    this._unsubscribers = [];
    this._timers.forEach(function(t) { clearInterval(t); clearTimeout(t); });
    this._timers = [];
    this._container = null;
  }

  // === 内部方法 ===

  /** 渲染组件外壳：标题栏 + body 区域 */
  _renderShell() {
    if (!this._container) return;
    var colorClass = {
      decision: 'color-decision',
      data: 'color-data',
      risk: 'color-risk',
      tool: 'color-tool'
    }[this.category] || 'color-data';

    this._container.innerHTML =
      '<div class="widget-header ' + colorClass + '">' +
        '<span class="widget-title">' + this.title + '</span>' +
        '<span class="data-timestamp" id="ts_' + this.id + '">—</span>' +
        '<span class="widget-actions">' +
          '<button class="widget-btn" data-action="collapse" title="折叠">−</button>' +
          '<button class="widget-btn" data-action="refresh" title="刷新">↻</button>' +
          '<button class="widget-btn" data-action="remove" title="删除">×</button>' +
        '</span>' +
      '</div>' +
      '<div class="widget-body" id="body_' + this.id + '"></div>' +
      '<div class="widget-error" id="err_' + this.id + '" style="display:none">' +
        '<span>组件加载失败</span>' +
      '</div>';

    this._bindShellEvents();
  }

  /** 绑定标题栏按钮事件 */
  _bindShellEvents() {
    if (!this._container) return;
    var self = this;

    self._container.addEventListener('click', function(e) {
      var btn = e.target.closest('.widget-btn');
      if (!btn) return;
      var action = btn.dataset.action;
      if (action === 'refresh') self.refresh();
      if (action === 'collapse') self._toggleCollapse();
      if (action === 'remove') self._triggerRemove();
    });
  }

  _toggleCollapse() {
    var body = this._container && this._container.querySelector('.widget-body');
    if (body) {
      body.style.display = body.style.display === 'none' ? '' : 'none';
    }
  }

  _triggerRemove() {
    // GridStack 移除 + 5 秒撤销 toast
    if (typeof window._removeWidget === 'function') {
      window._removeWidget(this.id);
    }
    this.unmount();
  }

  // === 渲染 body（try-catch 隔离）===
  _renderBody() {
    var body = this._container && this._container.querySelector('.widget-body');
    var errEl = this._container && this._container.querySelector('.widget-error');
    if (!body) return;

    try {
      var data = DataStore.get ? DataStore : null;
      this.render(DataStore.merged || {});
      if (errEl) errEl.style.display = 'none';
      if (body) body.style.display = '';
    } catch(e) {
      console.error('[' + this.id + '] render error:', e);
      if (body) body.style.display = 'none';
      if (errEl) errEl.style.display = '';
    }
  }

  // === 数据订阅 ===
  _subscribe() {
    var self = this;
    if (!self.dataPaths.length) return;

    var unsub = DataStore.subscribe(self.dataPaths, function() {
      if (isDragging) return; // 拖拽期间不刷新
      self._renderBody();
    });
    self._unsubscribers.push(unsub);
  }

  // === 定时器 ===
  _startTimers() {
    var self = this;
    if (self.tier === 'manual' || self.tier === 'daily') return;

    var tierConfig = DataStore.tiers[self.tier];
    if (tierConfig && tierConfig.interval) {
      var timer = setInterval(function() {
        if (!isDragging) {
          DataStore.refresh(self.tier);
        }
      }, tierConfig.interval);
      self._timers.push(timer);
    }
  }

  // === 公共方法（子类可调用）===

  /** 手动刷新 */
  refresh() {
    if (isDragging) return;
    DataStore.refresh(this.tier);
    this._renderBody();
  }

  /** 获取 body DOM 元素 */
  getBody() {
    return this._container && this._container.querySelector('.widget-body');
  }

  /** 获取标题栏元素 */
  getHeader() {
    return this._container && this._container.querySelector('.widget-header');
  }

  /** 更新数据时间戳 */
  updateTimestamp(time) {
    var ts = this._container && this._container.querySelector('.data-timestamp');
    if (ts) {
      var d = time || new Date();
      ts.textContent = d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      // 超过 2 倍刷新间隔则变 warn 色
      var tierConfig = DataStore.tiers[this.tier];
      if (tierConfig && tierConfig.interval && this._lastRender) {
        var elapsed = Date.now() - this._lastRender;
        if (elapsed > tierConfig.interval * 2) {
          ts.classList.add('data-timestamp--stale');
        } else {
          ts.classList.remove('data-timestamp--stale');
        }
      }
    }
    this._lastRender = Date.now();
  }

  /** 子类必须覆盖：渲染内容到 this.getBody() */
  render(data) {
    // 子类实现
  }

  /** 子类可选覆盖：尺寸变化回调 */
  onResize(w, h) {
    // 子类实现
  }
}
