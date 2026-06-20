# Named Layout Views Design

## Background

Dashboard 3.0 Phase 1 made the intraday cockpit smaller and clearer, but a fixed cockpit cannot fit every screen size or every trading day. The next step is to let the user build, name, switch, and maintain multiple saved layouts without changing account, ticket, health, quote, or data-source behavior.

## Goal

Add a local named layout view system:

- Start from a blank canvas.
- Add widgets from high-frequency shortcuts or the full component library.
- Drag and resize widgets.
- Save the current canvas as a named view such as `驾驶舱` or `风控面板`.
- Switch between saved views.
- Rename, delete, and set a default view.
- Restore the last active/default view after refresh.

The system should make Phase 1 more flexible, not reverse it. The built-in cockpit remains available as a starter template, while user-saved layouts become the primary workflow.

## Non-Goals

- No backend API or cloud sync in this phase.
- No POST requests to production services.
- No changes to account SSOT, ticket APIs, health gates, quote collection, or W22 PnL calculations.
- No forced compression or simplification of W22 or other normal widgets.
- No removal of existing components.

## Storage Model

Use browser `localStorage`.

New keys:

- `dash_named_layouts_v1`: object keyed by layout id.
- `dash_active_layout_id`: current layout id.
- `dash_default_layout_id`: default layout id used on first load.

Each layout:

```json
{
  "id": "layout_20260620_xxxx",
  "name": "驾驶舱",
  "kind": "user",
  "createdAt": "ISO",
  "updatedAt": "ISO",
  "items": [
    {"id": "W25", "x": 0, "y": 0, "w": 6, "h": 9}
  ]
}
```

Built-in templates are not stored as user records until the user saves them. The built-in cockpit is loaded from `COCKPIT_LAYOUT` and can be saved as a user view.

## UI

Topbar keeps two areas:

- `操作`: high-frequency widget shortcuts and the full component library.
- `布局`: view selection and view management.

Layout menu actions:

- View selector: switch saved views.
- `新建空白`: clear the canvas and start an unsaved blank layout.
- `保存`: update the current saved view; if the current canvas is unsaved, open `另存为`.
- `另存为`: prompt for a name and save the current canvas as a new view.
- `重命名`: prompt for a new name for the current saved view.
- `删除`: delete the current saved view after confirmation.
- `设为默认`: make the current saved view the refresh/default landing view.
- `内置驾驶舱`: load the Phase 1 cockpit starter template.
- `导出/导入`: keep as advanced compatibility actions, but not as the primary workflow.

## Behavior

- Loading a saved view clears the grid, mounts exactly the saved items, and preserves each widget position and size.
- Blank view does not auto-add W25/W15/W24.
- If there are no saved layouts, first load uses the built-in cockpit template without persisting it as a user layout.
- After the user saves a layout, refresh restores `dash_active_layout_id`; if missing, it falls back to `dash_default_layout_id`; if missing, it falls back to built-in cockpit.
- Deleting the active view switches to the default view, or the next available view, or the built-in cockpit.
- Deleting the default view chooses the next available view as default, or clears default if no user view remains.
- `cockpit-mode` is only applied to the built-in cockpit template or a saved view whose id is explicitly marked as cockpit. Normal user layouts should not be silently rewritten by cockpit version migration.

## Phase 1 Compatibility

Keep:

- Widget `usageRole` metadata.
- First-screen and secondary-evidence grouping.
- Evidence shelf.
- Full component library.
- Topbar high-frequency widget shortcuts.
- Existing `grid.save(false)` and `_mountLayoutWidget(item)` mechanics.

Migrate:

- `dash_layout_v2` single-layout autosave becomes legacy import-on-first-load only.
- `dash_layout_mode` and `dash_cockpit_layout_version` stop controlling user layouts.
- `applyCockpitLayout()` becomes a built-in template loader, not the only default layout.

Remove from user-layout path:

- Required widget auto-injection for blank or named views.
- Automatic cockpit version replacement of user-saved layouts.

## Testing

Frontend tests should cover:

- New localStorage keys exist.
- Named layouts can be saved, switched, renamed, deleted, and set as default.
- Blank view does not call required-widget injection.
- Legacy `dash_layout_v2` can be migrated into a named view.
- Built-in cockpit remains available and still uses the six Phase 1 first-screen widgets.
- Topbar still exposes high-frequency shortcuts plus component library and evidence shelf.
- W22 remains a full normal widget with chart, legend, and drawer available.

Browser verification should cover:

- Save a layout named `驾驶舱`, refresh, and verify it restores.
- Save a second layout named `风控面板`, switch between both, and verify positions change.
- Rename and delete a view.
- Create blank view, add a widget, save it, refresh.

## Rollout

Implement behind the normal frontend path; no feature flag is required because it only affects local layout state. Keep legacy layout import defensive and reversible by leaving old keys untouched until a named layout is successfully created.
