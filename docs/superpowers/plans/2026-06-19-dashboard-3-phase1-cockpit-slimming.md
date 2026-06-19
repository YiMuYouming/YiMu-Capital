# Dashboard 3.0 Phase 1 Cockpit Slimming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Dashboard 3.0 Phase 1 by slimming the default intraday cockpit, adding explicit widget usage metadata, and making secondary evidence modules easy to open without cluttering the first screen.

**Architecture:** Keep the existing GridStack, DataStore, and widget system. Add lightweight metadata to `widget-registry.js`, then consume that metadata in `index.html` to drive default cockpit layout, core/secondary visibility, topbar shortcuts, and widget picker labels. No account, ticket, health, or data-source API behavior changes in this phase.

**Tech Stack:** Plain HTML/CSS/JavaScript, GridStack v12 CDN, Python `unittest` with Node-based frontend render/string tests.

---

## Scope

This plan implements only Phase 1 from `docs/superpowers/specs/2026-06-19-dashboard-3-ai-ops-cockpit-design.md`.

Included:

- Widget usage roles for first-screen, secondary evidence, review/low-frequency, and hidden/evaluation modules.
- Intraday cockpit default layout with 6 first-screen widgets.
- Widget picker labels that show whether a module is first-screen, secondary, review, or hidden/evaluation.
- Topbar high-frequency shortcut reduction, while preserving the evidence shelf and full component panel.
- Tests and review gates after every task.

Excluded:

- `/api/ai/context`.
- Sidecar agent.
- Review packet automation.
- Any POST behavior or production data changes.
- Any `data/*` git changes.

## File Structure

- Modify `widget-registry.js`
  - Owns widget metadata.
  - Add `usageRole` and `usageLabel` to each widget.
  - Add helper methods: `listByUsageRole()` and `isFirstScreen(id)`.

- Modify `index.html`
  - Consume registry metadata for `FIRST_SCREEN_WIDGETS`, `SECONDARY_EVIDENCE_WIDGETS`, and cockpit layout.
  - Reduce topbar direct shortcuts to high-frequency items.
  - Use `usageRole` labels in context menu and widget picker.

- Modify `css/theme.css`
  - Add compact visual treatment for usage-role pills in widget panel/context menu.
  - Keep dense, utilitarian dashboard style.

- Modify `tests/test_frontend_rule_state.py`
  - Add string/Node tests for metadata, layout, topbar shortcuts, and picker labels.

## Task 1: Widget Usage Metadata

**Files:**
- Modify: `widget-registry.js`
- Test: `tests/test_frontend_rule_state.py`

- [ ] **Step 1: Write failing metadata tests**

Add these tests to `WidgetPanelUxTest` in `tests/test_frontend_rule_state.py`:

```python
    def test_widget_registry_declares_dashboard_3_usage_roles(self):
        registry = (ROOT / "widget-registry.js").read_text(encoding="utf-8")
        for role in ["first_screen", "secondary_evidence", "review_low", "hidden_eval"]:
            self.assertIn("usageRole:'" + role + "'", registry)
        for wid in ["W25", "W15", "W24", "W14", "W04", "W22"]:
            self.assertRegex(
                registry,
                r"id:'" + wid + r"'.+usageRole:'first_screen'",
                "first-screen widget missing usageRole: " + wid,
            )
        for wid in ["W08", "W09", "W10", "W12", "W13", "W21", "W06"]:
            self.assertRegex(
                registry,
                r"id:'" + wid + r"'.+usageRole:'secondary_evidence'",
                "secondary evidence widget missing usageRole: " + wid,
            )
        for wid in ["W20", "W23", "W05", "W11", "W17", "W18", "W19"]:
            self.assertRegex(
                registry,
                r"id:'" + wid + r"'.+usageRole:'review_low'",
                "review/low-frequency widget missing usageRole: " + wid,
            )
        for wid in ["W01", "W02", "W03", "W07", "W16"]:
            self.assertRegex(
                registry,
                r"id:'" + wid + r"'.+usageRole:'hidden_eval'",
                "hidden/evaluation widget missing usageRole: " + wid,
            )

    def test_widget_registry_exposes_usage_helpers(self):
        registry = (ROOT / "widget-registry.js").read_text(encoding="utf-8")
        self.assertIn("function listByUsageRole()", registry)
        self.assertIn("function isFirstScreen(id)", registry)
        self.assertIn("listByUsageRole: listByUsageRole", registry)
        self.assertIn("isFirstScreen: isFirstScreen", registry)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_frontend_rule_state.WidgetPanelUxTest
```

Expected:

- FAIL.
- Failure should mention missing `usageRole:'first_screen'` or missing helper functions.

- [ ] **Step 3: Add metadata and helper methods**

In `widget-registry.js`, add `usageRole` and `usageLabel` to every widget object:

```javascript
usageRole:'first_screen', usageLabel:'首屏'
usageRole:'secondary_evidence', usageLabel:'侧屏'
usageRole:'review_low', usageLabel:'复盘'
usageRole:'hidden_eval', usageLabel:'隐藏'
```

Use this mapping:

```text
first_screen: W25, W15, W24, W14, W04, W22
secondary_evidence: W08, W09, W10, W12, W13, W21, W06
review_low: W20, W23, W05, W11, W17, W18, W19
hidden_eval: W01, W02, W03, W07, W16
```

Then add these helper functions before `return`:

```javascript
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
```

Expose them in the returned object:

```javascript
    listByUsageRole: listByUsageRole,
    isFirstScreen: isFirstScreen,
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```bash
python3 -m unittest tests.test_frontend_rule_state.WidgetPanelUxTest
```

Expected:

- PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add widget-registry.js tests/test_frontend_rule_state.py
git commit -m "Add dashboard widget usage roles"
```

## Task 2: Intraday Cockpit Layout From Usage Roles

**Files:**
- Modify: `index.html`
- Test: `tests/test_frontend_rule_state.py`

- [ ] **Step 1: Write failing layout tests**

Add this test to `WidgetPanelUxTest`:

```python
    def test_intraday_cockpit_layout_uses_first_screen_widgets_only(self):
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("FIRST_SCREEN_WIDGETS = ['W25','W15','W24','W14','W04','W22']", index)
        self.assertIn("SECONDARY_EVIDENCE_WIDGETS = ['W08','W09','W10','W12','W13','W21','W06']", index)
        self.assertIn("EVIDENCE_SHELF_WIDGETS = SECONDARY_EVIDENCE_WIDGETS", index)
        self.assertIn("COCKPIT_LAYOUT = [", index)
        for wid in ["W25", "W15", "W24", "W14", "W04", "W22"]:
            self.assertRegex(index, r"\\{ id:'" + wid + r"', x:\\d+, y:\\d+, w:\\d+, h:\\d+ \\}")
        for wid in ["W08", "W09", "W10", "W12", "W13", "W21", "W06"]:
            self.assertNotRegex(index, r"COCKPIT_LAYOUT = \\[[\\s\\S]*\\{ id:'" + wid + r"'")
        self.assertIn("WidgetRegistry.isFirstScreen(id)", index)
        self.assertIn("FIRST_SCREEN_WIDGETS.forEach", index)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_frontend_rule_state.WidgetPanelUxTest
```

Expected:

- FAIL.
- Failure should mention missing `FIRST_SCREEN_WIDGETS` or current `CORE_IDS`/`EVIDENCE_SHELF_WIDGETS` definitions.

- [ ] **Step 3: Update cockpit constants and core-widget logic**

In `index.html`, replace current constants:

```javascript
var REQUIRED_LAYOUT_WIDGETS = ['W25', 'W15', 'W24'];
var CORE_IDS = ['W25','W04','W07','W08','W09','W14','W24','W15','W22'];
var EVIDENCE_SHELF_WIDGETS = ['W10', 'W12', 'W13', 'W21'];
```

with:

```javascript
var FIRST_SCREEN_WIDGETS = ['W25','W15','W24','W14','W04','W22'];
var SECONDARY_EVIDENCE_WIDGETS = ['W08','W09','W10','W12','W13','W21','W06'];
var REQUIRED_LAYOUT_WIDGETS = ['W25', 'W15', 'W24'];
var CORE_IDS = FIRST_SCREEN_WIDGETS.slice();
var EVIDENCE_SHELF_WIDGETS = SECONDARY_EVIDENCE_WIDGETS;
```

Replace `COCKPIT_LAYOUT` with:

```javascript
var COCKPIT_LAYOUT = [
  { id:'W25', x:0, y:0, w:12, h:7 },
  { id:'W15', x:0, y:7, w:5, h:6 },
  { id:'W24', x:5, y:7, w:4, h:6 },
  { id:'W14', x:9, y:7, w:3, h:6 },
  { id:'W04', x:0, y:13, w:4, h:3 },
  { id:'W22', x:4, y:13, w:8, h:6 }
];
```

In `_mountLayoutWidget`, replace:

```javascript
  if (CORE_IDS.indexOf(id) >= 0) gsItem.classList.add('core-widget');
```

with:

```javascript
  if (WidgetRegistry.isFirstScreen && WidgetRegistry.isFirstScreen(id)) gsItem.classList.add('core-widget');
```

In `initCompactMode`, replace direct `CORE_IDS.forEach` with:

```javascript
  FIRST_SCREEN_WIDGETS.forEach(function(id) {
```

Also update the wrapper around `_addWidgetToGrid` so it uses:

```javascript
      if (el && WidgetRegistry.isFirstScreen && WidgetRegistry.isFirstScreen(widgetId)) el.classList.add('core-widget');
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```bash
python3 -m unittest tests.test_frontend_rule_state.WidgetPanelUxTest
```

Expected:

- PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add index.html tests/test_frontend_rule_state.py
git commit -m "Slim intraday cockpit layout"
```

## Task 3: Widget Picker And Topbar Slimming

**Files:**
- Modify: `index.html`
- Modify: `css/theme.css`
- Test: `tests/test_frontend_rule_state.py`

- [ ] **Step 1: Write failing UX tests**

Add these tests to `WidgetPanelUxTest`:

```python
    def test_topbar_keeps_high_frequency_shortcuts_only(self):
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        topbar = index[index.index('<div class="topbar-shortcuts"'):index.index('</div>', index.index('<div class="topbar-shortcuts"'))]
        for wid in ["W25", "W04", "W24", "W15"]:
            self.assertIn('data-widget="' + wid + '"', topbar)
        for wid in ["W12", "W13"]:
            self.assertNotIn('data-widget="' + wid + '"', topbar)
        self.assertIn('id="evidenceShelfBtn"', topbar)
        self.assertIn('id="addWidgetBtn"', topbar)
        self.assertIn('id="compactBtn"', topbar)

    def test_widget_panel_surfaces_usage_role_pills(self):
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        theme = (ROOT / "css" / "theme.css").read_text(encoding="utf-8")
        self.assertIn("usageRoleLabels", index)
        self.assertIn("item-pill-role", index)
        self.assertIn("w.usageRole", index)
        self.assertIn(".item-pill-role", theme)
        self.assertIn('[data-usage-role="first_screen"]', index)
        self.assertIn('[data-usage-role="secondary_evidence"]', index)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_frontend_rule_state.WidgetPanelUxTest
```

Expected:

- FAIL.
- Failure should mention W12/W13 still in topbar or missing `usageRoleLabels`.

- [ ] **Step 3: Reduce topbar direct shortcuts**

In `index.html`, remove the direct topbar shortcut buttons for W12 and W13:

```html
<button class="topbar-shortcut topbar-shortcut-data" data-widget="W12" title="W12 连板池"><b>W12</b><span>连板</span></button>
<button class="topbar-shortcut topbar-shortcut-data" data-widget="W13" title="W13 趋势池"><b>W13</b><span>趋势</span></button>
```

Keep:

```html
<button id="evidenceShelfBtn" class="topbar-shortcut topbar-shortcut-data" title="候选与市场证据副屏"><b>E</b><span>证据</span></button>
```

- [ ] **Step 4: Add usage labels to picker and context menu**

In `_showContextMenu`, add:

```javascript
  var usageRoleLabels = { first_screen: '首屏', secondary_evidence: '侧屏', review_low: '复盘', hidden_eval: '隐藏' };
```

Change context menu item markup to include `data-usage-role` and role text:

```javascript
      html += '<div class="context-menu-item" data-widget="' + w.id + '" data-category="' + w.category + '" data-usage-role="' + (w.usageRole || '') + '">' +
        '<span>' + w.title + '</span><b>' + (usageRoleLabels[w.usageRole] || w.id) + ' · ' + w.id + '</b></div>';
```

In `_showWidgetPanel`, add:

```javascript
  var usageRoleLabels = { first_screen: '首屏', secondary_evidence: '侧屏', review_low: '复盘', hidden_eval: '隐藏' };
```

Change widget panel item markup to include:

```javascript
      html += '<div class="widget-panel-item" data-widget="' + w.id + '" data-category="' + w.category + '" data-usage-role="' + (w.usageRole || '') + '">' +
```

and add a usage-role pill before priority:

```javascript
          '<span class="item-pill item-pill-role">' + (usageRoleLabels[w.usageRole] || '模块') + '</span>' +
```

- [ ] **Step 5: Add compact CSS**

In `css/theme.css`, near `.widget-panel-item .item-pill-priority`, add:

```css
.widget-panel-item .item-pill-role{font-weight:850;color:var(--info);background:var(--info-bg);border-color:rgba(37,99,235,.18)}
.widget-panel-item[data-usage-role="first_screen"] .item-pill-role{color:var(--up);background:var(--up-bg);border-color:rgba(220,38,38,.18)}
.widget-panel-item[data-usage-role="secondary_evidence"] .item-pill-role{color:var(--info);background:var(--info-bg);border-color:rgba(37,99,235,.18)}
.widget-panel-item[data-usage-role="review_low"] .item-pill-role{color:var(--accent);background:var(--accent-bg);border-color:rgba(217,119,6,.18)}
.widget-panel-item[data-usage-role="hidden_eval"] .item-pill-role{color:var(--text-disabled);background:var(--bg-base);border-color:var(--border-light)}
.context-menu-item[data-usage-role="first_screen"] b{color:var(--up)}
.context-menu-item[data-usage-role="secondary_evidence"] b{color:var(--info)}
.context-menu-item[data-usage-role="review_low"] b{color:var(--accent)}
.context-menu-item[data-usage-role="hidden_eval"] b{color:var(--text-disabled)}
```

- [ ] **Step 6: Run tests and verify they pass**

Run:

```bash
python3 -m unittest tests.test_frontend_rule_state.WidgetPanelUxTest
```

Expected:

- PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add index.html css/theme.css tests/test_frontend_rule_state.py
git commit -m "Surface cockpit widget roles"
```

## Task 4: Phase 1 Regression Sweep And Documentation Update

**Files:**
- Modify: `docs/superpowers/specs/2026-06-19-dashboard-3-ai-ops-cockpit-design.md`
- Test: existing frontend test suite

- [ ] **Step 1: Add Phase 1 implementation note**

Append this section to `docs/superpowers/specs/2026-06-19-dashboard-3-ai-ops-cockpit-design.md`:

```markdown
## Phase 1 Implementation Note

Phase 1 implemented the cockpit slimming layer:

- Widgets now declare `usageRole` metadata.
- Intraday cockpit defaults to six first-screen modules: W25, W15, W24, W14, W04, W22.
- W08/W09/W10/W12/W13/W21/W06 remain available through the evidence shelf or component panel.
- Topbar direct shortcuts are limited to high-frequency modules plus evidence shelf and full component panel.
- No account SSOT, ticket API, health gate, data source, or POST behavior changed.
```

- [ ] **Step 2: Run focused frontend regression**

Run:

```bash
python3 -m unittest tests.test_frontend_rule_state.WidgetPanelUxTest tests.test_frontend_rule_state.TransientSurfaceUxTest
```

Expected:

- PASS.

- [ ] **Step 3: Run full frontend rule-state regression**

Run:

```bash
python3 -m unittest tests.test_frontend_rule_state
```

Expected:

- PASS.

- [ ] **Step 4: Check diff hygiene**

Run:

```bash
git diff --check
git status --short
```

Expected:

- `git diff --check` exits 0.
- `git status --short` shows only intended files.

- [ ] **Step 5: Commit**

Run:

```bash
git add docs/superpowers/specs/2026-06-19-dashboard-3-ai-ops-cockpit-design.md
git commit -m "Document dashboard phase 1 cockpit slimming"
```

## Subagent Review Gates

After each implementation task:

1. Dispatch a spec-compliance reviewer subagent.
   - Ask it to compare the task requirements with the current diff.
   - It must report Critical/Important/Minor findings.
   - Critical and Important issues must be fixed before continuing.

2. Dispatch a code/interaction reviewer subagent.
   - Ask it to review functional behavior, code quality, and cockpit interaction clarity.
   - It must inspect the diff and tests, not rely on worker claims.
   - Critical and Important issues must be fixed before continuing.

3. Re-run the task's verification command after fixes.

## Final Verification

Before reporting Phase 1 complete:

```bash
python3 -m unittest tests.test_frontend_rule_state
git diff --check
git status --short --branch
```

Expected:

- Tests pass.
- Diff check exits 0.
- Branch is `codex/dashboard-3-phase1`.
- Working tree is clean after commits.
