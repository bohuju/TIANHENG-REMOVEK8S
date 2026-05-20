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
