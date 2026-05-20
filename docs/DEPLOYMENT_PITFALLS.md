# 部署踩坑记录

记录 Sherpa 在本地部署和开发过程中遇到的实际问题、根因和修复方案。

## 1. 磁盘空间不足导致 clone 失败 (ENOSPC)

**现象**：任务在 INIT 阶段报 `OSError: [Errno 28] No space left on device`，无法创建 `/tmp/sherpa-fuzz-*` 临时目录。日志写入也失败（loguru handler 报同样错误）。

**根因**：`/` 分区磁盘满（Docker 镜像/容器/数据卷占大量空间），`tempfile.mkdtemp()` 在 `_clone_repo` 一开头就失败。

**修复**：
```bash
df -h /                         # 确认磁盘使用率
sudo docker system prune -a      # 清理未使用的 Docker 资源
sudo du -sh /var/lib/docker/*    # 排查 Docker 占用
```

**预防**：定期清理 Docker 资源，监控磁盘使用率。`/tmp` 在根分区上，Docker 数据卷（`/var/lib/docker/overlay2`）是主要空间消耗源。

---

## 2. 无限重试循环 — 缺少 restart 上限检查

**现象**：任务遇到错误（如磁盘满）后陷入无限循环，日志反复出现 `stage plan failed (stage_dispatch_exception): ... -> fallback to plan`，永远不终止。

**根因**：`main.py` 的两个异常处理器（`except _K8sJobFailure` 和 `except Exception`）捕获异常后无条件设置 `restart_to_plan: True` 和 `workflow_recommended_next: "plan"`。外层 `while current_stage:` 循环不断重试，但 `restart_to_plan_count` 从未在异常处理器中递增或检查。已有上限 `_re_restart_limit()`（默认 1）仅在 workflow_graph.py 的 re-build/re-run/crash-analysis 阶段生效，这些阶段因 init 即失败而永远无法到达。

**修复** — [main.py](../harness_generator/src/langchain_agent/main.py) 两处异常处理器：

1. **`except _K8sJobFailure`**（~line 4315）：从 `workflow_ctx` 读取当前 `restart_to_plan_count`，与 `SHERPA_RESTART_FROM_PLAN_MAX`（默认 1）比较：
   - 超过上限 → `workflow_recommended_next: "stop"`, `failed: True`，任务以 error 终止
   - 未超上限 → `restart_to_plan_count + 1`，允许从 plan 重新开始

2. **`except Exception`**（~line 4383）：同样逻辑，且每次重试前保留 `restart_to_plan_count` 到 `stage_result` 中以持久化到 workflow context。

**配置**：`SHERPA_RESTART_FROM_PLAN_MAX`（默认 1），设为 0 则首次失败立即终止。

**涉及文件**：[main.py](../harness_generator/src/langchain_agent/main.py) — 两个异常处理器中的 restart 上限检查

---

## 3. Docker 内 git "dubious ownership" + 权限拒绝

这是部署过程中绕过层次最多的坑，经历了三个阶段才彻底修复。

### 3a. 初始错误：dubious ownership

**现象**：clone 成功后，在 `_ensure_git_repo_docker` 中报错：
```
RuntimeError: Failed to create initial git commit inside docker.
stderr=fatal: detected dubious ownership in repository at '/repo'
```

**根因**：[codex_helper.py:840](../harness_generator/src/codex_helper.py#L840) 中 `_docker_git()` 每次调用都启动一个全新的 `docker run --rm` 容器。原有代码 `git config --global --add safe.directory /repo` 在一个容器中设置，但后续 `git add -A` 在另一个新容器中执行，`--global` 配置不持久。git >= 2.35.2 检测到仓库目录属主与容器内用户不匹配，拒绝操作。

### 3b. 后续错误：Permission denied on index.lock

**现象**：`safe.directory` 修复后，`_git_add_all`（plan 阶段 LLM 修改文件后调用）仍然报错：
```
RuntimeError: git add failed in docker:
fatal: Unable to create '/repo/.git/index.lock': Permission denied
```

**根因**：`alpine/git` 镜像默认用户为非 root（通常是 `git` 用户，UID ≠ 宿主机用户 UID）。而工作目录中的文件由宿主机 git（host git fallback）克隆，属主为宿主机用户（`bohuju:docker`）。容器内非 root 用户无权限在宿主机属主的目录中创建锁文件。

### 3c. 最终修复

在 `_docker_git` 方法层面一次解决所有权和权限两个问题：

```python
# codex_helper.py _docker_git 方法
cmd = [
    "docker", "run", "--rm",
    "--user", "0:0",                # 以 root 运行，不受宿主机文件属主限制
    "-v", f"{str(self.working_dir.resolve())}:/repo",
    "-w", "/repo",
    self.git_docker_image,
    "git",
    "-c", "safe.directory=/repo",   # 绕过 git ownership 安全检查
] + list(args)
```

两条修复缺一不可：
- `-c safe.directory=/repo` — 绕过 git 的所有权检查（`--global` 在 `--rm` 容器中无效）
- `--user 0:0` — 容器以 root 运行，可写入任意属主的文件

**涉及文件**：[codex_helper.py](../harness_generator/src/codex_helper.py) — `_docker_git()` 方法，`_ensure_git_repo_docker()` 方法

---

## 4. 前端 API 代理端口不匹配

**现象**：后端 API 运行正常（`curl localhost:8001/api/system` 有响应），但前端显示"系统离线"。

**根因**：[frontend-next/next.config.mjs:9](../frontend-next/next.config.mjs#L9) 的 `rewrites` 将 `/api/*` 代理到 `http://localhost:9010/api/*`，但后端实际运行在 8001 端口。

**修复**：修改 `next.config.mjs` 中 destination 端口为实际后端端口，重启前端 dev server。

---

## 5. API Key 未配置导致 plan 阶段失败

**现象**：任务在 PLAN 阶段失败，`openai_api_key_set: false`。

**根因**：后端代码通过 `load_dotenv()` 读取 `.env` 文件中的 API key，未配置时 LLM 调用失败。

**修复** — 在仓库根目录创建 `.env`（已在 `.gitignore` 中）：
```bash
OPENAI_API_KEY=sk-yOUR-kEY
OPENCODE_MODEL=deepseek-v4-flash
SHERPA_OPENCODE_IDLE_TIMEOUT_SEC=600
```

`load_dotenv()` 在 `fuzz_relative_functions.py` 模块导入时执行，修改 `.env` 后必须重启服务。

**API Key 读取优先级**（[persistent_config.py:686](../harness_generator/src/langchain_agent/persistent_config.py#L686)）：
1. `LLM_key`
2. `DEEPSEEK_API_KEY`
3. `OPENAI_API_KEY`
4. `MINIMAX_API_KEY`

---

## 6. Plan 阶段超时 — time_budget 不足

**现象**：plan 阶段 OpenCode 运行 ~50s 后被 hard timeout 终止。

**根因**：[codex_helper.py](../harness_generator/src/codex_helper.py) 中 `run_codex_command` 的 `timeout` 参数来自 `_remaining_time_budget_sec()`，计算公式为 `time_budget - workflow_elapsed`。当任务 `time_budget=120`（2 分钟）而 init + analysis 已消耗 ~70s 时，plan 只剩 ~50s，不足以完成 LLM 代码分析和目标选择。

**修复**：
- 创建任务时设置 `time_budget >= 600`（10 分钟以上）
- `.env` 中设置 `SHERPA_OPENCODE_IDLE_TIMEOUT_SEC=600`
- 使用更快的模型：`OPENCODE_MODEL=deepseek-v4-flash`

---

## 7. 前端工作流管线阶段不更新

**现象**：任务正在运行，但前端工作流管线不显示当前阶段（如 PLAN）。

**原因**：[main.py:2385](../harness_generator/src/langchain_agent/main.py#L2385) 的 `_phase_for_job()` 读取顺序为：
1. `workflow_active_step` — 阶段派发**开始时**设置（[main.py:4214](../harness_generator/src/langchain_agent/main.py#L4214)）
2. `workflow_last_step` — 阶段派发**完成后**设置

在 LLM 长时间运行期间（如 plan 的 OpenCode 调用），前端无法获得实时进度反馈，因为整个阶段是进程内阻塞执行。

**当前缓解方案**：前端可通过 `active_child_phase` 字段查看子任务的内在工作流阶段（如"plan", "synthesize"），该字段由 inner state machine 更新。

**已知限制**：Docker executor 模式下，阶段执行中无法向数据库写入中间状态。

---

## 8. 服务器启动注意事项

### 启动命令

```bash
cd /home/bohuju/TIanHeng_project/Sherpa/harness_generator/src/langchain_agent && \
  sg docker -c "/home/bohuju/TIanHeng_project/Sherpa/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8001"
```

### 关键注意点

- **`sg docker`** 必须使用，因为当前用户不在 `docker` 组中，需要以此获取 Docker daemon 访问权限
- **`.env` 修改后必须重启** — `load_dotenv()` 在 `fuzz_relative_functions.py` 模块导入时执行一次
- **代码修改后必须重启** — uvicorn 默认不带 `--reload`，Python 进程不会自动重载
- **旧进程检查** — 开发过程中可能残留多个 uvicorn 实例，用 `ps aux | grep uvicorn` 确认后 `pkill`
- **前端 `next.config.mjs` 修改后也需重启** Next.js dev server
- **`/tmp` 在根分区** — 磁盘满会导致所有阶段失败

---

## 快速排查检查清单

| 检查项 | 命令 / 方法 |
|--------|------------|
| 磁盘空间 | `df -h /` |
| inode 使用率 | `df -i /` |
| 后端运行状态 | `curl -s http://localhost:8001/api/system` |
| API key 已加载 | 同上，检查 `openai_api_key_set: true` |
| 模型配置 | 同上，检查 `config` 中的模型名称 |
| 前端代理正确 | 检查 `next.config.mjs` 中 `destination` 端口 |
| Docker 可用 | `docker ps` |
| 旧进程已清理 | `ps aux \| grep uvicorn \| grep -v grep` |
| .env 已配置 | `cat .env` |
| 任务列表 | `curl -s http://localhost:8001/api/tasks \| python3 -m json.tool` |
| 具体任务状态 | `curl -s http://localhost:8001/api/task/<job_id>` |
