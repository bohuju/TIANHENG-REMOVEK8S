# Memory Management Page — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a full-featured `/memory` management page with stats dashboard, batch operations, and fix the "unknown" type detection bug.

**Architecture:** Backend fixes two type-detection bugs in existing endpoints + adds 3 new REST endpoints (stats, batch-delete, batch-retype). Frontend adds a new Next.js route `/memory` with dedicated components (StatsBar, ToolBar, MemoryTable, DetailPanel) and adds an entry button in the existing MemoryDrawer.

**Tech Stack:** FastAPI (Python), Next.js 14 + MUI + React Query + Zod (TypeScript)

---

## File Map

| Action | File | Purpose |
|---|---|---|
| Modify | `harness_generator/src/langchain_agent/main.py` | Fix type detection + 3 new endpoints |
| Modify | `frontend-next/lib/api/schemas.ts` | Zod schemas for new API responses |
| Modify | `frontend-next/lib/api/client.ts` | New API client functions |
| Modify | `frontend-next/lib/api/hooks.ts` | New React Query hooks |
| Create | `frontend-next/app/memory/page.tsx` | `/memory` route page |
| Create | `frontend-next/components/MemoryStatsBar.tsx` | Stats cards row |
| Create | `frontend-next/components/MemoryToolBar.tsx` | Filters + batch action bar |
| Create | `frontend-next/components/MemoryTable.tsx` | Multi-select table with pagination |
| Create | `frontend-next/components/MemoryPageDrawer.tsx` | Detail/edit drawer for /memory |
| Modify | `frontend-next/components/MemoryDrawer.tsx` | Add "open in full page" button |

---

### Task 1: Fix type detection in `memory_search` and `memory_pages`

**Files:**
- Modify: `harness_generator/src/langchain_agent/main.py:133-139,3730-3802`

- [ ] **Step 1: Add import and helper function in main.py**

Add near line 133, after the existing `_MEMORY_TYPE_PREFIX` block:

```python
from memory.schemas import PAGE_TYPE_PREFIX

def _page_type_key_from_slug(slug: str) -> str:
    """Determine the memory type key from a page slug."""
    for page_type, slug_prefix in PAGE_TYPE_PREFIX.items():
        if slug.startswith(slug_prefix + "/"):
            for key, pt in _MEMORY_TYPE_PREFIX.items():
                if pt == page_type:
                    return key
    return "unknown"
```

- [ ] **Step 2: Fix `memory_search` type detection**

Replace lines 3751-3759 in the `memory_search` function:

```python
    results = []
    for r in raw:
        slug = r.get("slug", "")
        page_type = _page_type_key_from_slug(slug)
        results.append({
            "slug": slug,
            "type": page_type,
            "title": r.get("title", slug.rsplit("/", 1)[-1] if "/" in slug else slug),
            "score": r.get("score", r.get("relevance", 0.0)),
            "snippet": r.get("snippet", r.get("summary", "")),
        })
```

- [ ] **Step 3: Fix `memory_pages` type detection**

Replace lines 3786-3795 in the `memory_pages` function:

```python
    results = []
    for r in raw:
        slug = r.get("slug", "")
        page_type = _page_type_key_from_slug(slug)
        results.append({
            "slug": slug,
            "type": page_type,
            "title": r.get("title", slug.rsplit("/", 1)[-1] if "/" in slug else slug),
            "score": 0.0,
            "snippet": r.get("summary", r.get("snippet", "")),
        })
```

- [ ] **Step 4: Verify syntax**

Run: `cd harness_generator/src/langchain_agent && python3 -c "import py_compile; py_compile.compile('main.py', doraise=True); print('Syntax OK')"`
Expected: `Syntax OK`

- [ ] **Step 5: Commit**

```bash
git add harness_generator/src/langchain_agent/main.py
git commit -m "fix: correct memory page type detection from slug prefix"
```

---

### Task 2: Add `GET /api/memory/stats` endpoint

**Files:**
- Modify: `harness_generator/src/langchain_agent/main.py`

- [ ] **Step 1: Add the endpoint**

Add after the `memory_pages` function (after line ~3802):

```python
@app.get("/api/memory/stats")
async def memory_stats():
    """Return memory page counts grouped by type."""
    adapter = getattr(app.state, "memory_adapter", None)
    if adapter is None:
        return {"enabled": False, "healthy": False, "total": 0, "by_type": {}}

    try:
        raw = await adapter.list_pages(type_prefix="", limit=500)
    except Exception as exc:
        logger.warning("memory_stats error: {}", exc)
        return {
            "enabled": True, "healthy": False,
            "total": 0, "by_type": {}, "error": str(exc),
        }

    by_type: dict[str, int] = {}
    for r in raw:
        slug = r.get("slug", "")
        key = _page_type_key_from_slug(slug)
        by_type[key] = by_type.get(key, 0) + 1

    return {
        "enabled": True,
        "healthy": adapter.status()["healthy"],
        "total": sum(by_type.values()),
        "by_type": by_type,
    }
```

- [ ] **Step 2: Verify syntax**

Run: `cd harness_generator/src/langchain_agent && python3 -c "import py_compile; py_compile.compile('main.py', doraise=True); print('Syntax OK')"`
Expected: `Syntax OK`

- [ ] **Step 3: Commit**

```bash
git add harness_generator/src/langchain_agent/main.py
git commit -m "feat: add GET /api/memory/stats endpoint for type distribution"
```

---

### Task 3: Add `POST /api/memory/batch-delete` endpoint

**Files:**
- Modify: `harness_generator/src/langchain_agent/main.py`

- [ ] **Step 1: Add the endpoint**

Add after the `memory_stats` function:

```python
@app.post("/api/memory/batch-delete")
async def memory_batch_delete(body: dict = Body(...)):
    """Delete multiple memory pages in one request."""
    adapter = getattr(app.state, "memory_adapter", None)
    if adapter is None:
        raise HTTPException(status_code=503, detail="Memory service not available")

    slugs = body.get("slugs")
    if not isinstance(slugs, list) or not slugs:
        raise HTTPException(status_code=400, detail="slugs must be a non-empty list")

    ok_count = 0
    failed: dict[str, str] = {}
    for slug in slugs:
        try:
            deleted = await adapter.delete_page(str(slug))
        except Exception as exc:
            deleted = False
            failed[str(slug)] = str(exc)
        if deleted:
            ok_count += 1
        else:
            failed[str(slug)] = failed.get(str(slug), "delete returned false")

    return {"ok": ok_count, "failed": len(failed), "errors": failed}
```

- [ ] **Step 2: Verify syntax**

Run: `cd harness_generator/src/langchain_agent && python3 -c "import py_compile; py_compile.compile('main.py', doraise=True); print('Syntax OK')"`
Expected: `Syntax OK`

- [ ] **Step 3: Commit**

```bash
git add harness_generator/src/langchain_agent/main.py
git commit -m "feat: add POST /api/memory/batch-delete endpoint"
```

---

### Task 4: Add `POST /api/memory/batch-retype` endpoint

**Files:**
- Modify: `harness_generator/src/langchain_agent/main.py`

- [ ] **Step 1: Add the endpoint**

Add after `memory_batch_delete`:

```python
@app.post("/api/memory/batch-retype")
async def memory_batch_retype(body: dict = Body(...)):
    """Reclassify multiple memory pages by updating their frontmatter type."""
    adapter = getattr(app.state, "memory_adapter", None)
    if adapter is None:
        raise HTTPException(status_code=503, detail="Memory service not available")

    changes = body.get("changes")
    if not isinstance(changes, list) or not changes:
        raise HTTPException(status_code=400, detail="changes must be a non-empty list")

    ok_count = 0
    failed: dict[str, str] = {}
    for ch in changes:
        slug = str(ch.get("slug", ""))
        new_type = str(ch.get("new_type", ""))
        if not slug or not new_type:
            failed[slug or "(empty)"] = "slug and new_type are required"
            continue
        try:
            page = await adapter.get_page(slug)
        except Exception as exc:
            failed[slug] = f"get_page error: {exc}"
            continue
        if page is None:
            failed[slug] = "page not found"
            continue

        existing_fm = page.get("frontmatter", {})
        if not isinstance(existing_fm, dict):
            existing_fm = {}
        existing_fm["type"] = new_type
        compiled_truth = page.get("compiled_truth", page.get("content", ""))
        timeline = page.get("timeline", [])

        try:
            ok = await adapter.write_page(slug, existing_fm, compiled_truth, timeline)
        except Exception as exc:
            ok = False
            failed[slug] = str(exc)
        if ok:
            ok_count += 1
        else:
            failed[slug] = failed.get(slug, "write_page returned false")

    return {"ok": ok_count, "failed": len(failed), "errors": failed}
```

- [ ] **Step 2: Verify syntax**

Run: `cd harness_generator/src/langchain_agent && python3 -c "import py_compile; py_compile.compile('main.py', doraise=True); print('Syntax OK')"`
Expected: `Syntax OK`

- [ ] **Step 3: Commit**

```bash
git add harness_generator/src/langchain_agent/main.py
git commit -m "feat: add POST /api/memory/batch-retype endpoint"
```

---

### Task 5: Add frontend API schemas, client functions, and hooks

**Files:**
- Modify: `frontend-next/lib/api/schemas.ts`
- Modify: `frontend-next/lib/api/client.ts`
- Modify: `frontend-next/lib/api/hooks.ts`

- [ ] **Step 1: Add Zod schemas in schemas.ts**

Add after the `memoryDeleteResponseSchema` (after line 168):

```typescript
export const memoryStatsResponseSchema = z.object({
  enabled: z.boolean().default(false),
  healthy: z.boolean().default(false),
  total: z.number().int().default(0),
  by_type: z.record(z.string(), z.number().int()).default({}),
  error: z.string().optional(),
});

export const memoryBatchDeleteResponseSchema = z.object({
  ok: z.number().int().default(0),
  failed: z.number().int().default(0),
  errors: z.record(z.string(), z.string()).default({}),
});

export const memoryBatchRetypeResponseSchema = z.object({
  ok: z.number().int().default(0),
  failed: z.number().int().default(0),
  errors: z.record(z.string(), z.string()).default({}),
});

export type MemoryStatsResponse = z.infer<typeof memoryStatsResponseSchema>;
export type MemoryBatchDeleteResponse = z.infer<typeof memoryBatchDeleteResponseSchema>;
export type MemoryBatchRetypeResponse = z.infer<typeof memoryBatchRetypeResponseSchema>;
```

- [ ] **Step 2: Add client functions in client.ts**

Update imports at top of file (line 1-18):

```typescript
import {
  configSchema,
  systemSchema,
  taskDetailSchema,
  taskListSchema,
  memorySearchResponseSchema,
  memoryPagesResponseSchema,
  memoryPageResponseSchema,
  memoryUpdateResponseSchema,
  memoryDeleteResponseSchema,
  memoryStatsResponseSchema,
  memoryBatchDeleteResponseSchema,
  memoryBatchRetypeResponseSchema,
  type WebConfig,
  type SystemStatus,
  type TaskDetail,
  type TaskSummary,
  type MemorySearchResponse,
  type MemoryPagesResponse,
  type MemoryPageResponse,
  type MemoryStatsResponse,
} from './schemas';
```

Add after `deleteMemoryPage` function (after line 168):

```typescript
export async function fetchMemoryStats(): Promise<MemoryStatsResponse> {
  const data = await request<unknown>('/memory/stats');
  return memoryStatsResponseSchema.parse(data);
}

export async function batchDeleteMemoryPages(slugs: string[]): Promise<{ ok: number; failed: number; errors: Record<string, string> }> {
  const data = await request<unknown>('/memory/batch-delete', {
    method: 'POST',
    body: JSON.stringify({ slugs }),
  });
  return memoryBatchDeleteResponseSchema.parse(data);
}

export async function batchRetypeMemoryPages(changes: { slug: string; new_type: string }[]): Promise<{ ok: number; failed: number; errors: Record<string, string> }> {
  const data = await request<unknown>('/memory/batch-retype', {
    method: 'POST',
    body: JSON.stringify({ changes }),
  });
  return memoryBatchRetypeResponseSchema.parse(data);
}
```

- [ ] **Step 3: Add hooks in hooks.ts**

Update imports at top (line 1-19):

```typescript
import {
  getConfig,
  getSystem,
  getTask,
  getTasks,
  putConfig,
  stopTask,
  deleteTask,
  submitTask,
  searchMemory,
  listMemoryPages,
  getMemoryPage,
  updateMemoryPage,
  deleteMemoryPage,
  fetchMemoryStats,
  batchDeleteMemoryPages,
  batchRetypeMemoryPages,
  type SubmitTaskInput,
} from './client';
```

Add after `useDeleteMemoryPageMutation` (after line 147):

```typescript
export function useMemoryStatsQuery() {
  return useQuery({
    queryKey: ['memory', 'stats'],
    queryFn: fetchMemoryStats,
  });
}

export function useBatchDeleteMemoryMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (slugs: string[]) => batchDeleteMemoryPages(slugs),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['memory', 'pages'] });
      void qc.invalidateQueries({ queryKey: ['memory', 'search'] });
      void qc.invalidateQueries({ queryKey: ['memory', 'stats'] });
    },
  });
}

export function useBatchRetypeMemoryMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (changes: { slug: string; new_type: string }[]) => batchRetypeMemoryPages(changes),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['memory', 'pages'] });
      void qc.invalidateQueries({ queryKey: ['memory', 'search'] });
      void qc.invalidateQueries({ queryKey: ['memory', 'stats'] });
    },
  });
}
```

- [ ] **Step 4: Verify TypeScript compilation**

Run: `cd frontend-next && npx tsc --noEmit --pretty 2>&1 | head -40`
Expected: No new errors from our changes (pre-existing errors may exist).

- [ ] **Step 5: Commit**

```bash
git add frontend-next/lib/api/schemas.ts frontend-next/lib/api/client.ts frontend-next/lib/api/hooks.ts
git commit -m "feat: add frontend API layer for memory stats, batch-delete, batch-retype"
```

---

### Task 6: Create `/memory` route page

**Files:**
- Create: `frontend-next/app/memory/page.tsx`

- [ ] **Step 1: Create the page skeleton**

```typescript
'use client';

import { useCallback, useState } from 'react';
import {
  Alert,
  Box,
  Snackbar,
  Typography,
} from '@mui/material';
import { useRouter } from 'next/navigation';
import { MemoryStatsBar } from '@/components/MemoryStatsBar';
import { MemoryToolBar } from '@/components/MemoryToolBar';
import { MemoryTable } from '@/components/MemoryTable';
import { MemoryPageDrawer } from '@/components/MemoryPageDrawer';
import {
  useMemoryPages,
  useMemorySearch,
  useMemoryStatsQuery,
} from '@/lib/api/hooks';
import type { MemoryResult } from '@/lib/api/schemas';

export default function MemoryPage() {
  const router = useRouter();
  const [pageType, setPageType] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [toast, setToast] = useState<{ message: string; severity: 'success' | 'error' | 'info' } | null>(null);

  const stats = useMemoryStatsQuery();
  const isSearchMode = searchQuery.length > 0;
  const pages = useMemoryPages(pageType);
  const search = useMemorySearch(searchQuery, pageType);

  const results: MemoryResult[] = isSearchMode ? (search.data?.results || []) : (pages.data?.results || []);
  const loading = isSearchMode ? search.isLoading : pages.isLoading;
  const enabled = isSearchMode ? search.data?.enabled !== false : pages.data?.enabled !== false;
  const total = isSearchMode ? (search.data?.total || 0) : (pages.data?.total || 0);

  const handleTypeFilter = useCallback((t: string) => {
    setPageType(t);
    setSearchQuery('');
    setSelected(new Set());
  }, []);

  const handleSearch = useCallback((q: string) => {
    setSearchQuery(q);
    setSelected(new Set());
  }, []);

  const handleSelectRow = useCallback((slug: string) => {
    setSelectedSlug(slug);
    setDrawerOpen(true);
  }, []);

  const handleCloseDrawer = useCallback(() => {
    setDrawerOpen(false);
    setSelectedSlug(null);
  }, []);

  const handleSelectionChange = useCallback((sel: Set<string>) => {
    setSelected(sel);
  }, []);

  const handleRefresh = useCallback(() => {
    stats.refetch();
    if (isSearchMode) search.refetch();
    else pages.refetch();
  }, [stats, isSearchMode, search, pages]);

  if (!enabled && !loading) {
    return (
      <Box sx={{ maxWidth: 1200, mx: 'auto', p: 3 }}>
        <Typography variant="h5" fontWeight={600} sx={{ mb: 2 }}>
          记忆库管理
        </Typography>
        <Alert severity="info">记忆服务未启用。请确保 gbrain 已安装并运行。</Alert>
        <Box sx={{ mt: 2 }}>
          <Typography
            component="a"
            href="/"
            sx={{ fontSize: 14, color: 'primary.main', textDecoration: 'underline', cursor: 'pointer' }}
          >
            ← 返回主页
          </Typography>
        </Box>
      </Box>
    );
  }

  return (
    <Box sx={{ maxWidth: 1200, mx: 'auto', p: 3 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 3 }}>
        <Typography variant="h5" fontWeight={600}>
          记忆库管理
        </Typography>
        <Typography
          component="a"
          href="/"
          sx={{ fontSize: 14, color: 'primary.main', textDecoration: 'underline', cursor: 'pointer' }}
        >
          ← 返回主页
        </Typography>
      </Box>

      {/* Stats */}
      <MemoryStatsBar
        stats={stats.data}
        loading={stats.isLoading}
        onFilterByType={handleTypeFilter}
        activeType={pageType}
      />

      {/* Toolbar */}
      <MemoryToolBar
        pageType={pageType}
        onTypeChange={handleTypeFilter}
        searchQuery={searchQuery}
        onSearch={handleSearch}
        selectedSlugs={selected}
        results={results}
        onRefresh={handleRefresh}
        onToast={setToast}
      />

      {/* Table */}
      <MemoryTable
        results={results}
        loading={loading}
        total={total}
        selected={selected}
        onSelectionChange={handleSelectionChange}
        onSelectRow={handleSelectRow}
        pageType={pageType}
      />

      {/* Detail Drawer */}
      <MemoryPageDrawer
        open={drawerOpen}
        slug={selectedSlug}
        onClose={handleCloseDrawer}
        onRefresh={handleRefresh}
        onToast={setToast}
      />

      {/* Toast */}
      <Snackbar
        open={Boolean(toast)}
        autoHideDuration={4000}
        onClose={() => setToast(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        {toast ? (
          <Alert severity={toast.severity} onClose={() => setToast(null)} variant="filled">
            {toast.message}
          </Alert>
        ) : undefined}
      </Snackbar>
    </Box>
  );
}
```

- [ ] **Step 2: Verify compilation**

Run: `cd frontend-next && npx tsc --noEmit --pretty 2>&1 | head -40`
Expected: Errors only for components not yet created (will be resolved in subsequent tasks).

- [ ] **Step 3: Commit**

```bash
git add frontend-next/app/memory/page.tsx
git commit -m "feat: create /memory route page skeleton"
```

---

### Task 7: Create MemoryStatsBar component

**Files:**
- Create: `frontend-next/components/MemoryStatsBar.tsx`

- [ ] **Step 1: Create the component**

```typescript
'use client';

import { Box, Card, CardActionArea, CircularProgress, Skeleton, Typography } from '@mui/material';

const TYPE_CONFIG: Record<string, { label: string; color: string }> = {
  targets: { label: '目标仓库', color: '#0f5ad8' },
  sessions: { label: '会话', color: '#2e7d32' },
  crashes: { label: '崩溃', color: '#c62828' },
  strategies: { label: '策略', color: '#ed6c02' },
  harnesses: { label: 'Harness', color: '#6a1b9a' },
  unknown: { label: '未知', color: '#d32f2f' },
};

interface MemoryStatsBarProps {
  stats: { total: number; by_type: Record<string, number>; enabled?: boolean } | undefined;
  loading: boolean;
  onFilterByType: (type: string) => void;
  activeType: string;
}

export function MemoryStatsBar({ stats, loading, onFilterByType, activeType }: MemoryStatsBarProps) {
  if (loading) {
    return (
      <Box sx={{ display: 'flex', gap: 2, mb: 3, flexWrap: 'wrap' }}>
        {Array.from({ length: 7 }).map((_, i) => (
          <Skeleton key={i} variant="rounded" width={140} height={80} />
        ))}
      </Box>
    );
  }

  const byType = stats?.by_type || {};
  const total = stats?.total || 0;
  const maxCount = Math.max(...Object.values(byType), 1);

  const cards = [
    { key: '', label: '总计', count: total, color: '#333' },
    ...Object.entries(TYPE_CONFIG).map(([key, cfg]) => ({
      key,
      label: cfg.label,
      count: byType[key] || 0,
      color: cfg.color,
    })),
  ];

  return (
    <Box sx={{ display: 'flex', gap: 1.5, mb: 3, flexWrap: 'wrap' }}>
      {cards.map((card) => {
        const isActive = activeType === card.key || (!activeType && card.key === '');
        const barWidth = maxCount > 0 ? (card.count / maxCount) * 100 : 0;
        return (
          <Card
            key={card.key}
            variant="outlined"
            sx={{
              flex: '1 1 130px',
              minWidth: 130,
              maxWidth: 160,
              borderColor: isActive ? card.color : undefined,
              borderWidth: isActive ? 2 : 1,
              opacity: activeType && !isActive ? 0.6 : 1,
            }}
          >
            <CardActionArea onClick={() => onFilterByType(card.key)} sx={{ p: 1.5 }}>
              <Typography variant="caption" color="text.secondary" sx={{ fontSize: 11 }}>
                {card.label}
              </Typography>
              <Typography variant="h5" fontWeight={700} sx={{ color: card.color, fontSize: 24 }}>
                {card.count}
              </Typography>
              <Box
                sx={{
                  mt: 0.5,
                  height: 3,
                  borderRadius: 1,
                  bgcolor: card.color,
                  width: `${Math.max(barWidth, card.count > 0 ? 4 : 0)}%`,
                  opacity: 0.3,
                }}
              />
            </CardActionArea>
          </Card>
        );
      })}
    </Box>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend-next/components/MemoryStatsBar.tsx
git commit -m "feat: add MemoryStatsBar component"
```

---

### Task 8: Create MemoryToolBar component

**Files:**
- Create: `frontend-next/components/MemoryToolBar.tsx`

- [ ] **Step 1: Create the component**

```typescript
'use client';

import { useState, useCallback } from 'react';
import {
  Box,
  Button,
  Chip,
  FormControl,
  IconButton,
  InputAdornment,
  Menu,
  MenuItem,
  Select,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import DeleteIcon from '@mui/icons-material/Delete';
import SearchIcon from '@mui/icons-material/Search';
import RefreshIcon from '@mui/icons-material/Refresh';
import {
  useBatchDeleteMemoryMutation,
  useBatchRetypeMemoryMutation,
} from '@/lib/api/hooks';
import type { MemoryResult } from '@/lib/api/schemas';

const TYPE_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'targets', label: '目标仓库' },
  { value: 'sessions', label: '会话' },
  { value: 'crashes', label: '崩溃' },
  { value: 'strategies', label: '策略' },
  { value: 'harnesses', label: 'Harness' },
  { value: 'unknown', label: '未知' },
];

const RETYPE_TARGETS = [
  { value: 'targets', label: '→ 目标仓库', newType: 'fuzz/target-repo' },
  { value: 'sessions', label: '→ 会话', newType: 'fuzz/session' },
  { value: 'crashes', label: '→ 崩溃', newType: 'fuzz/crash' },
  { value: 'strategies', label: '→ 策略', newType: 'fuzz/strategy' },
  { value: 'harnesses', label: '→ Harness', newType: 'fuzz/harness' },
];

interface MemoryToolBarProps {
  pageType: string;
  onTypeChange: (type: string) => void;
  searchQuery: string;
  onSearch: (q: string) => void;
  selectedSlugs: Set<string>;
  results: MemoryResult[];
  onRefresh: () => void;
  onToast: (toast: { message: string; severity: 'success' | 'error' | 'info' } | null) => void;
}

export function MemoryToolBar({
  pageType,
  onTypeChange,
  searchQuery,
  onSearch,
  selectedSlugs,
  results,
  onRefresh,
  onToast,
}: MemoryToolBarProps) {
  const [searchInput, setSearchInput] = useState(searchQuery);
  const [retypeAnchor, setRetypeAnchor] = useState<HTMLElement | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const batchDelete = useBatchDeleteMemoryMutation();
  const batchRetype = useBatchRetypeMemoryMutation();

  const selectedCount = selectedSlugs.size;

  const handleSearchSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      onSearch(searchInput.trim());
    },
    [searchInput, onSearch],
  );

  const handleBatchDelete = useCallback(async () => {
    if (selectedCount === 0) return;
    const slugs = Array.from(selectedSlugs);
    try {
      const result = await batchDelete.mutateAsync(slugs);
      if (result.failed > 0) {
        onToast({ message: `删除完成：成功 ${result.ok} 条，失败 ${result.failed} 条`, severity: 'warning' });
      } else {
        onToast({ message: `成功删除 ${result.ok} 条记忆`, severity: 'success' });
      }
      onRefresh();
    } catch (err) {
      onToast({ message: `批量删除失败：${err instanceof Error ? err.message : '未知错误'}`, severity: 'error' });
    }
  }, [selectedSlugs, batchDelete, onRefresh, onToast, selectedCount]);

  const handleBatchRetype = useCallback(
    async (targetValue: string) => {
      setRetypeAnchor(null);
      if (selectedCount === 0) return;
      const target = RETYPE_TARGETS.find((t) => t.value === targetValue);
      if (!target) return;
      const changes = Array.from(selectedSlugs).map((slug) => ({
        slug,
        new_type: target.newType,
      }));
      try {
        const result = await batchRetype.mutateAsync(changes);
        if (result.failed > 0) {
          onToast({ message: `重分类完成：成功 ${result.ok} 条，失败 ${result.failed} 条`, severity: 'warning' });
        } else {
          onToast({ message: `成功重分类 ${result.ok} 条记忆为 ${target.label.slice(2)}`, severity: 'success' });
        }
        onRefresh();
      } catch (err) {
        onToast({ message: `重分类失败：${err instanceof Error ? err.message : '未知错误'}`, severity: 'error' });
      }
    },
    [selectedSlugs, batchRetype, onRefresh, onToast, selectedCount],
  );

  return (
    <Box sx={{ mb: 2 }}>
      <Stack direction="row" spacing={1} sx={{ mb: 1.5 }} useFlexGap flexWrap="wrap">
        {/* Type filter chips */}
        {TYPE_OPTIONS.map((opt) => (
          <Chip
            key={opt.value}
            label={opt.label}
            size="small"
            variant={pageType === opt.value ? 'filled' : 'outlined'}
            color={pageType === opt.value ? 'primary' : 'default'}
            onClick={() => onTypeChange(opt.value)}
            sx={{ fontSize: 12 }}
          />
        ))}

        <Box sx={{ flex: 1 }} />

        {/* Search */}
        <Box component="form" onSubmit={handleSearchSubmit} sx={{ display: 'flex', alignItems: 'center' }}>
          <TextField
            size="small"
            placeholder="搜索记忆..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon fontSize="small" />
                </InputAdornment>
              ),
            }}
            sx={{ width: 220, '& .MuiInputBase-input': { fontSize: 13 } }}
          />
          <Tooltip title="刷新">
            <IconButton size="small" onClick={onRefresh} sx={{ ml: 0.5 }}>
              <RefreshIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Box>
      </Stack>

      {/* Batch action bar — visible only when items selected */}
      {selectedCount > 0 ? (
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 1,
            py: 1,
            px: 1.5,
            bgcolor: 'primary.main',
            color: 'primary.contrastText',
            borderRadius: 1,
          }}
        >
          <Typography variant="body2" sx={{ fontSize: 13 }}>
            已选 {selectedCount} 项
          </Typography>
          <Button
            size="small"
            variant="contained"
            color="error"
            startIcon={<DeleteIcon fontSize="small" />}
            onClick={handleBatchDelete}
            disabled={batchDelete.isPending}
            sx={{ fontSize: 12 }}
          >
            {batchDelete.isPending ? '删除中...' : '批量删除'}
          </Button>
          <Button
            size="small"
            variant="contained"
            color="secondary"
            onClick={(e) => setRetypeAnchor(e.currentTarget)}
            disabled={batchRetype.isPending}
            sx={{ fontSize: 12 }}
          >
            {batchRetype.isPending ? '处理中...' : '批量重分类'}
          </Button>
          <Menu
            anchorEl={retypeAnchor}
            open={Boolean(retypeAnchor)}
            onClose={() => setRetypeAnchor(null)}
          >
            {RETYPE_TARGETS.map((t) => (
              <MenuItem key={t.value} onClick={() => handleBatchRetype(t.value)}>
                {t.label}
              </MenuItem>
            ))}
          </Menu>
          <Box sx={{ flex: 1 }} />
          <Button
            size="small"
            sx={{ color: 'inherit', fontSize: 12 }}
            onClick={() => onSearch(searchQuery)}
          >
            取消选择
          </Button>
        </Box>
      ) : null}
    </Box>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend-next/components/MemoryToolBar.tsx
git commit -m "feat: add MemoryToolBar component with batch actions"
```

---

### Task 9: Create MemoryTable component

**Files:**
- Create: `frontend-next/components/MemoryTable.tsx`

- [ ] **Step 1: Create the component**

```typescript
'use client';

import { useCallback, useMemo, useState } from 'react';
import {
  Box,
  Checkbox,
  Chip,
  CircularProgress,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  TableSortLabel,
  Typography,
} from '@mui/material';
import type { MemoryResult } from '@/lib/api/schemas';

const TYPE_LABELS: Record<string, string> = {
  targets: '目标仓库',
  sessions: '会话',
  crashes: '崩溃',
  strategies: '策略',
  harnesses: 'Harness',
  unknown: '未知',
};

const TYPE_COLORS: Record<string, string> = {
  targets: '#0f5ad8',
  sessions: '#2e7d32',
  crashes: '#c62828',
  strategies: '#ed6c02',
  harnesses: '#6a1b9a',
  unknown: '#d32f2f',
};

const ROWS_PER_PAGE = 50;

interface MemoryTableProps {
  results: MemoryResult[];
  loading: boolean;
  total: number;
  selected: Set<string>;
  onSelectionChange: (sel: Set<string>) => void;
  onSelectRow: (slug: string) => void;
  pageType: string;
}

export function MemoryTable({
  results,
  loading,
  total,
  selected,
  onSelectionChange,
  onSelectRow,
  pageType,
}: MemoryTableProps) {
  const [page, setPage] = useState(0);
  const [sortBy, setSortBy] = useState<'type' | 'title'>('type');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');

  const handleSort = useCallback(
    (col: 'type' | 'title') => {
      if (sortBy === col) {
        setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
      } else {
        setSortBy(col);
        setSortDir('asc');
      }
    },
    [sortBy],
  );

  const sorted = useMemo(() => {
    const arr = [...results];
    arr.sort((a, b) => {
      const av = sortBy === 'type' ? a.type : a.title;
      const bv = sortBy === 'type' ? b.type : b.title;
      const cmp = av.localeCompare(bv);
      return sortDir === 'asc' ? cmp : -cmp;
    });
    return arr;
  }, [results, sortBy, sortDir]);

  const paged = useMemo(() => {
    const start = page * ROWS_PER_PAGE;
    return sorted.slice(start, start + ROWS_PER_PAGE);
  }, [sorted, page]);

  const allOnPageSelected = paged.length > 0 && paged.every((r) => selected.has(r.slug));
  const someOnPageSelected = paged.some((r) => selected.has(r.slug));

  const handleSelectAll = useCallback(() => {
    const next = new Set(selected);
    if (allOnPageSelected) {
      paged.forEach((r) => next.delete(r.slug));
    } else {
      paged.forEach((r) => next.add(r.slug));
    }
    onSelectionChange(next);
  }, [selected, paged, allOnPageSelected, onSelectionChange]);

  const handleCheck = useCallback(
    (slug: string) => {
      const next = new Set(selected);
      if (next.has(slug)) {
        next.delete(slug);
      } else {
        next.add(slug);
      }
      onSelectionChange(next);
    },
    [selected, onSelectionChange],
  );

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
        <CircularProgress size={36} />
      </Box>
    );
  }

  if (results.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: 'center' }}>
        暂无记忆数据
      </Typography>
    );
  }

  return (
    <>
      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell padding="checkbox">
                <Checkbox
                  size="small"
                  indeterminate={someOnPageSelected && !allOnPageSelected}
                  checked={allOnPageSelected}
                  onChange={handleSelectAll}
                />
              </TableCell>
              <TableCell sx={{ width: 120 }}>
                <TableSortLabel
                  active={sortBy === 'type'}
                  direction={sortBy === 'type' ? sortDir : 'asc'}
                  onClick={() => handleSort('type')}
                >
                  类型
                </TableSortLabel>
              </TableCell>
              <TableCell>Slug</TableCell>
              <TableCell>
                <TableSortLabel
                  active={sortBy === 'title'}
                  direction={sortBy === 'title' ? sortDir : 'asc'}
                  onClick={() => handleSort('title')}
                >
                  标题
                </TableSortLabel>
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {paged.map((r) => {
              const isUnknown = r.type === 'unknown';
              return (
                <TableRow
                  key={r.slug}
                  hover
                  selected={selected.has(r.slug)}
                  sx={{
                    cursor: 'pointer',
                    bgcolor: isUnknown ? 'warning.50' : undefined,
                    '&:hover': { bgcolor: isUnknown ? 'warning.100' : undefined },
                  }}
                  onClick={() => onSelectRow(r.slug)}
                >
                  <TableCell padding="checkbox" onClick={(e) => e.stopPropagation()}>
                    <Checkbox
                      size="small"
                      checked={selected.has(r.slug)}
                      onChange={() => handleCheck(r.slug)}
                    />
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={TYPE_LABELS[r.type] || r.type}
                      size="small"
                      sx={{
                        fontSize: 11,
                        height: 22,
                        bgcolor: isUnknown ? '#fff3e0' : `${TYPE_COLORS[r.type] || '#666'}15`,
                        color: TYPE_COLORS[r.type] || '#666',
                        fontWeight: isUnknown ? 700 : 500,
                      }}
                    />
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: 12 }}>
                      {r.slug}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" sx={{ fontSize: 13 }}>
                      {r.title}
                    </Typography>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </TableContainer>
      <TablePagination
        component="div"
        count={total || results.length}
        page={page}
        onPageChange={(_, p) => setPage(p)}
        rowsPerPage={ROWS_PER_PAGE}
        rowsPerPageOptions={[ROWS_PER_PAGE]}
        labelDisplayedRows={({ from, to, count }) => `${from}-${to} / ${count}`}
      />
    </>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend-next/components/MemoryTable.tsx
git commit -m "feat: add MemoryTable component with multi-select and sorting"
```

---

### Task 10: Create MemoryPageDrawer component

**Files:**
- Create: `frontend-next/components/MemoryPageDrawer.tsx`

- [ ] **Step 1: Create the component**

```typescript
'use client';

import { useCallback, useState } from 'react';
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  CircularProgress,
  Drawer,
  IconButton,
  Typography,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import {
  useMemoryPage,
  useUpdateMemoryPageMutation,
  useDeleteMemoryPageMutation,
} from '@/lib/api/hooks';
import { MemoryDetail } from './MemoryDetail';
import { MemoryEditForm } from './MemoryEditForm';

type ViewMode = 'detail' | 'edit';

interface MemoryPageDrawerProps {
  open: boolean;
  slug: string | null;
  onClose: () => void;
  onRefresh: () => void;
  onToast: (toast: { message: string; severity: 'success' | 'error' | 'info' } | null) => void;
}

export function MemoryPageDrawer({ open, slug, onClose, onRefresh, onToast }: MemoryPageDrawerProps) {
  const [viewMode, setViewMode] = useState<ViewMode>('detail');
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  const detail = useMemoryPage(slug);
  const updatePage = useUpdateMemoryPageMutation();
  const deletePage = useDeleteMemoryPageMutation();

  const page = detail.data?.page;
  const frontmatter = (page?.frontmatter || {}) as Record<string, unknown>;
  const compiledTruth = String(page?.compiled_truth || page?.content || '');
  const pageType = (page?.frontmatter as Record<string, unknown>)?.type as string | undefined || 'unknown';

  const handleClose = useCallback(() => {
    setViewMode('detail');
    onClose();
  }, [onClose]);

  const handleEdit = useCallback(() => {
    setViewMode('edit');
  }, []);

  const handleSave = useCallback(
    async (fm: Record<string, unknown>) => {
      if (!slug) return;
      try {
        await updatePage.mutateAsync({ slug, frontmatter: fm });
        setViewMode('detail');
        onRefresh();
        onToast({ message: '保存成功', severity: 'success' });
      } catch (err) {
        onToast({ message: `保存失败：${err instanceof Error ? err.message : '未知错误'}`, severity: 'error' });
      }
    },
    [slug, updatePage, onRefresh, onToast],
  );

  const handleDeleteClick = useCallback(() => {
    setDeleteDialogOpen(true);
  }, []);

  const handleDeleteConfirm = useCallback(async () => {
    if (!slug) return;
    try {
      await deletePage.mutateAsync(slug);
      setDeleteDialogOpen(false);
      onClose();
      onRefresh();
      onToast({ message: '已删除', severity: 'info' });
    } catch (err) {
      onToast({ message: `删除失败：${err instanceof Error ? err.message : '未知错误'}`, severity: 'error' });
      setDeleteDialogOpen(false);
    }
  }, [slug, deletePage, onClose, onRefresh, onToast]);

  return (
    <>
      <Drawer
        anchor="right"
        open={open}
        onClose={handleClose}
        PaperProps={{ sx: { width: { xs: '100%', sm: 480, md: 560 } } }}
      >
        <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
          {/* Header */}
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              px: 2,
              py: 1.5,
              borderBottom: '1px solid',
              borderColor: 'divider',
            }}
          >
            <Typography variant="h6" fontWeight={600} sx={{ fontSize: 18 }}>
              记忆详情
            </Typography>
            <IconButton size="small" onClick={handleClose} aria-label="关闭">
              <CloseIcon fontSize="small" />
            </IconButton>
          </Box>

          {/* Body */}
          <Box sx={{ flex: 1, overflow: 'auto', px: 2, py: 2 }}>
            {detail.isLoading ? (
              <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
                <CircularProgress size={32} />
              </Box>
            ) : !page ? (
              <Typography variant="body2" color="text.secondary" sx={{ py: 3, textAlign: 'center' }}>
                页面不存在或无法加载
              </Typography>
            ) : viewMode === 'detail' ? (
              <MemoryDetail
                slug={slug || ''}
                pageType={pageType}
                frontmatter={frontmatter}
                compiledTruth={compiledTruth}
                timeline={page?.timeline || []}
                onBack={handleClose}
                onEdit={handleEdit}
                onDelete={handleDeleteClick}
              />
            ) : (
              <MemoryEditForm
                slug={slug || ''}
                pageType={pageType}
                frontmatter={frontmatter}
                onSave={handleSave}
                onCancel={() => setViewMode('detail')}
                saving={updatePage.isPending}
              />
            )}
          </Box>
        </Box>
      </Drawer>

      {/* Delete confirmation */}
      <Dialog open={deleteDialogOpen} onClose={() => setDeleteDialogOpen(false)}>
        <DialogTitle>确认删除</DialogTitle>
        <DialogContent>
          <DialogContentText>
            确定删除 {slug} 吗？此操作不可恢复。
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteDialogOpen(false)} size="small">取消</Button>
          <Button
            onClick={handleDeleteConfirm}
            size="small"
            color="error"
            variant="contained"
            disabled={deletePage.isPending}
          >
            {deletePage.isPending ? '删除中...' : '删除'}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend-next/components/MemoryPageDrawer.tsx
git commit -m "feat: add MemoryPageDrawer component for /memory route"
```

---

### Task 11: Add "open in full page" button in MemoryDrawer

**Files:**
- Modify: `frontend-next/components/MemoryDrawer.tsx`

- [ ] **Step 1: Add import and button in MemoryDrawer header**

Add import at top (line 4-5 area):

```typescript
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import { useRouter } from 'next/navigation';
```

In the component body (after line 56 `export function MemoryDrawer(...)`, add router):

```typescript
  const router = useRouter();
```

Replace the header buttons section (lines 200-208) — add the new button before the close button:

```typescript
            <Box sx={{ display: 'flex', gap: 1 }}>
              {viewMode === 'list' ? (
                <Button size="small" variant="outlined" onClick={handleCreate} sx={{ fontSize: 12 }}>
                  + 新建
                </Button>
              ) : null}
              <Tooltip title="在新页面打开">
                <IconButton
                  size="small"
                  onClick={() => router.push('/memory')}
                  aria-label="在新页面打开"
                >
                  <OpenInNewIcon fontSize="small" />
                </IconButton>
              </Tooltip>
              <IconButton size="small" onClick={onClose} aria-label="关闭">
                <CloseIcon fontSize="small" />
              </IconButton>
            </Box>
```

Need to add `Tooltip` import at top (it's already imported via MUI? Let me check — the current MemoryDrawer imports from `@mui/material`, need to add `Tooltip`):

Replace the MUI import line at top:

```typescript
import {
  Alert,
  Box,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Button,
  CircularProgress,
  Drawer,
  IconButton,
  Stack,
  Tooltip,
  Typography,
} from '@mui/material';
```

- [ ] **Step 2: Verify TypeScript compilation**

Run: `cd frontend-next && npx tsc --noEmit --pretty 2>&1 | head -40`
Expected: No new errors from our changes.

- [ ] **Step 3: Commit**

```bash
git add frontend-next/components/MemoryDrawer.tsx
git commit -m "feat: add 'open in full page' button to MemoryDrawer"
```

---

### Task 12: Final verification

- [ ] **Step 1: Check all backend syntax**

Run: `cd harness_generator/src/langchain_agent && python3 -c "import py_compile; py_compile.compile('main.py', doraise=True); print('Syntax OK')"`
Expected: `Syntax OK`

- [ ] **Step 2: Check all frontend TypeScript**

Run: `cd frontend-next && npx tsc --noEmit --pretty 2>&1 | head -40`
Expected: No new errors from our changes.

- [ ] **Step 3: Review changed files list**

Run: `git diff --name-only HEAD~6`
Expected: List of all files we created/modified across the 12 commits.

- [ ] **Step 4: Final commit (if any cleanup)**

No commit needed unless issues found and fixed.
