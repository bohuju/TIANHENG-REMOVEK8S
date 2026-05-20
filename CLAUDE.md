# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Sherpa is a fuzz orchestration system for public Git repositories. It automates the full fuzzing lifecycle: target selection, harness generation, build, run, coverage analysis, crash triage, and crash reproduction. Each stage runs in-process via `fuzz_logic()` dispatched by `_execute_docker_stage()`. Docker is used for fuzzing runtime containers (build/run isolation).

## Architecture

```
Frontend (Next.js) → FastAPI (main.py) → Postgres
                                        → _execute_docker_stage() → fuzz_logic() (in-process)
                                            → workflow_graph.py (state machine)
                                                → fuzz_unharnessed_repo.py (exec primitives)
                                                    → codex_helper.py (OpenCode AI CLI wrapper)
```

- **Control plane**: `harness_generator/src/langchain_agent/main.py` — FastAPI server exposing `/api/task`, `/api/tasks`, `/api/system`, `/api/config`
- **Executor**: `_execute_docker_stage()` in main.py — calls `fuzz_logic()` directly in-process for each workflow stage; `_executor_mode()` defaults to `"docker"`
- **Workflow state machine**: `harness_generator/src/langchain_agent/workflow_graph.py` — LangGraph-based state machine defining nodes (`plan`, `synthesize`, `build`, `run`, `coverage-analysis`, `improve-harness`, `crash-triage`, `fix-harness`, `re-build`, `re-run`, `crash-analysis`) and routing logic
- **Execution primitives**: `harness_generator/src/fuzz_unharnessed_repo.py` — ~310KB single-file module; clone repos, generate harnesses, build, run fuzzers, collect coverage/crash signals
- **Stage skills**: `harness_generator/src/langchain_agent/opencode_skills/<stage>/SKILL.md` — per-stage AI contracts (goals, inputs, outputs, acceptance criteria)
- **AI CLI wrapper**: `harness_generator/src/codex_helper.py` — OpenCode session management, prompt assembly, command allowlists

### Additional services

- **promefuzz-mcp/**: MCP server providing project-aware fuzz context (AST preprocessing, code navigation, comprehension tools). Written in Python, uses a TOML config. Embedded in-process for Docker executor mode.
- **frontend-next/**: Next.js 14 + MUI + React Query + Zustand dashboard. Exposes task creation, monitoring, logs, and system config.

## Commands

### Python backend

```bash
# Setup virtualenv and install deps
source setup-env.sh          # or: make setup

# Run the API server (from harness_generator/src/langchain_agent/)
source ../../.venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8001

# Run a single test
source .venv/bin/activate
python -m pytest tests/test_api_stability.py -xvs

# Run all tests
python -m pytest tests/ -xvs
```

### Frontend

```bash
cd frontend-next
npm run dev          # Next.js dev server on port 3000
npm run build        # production build
npm run lint         # ESLint (Next.js config)
npm test             # vitest run
```

### Docker Compose (full stack)

```bash
docker compose up -d              # all services (API + Postgres + frontend + gateway + Docker-in-Docker)
docker compose build sherpa-web   # rebuild API image after source changes
```

### OpenCode helper image

```bash
docker compose --profile opencode build sherpa-opencode
```

## Key environment variables

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` / `LLM_key` | LLM provider API key |
| `OPENAI_BASE_URL` | LLM base URL (default: DeepSeek API) |
| `OPENAI_MODEL` / `OPENCODE_MODEL` | Model name (default: `deepseek-reasoner`) |
| `SHERPA_CODEX_CLI` | CLI backend for code edits (default: `opencode`) |
| `SHERPA_EXECUTOR_MODE` | Executor mode: `"docker"` (default, in-process). `"k8s_job"` was removed. |
| `DATABASE_URL` | Postgres connection string |
| `SHERPA_OUTPUT_DIR` | Artifact output directory (default: `/shared/output`) |
| `SHERPA_PARALLEL_FUZZERS` | Number of parallel fuzzers per run (default: 2) |
| `SHERPA_RUN_UNLIMITED_ROUND_BUDGET_SEC` | Max seconds for unlimited run rounds (default: 7200) |
| `SHERPA_VERIFY_STAGE_NO_AI` | Set to `1` to disallow AI code changes during fuzz verification |

## Branch and PR workflow

1. Create feature branch from `dev`: `git checkout dev && git pull && git checkout -b codex/<topic>`
2. Push and open PR targeting `dev`
3. After `dev` CI passes, open PR from `dev` → `main`
4. Direct pushes to `dev`/`main` are forbidden; `main` only accepts PRs from `dev`
5. Every PR must include: change summary, risk/rollback points, and reproducible verification

## Project structure (key paths)

- `harness_generator/src/langchain_agent/main.py` — API entrypoint + executor dispatch
- `harness_generator/src/langchain_agent/workflow_graph.py` — workflow state machine
- `harness_generator/src/fuzz_unharnessed_repo.py` — core fuzzing primitives
- `harness_generator/src/codex_helper.py` — OpenCode AI CLI wrapper
- `harness_generator/src/langchain_agent/opencode_skills/` — per-stage AI skill contracts
- `harness_generator/src/langchain_agent/prompts/` — global prompt templates for OpenCode
- `harness_generator/src/langchain_agent/persistent_config.py` — runtime config persistence
- `harness_generator/src/langchain_agent/job_store.py` — job persistence (SQLite / Postgres)
- `harness_generator/src/langchain_agent/workflow_context_store.py` — cross-stage context management
- `harness_generator/src/langchain_agent/promefuzz_companion.py` — in-process MCP companion
- `frontend-next/` — Next.js dashboard
- `promefuzz-mcp/` — MCP server for fuzz context
- `tests/` — pytest suite (import from `harness_generator/src/langchain_agent/`)
- `docker/` — Dockerfiles per component (web, fuzz, fuzz-cpp, fuzz-java, frontend, gateway, opencode)
- `docker-compose.yml` — local full-stack deployment

## Testing notes

- Python tests live in `tests/` and import from `harness_generator/src/langchain_agent/`. They require the virtualenv to be active with all deps installed.
- Frontend tests use `vitest` with `jsdom` environment.
- Test files are contracts/behavior tests: they validate stage skill bindings, API stability, worker behavior, prompt templates, etc. There are no traditional unit tests.
