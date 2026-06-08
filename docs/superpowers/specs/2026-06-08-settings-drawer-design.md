# Settings Drawer — Design Spec

**Date**: 2026-06-08
**Status**: Approved
**Topic**: Add a settings drawer to the main page for configuring model, fuzz, and docker parameters, with a model connectivity test.

## Motivation

The current UI has no way to configure LLM credentials, model selection, or fuzz parameters. Users must manually edit environment variables or config files. A settings drawer provides a UI for all configuration, plus a one-click model connectivity test.

## Architecture

```
Main page navbar → settings gear icon → right-side Drawer

SettingsDrawer (new component)
  ├── Tabs: 模型配置 | Fuzz 参数 | Docker
  ├── Tab 1 (模型): api_key, base_url, model, opencode_model, openrouter fields + test button
  ├── Tab 2 (Fuzz): time budgets, plateau threshold
  ├── Tab 3 (Docker): use_docker toggle, image, proxy settings
  └── Sticky footer: [保存] [取消]

Backend:
  POST /api/config/test-model (new) — minimal LLM ping with current config
```

Existing `GET/PUT /api/config` and frontend hooks are reused.

## Backend

### `POST /api/config/test-model`

Reads current config via `_cfg_get()`, sends a minimal chat completion request (`max_tokens=1`, prompt "hi"), returns latency and status.

**Response (success):**
```json
{"ok": true, "model": "deepseek-reasoner", "latency_ms": 342}
```

**Response (failure):**
```json
{"ok": false, "error": "401 Unauthorized"}
```

Timeout: 15s. Uses `httpx` or `requests` to call the LLM endpoint.

## Frontend

### Files

| Action | File | Purpose |
|---|---|---|
| Modify | `app/page.tsx` | Add settings icon in navbar |
| Create | `components/SettingsDrawer.tsx` | Main drawer component |
| Modify | `lib/api/client.ts` | Add `testModel()` function |
| Modify | `lib/api/hooks.ts` | Add `useTestModelMutation()` |

### SettingsDrawer

- Uses `useConfigQuery` to populate form on open
- Uses `useSaveConfigMutation` to save on submit
- Three MUI Tabs: 模型配置, Fuzz 参数, Docker
- Each tab contains `TextField` inputs bound to config fields
- API Key field uses `type="password"` with show/hide toggle
- Docker toggle uses MUI `Switch`
- Test button shows loading spinner, then green checkmark + latency or red error message
- Sticky footer bar with Save/Cancel buttons

### Navbar Entry

Add a `Tooltip` + `IconButton` (SettingsIcon) in the main page header next to existing buttons. Opens the SettingsDrawer.

## Data Flow

```
Open drawer → GET /api/config → populate form
Edit fields → local state
Click Save → PUT /api/config → invalidate queries → close drawer
Click Test → POST /api/config/test-model → show result inline
Click Cancel → close drawer, discard changes
```

## Error Handling

| Scenario | Behavior |
|---|---|
| Config load fails | Show Alert in drawer |
| Save fails | Show error toast |
| Test times out (>15s) | Show "超时" error |
| Test returns error | Show red error message inline |

## Implementation Order

1. Backend: add `POST /api/config/test-model`
2. Frontend: add `testModel()` client + `useTestModelMutation()` hook
3. Frontend: create `SettingsDrawer.tsx`
4. Frontend: add settings icon to `page.tsx` navbar
5. Verify: syntax check, rebuild, smoke test
