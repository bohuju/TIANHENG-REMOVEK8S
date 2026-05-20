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
