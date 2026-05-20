'use client';

import { useState } from 'react';
import { Box, Button, Stack, TextField, Typography } from '@mui/material';
import SaveIcon from '@mui/icons-material/Save';

const EDITABLE_FIELDS: Record<string, string[]> = {
  targets: ['repo_url', 'repo_language', 'total_sessions', 'total_crashes_found', 'true_vulns_found', 'cve_ids', 'recommended_strategies'],
  sessions: ['repo', 'started_at', 'ended_at', 'duration_seconds', 'stages_completed', 'total_harnesses', 'total_crashes', 'coverage_start', 'coverage_end'],
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
  const fields = EDITABLE_FIELDS[pageType] || [];
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
      if (['true_vulns_found', 'total_sessions', 'total_crashes_found', 'total_harnesses', 'total_crashes', 'stages_completed', 'duration_seconds'].includes(key)) {
        result[key] = raw === '' ? 0 : parseInt(raw, 10) || 0;
      } else if (['top_coverage', 'coverage_start', 'coverage_end', 'success_rate', 'coverage_achieved'].includes(key)) {
        result[key] = raw === '' ? 0 : parseFloat(raw) || 0;
      } else if (['cve_ids', 'recommended_strategies', 'seed_families', 'build_flags'].includes(key)) {
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
