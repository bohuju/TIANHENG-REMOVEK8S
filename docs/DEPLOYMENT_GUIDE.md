# Sherpa 部署指南

本文档记录 Sherpa 在本地 Docker Compose 环境下的完整部署流程、已修复的问题及注意事项。

## 前置条件

| 依赖 | 版本要求 | 验证命令 |
|------|---------|---------|
| Docker | 27+ | `docker --version` |
| Docker Compose | v5+ | `docker compose version` |
| 磁盘空间 | `/` 分区 > 20GB 可用 | `df -h /` |
| 宿主机代理（可选） | v2raya / clash | `ss -tlnp \| grep -E '20170\|20171'` |
| API Key | DeepSeek / OpenAI | `.env` 文件中配置 |

## 快速启动

### 1. 确保 Docker 可用

```bash
# 检查 daemon 状态
docker ps

# 如果报 permission denied，使用 sg 绕过会话组限制
sg docker -c "docker ps"

# 如果 daemon 未运行
sudo systemctl start docker
```

**注意**：用户已加入 `docker` 组，但当前 shell 会话可能未激活该组成员身份。所有 Docker 命令需通过 `sg docker -c "..."` 执行，或重新登录使组成员身份生效。

### 2. 配置环境变量

在仓库根目录创建 `.env`（已在 `.gitignore` 中）：

```bash
OPENAI_API_KEY=sk-YOUR-KEY
OPENCODE_MODEL=deepseek-v4-flash
OPENAI_BASE_URL=https://api.deepseek.com/v1
SHERPA_OPENCODE_IDLE_TIMEOUT_SEC=600
```

如果宿主机有代理，可配置 dind 使用代理拉取镜像：

```bash
SHERPA_DOCKER_HTTP_PROXY=http://host.docker.internal:20171
SHERPA_DOCKER_HTTPS_PROXY=http://host.docker.internal:20171
```

### 3. 启动全栈

```bash
cd /home/bohuju/TIanHeng_project/remove_k8s
sg docker -c "docker compose up -d"
```

首次启动会自动构建未缓存的镜像（`sherpa-web`、`sherpa-frontend`、`sherpa-gateway`），后续启动直接使用已有镜像。

### 4. 验证服务

```bash
# 后端 API
curl -s http://localhost:8000/api/system | python3 -m json.tool

# 前端
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000
# 期望输出: 200
```

浏览器访问 `http://localhost:8000` 打开控制台。

## 服务架构

```
                   :8000
                     │
              sherpa-gateway (nginx)
                /api/*     │     /*
          sherpa-web:8001  │  sherpa-frontend:3000
                │          │
          ┌─────┘          │
          │                │
     postgres:5432   sherpa-docker:2375 (dind)
```

| 服务 | 容器名 | 端口 | 说明 |
|------|--------|------|------|
| postgres | remove_k8s-postgres-1 | 5432（内部） | 任务与配置持久化 |
| sherpa-web | remove_k8s-sherpa-web-1 | 8001（内部） | FastAPI 后端，进程内执行工作流 |
| sherpa-frontend | remove_k8s-sherpa-frontend-1 | 3000（内部） | Next.js 14 控制台 |
| sherpa-docker | remove_k8s-sherpa-docker-1 | 2375（内部） | Docker-in-Docker，构建与运行 fuzz 容器 |
| sherpa-gateway | remove_k8s-sherpa-gateway-1 | 8000（宿主机） | nginx 反向代理，统一入口 |

## 已修复的部署问题

以下是本次部署过程中发现并修复的问题（已合并到代码中）。

### 1. sherpa-web 缺少 Docker CLI

**现象**：任务在 clone / build 阶段报错 `Docker not found in PATH`。

**根因**：sherpa-web 通过 `DOCKER_HOST=tcp://sherpa-docker:2375` 与 dind 通信，但镜像中未安装 `docker` CLI 二进制。

**修复**：[docker/Dockerfile.web](../docker/Dockerfile.web) — 添加 Docker CLI 静态二进制安装步骤（版本 27.5.1，从 tuna 镜像下载）：

```dockerfile
ARG DOCKER_VERSION=27.5.1
RUN set -e; \
    arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    case "$arch" in \
        amd64|x86_64) docker_arch="x86_64" ;; \
        arm64|aarch64) docker_arch="aarch64" ;; \
    esac; \
    curl -fsSL "https://mirrors.tuna.tsinghua.edu.cn/docker-ce/linux/static/stable/${docker_arch}/docker-${DOCKER_VERSION}.tgz" -o /tmp/docker.tgz; \
    tar -xzf /tmp/docker.tgz -C /usr/local/bin --strip-components=1 docker/docker; \
    rm -f /tmp/docker.tgz; \
    docker --version
```

**验证**：
```bash
docker exec remove_k8s-sherpa-web-1 docker --version
# Docker version 27.5.1, build 9f9e405
```

### 2. dind 代理端口错误

**现象**：dind 无法拉取任何镜像，报错 `proxyconnect tcp: dial tcp 172.17.0.1:7897: connect: connection refused`。

**根因**：[docker-compose.yml](../docker-compose.yml) 中 dind 的 HTTP_PROXY 默认值硬编码为 `http://host.docker.internal:7897`，但宿主机上该端口无代理服务。实际代理（v2raya）在 `127.0.0.1:20171`（HTTP），且只监听 loopback，Docker 容器无法访问。

**修复**：将 dind 的代理默认值改为空。dind 通过 registry mirror（`https://7m856d3fdvb9yp.xuanyuan.run`）直接拉取镜像：

```yaml
HTTP_PROXY: ${SHERPA_DOCKER_HTTP_PROXY:-}
HTTPS_PROXY: ${SHERPA_DOCKER_HTTPS_PROXY:-}
```

如需使用代理，通过环境变量显式指定：
```bash
SHERPA_DOCKER_HTTP_PROXY=http://host.docker.internal:20171 docker compose up -d
```

同时需确保代理服务监听 `0.0.0.0` 而非 `127.0.0.1`（v2raya 默认只监听 loopback，需修改配置）。

### 3. Gateway 端口冲突

**现象**：gateway 启动失败 `failed to bind host port 0.0.0.0:8000: address already in use`。

**根因**：宿主机上残留的 Next.js dev server 占用了 8000 端口。

**修复**：
```bash
# 找到占用进程
ss -tlnp | grep 8000
# 终止占用进程
kill <PID>
# 重启 gateway
sg docker -c "docker compose up -d sherpa-gateway"
```

### 4. Gateway tmpfs 权限拒绝

**现象**：gateway 容器中 nginx 无法启动，报错 `mkdir() "/var/cache/nginx/client_temp" failed (13: Permission denied)`。

**根因**：[docker-compose.yml](../docker-compose.yml) 中 gateway 的 tmpfs 挂载 `/var/cache/nginx` 默认属主为 root，但 nginx 进程以 uid 101（nginx 用户）运行。tmpfs 覆盖了 Dockerfile 中的 `chown`。

**修复**：为 tmpfs 挂载添加 uid/gid 选项：
```yaml
tmpfs:
  - /var/cache/nginx:uid=101,gid=101,mode=0755
  - /var/run:uid=101,gid=101,mode=0755
  - /tmp:uid=101,gid=101,mode=0755
```

### 5. Gateway 网络未连接

**现象**：gateway 容器启动后无法解析 `sherpa-web` 和 `sherpa-frontend` 服务名，nginx 报 `host not found in upstream`。

**根因**：gateway 在端口冲突后单独重启，Docker Compose 未正确将其加入共享网络。

**修复**：
```bash
sg docker -c "docker compose stop sherpa-gateway && docker compose up -d sherpa-gateway"
```

### 6. HTTPS 默认跳转

**现象**：最初配置中 nginx 将所有 HTTP 请求 301 跳转到 HTTPS，本地开发不便。

**修复**：修改 [docker/nginx/sherpa.conf](../docker/nginx/sherpa.conf)，去掉 SSL server block，直接在 80 端口提供 HTTP 服务。

### 7. Clone 目录权限问题

**现象**：clone 成功后（`Checked out commit xxx`），但创建子目录时失败 `PermissionError: [Errno 13] Permission denied: '/shared/output/zlib-xxx/fuzz'`。

**根因**：`docker run alpine/git clone` 在 dind 中以 root 执行，克隆的文件属主为 root:root。但 sherpa-web 以 `USER 10001:10001` 运行，无法在 root 拥有的目录下创建子目录。

**修复**：[fuzz_unharnessed_repo.py](../harness_generator/src/fuzz_unharnessed_repo.py) — 在 `docker run` 命令中添加 `--user 10001:10001`：
```python
clone_cmd = [
    "docker",
    "run",
    "--rm",
    "--user",
    "10001:10001",   # 与 sherpa-web 容器用户一致
    ...
]
```

**补充说明**：[codex_helper.py](../harness_generator/src/codex_helper.py) 中 `_docker_git()` 方法使用的是 `--user 0:0`（root），因为 AI 修改文件需要跨越不同属主的文件——该场景与 clone 不同，各自有各自的用户策略。

### 8. GBrain 记忆系统集成

**现状**：GBrain 长期记忆系统已于 2026-06-01 完成优化并入镜像。gbrain 源码位于项目 `./gbrain/`，Bun 运行时和依赖在 Dockerfile 中安装，容器启动后零干预可用。

**前置条件**：

1. gbrain 数据库容器必须运行并接入同一 Docker 网络：
   ```bash
   sg docker -c "docker start gbrain-mcp-pg"
   sg docker -c "docker network connect remove_k8s_default gbrain-mcp-pg"
   ```
2. Docker daemon DNS 必须可用（见问题 8 排查）。

**验证**：
```bash
curl -s http://localhost:8000/api/memory/health | python3 -m json.tool
# 期望 healthy: true, proc_alive: true
```

**文档**：详细优化方案与实施记录见 [`GBRAIN_OPTIMIZATION.md`](GBRAIN_OPTIMIZATION.md)。

### 9. Docker 构建 DNS 解析失败

**现象**：`docker compose build` 时 pip install / curl 报 `Temporary failure in name resolution` 或 `Could not resolve host`。

**根因**：Docker daemon 继承的 DNS 服务器（从 `/etc/resolv.conf`）不可达。

**修复**：在 `/etc/docker/daemon.json` 中指定公共 DNS：
```json
{"dns": ["8.8.8.8", "1.1.1.1"]}
```
然后重启 Docker：
```bash
sudo systemctl restart docker
```

---

## 日常维护

### 重启服务

```bash
# 全部重启
sg docker -c "docker compose restart"

# 仅重启后端（代码修改后）
sg docker -c "docker compose restart sherpa-web"

# 重新构建并重启（Dockerfile 修改后）
sg docker -c "docker compose up -d --build sherpa-web"
```

### 查看日志

```bash
# 后端日志
sg docker -c "docker logs remove_k8s-sherpa-web-1 --tail 100"

# 容器内任务日志
sg docker -c "docker exec remove_k8s-sherpa-web-1 ls /app/job-logs/jobs/"
sg docker -c "docker exec remove_k8s-sherpa-web-1 tail -100 /app/job-logs/jobs/<job_id>.log"
```

### 清理磁盘

```bash
# 清理 Docker 构建缓存
sg docker -c "docker system prune -a"

# 清理挂载卷中的旧输出
rm -rf ./output/_jobs ./output/zlib-*
```

### 检查代理配置

如果镜像拉取缓慢，可临时配置宿主机代理：

```bash
# 确认代理可用
curl -x http://127.0.0.1:20171 https://hub.docker.com -o /dev/null -w "%{http_code}"

# 如果 v2raya 只监听 127.0.0.1，需修改为 0.0.0.0
# 编辑 v2raya 配置（通常在 /etc/v2raya/），将 inbounds 中的 "listen": "127.0.0.1" 改为 "0.0.0.0"
```

## 排查检查清单

| 检查项 | 命令 |
|--------|------|
| 磁盘空间 | `df -h /` |
| 后端状态 | `curl -s http://localhost:8000/api/system \| python3 -m json.tool` |
| API Key 已加载 | 同上，检查 `openai_api_key_set: true` |
| Docker 可用 | `sg docker -c "docker ps"` |
| dind 健康 | `sg docker -c "docker exec remove_k8s-sherpa-docker-1 docker info"` |
| 镜像拉取正常 | `sg docker -c "docker exec remove_k8s-sherpa-docker-1 docker pull alpine"` |
| 容器全部运行 | `sg docker -c "docker compose ps"` |
| 端口 8000 无冲突 | `ss -tlnp \| grep 8000` |
| 代码改动已生效 | `sg docker -c "docker compose restart sherpa-web"` |
| 任务列表 | `curl -s http://localhost:8000/api/tasks` |
| 具体任务状态 | `curl -s http://localhost:8000/api/task/<job_id>` |
