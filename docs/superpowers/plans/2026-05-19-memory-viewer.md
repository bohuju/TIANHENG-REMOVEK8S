# Memory Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a sidebar drawer in the frontend dashboard for viewing, searching, editing, and deleting GBrain memory pages, backed by 5 new REST API endpoints.

**Architecture:** Add `list_pages` and `delete_page` methods to MemoryAdapter, create a singleton MemoryAdapter in FastAPI lifespan, expose 5 endpoints (`/api/memory/*`), then build a MUI Drawer component in the frontend with search, type tabs, result list, detail view, and edit form. Follow existing patterns: zod schemas, fetch-based client, React Query hooks, MUI v7 components.

**Tech Stack:** Python/FastAPI (backend), TypeScript/Next.js 14/MUI v7/React Query v5/Zod (frontend)

---

### Task 1: Add `list_pages` and `delete_page` to MemoryAdapter

**Files:**
- Modify: `harness_generator/src/langchain_agent/memory_adapter.py`

- [ ] **Step 1: Add `list_pages` method**

Add after the `query_experience` method (after line 233):

```python
    async def list_pages(self, type_prefix: str = "", limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """List pages by type prefix. Falls back to query_experience if gbrain lacks list_pages tool."""
        result = await self._call_tool("list_pages", {
            "prefix": type_prefix,
            "limit": limit,
            "offset": offset,
        })
        if "error" in result:
            logger.debug("list_pages tool not available, falling back to query_experience: {}", result["error"])
            return await self.query_experience(f"type:{type_prefix}" if type_prefix else "", timeout=5.0)
        return result.get("pages", result.get("results", []))
```

- [ ] **Step 2: Add `delete_page` method**

Add after `list_pages`:

```python
    async def delete_page(self, slug: str) -> bool:
        """Delete a page by slug. Falls back to writing empty content if gbrain lacks delete_page tool."""
        result = await self._call_tool("delete_page", {"slug": slug})
        if "error" in result:
            logger.debug("delete_page tool not available, falling back to soft-delete: {}", result["error"])
            return await self.write_page(slug, {"deleted": True, "type": "fuzz/deleted"}, "")
        return "error" not in result
```

- [ ] **Step 2: Commit**

```bash
git add harness_generator/src/langchain_agent/memory_adapter.py
git commit -m "feat: add list_pages and delete_page methods to MemoryAdapter"
```

---

### Task 2: Add MemoryAdapter singleton to FastAPI lifespan

**Files:**
- Modify: `harness_generator/src/langchain_agent/main.py`

- [ ] **Step 1: Import MemoryAdapter**

Add near the top of main.py (after the existing imports, around line 10-14):

```python
from harness_generator.src.langchain_agent.memory_adapter import MemoryAdapter
```

- [ ] **Step 2: Initialize MemoryAdapter in `_lifespan`**

In the `_lifespan` function (around line 48-58), initialize the adapter and set it on `app.state`:

```python
@asynccontextmanager
async def _lifespan(app: FastAPI):
    # ... existing startup code ...
    apply_config_to_env(cfg)
    _init_job_store()

    # Initialize MemoryAdapter singleton for API access
    memory_adapter = MemoryAdapter()
    app.state.memory_adapter = memory_adapter
    logger.info("MemoryAdapter initialized for API access")

    yield

    # Shutdown: close MemoryAdapter
    try:
        await memory_adapter.close()
        logger.info("MemoryAdapter closed")
    except Exception as exc:
        logger.warning("Error closing MemoryAdapter: {}", exc)
```

- [ ] **Step 2: Commit**

```bash
git add harness_generator/src/langchain_agent/main.py
git commit -m "feat: add MemoryAdapter singleton to FastAPI lifespan"
```

---

### Task 3: Add 5 memory API endpoints to main.py

**Files:**
- Modify: `harness_generator/src/langchain_agent/main.py`

- [ ] **Step 1: Add `Query` to FastAPI import**

Change line 5 from:

```python
from fastapi import FastAPI, Body, HTTPException, Response, Request
```

to:

```python
from fastapi import FastAPI, Body, HTTPException, Query, Response, Request
```

- [ ] **Step 2: Add type mapping dict**

Add a constant near the top of main.py (after the existing constants, around line 127):

```python
_MEMORY_TYPE_PREFIX: dict[str, str] = {
    "targets": "fuzz/targets",
    "sessions": "fuzz/sessions",
    "crashes": "fuzz/crashes",
    "strategies": "fuzz/strategies",
    "harnesses": "fuzz/harnesses",
}
```

- [ ] **Step 3: Add `GET /api/memory/search` endpoint**

Add after the existing endpoints, before the `if __name__ == "__main__"` block (around line 3615):

```python
@app.get("/api/memory/search")
async def memory_search(q: str = "", type: str = ""):
    """Full-text search across memory pages, optionally filtered by type."""
    adapter = getattr(app.state, "memory_adapter", None)
    if adapter is None:
        return {"enabled": False, "results": [], "total": 0}

    query_text = q.strip()
    if type:
        prefix = _MEMORY_TYPE_PREFIX.get(type, "")
        if prefix and query_text:
            query_text = f"type:{prefix} {query_text}"
        elif prefix:
            query_text = f"type:{prefix}"

    try:
        raw = await adapter.query_experience(query_text, timeout=5.0)
    except Exception as exc:
        logger.warning("memory_search error: {}", exc)
        return {"enabled": True, "results": [], "total": 0, "error": str(exc)}

    results = []
    for r in raw:
        slug = r.get("slug", "")
        page_type = "unknown"
        for key, prefix in _MEMORY_TYPE_PREFIX.items():
            if slug.startswith(prefix + "/"):
                page_type = key
                break
        results.append({
            "slug": slug,
            "type": page_type,
            "title": r.get("title", slug.rsplit("/", 1)[-1] if "/" in slug else slug),
            "score": r.get("score", r.get("relevance", 0.0)),
            "snippet": r.get("snippet", r.get("summary", "")),
        })
    return {"enabled": True, "results": results, "total": len(results)}
```

- [ ] **Step 4: Add `GET /api/memory/pages` endpoint**

```python
@app.get("/api/memory/pages")
async def memory_pages(type: str = "", limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)):
    """List memory pages by type."""
    adapter = getattr(app.state, "memory_adapter", None)
    if adapter is None:
        return {"enabled": False, "results": [], "total": 0}

    prefix = _MEMORY_TYPE_PREFIX.get(type, "")
    try:
        raw = await adapter.list_pages(type_prefix=prefix, limit=limit, offset=offset)
    except Exception as exc:
        logger.warning("memory_pages error: {}", exc)
        return {"enabled": True, "results": [], "total": 0, "error": str(exc)}

    results = []
    for r in raw:
        slug = r.get("slug", "")
        results.append({
            "slug": slug,
            "type": type or "unknown",
            "title": r.get("title", slug.rsplit("/", 1)[-1] if "/" in slug else slug),
            "score": 0.0,
            "snippet": r.get("summary", r.get("snippet", "")),
        })
    return {"enabled": True, "results": results, "total": len(results)}
```

- [ ] **Step 5: Add `GET /api/memory/page/{slug}` endpoint**

```python
@app.get("/api/memory/page/{slug:path}")
async def memory_get_page(slug: str):
    """Get a single memory page by slug."""
    adapter = getattr(app.state, "memory_adapter", None)
    if adapter is None:
        raise HTTPException(status_code=503, detail="Memory service not available")

    try:
        page = await adapter.get_page(slug)
    except Exception as exc:
        logger.warning("memory_get_page({}) error: {}", slug, exc)
        raise HTTPException(status_code=504, detail="Memory service timeout")

    if page is None:
        raise HTTPException(status_code=404, detail=f"Page not found: {slug}")

    return {"enabled": True, "page": page}
```

Note: This endpoint MUST be registered AFTER `/api/memory/search` and `/api/memory/pages` to avoid FastAPI route conflicts (the `{slug:path}` wildcard would otherwise capture `/api/memory/search`).

- [ ] **Step 6: Add `PUT /api/memory/page/{slug}` endpoint**

```python
@app.put("/api/memory/page/{slug:path}")
async def memory_update_page(slug: str, frontmatter: dict):
    """Update a memory page's frontmatter."""
    adapter = getattr(app.state, "memory_adapter", None)
    if adapter is None:
        raise HTTPException(status_code=503, detail="Memory service not available")

    try:
        page = await adapter.get_page(slug)
    except Exception:
        raise HTTPException(status_code=504, detail="Memory service timeout")

    if page is None:
        raise HTTPException(status_code=404, detail=f"Page not found: {slug}")

    existing_fm = page.get("frontmatter", {})
    compiled_truth = page.get("compiled_truth", page.get("content", ""))
    timeline = page.get("timeline", [])

    existing_fm.update(frontmatter)

    ok = await adapter.write_page(slug, existing_fm, compiled_truth, timeline)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update page")

    return {"ok": True, "slug": slug}
```

- [ ] **Step 7: Add `DELETE /api/memory/page/{slug}` endpoint**

```python
@app.delete("/api/memory/page/{slug:path}")
async def memory_delete_page(slug: str):
    """Delete a memory page."""
    adapter = getattr(app.state, "memory_adapter", None)
    if adapter is None:
        raise HTTPException(status_code=503, detail="Memory service not available")

    try:
        page = await adapter.get_page(slug)
    except Exception:
        raise HTTPException(status_code=504, detail="Memory service timeout")

    if page is None:
        raise HTTPException(status_code=404, detail=f"Page not found: {slug}")

    ok = await adapter.delete_page(slug)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to delete page")

    return {"ok": True, "slug": slug}
```

- [ ] **Step 8: Commit**

```bash
git add harness_generator/src/langchain_agent/main.py
git commit -m "feat: add 5 memory API endpoints (search, pages, get, update, delete)"
```

---

### Task 4: Add backend tests for memory API

**Files:**
- Create: `tests/test_memory_api.py`

- [ ] **Step 1: Write test file**

```python
"""Tests for the /api/memory endpoints."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def mock_adapter():
    """Create a mock MemoryAdapter."""
    adapter = MagicMock()
    adapter.query_experience = AsyncMock(return_value=[
        {
            "slug": "fuzz/targets/test-lib",
            "title": "test-lib",
            "score": 0.95,
            "snippet": "A test library",
        }
    ])
    adapter.list_pages = AsyncMock(return_value=[
        {
            "slug": "fuzz/targets/test-lib",
            "title": "test-lib",
            "summary": "A test library",
        }
    ])
    adapter.get_page = AsyncMock(return_value={
        "slug": "fuzz/targets/test-lib",
        "frontmatter": {"repo_url": "https://github.com/test/lib", "repo_language": "C"},
        "compiled_truth": "## Overview\nTest library",
        "timeline": [],
    })
    adapter.write_page = AsyncMock(return_value=True)
    adapter.delete_page = AsyncMock(return_value=True)
    return adapter


@pytest.fixture
def client(mock_adapter):
    """Create a TestClient with mock adapter on app.state."""
    from harness_generator.src.langchain_agent.main import app
    app.state.memory_adapter = mock_adapter
    return TestClient(app)


class TestMemorySearch:
    def test_search_returns_results(self, client, mock_adapter):
        resp = client.get("/api/memory/search?q=fuzz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["total"] == 1
        assert data["results"][0]["slug"] == "fuzz/targets/test-lib"
        mock_adapter.query_experience.assert_called_once()

    def test_search_with_type_filter(self, client, mock_adapter):
        resp = client.get("/api/memory/search?q=fuzz&type=targets")
        assert resp.status_code == 200
        mock_adapter.query_experience.assert_called_once()


class TestMemoryPages:
    def test_pages_returns_results(self, client, mock_adapter):
        resp = client.get("/api/memory/pages?type=targets")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert len(data["results"]) == 1
        mock_adapter.list_pages.assert_called_once_with(
            type_prefix="fuzz/targets", limit=50, offset=0
        )


class TestMemoryGetPage:
    def test_get_page_returns_page(self, client, mock_adapter):
        url = "/api/memory/page/fuzz/targets/test-lib"
        resp = client.get(url)
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert "page" in data

    def test_get_page_not_found(self, client, mock_adapter):
        mock_adapter.get_page.return_value = None
        url = "/api/memory/page/fuzz/targets/nonexistent"
        resp = client.get(url)
        assert resp.status_code == 404


class TestMemoryUpdatePage:
    def test_update_page(self, client, mock_adapter):
        url = "/api/memory/page/fuzz/targets/test-lib"
        resp = client.put(url, json={"repo_language": "C++"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_update_page_not_found(self, client, mock_adapter):
        mock_adapter.get_page.return_value = None
        url = "/api/memory/page/fuzz/targets/nonexistent"
        resp = client.put(url, json={})
        assert resp.status_code == 404


class TestMemoryDeletePage:
    def test_delete_page(self, client, mock_adapter):
        url = "/api/memory/page/fuzz/targets/test-lib"
        resp = client.delete(url)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_delete_page_not_found(self, client, mock_adapter):
        mock_adapter.get_page.return_value = None
        url = "/api/memory/page/fuzz/targets/nonexistent"
        resp = client.delete(url)
        assert resp.status_code == 404


class TestMemoryDisabled:
    def test_search_when_disabled(self):
        from harness_generator.src.langchain_agent.main import app
        app.state.memory_adapter = None
        client = TestClient(app)
        resp = client.get("/api/memory/search")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False
        assert data["results"] == []

    def test_page_when_disabled(self):
        from harness_generator.src.langchain_agent.main import app
        app.state.memory_adapter = None
        client = TestClient(app)
        url = "/api/memory/page/fuzz/targets/test"
        resp = client.get(url)
        assert resp.status_code == 503
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
cd /home/bohuju/TIanHeng_project/Sherpa/.claude/worktrees/remove-k8s
source harness_generator/.venv/bin/activate
python -m pytest tests/test_memory_api.py -xvs
```

Expected: All 8 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_memory_api.py
git commit -m "test: add memory API endpoint tests"
```

---

### Task 5: Add frontend Zod schemas for memory

**Files:**
- Modify: `frontend-next/lib/api/schemas.ts`

- [ ] **Step 1: Add memory schemas**

Add at the end of `schemas.ts` (after line 129):

```typescript
// ── Memory ──

export const memoryResultSchema = z.object({
  slug: z.string(),
  type: z.string(),
  title: z.string(),
  score: z.number().default(0),
  snippet: z.string().default(''),
});

export const memorySearchResponseSchema = z.object({
  enabled: z.boolean().default(false),
  results: z.array(memoryResultSchema).default([]),
  total: z.number().int().default(0),
  error: z.string().optional(),
});

export const memoryPagesResponseSchema = z.object({
  enabled: z.boolean().default(false),
  results: z.array(memoryResultSchema).default([]),
  total: z.number().int().default(0),
  error: z.string().optional(),
});

export const memoryPageResponseSchema = z.object({
  enabled: z.boolean().default(true),
  page: z.any(),
});

export const memoryUpdateResponseSchema = z.object({
  ok: z.boolean(),
  slug: z.string(),
});

export const memoryDeleteResponseSchema = z.object({
  ok: z.boolean(),
  slug: z.string(),
});

export type MemoryResult = z.infer<typeof memoryResultSchema>;
export type MemorySearchResponse = z.infer<typeof memorySearchResponseSchema>;
export type MemoryPagesResponse = z.infer<typeof memoryPagesResponseSchema>;
export type MemoryPageResponse = z.infer<typeof memoryPageResponseSchema>;
```

- [ ] **Step 2: Commit**

```bash
git add frontend-next/lib/api/schemas.ts
git commit -m "feat: add memory Zod schemas to frontend"
```

---

### Task 6: Add frontend API client functions for memory

**Files:**
- Modify: `frontend-next/lib/api/client.ts`

- [ ] **Step 1: Add imports**

Add to the import block at the top of `client.ts`:

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
  type WebConfig,
  type SystemStatus,
  type TaskDetail,
  type TaskSummary,
  type MemorySearchResponse,
  type MemoryPagesResponse,
  type MemoryPageResponse,
} from './schemas';
```

- [ ] **Step 2: Add memory API functions**

Add at the end of `client.ts` (after line 121):

```typescript
// ── Memory ──

export async function searchMemory(q: string, type?: string): Promise<MemorySearchResponse> {
  const params = new URLSearchParams({ q });
  if (type) params.set('type', type);
  const data = await request<unknown>(`/memory/search?${params.toString()}`);
  return memorySearchResponseSchema.parse(data);
}

export async function listMemoryPages(type: string, limit = 50, offset = 0): Promise<MemoryPagesResponse> {
  const params = new URLSearchParams({ type, limit: String(limit), offset: String(offset) });
  const data = await request<unknown>(`/memory/pages?${params.toString()}`);
  return memoryPagesResponseSchema.parse(data);
}

export async function getMemoryPage(slug: string): Promise<MemoryPageResponse> {
  const data = await request<unknown>(`/memory/page/${encodeURIComponent(slug)}`);
  return memoryPageResponseSchema.parse(data);
}

export async function updateMemoryPage(slug: string, frontmatter: Record<string, unknown>): Promise<{ ok: boolean; slug: string }> {
  const data = await request<unknown>(`/memory/page/${encodeURIComponent(slug)}`, {
    method: 'PUT',
    body: JSON.stringify(frontmatter),
  });
  return memoryUpdateResponseSchema.parse(data);
}

export async function deleteMemoryPage(slug: string): Promise<{ ok: boolean; slug: string }> {
  const data = await request<unknown>(`/memory/page/${encodeURIComponent(slug)}`, {
    method: 'DELETE',
  });
  return memoryDeleteResponseSchema.parse(data);
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend-next/lib/api/client.ts
git commit -m "feat: add memory API client functions"
```

---

### Task 7: Add frontend React Query hooks for memory

**Files:**
- Modify: `frontend-next/lib/api/hooks.ts`

- [ ] **Step 1: Add imports**

Add to the import block at the top of `hooks.ts`:

```typescript
import {
  getConfig,
  getSystem,
  getTask,
  getTasks,
  putConfig,
  stopTask,
  submitTask,
  searchMemory,
  listMemoryPages,
  getMemoryPage,
  updateMemoryPage,
  deleteMemoryPage,
  type SubmitTaskInput,
} from './client';
```

- [ ] **Step 2: Add memory hooks**

Add at the end of `hooks.ts` (after line 80):

```typescript
// ── Memory ──

export function useMemorySearch(q: string, type: string) {
  return useQuery({
    queryKey: ['memory', 'search', q, type],
    queryFn: () => searchMemory(q, type || undefined),
    enabled: q.length > 0,
  });
}

export function useMemoryPages(type: string) {
  return useQuery({
    queryKey: ['memory', 'pages', type],
    queryFn: () => listMemoryPages(type),
  });
}

export function useMemoryPage(slug: string | null) {
  return useQuery({
    queryKey: ['memory', 'page', slug],
    queryFn: () => getMemoryPage(slug as string),
    enabled: Boolean(slug),
  });
}

export function useUpdateMemoryPageMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ slug, frontmatter }: { slug: string; frontmatter: Record<string, unknown> }) =>
      updateMemoryPage(slug, frontmatter),
    onSuccess: (_data, variables) => {
      void qc.invalidateQueries({ queryKey: ['memory', 'page', variables.slug] });
      void qc.invalidateQueries({ queryKey: ['memory', 'pages'] });
      void qc.invalidateQueries({ queryKey: ['memory', 'search'] });
    },
  });
}

export function useDeleteMemoryPageMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (slug: string) => deleteMemoryPage(slug),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['memory', 'pages'] });
      void qc.invalidateQueries({ queryKey: ['memory', 'search'] });
    },
  });
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend-next/lib/api/hooks.ts
git commit -m "feat: add React Query hooks for memory API"
```

---

### Task 8: Create MemoryTypeTabs component

**Files:**
- Create: `frontend-next/components/MemoryTypeTabs.tsx`

- [ ] **Step 1: Write component**

```typescript
'use client';

import { Chip, Stack } from '@mui/material';

const TYPE_OPTIONS = [
  { key: '', label: '全部' },
  { key: 'targets', label: '目标仓库' },
  { key: 'sessions', label: 'Session' },
  { key: 'crashes', label: 'Crash' },
  { key: 'strategies', label: '策略' },
  { key: 'harnesses', label: 'Harness' },
] as const;

interface MemoryTypeTabsProps {
  value: string;
  onChange: (type: string) => void;
}

export function MemoryTypeTabs({ value, onChange }: MemoryTypeTabsProps) {
  return (
    <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
      {TYPE_OPTIONS.map((opt) => (
        <Chip
          key={opt.key}
          label={opt.label}
          size="small"
          variant={value === opt.key ? 'filled' : 'outlined'}
          color={value === opt.key ? 'primary' : 'default'}
          onClick={() => onChange(opt.key)}
          sx={{ fontSize: 13 }}
        />
      ))}
    </Stack>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend-next/components/MemoryTypeTabs.tsx
git commit -m "feat: add MemoryTypeTabs component"
```

---

### Task 9: Create MemorySearchBar component

**Files:**
- Create: `frontend-next/components/MemorySearchBar.tsx`

- [ ] **Step 1: Write component**

```typescript
'use client';

import { useState } from 'react';
import { IconButton, InputAdornment, TextField } from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';

interface MemorySearchBarProps {
  onSearch: (q: string) => void;
}

export function MemorySearchBar({ onSearch }: MemorySearchBarProps) {
  const [value, setValue] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSearch(value.trim());
  };

  return (
    <form onSubmit={handleSubmit}>
      <TextField
        fullWidth
        size="small"
        placeholder="搜索记忆关键词..."
        value={value}
        onChange={(e) => setValue(e.target.value)}
        slotProps={{
          input: {
            endAdornment: (
              <InputAdornment position="end">
                <IconButton size="small" type="submit" aria-label="搜索">
                  <SearchIcon fontSize="small" />
                </IconButton>
              </InputAdornment>
            ),
          },
        }}
      />
    </form>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend-next/components/MemorySearchBar.tsx
git commit -m "feat: add MemorySearchBar component"
```

---

### Task 10: Create MemoryResultsList component

**Files:**
- Create: `frontend-next/components/MemoryResultsList.tsx`

- [ ] **Step 1: Write component**

```typescript
'use client';

import { Box, Chip, CircularProgress, Paper, Stack, Typography } from '@mui/material';
import type { MemoryResult } from '@/lib/api/schemas';

const TYPE_LABELS: Record<string, string> = {
  targets: '目标仓库',
  sessions: 'Session',
  crashes: 'Crash',
  strategies: '策略',
  harnesses: 'Harness',
};

const TYPE_COLORS: Record<string, { bg: string; color: string }> = {
  targets: { bg: '#e3f2fd', color: '#0f5ad8' },
  sessions: { bg: '#e8f5e9', color: '#2e7d32' },
  crashes: { bg: '#fce4ec', color: '#c62828' },
  strategies: { bg: '#fff3e0', color: '#ed6c02' },
  harnesses: { bg: '#f3e5f5', color: '#6a1b9a' },
};

interface MemoryResultsListProps {
  results: MemoryResult[];
  loading: boolean;
  emptyText: string;
  onSelect: (slug: string) => void;
}

export function MemoryResultsList({ results, loading, emptyText, onSelect }: MemoryResultsListProps) {
  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress size={32} />
      </Box>
    );
  }

  if (results.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ py: 3, textAlign: 'center' }}>
        {emptyText}
      </Typography>
    );
  }

  return (
    <Stack spacing={1}>
      {results.map((r) => {
        const colors = TYPE_COLORS[r.type] || { bg: '#f5f5f5', color: '#666' };
        return (
          <Paper
            key={r.slug}
            variant="outlined"
            sx={{ p: 1.5, cursor: 'pointer', '&:hover': { bgcolor: 'action.hover' } }}
            onClick={() => onSelect(r.slug)}
          >
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 0.5 }}>
              <Typography variant="subtitle2" sx={{ fontSize: 13, fontWeight: 600 }}>
                {r.title}
              </Typography>
              <Chip
                label={TYPE_LABELS[r.type] || r.type}
                size="small"
                sx={{
                  fontSize: 11,
                  height: 22,
                  bgcolor: colors.bg,
                  color: colors.color,
                  flexShrink: 0,
                  ml: 1,
                }}
              />
            </Box>
            {r.snippet ? (
              <Typography variant="body2" color="text.secondary" sx={{ fontSize: 12, mb: 0.5 }}>
                {r.snippet}
              </Typography>
            ) : null}
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Typography variant="caption" color="text.disabled" sx={{ fontSize: 11 }}>
                {r.slug}
              </Typography>
              {r.score > 0 ? (
                <Typography variant="caption" color="text.disabled" sx={{ fontSize: 11 }}>
                  相关度 {r.score.toFixed(2)}
                </Typography>
              ) : null}
            </Box>
          </Paper>
        );
      })}
    </Stack>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend-next/components/MemoryResultsList.tsx
git commit -m "feat: add MemoryResultsList component"
```

---

### Task 11: Create MemoryDetail component

**Files:**
- Create: `frontend-next/components/MemoryDetail.tsx`

- [ ] **Step 1: Write component**

```typescript
'use client';

import { Box, Button, Chip, Stack, Typography } from '@mui/material';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';

const TYPE_LABELS: Record<string, string> = {
  targets: '目标仓库',
  sessions: 'Session',
  crashes: 'Crash',
  strategies: '策略',
  harnesses: 'Harness',
};

interface MemoryDetailProps {
  slug: string;
  pageType: string;
  frontmatter: Record<string, unknown>;
  compiledTruth: string;
  onBack: () => void;
  onEdit: () => void;
  onDelete: () => void;
}

export function MemoryDetail({
  slug,
  pageType,
  frontmatter,
  compiledTruth,
  onBack,
  onEdit,
  onDelete,
}: MemoryDetailProps) {
  const entries = Object.entries(frontmatter).filter(
    ([, v]) => v !== null && v !== undefined && v !== '',
  );

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
        <Button size="small" onClick={onBack} sx={{ minWidth: 0, fontSize: 13 }}>
          ← 返回列表
        </Button>
        <Chip
          label={TYPE_LABELS[pageType] || pageType}
          size="small"
          sx={{ ml: 'auto', fontSize: 11, height: 22 }}
        />
      </Box>

      <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 0.5 }}>
        {String(frontmatter.title || slug.split('/').pop() || slug)}
      </Typography>
      <Typography variant="caption" color="text.disabled" sx={{ mb: 2, display: 'block' }}>
        slug: {slug}
      </Typography>

      <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1.5, mb: 2 }}>
        {entries.map(([key, value]) => (
          <Box key={key}>
            <Typography variant="caption" color="text.secondary" sx={{ fontSize: 11 }}>
              {key}
            </Typography>
            <Typography variant="body2" sx={{ fontSize: 13, fontWeight: 500, wordBreak: 'break-all' }}>
              {Array.isArray(value) ? value.join(', ') : String(value)}
            </Typography>
          </Box>
        ))}
      </Box>

      {compiledTruth ? (
        <Box sx={{ mb: 2 }}>
          <Typography variant="caption" color="text.secondary" sx={{ fontSize: 11 }}>
            内容
          </Typography>
          <Typography
            variant="body2"
            sx={{
              fontSize: 12,
              whiteSpace: 'pre-wrap',
              bgcolor: 'grey.50',
              p: 1.5,
              borderRadius: 1,
              maxHeight: 200,
              overflow: 'auto',
            }}
          >
            {compiledTruth.slice(0, 2000)}
          </Typography>
        </Box>
      ) : null}

      <Stack direction="row" spacing={1} sx={{ pt: 1.5, borderTop: '1px solid', borderColor: 'divider' }}>
        <Button size="small" variant="contained" startIcon={<EditIcon fontSize="small" />} onClick={onEdit}>
          编辑
        </Button>
        <Button
          size="small"
          variant="outlined"
          color="error"
          startIcon={<DeleteIcon fontSize="small" />}
          onClick={onDelete}
        >
          删除
        </Button>
      </Stack>
    </Box>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend-next/components/MemoryDetail.tsx
git commit -m "feat: add MemoryDetail component"
```

---

### Task 12: Create MemoryEditForm component

**Files:**
- Create: `frontend-next/components/MemoryEditForm.tsx`

- [ ] **Step 1: Write component**

```typescript
'use client';

import { useState } from 'react';
import { Box, Button, Stack, TextField, Typography } from '@mui/material';
import SaveIcon from '@mui/icons-material/Save';

const EDITABLE_FIELDS: Record<string, string[]> = {
  targets: ['repo_url', 'repo_language', 'true_vulns_found', 'cve_ids', 'recommended_strategies', 'top_coverage'],
  sessions: ['repo', 'started_at', 'ended_at', 'stages_completed', 'total_harnesses', 'total_crashes', 'coverage_start', 'coverage_end'],
  crashes: ['crash_signature', 'crash_type', 'verdict', 'severity', 'cve_id', 'asan_report'],
  strategies: ['strategy_type', 'target_language', 'harness_pattern', 'seed_families', 'build_flags', 'success_rate'],
  harnesses: ['target_function', 'build_status', 'fuzz_result', 'coverage_achieved'],
};

interface MemoryEditFormProps {
  slug: string;
  pageType: string;
  frontmatter: Record<string, unknown>;
  onSave: (frontmatter: Record<string, unknown>) => void;
  onCancel: () => void;
  saving: boolean;
}

export function MemoryEditForm({ slug, pageType, frontmatter, onSave, onCancel, saving }: MemoryEditFormProps) {
  const fields = EDITABLE_FIELDS[pageType] || Object.keys(frontmatter);
  const [form, setForm] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    for (const key of fields) {
      const v = frontmatter[key];
      if (v === null || v === undefined) {
        init[key] = '';
      } else if (Array.isArray(v)) {
        init[key] = v.join(', ');
      } else {
        init[key] = String(v);
      }
    }
    return init;
  });

  const handleChange = (key: string, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const result: Record<string, unknown> = {};
    for (const key of fields) {
      const raw = form[key]?.trim() ?? '';
      if (['true_vulns_found', 'total_harnesses', 'total_crashes', 'validated_sessions'].includes(key)) {
        result[key] = raw === '' ? 0 : parseInt(raw, 10) || 0;
      } else if (['top_coverage', 'coverage_start', 'coverage_end', 'success_rate', 'avg_coverage_gain', 'coverage_achieved'].includes(key)) {
        result[key] = raw === '' ? 0 : parseFloat(raw) || 0;
      } else if (['cve_ids', 'recommended_strategies', 'attack_surfaces', 'stages_completed', 'seed_families', 'build_flags', 'effective_for_repos'].includes(key)) {
        result[key] = raw === '' ? [] : raw.split(',').map((s) => s.trim()).filter(Boolean);
      } else {
        result[key] = raw;
      }
    }
    onSave(result);
  };

  return (
    <Box component="form" onSubmit={handleSubmit}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
        <Button size="small" onClick={onCancel} sx={{ minWidth: 0, fontSize: 13 }}>
          ← 取消编辑
        </Button>
        <Typography variant="caption" color="warning.main" sx={{ ml: 'auto', fontWeight: 500 }}>
          编辑模式
        </Typography>
      </Box>

      <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 2 }}>
        {String(frontmatter.title || slug.split('/').pop() || slug)}
      </Typography>

      <Stack spacing={1.5}>
        {fields.map((key) => (
          <Box key={key}>
            <Typography variant="caption" color="text.secondary" sx={{ fontSize: 11, mb: 0.25, display: 'block' }}>
              {key}
            </Typography>
            <TextField
              fullWidth
              size="small"
              value={form[key] ?? ''}
              onChange={(e) => handleChange(key, e.target.value)}
              multiline={key === 'asan_report'}
              minRows={key === 'asan_report' ? 3 : 1}
              sx={{ '& .MuiInputBase-input': { fontSize: 13 } }}
            />
          </Box>
        ))}
      </Stack>

      <Stack direction="row" spacing={1} sx={{ pt: 2, mt: 1, borderTop: '1px solid', borderColor: 'divider' }}>
        <Button
          type="submit"
          size="small"
          variant="contained"
          color="success"
          startIcon={<SaveIcon fontSize="small" />}
          disabled={saving}
        >
          {saving ? '保存中...' : '保存'}
        </Button>
        <Button size="small" variant="outlined" onClick={onCancel} disabled={saving}>
          取消
        </Button>
      </Stack>
    </Box>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend-next/components/MemoryEditForm.tsx
git commit -m "feat: add MemoryEditForm component"
```

---

### Task 13: Create MemoryDrawer container component

**Files:**
- Create: `frontend-next/components/MemoryDrawer.tsx`

- [ ] **Step 1: Write component**

```typescript
'use client';

import { useCallback, useState } from 'react';
import {
  Alert,
  Box,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Button,
  Drawer,
  IconButton,
  Typography,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import {
  useMemorySearch,
  useMemoryPages,
  useMemoryPage,
  useUpdateMemoryPageMutation,
  useDeleteMemoryPageMutation,
} from '@/lib/api/hooks';
import { MemorySearchBar } from './MemorySearchBar';
import { MemoryTypeTabs } from './MemoryTypeTabs';
import { MemoryResultsList } from './MemoryResultsList';
import { MemoryDetail } from './MemoryDetail';
import { MemoryEditForm } from './MemoryEditForm';

type ViewMode = 'list' | 'detail' | 'edit';

interface MemoryDrawerProps {
  open: boolean;
  onClose: () => void;
}

export function MemoryDrawer({ open, onClose }: MemoryDrawerProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [activeSearch, setActiveSearch] = useState('');
  const [pageType, setPageType] = useState('');
  const [viewMode, setViewMode] = useState<ViewMode>('list');
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  const search = useMemorySearch(activeSearch, pageType);
  const pages = useMemoryPages(pageType);
  const detail = useMemoryPage(selectedSlug);
  const updatePage = useUpdateMemoryPageMutation();
  const deletePage = useDeleteMemoryPageMutation();

  const isSearchMode = activeSearch.length > 0;
  const results = isSearchMode ? search.data : pages.data;
  const loading = isSearchMode ? search.isLoading : pages.isLoading;

  const handleSearch = useCallback((q: string) => {
    setActiveSearch(q);
    setViewMode('list');
    setSelectedSlug(null);
  }, []);

  const handleTypeChange = useCallback((t: string) => {
    setPageType(t);
    setActiveSearch('');
    setViewMode('list');
    setSelectedSlug(null);
  }, []);

  const handleSelect = useCallback((slug: string) => {
    setSelectedSlug(slug);
    setViewMode('detail');
  }, []);

  const handleBack = useCallback(() => {
    setViewMode('list');
    setSelectedSlug(null);
  }, []);

  const handleEdit = useCallback(() => {
    setViewMode('edit');
  }, []);

  const handleSave = useCallback(
    async (fm: Record<string, unknown>) => {
      if (!selectedSlug) return;
      await updatePage.mutateAsync({ slug: selectedSlug, frontmatter: fm });
      setViewMode('detail');
    },
    [selectedSlug, updatePage],
  );

  const handleDeleteClick = useCallback(() => {
    setDeleteDialogOpen(true);
  }, []);

  const handleDeleteConfirm = useCallback(async () => {
    if (!selectedSlug) return;
    await deletePage.mutateAsync(selectedSlug);
    setDeleteDialogOpen(false);
    setSelectedSlug(null);
    setViewMode('list');
  }, [selectedSlug, deletePage]);

  const page = detail.data?.page;
  const frontmatter = (page?.frontmatter || {}) as Record<string, unknown>;
  const compiledTruth = String(page?.compiled_truth || page?.content || '');

  return (
    <>
      <Drawer
        anchor="right"
        open={open}
        onClose={onClose}
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
              记忆查看
            </Typography>
            <IconButton size="small" onClick={onClose} aria-label="关闭">
              <CloseIcon fontSize="small" />
            </IconButton>
          </Box>

          {/* Body */}
          <Box sx={{ flex: 1, overflow: 'auto', px: 2, py: 2 }}>
            {results && !results.enabled ? (
              <Alert severity="info" sx={{ mb: 2 }}>
                记忆服务未启用。请确保 gbrain 已安装并运行。
              </Alert>
            ) : null}

            {viewMode === 'list' ? (
              <>
                <Stack spacing={2}>
                  <MemorySearchBar onSearch={handleSearch} />
                  <MemoryTypeTabs value={pageType} onChange={handleTypeChange} />
                </Stack>
                <Box sx={{ mt: 2 }}>
                  <MemoryResultsList
                    results={results?.results || []}
                    loading={loading}
                    emptyText={isSearchMode ? '未找到匹配的记忆' : '暂无记忆数据'}
                    onSelect={handleSelect}
                  />
                </Box>
              </>
            ) : null}

            {viewMode === 'detail' && page ? (
              <MemoryDetail
                slug={selectedSlug || ''}
                pageType={pageType || (results?.results || []).find((r) => r.slug === selectedSlug)?.type || ''}
                frontmatter={frontmatter}
                compiledTruth={compiledTruth}
                onBack={handleBack}
                onEdit={handleEdit}
                onDelete={handleDeleteClick}
              />
            ) : null}

            {viewMode === 'edit' ? (
              <MemoryEditForm
                slug={selectedSlug || ''}
                pageType={pageType || (results?.results || []).find((r) => r.slug === selectedSlug)?.type || ''}
                frontmatter={frontmatter}
                onSave={handleSave}
                onCancel={() => setViewMode('detail')}
                saving={updatePage.isPending}
              />
            ) : null}
          </Box>
        </Box>
      </Drawer>

      <Dialog open={deleteDialogOpen} onClose={() => setDeleteDialogOpen(false)}>
        <DialogTitle>确认删除</DialogTitle>
        <DialogContent>
          <DialogContentText>
            确定删除 {selectedSlug} 吗？此操作不可恢复。
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteDialogOpen(false)} size="small">
            取消
          </Button>
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
git add frontend-next/components/MemoryDrawer.tsx
git commit -m "feat: add MemoryDrawer container component"
```

---

### Task 14: Integrate MemoryDrawer into page.tsx

**Files:**
- Modify: `frontend-next/app/page.tsx`

- [ ] **Step 1: Add state and button to open drawer**

Add `useState` for drawer and the trigger button in page.tsx:

```typescript
'use client';

import { useEffect, useMemo, useState } from 'react';
import { Alert, Box, Button, Stack, Typography } from '@mui/material';
import PsychologyIcon from '@mui/icons-material/Psychology';
import { ConfigPanel } from '@/components/ConfigPanel';
import { LogPanel } from '@/components/LogPanel';
import { MemoryDrawer } from '@/components/MemoryDrawer';
import { SessionPanel } from '@/components/SessionPanel';
import { SystemOverviewCard } from '@/components/SystemOverviewCard';
import { TaskProgressPanel } from '@/components/TaskProgressPanel';
import { useStopTaskMutation, useSystemQuery, useTaskDetailQuery, useTasksQuery } from '@/lib/api/hooks';
import { useUiStore } from '@/store/useUiStore';

export default function HomePage() {
  // ... existing state / hooks ...

  const [memoryOpen, setMemoryOpen] = useState(false);

  // ... existing logic ...

  return (
    <Box sx={{ maxWidth: 1600, mx: 'auto', px: 2.5, py: 2.5 }}>
      <Stack spacing={2}>
        <Stack direction="row" alignItems="center" justifyContent="space-between">
          <Box>
            <Typography variant="h4" fontWeight={700}>Sherpa 控制台</Typography>
            <Typography variant="body2" color="text.secondary">
              重点视图：任务进度、子任务状态、日志与错误摘要。
            </Typography>
          </Box>
          <Button
            variant="outlined"
            startIcon={<PsychologyIcon />}
            onClick={() => setMemoryOpen(true)}
            size="small"
          >
            记忆查看
          </Button>
        </Stack>

        {/* ... rest of the existing JSX unchanged ... */}

        <MemoryDrawer open={memoryOpen} onClose={() => setMemoryOpen(false)} />
      </Stack>
    </Box>
  );
}
```

Note: The existing JSX structure (SystemOverviewCard, ConfigPanel, SessionPanel, etc.) remains unchanged. Only add the `useState`, `Button` in the header, and `<MemoryDrawer>` at the end of the Stack.

- [ ] **Step 2: Commit**

```bash
git add frontend-next/app/page.tsx
git commit -m "feat: integrate MemoryDrawer into dashboard page"
```

---

### Task 15: Final verification

- [ ] **Step 1: Run backend tests**

```bash
cd /home/bohuju/TIanHeng_project/Sherpa/.claude/worktrees/remove-k8s
source harness_generator/.venv/bin/activate
python -m pytest tests/test_memory_api.py -xvs
```

Expected: All tests pass.

- [ ] **Step 2: Run existing tests to verify no regressions**

```bash
python -m pytest tests/ -xvs
```

- [ ] **Step 3: Type-check frontend**

```bash
cd frontend-next
npx tsc --noEmit
```

Expected: No new type errors.

- [ ] **Step 4: Build frontend**

```bash
npm run build
```

Expected: Build succeeds.

- [ ] **Step 5: Commit any fixes**

```bash
git add -A
git commit -m "chore: final verification fixes"
```
