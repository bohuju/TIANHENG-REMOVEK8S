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
