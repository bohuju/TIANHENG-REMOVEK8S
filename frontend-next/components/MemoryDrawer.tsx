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
  CircularProgress,
  Drawer,
  IconButton,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import { useRouter } from 'next/navigation';
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

type ViewMode = 'list' | 'detail' | 'edit' | 'create';

const TYPE_OPTIONS = [
  { value: 'targets', label: '目标仓库' },
  { value: 'sessions', label: '会话' },
  { value: 'crashes', label: '崩溃' },
  { value: 'strategies', label: '策略' },
  { value: 'harnesses', label: '脚手架' },
];

const TYPE_PREFIXES: Record<string, string> = {
  targets: 'fuzz/targets',
  sessions: 'fuzz/sessions',
  crashes: 'fuzz/crashes',
  strategies: 'fuzz/strategies',
  harnesses: 'fuzz/harnesses',
};

interface MemoryDrawerProps {
  open: boolean;
  onClose: () => void;
}

export function MemoryDrawer({ open, onClose }: MemoryDrawerProps) {
  const router = useRouter();
  const [activeSearch, setActiveSearch] = useState('');
  const [searchKey, setSearchKey] = useState(0);
  const [pageType, setPageType] = useState('');
  const [viewMode, setViewMode] = useState<ViewMode>('list');
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [createSlug, setCreateSlug] = useState('');
  const [createType, setCreateType] = useState('targets');

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
    setErrorMessage(null);
    setViewMode('list');
    setSelectedSlug(null);
  }, []);

  const handleTypeChange = useCallback((t: string) => {
    setPageType(t);
    setActiveSearch('');
    setSearchKey((k) => k + 1);
    setErrorMessage(null);
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
      try {
        await updatePage.mutateAsync({ slug: selectedSlug, frontmatter: fm });
        setErrorMessage(null);
        setViewMode('detail');
      } catch (err) {
        setErrorMessage(`保存失败：${err instanceof Error ? err.message : '未知错误'}`);
      }
    },
    [selectedSlug, updatePage],
  );

  const handleDeleteClick = useCallback(() => {
    setDeleteDialogOpen(true);
  }, []);

  const handleDeleteConfirm = useCallback(async () => {
    if (!selectedSlug) return;
    try {
      await deletePage.mutateAsync(selectedSlug);
      setDeleteDialogOpen(false);
      setSelectedSlug(null);
      setViewMode('list');
    } catch (err) {
      setErrorMessage(`删除失败：${err instanceof Error ? err.message : '未知错误'}`);
      setDeleteDialogOpen(false);
    }
  }, [selectedSlug, deletePage]);

  const handleCreate = useCallback(() => {
    setCreateSlug('');
    setCreateType('targets');
    setErrorMessage(null);
    setViewMode('create');
    setSelectedSlug(null);
  }, []);

  const handleCreateSave = useCallback(
    async (fm: Record<string, unknown>) => {
      const slugRaw = createSlug.trim();
      if (!slugRaw) {
        setErrorMessage('请输入页面路径 (slug)');
        return;
      }
      const prefix = TYPE_PREFIXES[createType] || 'fuzz/targets';
      const typeMap: Record<string, string> = {
        targets: 'fuzz/target-repo', sessions: 'fuzz/session', crashes: 'fuzz/crash',
        strategies: 'fuzz/strategy', harnesses: 'fuzz/harness',
      };
      const fullSlug = `${prefix}/${slugRaw}`;
      try {
        await updatePage.mutateAsync({ slug: fullSlug, frontmatter: { ...fm, type: typeMap[createType] || 'fuzz/target-repo' } as unknown as Record<string, unknown> });
        setErrorMessage(null);
        setSelectedSlug(fullSlug);
        setViewMode('detail');
      } catch (err) {
        setErrorMessage(`创建失败：${err instanceof Error ? err.message : '未知错误'}`);
      }
    },
    [createSlug, createType, updatePage],
  );

  const page = detail.data?.page;
  const frontmatter = (page?.frontmatter || {}) as Record<string, unknown>;
  const compiledTruth = String(page?.compiled_truth || page?.content || '');
  const detailPageType = (page?.frontmatter as Record<string, unknown>)?.type as string | undefined || pageType;

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
          </Box>

          {/* Body */}
          <Box sx={{ flex: 1, overflow: 'auto', px: 2, py: 2 }}>
            {results && !results.enabled ? (
              <Alert severity="info" sx={{ mb: 2 }}>
                记忆服务未启用。请确保 gbrain 已安装并运行。
              </Alert>
            ) : results && results.healthy === false ? (
              <Alert severity="warning" sx={{ mb: 2 }}>
                记忆服务异常：{results.status?.last_error || 'gbrain 连接失败'}。数据可能不完整。
              </Alert>
            ) : null}

            {errorMessage ? (
              <Alert severity="error" sx={{ mb: 2 }} onClose={() => setErrorMessage(null)}>
                {errorMessage}
              </Alert>
            ) : null}

            {viewMode === 'list' ? (
              <>
                <Stack spacing={2}>
                  <MemorySearchBar key={searchKey} onSearch={handleSearch} />
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

            {(viewMode === 'detail' || viewMode === 'edit') && detail.isLoading ? (
              <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
                <CircularProgress size={32} />
              </Box>
            ) : null}

            {viewMode === 'detail' && page ? (
              <MemoryDetail
                slug={selectedSlug || ''}
                pageType={detailPageType}
                frontmatter={frontmatter}
                compiledTruth={compiledTruth}
                timeline={page?.timeline || []}
                onBack={handleBack}
                onEdit={handleEdit}
                onDelete={handleDeleteClick}
              />
            ) : null}

            {viewMode === 'edit' && page ? (
              <MemoryEditForm
                slug={selectedSlug || ''}
                pageType={detailPageType}
                frontmatter={frontmatter}
                onSave={handleSave}
                onCancel={() => setViewMode('detail')}
                saving={updatePage.isPending}
              />
            ) : null}

            {viewMode === 'create' ? (
              <Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
                  <Button size="small" onClick={handleBack} sx={{ minWidth: 0, fontSize: 13 }}>
                    ← 取消
                  </Button>
                  <Typography variant="caption" color="success.main" sx={{ ml: 'auto', fontWeight: 500 }}>
                    新建模式
                  </Typography>
                </Box>

                <Stack spacing={1.5} sx={{ mb: 2 }}>
                  <Box>
                    <Typography variant="caption" color="text.secondary" sx={{ fontSize: 11, mb: 0.25, display: 'block' }}>
                      Type
                    </Typography>
                    <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                      {TYPE_OPTIONS.map((opt) => (
                        <Button
                          key={opt.value}
                          size="small"
                          variant={createType === opt.value ? 'contained' : 'outlined'}
                          onClick={() => setCreateType(opt.value)}
                          sx={{ fontSize: 11, py: 0.25 }}
                        >
                          {opt.label}
                        </Button>
                      ))}
                    </Box>
                  </Box>
                  <Box>
                    <Typography variant="caption" color="text.secondary" sx={{ fontSize: 11, mb: 0.25, display: 'block' }}>
                      Slug
                    </Typography>
                    <TextField
                      fullWidth
                      size="small"
                      value={createSlug}
                      onChange={(e) => setCreateSlug(e.target.value)}
                      placeholder="my-page-slug"
                      InputProps={{
                        startAdornment: (
                          <Typography variant="caption" color="text.secondary" sx={{ mr: 0.5, fontSize: 11 }}>
                            {TYPE_PREFIXES[createType] || 'fuzz/targets'}/
                          </Typography>
                        ),
                      }}
                      sx={{ '& .MuiInputBase-input': { fontSize: 13 } }}
                    />
                  </Box>
                </Stack>

                <MemoryEditForm
                  slug={createSlug || 'new'}
                  pageType={createType}
                  frontmatter={{}}
                  onSave={handleCreateSave}
                  onCancel={handleBack}
                  saving={updatePage.isPending}
                />
              </Box>
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
