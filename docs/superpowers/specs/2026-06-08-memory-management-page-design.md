# Memory Management Page — Design Spec

**Date**: 2026-06-08
**Status**: Approved
**Topic**: Design and implement a full-featured `/memory` management page for GBrain long-term memory

## Motivation

1. Many memory pages appear as type "unknown" due to a bug in the API type-detection logic.
2. The existing `MemoryDrawer` is a narrow sidebar suitable for quick browsing but not for batch management (bulk delete, bulk reclassify, overview stats).

## Architecture Overview

```
Browser /memory route (Next.js page)
  ├── StatsBar          — stat cards (total, by type, unknown count)
  ├── ToolBar           — type filter, search, multi-select actions
  ├── MemoryTable       — selectable table with pagination
  └── DetailPanel       — right-side drawer for detail / edit

Backend (FastAPI, existing /api/memory/*):
  GET  /api/memory/stats         (new)  — type distribution counts
  POST /api/memory/batch-delete  (new)  — bulk delete pages
  POST /api/memory/batch-retype  (new)  — bulk reclassify pages
  GET  /api/memory/search        (fix)  — correct type from slug prefix
  GET  /api/memory/pages         (fix)  — infer real type from slug
```

The existing `MemoryDrawer` remains unchanged and gains an "open in full page" link button.

---

## Backend

### Bug Fixes

**`GET /api/memory/search`** (main.py ~line 3730):
- Current: checks `slug.startswith(prefix + "/")` where `prefix` is the page *type* (e.g. `"fuzz/target-repo"`), but slugs use the slug prefix (e.g. `"fuzz/targets/"`). The match always fails → "unknown".
- Fix: use `PAGE_TYPE_PREFIX` from `memory/schemas.py` to map slug prefix → type key. For each result, find which slug prefix matches and assign the corresponding type key. If no prefix matches, mark as "unknown".

**`GET /api/memory/pages`** (main.py ~line 3769):
- Current: sets `"type": type or "unknown"` — when no type filter is given, ALL results show as "unknown".
- Fix: introspect each result's slug against `PAGE_TYPE_PREFIX` to determine the real type key.

### New Endpoints

#### `GET /api/memory/stats`

Returns type distribution for overview cards.

**Response**:
```json
{
  "total": 142,
  "by_type": {
    "targets": 23,
    "sessions": 45,
    "crashes": 38,
    "strategies": 12,
    "harnesses": 8,
    "unknown": 16
  },
  "healthy": true
}
```

**Implementation**: call `adapter.list_pages(type_prefix="", limit=500)`, iterate all pages, classify each by slug prefix using `PAGE_TYPE_PREFIX`, return counts.

#### `POST /api/memory/batch-delete`

Delete multiple pages in one request.

**Request**: `{"slugs": ["fuzz/targets/foo", "fuzz/crashes/bar"]}`
**Response**: `{"ok": 2, "failed": 0, "errors": {}}`

Each slug is deleted via `adapter.delete_page()`. Failures are collected and returned per-slug; partial success is allowed.

#### `POST /api/memory/batch-retype`

Change the `type` field in frontmatter for multiple pages.

**Request**:
```json
{
  "changes": [
    {"slug": "some/unknown/slug", "new_type": "fuzz/crash"}
  ]
}
```

**Response**: `{"ok": 1, "failed": 0, "errors": {}}`

**Implementation**: for each change, read the existing page via `adapter.get_page(slug)`, update `frontmatter.type` to `new_type`, write back via `adapter.write_page()`. The slug itself is not changed — only the frontmatter type field.

---

## Frontend

### Route

New Next.js app router page at `frontend-next/app/memory/page.tsx`, accessible at `/memory`.

### Components

#### StatsBar

A row of 6 MUI `Card` components:
- Total pages, Targets, Sessions, Crashes, Strategies, Harnesses, Unknown
- Each card shows the count and a small colored bar proportional to the total
- Clicking a card sets the type filter to that type (click "Unknown 16" → filter table to unknown pages)
- Unknown card uses `warning.main` color to draw attention

Data source: `GET /api/memory/stats`

#### ToolBar

- **Type filter**: MUI `ToggleButtonGroup` or `Chip` row — All / Targets / Sessions / Crashes / Strategies / Harnesses / Unknown. Selecting one triggers `GET /api/memory/pages?type=xxx`.
- **Search**: MUI `TextField` with debounce (300ms). Triggers `GET /api/memory/search?q=xxx`.
- **Batch actions**: `Button` "批量删除" + `Button` + `Select` "批量重分类 → targets/sessions/crashes/strategies/harnesses". Enabled only when ≥1 row selected.
- **Select all checkbox** on the left.

#### MemoryTable

- MUI `Table` with columns: checkbox, type badge (colored Chip), slug (monospace), title, updated time.
- Unknown type rows get a light warning background (`warning.light` + low opacity).
- Pagination: MUI `TablePagination`, 50 rows per page.
- Sorting: by type or title (client-side within current page).
- Row click → opens DetailPanel.

#### DetailPanel

- MUI `Drawer` (anchor="right", same width as existing MemoryDrawer).
- Shows detail view (reuses existing `MemoryDetail` component logic, adapted).
- Edit mode (reuses existing `MemoryEditForm` component logic, adapted).
- Delete button with confirmation dialog.

### Data Flow

```
Page mount
  → GET /api/memory/stats     → StatsBar
  → GET /api/memory/pages     → MemoryTable

Type filter change
  → GET /api/memory/pages?type=xxx

Search
  → GET /api/memory/search?q=xxx

Row click
  → GET /api/memory/page/{slug} → DetailPanel

Edit save
  → PUT /api/memory/page/{slug} → invalidate queries → refresh

Single delete
  → DELETE /api/memory/page/{slug} → invalidate queries → refresh

Batch delete
  → POST /api/memory/batch-delete → invalidate queries → refresh

Batch retype
  → POST /api/memory/batch-retype → invalidate queries → refresh
```

All mutations use React Query `useMutation` with `onSettled` invalidating `['memory', 'pages']`, `['memory', 'search']`, and `['memory', 'stats']` query keys.

### New API Client Functions

Add to `frontend-next/lib/api/client.ts`:
- `fetchMemoryStats()` → `GET /api/memory/stats`
- `batchDeleteMemoryPages(slugs: string[])` → `POST /api/memory/batch-delete`
- `batchRetypeMemoryPages(changes: {slug, new_type}[])` → `POST /api/memory/batch-retype`

Add to `frontend-next/lib/api/hooks.ts`:
- `useMemoryStats()` — query hook
- `useBatchDeleteMemoryMutation()` — mutation hook
- `useBatchRetypeMemoryMutation()` — mutation hook

### Entry Point from MemoryDrawer

Add a `Button` or `IconButton` (e.g. "在新页面打开" or an external-link icon) in the MemoryDrawer header that navigates to `/memory` using Next.js `useRouter().push('/memory')`.

---

## Error Handling

| Scenario | Behavior |
|---|---|
| Memory service not available | StatsBar and table area show `Alert` with "记忆服务未启用" |
| API call timeout / network error | Snackbar toast with error message |
| Batch operation partial failure | Show result summary: "成功 X 条，失败 Y 条"; failed slugs listed |
| Page not found (404 on detail) | DetailPanel shows "页面不存在" message |

---

## Implementation Order

1. Backend: fix `memory_search` slug type detection
2. Backend: fix `memory_pages` slug type detection
3. Backend: add `GET /api/memory/stats`
4. Backend: add `POST /api/memory/batch-delete`
5. Backend: add `POST /api/memory/batch-retype`
6. Frontend: add API client functions + hooks
7. Frontend: create `/memory` page with StatsBar
8. Frontend: add MemoryTable with multi-select + pagination
9. Frontend: add ToolBar with filters + batch actions
10. Frontend: add DetailPanel (detail view + edit mode)
11. Frontend: add entry button in MemoryDrawer
12. Verify: syntax check, manual review of all changed files
