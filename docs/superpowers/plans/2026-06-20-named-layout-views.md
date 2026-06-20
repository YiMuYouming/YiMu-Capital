# Named Layout Views Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local named layout view system so the user can create blank canvases, save named layouts, switch, rename, delete, set default, and restore layouts after refresh.

**Architecture:** Keep the current GridStack and widget registry. Add a small layout-view layer in `index.html` that serializes grid state into new `localStorage` keys declared in `store.js`, while keeping Phase 1 cockpit as a built-in starter template. Do not change backend APIs, account SSOT, ticket flows, health gates, quotes, or W22 PnL calculations.

**Tech Stack:** Plain HTML/CSS/JavaScript, GridStack v12 CDN, browser `localStorage`, Python `unittest` string/runtime checks, Playwright for final browser verification.

---

## File Structure

- Modify `store.js`
  - Add localStorage keys for named layouts, active layout id, and default layout id.

- Modify `index.html`
  - Add layout-view helpers: read/write records, capture grid layout, load layout items, create blank canvas, save-as, rename, delete, set default, refresh selector.
  - Convert the layout menu from fixed buttons to view management controls.
  - Keep `applyCockpitLayout()` as a built-in template loader.
  - Stop required-widget injection for named layouts and blank canvases.

- Modify `css/theme.css`
  - Add compact menu styling for the layout selector and management buttons.

- Modify `tests/test_frontend_rule_state.py`
  - Add string and runtime checks for storage keys, behavior helpers, blank view behavior, Phase 1 compatibility, and W22 preservation.

## Task 1: Storage Keys And Spec Guards

**Files:**
- Modify: `store.js`
- Modify: `tests/test_frontend_rule_state.py`

- [ ] **Step 1: Write failing tests**

Add tests to `WidgetPanelUxTest`:

```python
def test_named_layout_storage_keys_are_declared(self):
    store = (ROOT / "store.js").read_text(encoding="utf-8")
    self.assertIn("namedLayouts: 'dash_named_layouts_v1'", store)
    self.assertIn("activeLayoutId: 'dash_active_layout_id'", store)
    self.assertIn("defaultLayoutId: 'dash_default_layout_id'", store)
```

- [ ] **Step 2: Run the focused test**

Run:

```bash
python3 -m unittest tests.test_frontend_rule_state.WidgetPanelUxTest.test_named_layout_storage_keys_are_declared
```

Expected: FAIL because the new keys do not exist.

- [ ] **Step 3: Add keys**

In `store.js`, extend `STORAGE_KEYS`:

```javascript
  namedLayouts: 'dash_named_layouts_v1',
  activeLayoutId: 'dash_active_layout_id',
  defaultLayoutId: 'dash_default_layout_id',
```

- [ ] **Step 4: Verify green**

Run the same focused test. Expected: PASS.

## Task 2: Named Layout Core Helpers

**Files:**
- Modify: `index.html`
- Modify: `tests/test_frontend_rule_state.py`

- [ ] **Step 1: Write failing tests**

Add tests checking the required helper names and migration boundaries:

```python
def test_named_layout_core_helpers_exist(self):
    index = (ROOT / "index.html").read_text(encoding="utf-8")
    for name in [
        "_readNamedLayouts",
        "_writeNamedLayouts",
        "_captureCurrentLayout",
        "_loadLayoutItems",
        "_saveCurrentLayoutView",
        "_saveCurrentLayoutAs",
        "_renameCurrentLayoutView",
        "_deleteCurrentLayoutView",
        "_setCurrentLayoutDefault",
        "_createBlankLayoutView",
        "_refreshLayoutViewSelector",
    ]:
        self.assertIn("function " + name, index)

def test_named_layouts_do_not_use_required_widget_injection(self):
    index = (ROOT / "index.html").read_text(encoding="utf-8")
    self.assertIn("function _loadLayoutItems(items, options)", index)
    load_body = index[index.index("function _loadLayoutItems(items, options)"):index.index("function applyCockpitLayout", index.index("function _loadLayoutItems(items, options)"))]
    self.assertNotIn("_ensureRequiredLayoutWidgets()", load_body)
```

- [ ] **Step 2: Run tests**

Run:

```bash
python3 -m unittest tests.test_frontend_rule_state.WidgetPanelUxTest.test_named_layout_core_helpers_exist tests.test_frontend_rule_state.WidgetPanelUxTest.test_named_layouts_do_not_use_required_widget_injection
```

Expected: FAIL because helpers do not exist.

- [ ] **Step 3: Implement helpers**

Add helpers near existing layout persistence code:

```javascript
function _readNamedLayouts() {
  try {
    var raw = localStorage.getItem(STORAGE_KEYS.namedLayouts);
    var parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch(e) {
    return {};
  }
}

function _writeNamedLayouts(layouts) {
  localStorage.setItem(STORAGE_KEYS.namedLayouts, JSON.stringify(layouts || {}));
}

function _newLayoutId() {
  return 'layout_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 7);
}

function _captureCurrentLayout() {
  return grid ? grid.save(false).map(function(item) {
    return { id:item.id, x:item.x||0, y:item.y||0, w:item.w||1, h:item.h||1 };
  }) : [];
}

function _loadLayoutItems(items, options) {
  options = options || {};
  _closeTransientSurfaces();
  _suppressLayoutSave = true;
  try {
    _clearGridWidgets();
    (items || []).forEach(_mountLayoutWidget);
  } finally {
    _suppressLayoutSave = false;
  }
  document.body.classList.toggle('cockpit-mode', options.cockpit === true);
}
```

- [ ] **Step 4: Verify green**

Run the focused tests. Expected: PASS.

## Task 3: Save, Switch, Rename, Delete, Default, Blank

**Files:**
- Modify: `index.html`
- Modify: `tests/test_frontend_rule_state.py`

- [ ] **Step 1: Write failing tests**

Add tests for the user-visible workflow:

```python
def test_named_layout_view_actions_are_wired(self):
    index = (ROOT / "index.html").read_text(encoding="utf-8")
    for element_id in [
        "layoutViewSelect",
        "blankLayoutBtn",
        "saveAsLayoutBtn",
        "renameLayoutBtn",
        "deleteLayoutBtn",
        "defaultLayoutBtn",
        "builtInCockpitBtn",
    ]:
        self.assertIn('id="' + element_id + '"', index)
    self.assertIn("_saveCurrentLayoutView()", index)
    self.assertIn("_saveCurrentLayoutAs()", index)
    self.assertIn("_renameCurrentLayoutView()", index)
    self.assertIn("_deleteCurrentLayoutView()", index)
    self.assertIn("_setCurrentLayoutDefault()", index)
    self.assertIn("_createBlankLayoutView()", index)

def test_named_layout_refresh_prefers_active_then_default(self):
    index = (ROOT / "index.html").read_text(encoding="utf-8")
    self.assertIn("localStorage.getItem(STORAGE_KEYS.activeLayoutId)", index)
    self.assertIn("localStorage.getItem(STORAGE_KEYS.defaultLayoutId)", index)
    self.assertIn("_loadActiveNamedLayoutOrFallback()", index)
```

- [ ] **Step 2: Run tests**

Run the two focused tests. Expected: FAIL because UI and actions are not wired.

- [ ] **Step 3: Implement behavior**

Implement:

- `_getCurrentLayoutId()`
- `_setCurrentLayoutId(id)`
- `_saveCurrentLayoutView()`
- `_saveCurrentLayoutAs()`
- `_renameCurrentLayoutView()`
- `_deleteCurrentLayoutView()`
- `_setCurrentLayoutDefault()`
- `_createBlankLayoutView()`
- `_loadNamedLayout(id)`
- `_loadActiveNamedLayoutOrFallback()`
- `_refreshLayoutViewSelector()`

Use `prompt()` for naming and `confirm()` for deletion in this phase to keep scope small.

- [ ] **Step 4: Replace initial load path**

Change `initGrid()` to call `_loadActiveNamedLayoutOrFallback()` instead of `_loadSavedLayout()` directly. Keep `_loadSavedLayout()` only as a legacy migration helper.

- [ ] **Step 5: Verify green**

Run the focused tests. Expected: PASS.

## Task 4: Layout Menu UI And Styling

**Files:**
- Modify: `index.html`
- Modify: `css/theme.css`
- Modify: `tests/test_frontend_rule_state.py`

- [ ] **Step 1: Write failing tests**

Add tests:

```python
def test_layout_menu_exposes_named_view_controls(self):
    index = (ROOT / "index.html").read_text(encoding="utf-8")
    theme = (ROOT / "css" / "theme.css").read_text(encoding="utf-8")
    self.assertIn("layout-view-select", index)
    self.assertIn("layout-menu-grid", index)
    self.assertIn(".layout-view-select", theme)
    self.assertIn(".layout-menu-grid", theme)
```

- [ ] **Step 2: Run test**

Run the focused test. Expected: FAIL because styling is missing.

- [ ] **Step 3: Implement menu markup and CSS**

Replace the layout popover buttons with:

```html
<select class="layout-view-select" id="layoutViewSelect" title="切换布局视图"></select>
<div class="layout-menu-grid">
  <button class="topbar-layout-btn" id="blankLayoutBtn">新建空白</button>
  <button class="topbar-layout-btn" id="saveLayoutBtn" title="保存当前布局 (Ctrl+S)">保存</button>
  <button class="topbar-layout-btn" id="saveAsLayoutBtn">另存为</button>
  <button class="topbar-layout-btn" id="renameLayoutBtn">重命名</button>
  <button class="topbar-layout-btn" id="deleteLayoutBtn">删除</button>
  <button class="topbar-layout-btn" id="defaultLayoutBtn">设为默认</button>
  <button class="topbar-layout-btn" id="builtInCockpitBtn">内置驾驶舱</button>
  <button class="topbar-layout-btn" id="exportLayoutBtn">导出</button>
  <button class="topbar-layout-btn" id="importLayoutBtn">导入</button>
</div>
```

Add compact menu CSS that preserves the dashboard's utilitarian density.

- [ ] **Step 4: Verify green**

Run the focused test. Expected: PASS.

## Task 5: Regression, Browser Verification, Review

**Files:**
- Verify only unless fixes are required.

- [ ] **Step 1: Run focused frontend tests**

```bash
python3 -m unittest tests.test_frontend_rule_state.WidgetPanelUxTest tests.test_frontend_rule_state.TransientSurfaceUxTest
```

Expected: PASS.

- [ ] **Step 2: Run full frontend rule-state tests**

```bash
python3 -m unittest tests.test_frontend_rule_state
```

Expected: PASS.

- [ ] **Step 3: Run diff hygiene**

```bash
git diff --check
git status --short --branch
```

Expected: no whitespace errors; only intended files plus the pre-existing unrelated deleted doc.

- [ ] **Step 4: Browser verification**

Use Playwright against local/production preview:

- Create blank view.
- Add W22.
- Save as `驾驶舱`.
- Refresh and confirm W22 remains.
- Save another layout named `风控面板`.
- Switch, rename, delete, and set default.

- [ ] **Step 5: Review gate**

Run a read-only review after implementation. Required findings format:

- Functional correctness
- Code quality
- Interaction clarity
- Phase 1 compatibility

- [ ] **Step 6: Commit and push**

```bash
git add store.js index.html css/theme.css tests/test_frontend_rule_state.py docs/superpowers/specs/2026-06-20-named-layout-views-design.md docs/superpowers/plans/2026-06-20-named-layout-views.md
git commit -m "Add named layout view system"
git push
```
