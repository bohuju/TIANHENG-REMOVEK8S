'use client';

import { useState, useCallback } from 'react';
import {
  Box,
  Button,
  Chip,
  IconButton,
  InputAdornment,
  Menu,
  MenuItem,
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
        </Box>
      ) : null}
    </Box>
  );
}
