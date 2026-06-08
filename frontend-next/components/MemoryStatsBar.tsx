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
