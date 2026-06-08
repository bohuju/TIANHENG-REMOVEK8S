'use client';

import { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Drawer,
  IconButton,
  Stack,
  Switch,
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import { useConfigQuery, useSaveConfigMutation, useTestModelMutation } from '@/lib/api/hooks';
import type { WebConfig } from '@/lib/api/schemas';

interface SettingsDrawerProps {
  open: boolean;
  onClose: () => void;
}

export function SettingsDrawer({ open, onClose }: SettingsDrawerProps) {
  const [tab, setTab] = useState(0);
  const cfgQuery = useConfigQuery();
  const saveCfg = useSaveConfigMutation();
  const testModel = useTestModelMutation();

  const [form, setForm] = useState<Partial<WebConfig>>({});
  const [saveMsg, setSaveMsg] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  useEffect(() => {
    if (cfgQuery.data && open) {
      setForm({ ...cfgQuery.data });
    }
  }, [cfgQuery.data, open]);

  const update = (key: string, value: unknown) => setForm((f) => ({ ...f, [key]: value }));

  const handleSave = async () => {
    try {
      await saveCfg.mutateAsync(form as WebConfig);
      setSaveMsg({ text: '配置已保存', type: 'success' });
    } catch (e) {
      setSaveMsg({ text: `保存失败：${e instanceof Error ? e.message : '未知错误'}`, type: 'error' });
    }
  };

  const handleTest = async () => {
    try {
      await saveCfg.mutateAsync(form as WebConfig);
    } catch {
      // continue to test even if save fails
    }
    testModel.mutate();
  };

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      PaperProps={{ sx: { width: { xs: '100%', sm: 480, md: 560 } } }}
    >
      <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        {/* Header */}
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', px: 2, py: 1.5, borderBottom: '1px solid', borderColor: 'divider' }}>
          <Typography variant="h6" fontWeight={600} sx={{ fontSize: 18 }}>系统设置</Typography>
          <IconButton size="small" onClick={onClose}><CloseIcon fontSize="small" /></IconButton>
        </Box>

        {/* Tabs */}
        <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ px: 2, borderBottom: '1px solid', borderColor: 'divider' }}>
          <Tab label="模型" />
          <Tab label="Fuzz" />
          <Tab label="Docker" />
        </Tabs>

        {/* Body */}
        <Box sx={{ flex: 1, overflow: 'auto', px: 2, py: 2 }}>
          {cfgQuery.isLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress size={32} /></Box>
          ) : (
            <>
              {tab === 0 && (
                <Stack spacing={2}>
                  <TextField label="API Key" type="password" size="small" fullWidth
                    value={form.openai_api_key || ''}
                    onChange={(e) => update('openai_api_key', e.target.value)}
                    helperText="支持 OpenAI 兼容的 API Key"
                  />
                  <TextField label="Base URL" size="small" fullWidth
                    value={form.openai_base_url || ''}
                    onChange={(e) => update('openai_base_url', e.target.value)}
                    placeholder="https://api.deepseek.com/v1"
                  />
                  <TextField label="Model" size="small" fullWidth
                    value={form.openai_model || ''}
                    onChange={(e) => update('openai_model', e.target.value)}
                    placeholder="deepseek-reasoner"
                  />
                  <TextField label="Opencode Model" size="small" fullWidth
                    value={form.opencode_model || ''}
                    onChange={(e) => update('opencode_model', e.target.value)}
                    helperText="代码助手使用的模型"
                  />
                  <TextField label="OpenRouter API Key" type="password" size="small" fullWidth
                    value={form.openrouter_api_key || ''}
                    onChange={(e) => update('openrouter_api_key', e.target.value)}
                  />
                  <TextField label="OpenRouter Base URL" size="small" fullWidth
                    value={form.openrouter_base_url || ''}
                    onChange={(e) => update('openrouter_base_url', e.target.value)}
                  />
                  <TextField label="OpenRouter Model" size="small" fullWidth
                    value={form.openrouter_model || ''}
                    onChange={(e) => update('openrouter_model', e.target.value)}
                  />

                  <Button variant="outlined" color="primary" onClick={handleTest}
                    disabled={testModel.isPending} fullWidth>
                    {testModel.isPending ? '测试中...' : '测试模型连通性'}
                  </Button>
                  {testModel.data && (
                    <Alert severity={testModel.data.ok ? 'success' : 'error'}>
                      {testModel.data.ok
                        ? `连通 — ${testModel.data.model} (${testModel.data.latency_ms}ms)`
                        : `失败：${testModel.data.error}`}
                    </Alert>
                  )}
                  {testModel.isError && (
                    <Alert severity="error">
                      测试请求失败：{(testModel.error as Error).message}
                    </Alert>
                  )}
                </Stack>
              )}

              {tab === 1 && (
                <Stack spacing={2}>
                  <TextField label="Fuzz 单次时长 (秒)" size="small" type="number" fullWidth
                    value={String(form.fuzz_time_budget || 900)}
                    onChange={(e) => update('fuzz_time_budget', Number(e.target.value) || 900)}
                  />
                  <TextField label="无限轮次总预算 (秒)" size="small" type="number" fullWidth
                    value={String(form.sherpa_run_unlimited_round_budget_sec || 7200)}
                    onChange={(e) => update('sherpa_run_unlimited_round_budget_sec', Number(e.target.value) || 7200)}
                    helperText="0 表示不限时，默认 7200（2小时）"
                  />
                  <TextField label="平台期空闲阈值 (秒)" size="small" type="number" fullWidth
                    value={String(form.sherpa_run_plateau_idle_growth_sec || 600)}
                    onChange={(e) => update('sherpa_run_plateau_idle_growth_sec', Math.max(30, Math.min(86400, Number(e.target.value) || 600)))}
                    inputProps={{ min: 30, max: 86400 }}
                    helperText="范围 30-86400 秒，默认 600"
                  />
                </Stack>
              )}

              {tab === 2 && (
                <Stack spacing={2}>
                  <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <Typography>使用 Docker</Typography>
                    <Switch
                      checked={form.fuzz_use_docker !== false}
                      onChange={(e) => update('fuzz_use_docker', e.target.checked)}
                    />
                  </Box>
                  <TextField label="Docker 镜像" size="small" fullWidth
                    value={form.fuzz_docker_image || 'auto'}
                    onChange={(e) => update('fuzz_docker_image', e.target.value)}
                    placeholder="auto"
                  />
                  <TextField label="HTTP 代理" size="small" fullWidth
                    value={form.sherpa_docker_http_proxy || ''}
                    onChange={(e) => update('sherpa_docker_http_proxy', e.target.value)}
                  />
                  <TextField label="HTTPS 代理" size="small" fullWidth
                    value={form.sherpa_docker_https_proxy || ''}
                    onChange={(e) => update('sherpa_docker_https_proxy', e.target.value)}
                  />
                  <TextField label="NO_PROXY" size="small" fullWidth
                    value={form.sherpa_docker_no_proxy || ''}
                    onChange={(e) => update('sherpa_docker_no_proxy', e.target.value)}
                  />
                  <TextField label="代理 Host" size="small" fullWidth
                    value={form.sherpa_docker_proxy_host || 'host.docker.internal'}
                    onChange={(e) => update('sherpa_docker_proxy_host', e.target.value)}
                  />
                </Stack>
              )}
            </>
          )}
        </Box>

        {/* Footer */}
        {saveMsg && (
          <Alert severity={saveMsg.type} onClose={() => setSaveMsg(null)} sx={{ mx: 2, mb: 1 }}>
            {saveMsg.text}
          </Alert>
        )}
        <Box sx={{ px: 2, py: 1.5, borderTop: '1px solid', borderColor: 'divider', display: 'flex', gap: 1 }}>
          <Button variant="contained" onClick={handleSave} disabled={saveCfg.isPending} fullWidth>
            {saveCfg.isPending ? '保存中...' : '保存'}
          </Button>
          <Button variant="outlined" onClick={onClose} fullWidth>取消</Button>
        </Box>
      </Box>
    </Drawer>
  );
}
