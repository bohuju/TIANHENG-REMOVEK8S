# Settings Drawer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) to implement this plan task-by-task.

**Goal:** Add a right-side settings drawer for model/API/Docker config with a one-click model connectivity test.

**Architecture:** New SettingsDrawer component (right drawer, tabbed layout), new `POST /api/config/test-model` backend endpoint, gear icon in main page navbar. Reuses existing `useConfigQuery`/`useSaveConfigMutation` hooks. The existing ConfigPanel (task submission form) remains unchanged.

**Tech Stack:** FastAPI + httpx (backend), Next.js 14 + MUI (frontend)

---

### Task 1: Backend — Add `POST /api/config/test-model` endpoint

**Files:**
- Modify: `harness_generator/src/langchain_agent/main.py`

- [ ] **Step 1: Add the endpoint**

Find the `put_config` function (around line 2103), add after it:

```python
@app.post("/api/config/test-model")
def test_model():
    """Send a minimal chat completion to verify the configured LLM is reachable."""
    cfg = _cfg_get()
    api_key = (cfg.openai_api_key or "").strip()
    base_url = (cfg.openai_base_url or "https://api.deepseek.com/v1").strip().rstrip("/")
    model = (cfg.openai_model or "deepseek-reasoner").strip()

    if not api_key:
        raise HTTPException(status_code=400, detail="API key is not configured")

    import urllib.request
    import urllib.error
    import time

    url = f"{base_url}/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
        "temperature": 0,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")

    started = time.monotonic()
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        returned_model = data.get("model", model)
        return {"ok": True, "model": returned_model, "latency_ms": elapsed_ms}
    except urllib.error.HTTPError as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        try:
            body_text = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            body_text = ""
        return {"ok": False, "error": f"HTTP {exc.code}: {body_text or exc.reason}", "latency_ms": elapsed_ms}
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return {"ok": False, "error": str(exc), "latency_ms": elapsed_ms}
```

- [ ] **Step 2: Verify syntax**

Run: `cd harness_generator/src/langchain_agent && python3 -c "import py_compile; py_compile.compile('main.py', doraise=True); print('Syntax OK')"`
Expected: `Syntax OK`

- [ ] **Step 3: Commit**

```bash
git add harness_generator/src/langchain_agent/main.py
git commit -m "feat: add POST /api/config/test-model endpoint"
```

---

### Task 2: Frontend API — Add `testModel()` client and hook

**Files:**
- Modify: `frontend-next/lib/api/client.ts`
- Modify: `frontend-next/lib/api/hooks.ts`

- [ ] **Step 1: Add client function**

In `client.ts`, add after existing exports:

```typescript
export async function testModel(): Promise<{ ok: boolean; model?: string; latency_ms?: number; error?: string }> {
  return request('/config/test-model', { method: 'POST' });
}
```

- [ ] **Step 2: Add hook**

In `hooks.ts`, add after existing hooks:

```typescript
export function useTestModelMutation() {
  return useMutation({
    mutationFn: () => testModel(),
  });
}
```

- [ ] **Step 3: Verify TypeScript**

Run: `cd frontend-next && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No new errors.

- [ ] **Step 4: Commit**

```bash
git add frontend-next/lib/api/client.ts frontend-next/lib/api/hooks.ts
git commit -m "feat: add testModel client function and mutation hook"
```

---

### Task 3: Frontend — Create SettingsDrawer component

**Files:**
- Create: `frontend-next/components/SettingsDrawer.tsx`

- [ ] **Step 1: Create the component**

```typescript
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
    // Save first then test
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
                    helperText="代码助手使用的模型（独立于主模型）"
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

                  {/* Test button */}
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
                  <TextField label="Fuzz 单次时长(秒)" size="small" type="number" fullWidth
                    value={String(form.fuzz_time_budget || 900)}
                    onChange={(e) => update('fuzz_time_budget', Number(e.target.value) || 900)}
                  />
                  <TextField label="无限轮次总预算(秒)" size="small" type="number" fullWidth
                    value={String(form.sherpa_run_unlimited_round_budget_sec || 7200)}
                    onChange={(e) => update('sherpa_run_unlimited_round_budget_sec', Number(e.target.value) || 7200)}
                    helperText="0 表示不限时，默认 7200（2小时）"
                  />
                  <TextField label="平台期空闲增长阈值(秒)" size="small" type="number" fullWidth
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
```

- [ ] **Step 2: Commit**

```bash
git add frontend-next/components/SettingsDrawer.tsx
git commit -m "feat: add SettingsDrawer component with tabs for model, fuzz, docker config"
```

---

### Task 4: Frontend — Add settings icon to main page navbar

**Files:**
- Modify: `frontend-next/app/page.tsx`

- [ ] **Step 1: Add import and state**

Add import at top:

```typescript
import SettingsIcon from '@mui/icons-material/Settings';
import { SettingsDrawer } from '@/components/SettingsDrawer';
```

Add state after `memoryOpen`:

```typescript
  const [settingsOpen, setSettingsOpen] = useState(false);
```

- [ ] **Step 2: Add button in navbar**

After the existing "记忆查看" button (line 80), add:

```typescript
          <Button
            variant="outlined"
            startIcon={<SettingsIcon />}
            onClick={() => setSettingsOpen(true)}
            size="small"
          >
            设置
          </Button>
```

- [ ] **Step 3: Add drawer below MemoryDrawer**

After `<MemoryDrawer open={memoryOpen} ... />` (line 119), add:

```typescript
        <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
```

- [ ] **Step 4: Commit**

```bash
git add frontend-next/app/page.tsx
git commit -m "feat: add settings gear icon and SettingsDrawer to main page"
```

---

### Task 5: Verify

- [ ] **Step 1: Backend syntax**

Run: `cd harness_generator/src/langchain_agent && python3 -c "import py_compile; py_compile.compile('main.py', doraise=True); print('Backend OK')"`
Expected: `Backend OK`

- [ ] **Step 2: Frontend TypeScript**

Run: `cd frontend-next && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No new errors.

- [ ] **Step 3: Build and deploy**

```bash
sg docker -c "docker compose -f /home/bohuju/TIanHeng_project/remove_k8s/docker-compose.yml build sherpa-web sherpa-frontend --no-cache"
sg docker -c "docker compose up -d sherpa-web sherpa-frontend"
```
