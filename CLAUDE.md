# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Sherpa is a fuzz orchestration system for public Git repositories. It automates the full fuzzing lifecycle: target selection, harness generation, build, run, coverage analysis, crash triage, and crash reproduction. Each stage runs in-process via `fuzz_logic()` dispatched by `_execute_docker_stage()`.

## Architecture

```
Browser (:8000) → nginx gateway
                  ├── /api/* → sherpa-web:8001 (FastAPI)
                  │              ├── Postgres :5432 (tasks/config)
                  │              ├── fuzz_logic() in-process
                  │              │   └── workflow_graph.py → fuzz_unharnessed_repo.py → codex_helper.py
                  │              ├── MemoryAdapter → gbrain serve (MCP stdio) → gbrain-postgres :5432
                  │              └── DOCKER_HOST=tcp://sherpa-docker:2375 (dind)
                  └── /* → sherpa-frontend:3000 (Next.js)
```

**Key components**:
- **Control plane**: `harness_generator/src/langchain_agent/main.py` — FastAPI, `/api/task`, `/api/tasks`, `/api/system`, `/api/config`, `/api/memory/*`
- **Workflow state machine**: `workflow_graph.py` — LangGraph with nodes: `plan`, `synthesize`, `build`, `run`, `coverage-analysis`, `improve-harness`, `crash-triage`, `fix-harness`, `re-build`, `re-run`, `crash-analysis`, `memory-summarize`
- **Execution primitives**: `fuzz_unharnessed_repo.py` — ~310KB; clone, harness gen, build, run fuzzers, coverage/crash collection
- **AI CLI wrapper**: `codex_helper.py` — OpenCode session management, prompt assembly, command allowlists
- **Memory system**: `memory/` + `memory_adapter.py` — GBrain MCP client for long-term fuzz experience (see GBrain section below)
- **Stage skills**: `opencode_skills/<stage>/SKILL.md` — per-stage AI contracts
- **promefuzz-mcp/**: MCP server for fuzz context (AST preprocessing, code nav). Embedded in-process.
- **frontend-next/**: Next.js 14 + MUI + React Query. MemoryDrawer for gbrain pages.

## Commands

**Important**: The Docker socket at `/var/run/docker.sock` is owned by `root:docker`. The current user is in the `docker` group but the shell session may not have it active. Wrap all Docker commands:

```bash
sg docker -c "docker compose up -d"
sg docker -c "docker compose ps"
```

### Docker Compose (primary deployment method)

```bash
sg docker -c "docker compose up -d"                    # start all 6 services
sg docker -c "docker compose down"                      # stop and remove all
sg docker -c "docker compose restart sherpa-web"        # restart API (source changes via volume mount)
sg docker -c "docker compose build sherpa-web"          # rebuild API image (Dockerfile changes)
sg docker -c "docker compose up -d --build sherpa-web"  # rebuild + restart in one step
```

### Python backend

```bash
source setup-env.sh                      # create venv + install deps
source .venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8001  # from harness_generator/src/langchain_agent/
python -m pytest tests/ -xvs            # all tests
python -m pytest tests/test_api_stability.py -xvs  # single test
```

### Frontend

```bash
cd frontend-next
npm run dev          # Next.js on :3000
npm run build        # production build
npm run lint         # ESLint
npm test             # vitest
```

## GBrain memory system

GBrain provides long-term fuzz experience storage. Architecture:

```
MemoryAdapter (memory_adapter.py)
  └── gbrain serve subprocess (Bun, MCP stdio JSON-RPC)
        └── gbrain-postgres :5432 (database: gbrain_mcp)
```

- **Source**: `gbrain/` — CLI + MCP server (v0.16.4), requires Bun runtime
- **Adapter**: `memory_adapter.py` — starts `gbrain serve`, communicates via JSON-RPC
- **Schemas**: `memory/schemas.py` — TargetRepo, Session, Crash, Strategy, Harness page types
- **API endpoints**: `/api/memory/search`, `/api/memory/pages`, `/api/memory/page/{slug}`, `/api/memory/health`
- **Frontend**: `MemoryDrawer.tsx` — list/search/detail/edit/create/delete memory pages
- **Image**: gbrain + Bun baked into Docker image via `Dockerfile.web` (COPY gbrain, bun install)
- **Key env**: `GBRAIN_DATABASE_URL` takes precedence over config file

Verify: `curl -s http://localhost:8000/api/memory/health` → `healthy: true`

## Key environment variables

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` / `LLM_key` | LLM provider API key |
| `OPENAI_BASE_URL` | LLM base URL (default: `https://api.deepseek.com/v1`) |
| `OPENAI_MODEL` / `OPENCODE_MODEL` | Model name (default: `deepseek-reasoner`) |
| `DATABASE_URL` | Sherpa Postgres (default: `postgresql://sherpa:sherpa@postgres:5432/sherpa`) |
| `GBRAIN_DATABASE_URL` | GBrain Postgres (default: `postgresql://postgres:postgres@gbrain-mcp-pg:5432/gbrain_mcp`) |
| `DOCKER_HOST` | dind daemon (default: `tcp://sherpa-docker:2375`) |
| `SHERPA_EXECUTOR_MODE` | `"docker"` (default, in-process). `"k8s_job"` removed. |
| `SHERPA_OUTPUT_DIR` | Artifacts (default: `/shared/output`) |
| `SHERPA_PARALLEL_FUZZERS` | Parallel fuzzers per run (default: 2) |
| `SHERPA_RUN_UNLIMITED_ROUND_BUDGET_SEC` | Max seconds for unlimited rounds (default: 7200) |

## Deployment caveats

- **Docker DNS**: If `docker build` fails with "Temporary failure in name resolution", add `{"dns": ["8.8.8.8", "1.1.1.1"]}` to `/etc/docker/daemon.json` and `sudo systemctl restart docker`.
- **Port 8000 conflicts**: Check `ss -tlnp | grep 8000` if gateway fails to bind.
- **User permissions**: Clone via `docker run alpine/git` must use `--user 10001:10001` (matches web container user). Code edits via `codex_helper.py` use `--user 0:0` (root) for cross-owner writes.
- **Gateway tmpfs**: `/var/cache/nginx` tmpfs needs `uid=101,gid=101,mode=0755` mount options.
- **dind proxy**: Default `HTTP_PROXY` was removed (port 7897 had no service). Set `SHERPA_DOCKER_HTTP_PROXY` explicitly if needed. The host proxy (v2raya) is on `127.0.0.1:20171` (HTTP), `127.0.0.1:20170` (SOCKS) — only loopback, not accessible from containers.
- **Source volume mount**: `./harness_generator/src:/app/harness_generator/src` — code changes need `docker compose restart sherpa-web`, not rebuild.

## Branch workflow

1. Branch from `dev`: `git checkout dev && git pull && git checkout -b <topic>`
2. PR → `dev`
3. After CI, PR `dev` → `main`
4. No direct pushes to `dev`/`main`

## Key files

| File | Purpose |
|---|---|
| `main.py` | FastAPI entrypoint, executor dispatch, all API routes |
| `workflow_graph.py` | LangGraph state machine (~13000+ lines) |
| `fuzz_unharnessed_repo.py` | Core fuzz primitives (~310KB) |
| `codex_helper.py` | OpenCode AI CLI wrapper |
| `memory_adapter.py` | GBrain MCP client |
| `memory/schemas.py` | Memory page dataclasses |
| `memory/suggestion_builder.py` | GBrain results → structured suggestions |
| `persistent_config.py` | Runtime config persistence |
| `job_store.py` | Job persistence (SQLite/Postgres) |
| `workflow_context_store.py` | Cross-stage context |
| `docker/Dockerfile.web` | API image (Python 3.10 + Docker CLI + Bun + gbrain) |
| `docker-compose.yml` | 6-service orchestration |
| `docker/nginx/sherpa.conf` | Gateway nginx config (plain HTTP on :80) |
| `docs/DEPLOYMENT_GUIDE.md` | Full deployment guide + known issues |
| `docs/GBRAIN_OPTIMIZATION.md` | GBrain optimization plan + implementation record |

## Testing notes

- Python tests in `tests/`, import from `harness_generator/src/langchain_agent/`, require venv.
- Frontend tests use `vitest` + `jsdom`.
- Tests are behavior/contract tests, not traditional unit tests.
