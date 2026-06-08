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
  onToast: (toast: { message: string; severity: 'success' | 'error' | 'info' | 'warning' } | null) => void;
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
