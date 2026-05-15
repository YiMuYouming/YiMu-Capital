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
    this._fsState = 0;         // 0=普通 1=内容适配 2=全屏铺满
  }

  /** 处理全屏退出事件（全局绑定一次） */
  static _initFullscreenESC() {
    if (YiMuWidget._escBound) return;
    YiMuWidget._escBound = true;
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape') {
        var fsEl = document.querySelector('.widget-fullscreen');
        if (fsEl) {
          var id = fsEl.closest('[gs-id]');
          var inst = id && window.widgetInstances && window.widgetInstances[id.getAttribute('gs-id')];
          if (inst && inst._fsState > 0) inst._exitFullscreen();
        }
      }
    });
  }

  // === 生命周期 ===

  /** GridStack 挂载：创建容器 → 渲染 → 订阅数据 → 启动定时器 */
  mount(container) {
    this._container = container;
    this._renderShell();   // 标题栏 + body 骨架
    this._renderBody();    // 内容（try-catch 隔离）
    this._subscribe();     // DataStore 订阅
    this._startTimers();   // 定时刷新
    YiMuWidget._initFullscreenESC(); // 全局 ESC 监听
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
          '<button class="widget-btn" data-action="fullscreen" title="内容展开" id="fs_' + this.id + '">□</button>' +
          '<button class="widget-btn" data-action="refresh" title="刷新">↻</button>' +
          '<button class="widget-btn" data-action="remove" title="删除">×</button>' +
        '</span>' +
      '</div>' +
      '<div class="widget-body" id="body_' + this.id + '">' +
        '<div class="widget-skeleton">' +
          '<div class="skeleton-bar" style="width:60%;height:12px;margin:8px 0;border-radius:4px"></div>' +
          '<div class="skeleton-bar" style="width:40%;height:12px;margin:8px 0;border-radius:4px"></div>' +
          '<div class="skeleton-bar" style="width:50%;height:12px;margin:8px 0;border-radius:4px"></div>' +
        '</div>' +
      '</div>' +
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
      if (action === 'fullscreen') self._toggleFullscreen();
      if (action === 'remove') self._triggerRemove();
    });
  }

  _toggleCollapse() {
    var body = this._container && this._container.querySelector('.widget-body');
    if (body) {
      body.style.display = body.style.display === 'none' ? '' : 'none';
    }
  }

  /** 全屏按钮：三态切换 普通→内容适配→全屏铺满→退出 */
  _toggleFullscreen() {
    if (!this._container) return;
    var self = this;
    var fsBtn = this._container.querySelector('[data-action="fullscreen"]');

    if (this._fsState === 0) {
      // 状态0→1：内容适配（居中按比例展开，内容完整可见）
      this._fsState = 1;
      var gsItem = this._container.closest('.grid-stack-item');
      if (!gsItem) return;
      var gridWrap = document.querySelector('.grid-stack');
      var gsRect = gridWrap ? gridWrap.getBoundingClientRect() : null;
      var ratio = this.defaultSize.w / this.defaultSize.h;
      this._container.style.setProperty('--fs-ratio', ratio);
      this._container.style.setProperty('--fs-origin-left', (gsRect ? gsRect.left : 0) + 'px');
      this._container.style.setProperty('--fs-origin-top', (gsRect ? gsRect.top : 0) + 'px');
      this._container.classList.add('widget-fullscreen', 'fs-fit');
      document.body.classList.add('has-fullscreen');
      if (fsBtn) { fsBtn.textContent = '⛶'; fsBtn.title = '全屏铺满'; }
      requestAnimationFrame(function() { self._renderBody(); });
    } else if (this._fsState === 1) {
      // 状态1→2：全屏铺满
      this._fsState = 2;
      this._container.classList.remove('fs-fit');
      this._container.classList.add('fs-cover');
      if (fsBtn) { fsBtn.textContent = '✕'; fsBtn.title = '退出 (ESC)'; }
      requestAnimationFrame(function() { self._renderBody(); });
    } else {
      // 状态2→0：退出
      this._exitFullscreen();
    }
  }

  /** 直接退出全屏（ESC 或按钮点击） */
  _exitFullscreen() {
    if (!this._container || this._fsState === 0) return;
    this._fsState = 0;
    var cls = this._container.classList;
    var fsBtn = this._container.querySelector('[data-action="fullscreen"]');
    cls.add('fs-exit');
    document.body.classList.remove('has-fullscreen');
    this._renderBody();
    if (fsBtn) { fsBtn.textContent = '□'; fsBtn.title = '内容展开'; }
    var self = this;
    setTimeout(function() {
      cls.remove('widget-fullscreen', 'fs-exit', 'fs-fit', 'fs-cover');
      self._container.style.removeProperty('--fs-ratio');
      self._container.style.removeProperty('--fs-origin-left');
      self._container.style.removeProperty('--fs-origin-top');
    }, 280);
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
