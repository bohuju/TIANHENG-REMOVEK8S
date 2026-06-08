'use client';

import { useCallback, useState } from 'react';
import {
  Alert,
  Box,
  Snackbar,
  Typography,
} from '@mui/material';
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

      <MemoryStatsBar
        stats={stats.data}
        loading={stats.isLoading}
        onFilterByType={handleTypeFilter}
        activeType={pageType}
      />

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

      <MemoryTable
        results={results}
        loading={loading}
        total={total}
        selected={selected}
        onSelectionChange={handleSelectionChange}
        onSelectRow={handleSelectRow}
        pageType={pageType}
      />

      <MemoryPageDrawer
        open={drawerOpen}
        slug={selectedSlug}
        onClose={handleCloseDrawer}
        onRefresh={handleRefresh}
        onToast={setToast}
      />

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
