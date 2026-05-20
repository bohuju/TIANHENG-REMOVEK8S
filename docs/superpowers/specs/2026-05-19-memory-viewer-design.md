# Memory Viewer — 前端记忆查看器

## 概述

在前端仪表盘中增加一个侧边栏抽屉（MUI Drawer），用于查看、搜索、编辑和删除 GBrain 中存储的 fuzz 记忆数据。

## 前置依赖

MemoryAdapter（`memory_adapter.py`）目前缺少两个方法，实现前需先补充：

- `list_pages(type_prefix: str, limit: int, offset: int)` — 按类型列出页面，调用 gbrain MCP 的 `list_pages` 或等效工具
- `delete_page(slug: str)` — 删除页面，调用 gbrain MCP 的 `delete_page` 或等效工具

如果 gbrain MCP 不提供这两个工具，则 `list_pages` 改用 `query_experience("", type=...)` 变通实现，`delete_page` 通过写入空内容或标记实现软删除。

## 后端 API 设计

### MemoryAdapter 生命周期

在 FastAPI `lifespan` 中创建 `MemoryAdapter` 单例，挂载到 `app.state.memory_adapter`。如果 `gbrain serve` 启动失败，adapter 为 `None`，所有接口返回 `{"enabled": false}`。

### 新增端点（5 个）

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/api/memory/search?q=...&type=...` | 全文搜索，可选按类型过滤。`type` 为空时搜索全部 |
| `GET` | `/api/memory/pages?type=targets\|sessions\|crashes\|strategies\|harnesses` | 按类型列出所有页面，默认按更新时间倒序 |
| `GET` | `/api/memory/page/{slug}` | 获取单个页面的完整内容（frontmatter + compiled_truth + timeline） |
| `PUT` | `/api/memory/page/{slug}` | 更新页面 frontmatter，请求体为 JSON 键值对 |
| `DELETE` | `/api/memory/page/{slug}` | 删除页面及其关联链接 |

### 搜索响应格式

```json
{
  "enabled": true,
  "results": [
    {
      "slug": "fuzz/targets/GNOME-libxml2",
      "type": "target-repo",
      "title": "GNOME/libxml2",
      "score": 0.95,
      "snippet": "C fuzzing target, 12 sessions..."
    }
  ],
  "total": 42
}
```

### 分页

`GET /api/memory/pages` 支持 `?limit=50&offset=0` 分页参数。

### 错误处理

- gbrain 不可用：返回 `{"enabled": false}`，HTTP 200
- 页面不存在：返回 `{"detail": "Page not found: xxx"}`, HTTP 404
- gbrain 调用超时（>5s）：返回 `{"detail": "Memory service timeout"}`, HTTP 504

## 前端设计

### 触发入口

在仪表盘页面顶部导航区域增加一个"记忆查看"按钮（Brain 图标），点击打开右侧 Drawer。

### 组件结构

```
MemoryDrawer (MUI Drawer, anchor="right", width≈40vw)
├── MemorySearchBar        — 搜索输入框 + 搜索按钮
├── MemoryTypeTabs         — 类型筛选 Chip 组（全部/目标仓库/Session/Crash/策略/Harness）
├── MemoryResultsList      — 搜索结果/页面列表
│   └── MemoryResultCard   — 单条结果卡片（标题、类型徽章、摘要、相关度）
├── MemoryDetail           — 只读详情面板（frontmatter 键值对展示）
├── MemoryEditForm         — 编辑表单（根据页面类型动态生成字段）
└── MemoryEmptyState       — gbrain 不可用或无结果时的空状态
```

### 交互流程

1. 点击"记忆查看"按钮 → Drawer 滑出，默认显示"全部"类型的结果列表
2. 切换类型 Tab → 重新加载对应类型的页面列表
3. 输入关键词搜索 → 调用 search API，显示搜索结果
4. 点击结果卡片 → 列表区域切换为只读详情面板
5. 详情面板点"编辑" → 切换为编辑表单，字段根据页面类型动态渲染
6. 编辑表单点"保存" → 调用 PUT API → 回到只读详情（显示更新后数据）
7. 详情面板点"删除" → 弹出确认对话框 → 确认后调用 DELETE API → 回到结果列表
8. 点"返回列表" → 从详情/编辑回到结果列表

### 编辑表单字段映射

不同页面类型展示不同的可编辑字段：

- **TargetRepo**: repo_url, repo_language, total_sessions, total_crashes_found, true_vulns_found, cve_ids, recommended_strategies
- **Session**: repo, started_at, ended_at, duration_seconds, stages_completed, total_harnesses, total_crashes, coverage_start, coverage_end
- **Crash**: crash_signature, crash_type, verdict, severity, cve_id, asan_report
- **Strategy**: strategy_type, target_language, harness_pattern, seed_families, build_flags, success_rate
- **Harness**: target_function, build_status, fuzz_result, coverage_achieved

### 状态管理

- 抽屉开关、当前 Tab、搜索关键词、选中页面 → React `useState` 在 `MemoryDrawer` 组件内管理
- API 数据 → React Query hooks（`useMemorySearch`, `useMemoryPages`, `useMemoryPage`, `useUpdateMemoryPage`, `useDeleteMemoryPage`）
- 不放入 Zustand store（这些状态是临时的、UI 局部的）

### 空状态和加载状态

- **gbrain 不可用**：显示"记忆服务未启用。请确保 gbrain 已安装并运行。"的 Alert
- **搜索无结果**：显示"未找到匹配的记忆"
- **加载中**：列表区域显示 CircularProgress
- **删除确认**：Dialog 文案为 "确定删除 [slug] 吗？此操作不可恢复。"

### 文件清单

| 文件 | 作用 |
|---|---|
| `frontend-next/components/MemoryDrawer.tsx` | 抽屉容器，管理 Tab/搜索/页面切换状态 |
| `frontend-next/components/MemorySearchBar.tsx` | 搜索输入框 |
| `frontend-next/components/MemoryTypeTabs.tsx` | 类型 Chip 切换 |
| `frontend-next/components/MemoryResultsList.tsx` | 结果列表 |
| `frontend-next/components/MemoryDetail.tsx` | 只读详情视图 |
| `frontend-next/components/MemoryEditForm.tsx` | 编辑表单 |
| `frontend-next/lib/api/schemas.ts` | 新增 memory 相关 Zod schemas |
| `frontend-next/lib/api/client.ts` | 新增 memory API 调用函数 |
| `frontend-next/lib/api/hooks.ts` | 新增 React Query hooks |
| `harness_generator/src/langchain_agent/main.py` | 新增 5 个 memory API 端点 + lifespan MemoryAdapter 初始化 |

### 测试

- 后端：在 `tests/` 中新增 `test_memory_api.py`，mock MemoryAdapter 验证端点行为
- 前端：在 `frontend-next/components/` 中新增组件单测（可选，视现有测试模式决定）
