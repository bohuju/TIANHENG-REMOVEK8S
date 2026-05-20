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
  timeline?: string[];
  onBack: () => void;
  onEdit: () => void;
  onDelete: () => void;
}

export function MemoryDetail({
  slug,
  pageType,
  frontmatter,
  compiledTruth,
  timeline,
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

      {timeline && timeline.length > 0 ? (
        <Box sx={{ mb: 2 }}>
          <Typography variant="caption" color="text.secondary" sx={{ fontSize: 11 }}>
            时间线
          </Typography>
          <Box
            sx={{
              fontSize: 12,
              bgcolor: (theme) => theme.palette.grey[50],
              p: 1.5,
              borderRadius: 1,
              maxHeight: 150,
              overflow: 'auto',
            }}
          >
            {timeline.map((entry, i) => (
              <Typography key={i} variant="body2" sx={{ fontSize: 12, mb: 0.5 }}>
                {entry}
              </Typography>
            ))}
          </Box>
        </Box>
      ) : null}

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
              bgcolor: (theme) => theme.palette.grey[50],
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
