# GBrain Memory 优化方案

## 现状

GBrain 是 Sherpa 的长期记忆节点，通过 MemoryAdapter（MCP client）以子进程方式启动 gbrain CLI，经 JSON-RPC over stdio 通信。记忆数据存储在独立 PostgreSQL（`gbrain_mcp` 库），前端通过 MemoryDrawer 面板查看。

当前链路：前端 → `/api/memory/*` → MemoryAdapter → `gbrain serve` 子进程 → PostgreSQL（gbrain_mcp）

---

## 1. gbrain 不在镜像内，依赖手工挂载

**现象**：gbrain 源码通过 volume 从 `~/self_project/gbrain` 挂载，Bun 二进制也是外挂。容器重建后 `/usr/local/bin/gbrain` wrapper 丢失，MemoryAdapter 静默失败，API 始终返回空结果。

**影响**：每次 `docker compose up -d`（含 recreate）后需手动重建 wrapper 脚本；无法在新环境一键部署。

**推荐方案**：

1. 将 gbrain 作为 git submodule 引入项目：
   ```bash
   git submodule add https://github.com/<gbrain-repo>.git gbrain
   ```
2. Dockerfile.web 中编译安装：
   ```dockerfile
   # Install Bun runtime
   RUN curl -fsSL https://bun.sh/install | bash
   # Copy gbrain source (from submodule)
   COPY gbrain /opt/gbrain
   # Create wrapper
   RUN printf '#!/usr/local/bin/bun\nimport "/opt/gbrain/src/cli.ts";\n' > /usr/local/bin/gbrain && chmod +x /usr/local/bin/gbrain
   ```
3. `GBRAIN_DATABASE_URL` 环境变量已配好，重建后零干预即可用。

---

## 2. MemoryAdapter 失败完全静默

**现象**：`_ensure_running()` 中 `FileNotFoundError` 被 catch 后仅 `logger.warning`，API 返回：
```json
{"enabled": true, "results": [], "total": 0}
```
前端显示"暂无记忆数据"，运维无法区分"真的没数据"和"gbrain 服务挂了"。

**影响**：排查问题耗时长，用户以为功能正常但实际从未连通。

**推荐方案**：

1. API 响应增加健康状态字段：
   ```diff
   - {"enabled": true, "results": [], "total": 0}
   + {"enabled": true, "healthy": false, "error": "gbrain subprocess not running", "results": [], "total": 0}
   ```
2. MemoryAdapter 增加 `status()` 方法，暴露：
   - `proc_alive` — 子进程是否存活
   - `last_error` — 最近一次错误信息
   - `last_call_latency_ms` — 最近一次调用延迟
3. 新增 `/api/memory/health` 端点，前端 MemoryDrawer 打开时先查健康状态，不健康时展示明确错误提示。

---

## 3. gbrain 数据库连接无容错

**现象**：`GBRAIN_DATABASE_URL` 指向固定 hostname，gbrain-postgres 挂了 API 照常返回空结果，无限重试、无降级提示。

**影响**：数据库短暂不可用时仍返回"无数据"，掩盖故障。

**推荐方案**：

1. MemoryAdapter 加连接重试：
   ```python
   async def _call_tool(self, tool_name, arguments, timeout=10.0, max_retries=3):
       for attempt in range(max_retries):
           result = await self._call_tool_raw(tool_name, arguments, timeout)
           if "error" not in result:
               return result
           if attempt < max_retries - 1:
               await asyncio.sleep(1.0 * (attempt + 1))  # 指数退避
       return result
   ```
2. gbrain 子进程意外退出时自动重启（已有 `_ensure_running`，改 `_call_tool` 中增加重试+重启逻辑）。
3. 连续 3 次失败后标记 `healthy: false`，前端展示红色状态。

---

## 4. 前端缺乏记忆写入入口

**现象**：MemoryDrawer 只能查看、编辑、删除已有记忆页面，没有创建入口。测试数据全靠 CLI 手工 `gbrain put`，用户无法从界面录入。

**影响**：记忆系统变成"只读"。用户想手动记录经验（如对某类 crash 的处置结论）必须离开前端去敲命令。

**推荐方案**：

1. MemoryDrawer 增加"新建记忆"按钮，通过 `PUT /api/memory/page/{slug}` 创建新页面。
   - 页面类型选择器（target-repo / session / crash / strategy）
   - Markdown 编辑器绑定 content
   - frontmatter 表单（根据类型动态生成字段）
2. 任务详情页嵌入"保存到记忆"操作：将当前任务的 crash 分析 / 策略决策一键存入 GBrain。
3. 后端增加 `POST /api/memory/page` 端点（或复用 `PUT`），支持 full page 创建 payload。

---

## 5. 工作流节点未真正接入记忆查询

**现象**：`get_suggestions()` 已定义了 plan、crash-triage、crash-analysis、coverage-analysis 四个节点的查询逻辑，MemoryAdapter 会构建对应 query 并查询 GBrain。但因为 gbrain 子进程从未成功启动，`is_actionable()` 始终返回 False，建议从未实际生效。

**影响**：长期记忆的核心价值（"曾经遇到过类似情况，上次怎么做"）完全未发挥。

**推荐方案**：

1. gbrain 联通后（优化 1 完成后），按节点启用建议：
   - **plan** — 展示同类仓库历史 fuzz 策略、top coverage、有效的 harness 模式
   - **crash-triage** — 匹配相似 crash signature 的历史结论（true_positive / false_positive）
   - **crash-analysis** — 展示同类型漏洞的根因分析摘要
   - **coverage-analysis** — 推荐对当前语言/模块有效的覆盖率提升策略
2. 前端通过轮询或 WebSocket 获取 suggestions，在工作流管线侧边栏展示建议卡片。
3. 建议卡片支持一键跳转到对应的 GBrain 记忆详情页（MemoryDrawer 联动打开）。

---

## 优先级建议

| 优先级 | 条目 | 理由 | 状态 |
|--------|------|------|------|
| P0 | 1. gbrain 入镜像 | 不修复所有功能不可用 | ✅ 已完成 |
| P1 | 2. 错误可观测 | 无此优化排查问题耗时巨大 | ✅ 已完成 |
| P1 | 3. 连接容错 | gbrain-postgres 重启是常见操作 | ✅ 已完成 |
| P2 | 5. 工作流接入记忆 | 记忆系统的核心价值 | ✅ 已完成 |
| P2 | 4. 前端写入入口 | 用户自主录入，增强记忆丰富度 | ✅ 已完成 |

---

## 实施记录（2026-06-01）

### P0：gbrain 入镜像

**改动文件**：
- `docker/Dockerfile.web` — 新增 Bun 下载安装（v1.2.0）、`COPY gbrain /opt/gbrain`、`bun install --production`
- `docker-compose.yml` — 移除 `./gbrain:/opt/gbrain` 和 `/home/bohuju/.bun/bin/bun:/usr/local/bin/bun:ro` 外部挂载
- `.gitignore` — 新增 `gbrain/node_modules/`、`gbrain/bin/`、`gbrain/.gitnexus/`
- `gbrain/` — 源码从 `~/self_project/gbrain` 复制入项目，11MB（不含 node_modules）

**效果**：镜像自包含 gbrain + Bun，不再依赖宿主机路径，`docker compose up -d` 后零干预可用。

---

### P1：错误可观测

**改动文件**：
- `harness_generator/src/langchain_agent/memory_adapter.py`
  - 新增字段：`_last_error`、`_last_error_time`、`_consecutive_failures`、`_healthy`、`_max_retries`、`_retry_base_delay`
  - 新增方法：`status()` → 返回 `{healthy, proc_alive, proc_pid, last_error, last_error_time, consecutive_failures}`
  - 新增方法：`_record_error(msg)`、`_record_success()` — 追踪错误状态
- `harness_generator/src/langchain_agent/main.py`
  - `GET /api/memory/pages` 响应增加 `healthy`、`status` 字段
  - 新增 `GET /api/memory/health` 端点
- `frontend-next/components/MemoryDrawer.tsx` — 列表页增加健康告警（不健康时展示红色警告）

**效果**：运维可通过 `/api/memory/health` 一眼判断 gbrain 是否正常；前端不再静默失败。

---

### P1：连接容错

**改动文件**：
- `harness_generator/src/langchain_agent/memory_adapter.py`
  - `_call_tool()` 重写：最多重试 3 次，指数退避（1s → 2s → 4s）
  - 检测 `BrokenPipeError` / `OSError` 时自动标记子进程为 dead，下一轮自动重启
  - 新增 `_unwrap_mcp_result()` — 解析 MCP `tools/call` 响应中的 `content[0].text` JSON 包装
  - `list_pages` MCP 参数从 `prefix` 修正为 `type`
- `harness_generator/src/langchain_agent/main.py`
  - `_MEMORY_TYPE_PREFIX` 从 slug 前缀（`fuzz/targets`）修正为 frontmatter type（`fuzz/target-repo`）

**效果**：gbrain 短暂不可用时自动重试恢复；MCP 响应正确解包，类型过滤生效。

---

### P2：前端写入入口

**改动文件**：
- `frontend-next/components/MemoryDrawer.tsx`
  - ViewMode 扩展为 `'list' | 'detail' | 'edit' | 'create'`
  - Header 增加"+ 新建"按钮（仅在列表视图显示）
  - Create 视图：类型选择器（targets/sessions/crashes/strategies/harnesses）+ slug 输入框 + MemoryEditForm
  - `handleCreateSave` — 自动拼接前缀生成完整 slug，设置正确的 frontmatter type

**效果**：前端可直接创建记忆页面，无需 CLI 手工 `gbrain put`。

---

### P2：工作流接入记忆 + MCP 数据修复

**改动文件**：
- 后端 `workflow_graph.py` 已有 `get_suggestions()` 调用（plan / crash-triage / crash-analysis），存储 `memory_suggestion_plan` 到 state
- gbrain 联通后 `is_actionable()` 自然返回 True，建议生效
- MCP 响应解析修复（`_unwrap_mcp_result`）使所有读写 API 正常工作

**效果**：验证通过 — `/api/memory/pages?type=targets` 返回 1 条，`?type=crashes` 返回 1 条，`?type=sessions` 返回 1 条，`/api/memory/health` 返回 `healthy: true`。

---

## 当前架构

```
前端 MemoryDrawer → /api/memory/* → MemoryAdapter
                                        │ MCP stdio (JSON-RPC)
                                        ▼
                                   gbrain serve (Bun)
                                        │
                                        ▼
                                   gbrain-mcp-pg (PostgreSQL :5432)
```

关键配置：
- `GBRAIN_DATABASE_URL=postgresql://postgres:postgres@gbrain-mcp-pg:5432/gbrain_mcp`
- gbrain-mcp-pg 需接入 `remove_k8s_default` 网络（`docker network connect remove_k8s_default gbrain-mcp-pg`）
- Docker DNS 已修复（`/etc/docker/daemon.json` → `{"dns": ["8.8.8.8", "1.1.1.1"]}`）
