# main.py
from __future__ import annotations
from loguru import logger

from fastapi import FastAPI, Body, HTTPException, Query, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
import hashlib
import math
import os
import re
import shutil
import resource
import subprocess
import sys
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import ContextVar
import threading
import time
import queue
import uuid
from collections import deque
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from io import StringIO
from pathlib import Path
from urllib.parse import urlparse
from fuzz_relative_functions import fuzz_logic
from job_store import JobStore, PostgresJobStore
from persistent_config import (
    WebPersistentConfig,
    apply_llm_env_source,
    apply_config_to_env,
    as_public_dict,
    list_opencode_provider_models_resolved,
    normalize_model_for_opencode,
    opencode_env_path,
    opencode_runtime_config_path,
    load_config,
    save_config,
)
from workflow_context_store import (
    context_dir_for_repo_root,
    merge_result_into_contexts,
    read_context_docs,
    strip_meta,
    write_context_docs,
)
from memory_adapter import MemoryAdapter

@asynccontextmanager
async def _lifespan(app: FastAPI):
    cfg = load_config()
    _cfg_set(cfg)
    apply_config_to_env(cfg)
    _init_job_store()

    # Initialize MemoryAdapter singleton for API access
    memory_adapter = MemoryAdapter()
    app.state.memory_adapter = memory_adapter
    logger.info("MemoryAdapter initialized for API access")

    yield

    # Shutdown: close MemoryAdapter
    try:
        await memory_adapter.close()
        logger.info("MemoryAdapter closed")
    except Exception as exc:
        logger.warning("Error closing MemoryAdapter: {}", exc)


app = FastAPI(title="LangChain Agent API", version="1.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _http_metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = None
    status_code = 500
    try:
        response = await call_next(request)
        status_code = int(getattr(response, "status_code", 500))
        return response
    finally:
        elapsed_ms = max(0.0, (time.perf_counter() - start) * 1000.0)
        now_ts = time.time()
        with _HTTP_METRICS_LOCK:
            _HTTP_REQUEST_EVENTS.append((now_ts, elapsed_ms, status_code))
            cutoff = now_ts - 3600.0
            while _HTTP_REQUEST_EVENTS and _HTTP_REQUEST_EVENTS[0][0] < cutoff:
                _HTTP_REQUEST_EVENTS.popleft()

#创建线程池
_MAX_WORKERS = int(os.environ.get("SHERPA_WEB_MAX_WORKERS", "5"))
executor = ThreadPoolExecutor(max_workers=max(1, _MAX_WORKERS))


_JOBS_LOCK = threading.Lock()
_JOBS: dict[str, dict] = {}
_APP_START = time.time()
_INIT_LOCK = threading.Lock()
_JOB_STORE: JobStore | None = None
_JOB_FUTURES_LOCK = threading.Lock()
_JOB_FUTURES: dict[str, Future] = {}
_HTTP_METRICS_LOCK = threading.Lock()
_HTTP_REQUEST_EVENTS: deque[tuple[float, float, int]] = deque()

# In-memory API log retention limit (characters).
# 0 or negative means unlimited (no truncation).
_JOB_MEMORY_LOG_MAX_CHARS = int(os.environ.get("SHERPA_WEB_JOB_LOG_MAX_CHARS", "0"))
_JOB_RESTORE_LOG_MAX_CHARS = int(os.environ.get("SHERPA_WEB_RESTORE_LOG_MAX_CHARS", "200000"))

_SENSITIVE_ENV_KEYS = (
    "LLM_key",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "DEEPSEEK_API_KEY",
    "MINIMAX_API_KEY",
    "ANTHROPIC_API_KEY",
    "DATABASE_URL",
    "POSTGRES_PASSWORD",
)

_MEMORY_TYPE_PREFIX: dict[str, str] = {
    "targets": "fuzz/target-repo",
    "sessions": "fuzz/session",
    "crashes": "fuzz/crash",
    "strategies": "fuzz/strategy",
    "harnesses": "fuzz/harness",
}

from memory.schemas import PAGE_TYPE_PREFIX

def _page_type_key_from_slug(slug: str) -> str:
    """Determine the memory type key from a page slug."""
    for page_type, slug_prefix in PAGE_TYPE_PREFIX.items():
        if slug.startswith(slug_prefix + "/"):
            for key, pt in _MEMORY_TYPE_PREFIX.items():
                if pt == page_type:
                    return key
    return "unknown"

_SENSITIVE_KV_RE = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|PASS))\s*=\s*([^\s,;]+)"
)
_AUTH_BEARER_RE = re.compile(r"(?i)\b(Authorization\s*:\s*Bearer\s+)([^\s]+)")

_ACTIVE_JOB_STDOUT_TEE: ContextVar[object | None] = ContextVar("ACTIVE_JOB_STDOUT_TEE", default=None)
_ACTIVE_JOB_STDERR_TEE: ContextVar[object | None] = ContextVar("ACTIVE_JOB_STDERR_TEE", default=None)


def _redact_sensitive_text(text: str) -> str:
    if not text:
        return text
    out = text
    for key in _SENSITIVE_ENV_KEYS:
        val = (os.environ.get(key) or "").strip()
        if val:
            out = out.replace(val, "***")
    out = _SENSITIVE_KV_RE.sub(lambda m: f"{m.group(1)}=***", out)
    out = _AUTH_BEARER_RE.sub(lambda m: f"{m.group(1)}***", out)
    return out


_REPO_ROOT = Path(__file__).resolve().parents[3]
_JOB_LOGS_DIR = Path(
    os.environ.get("SHERPA_WEB_JOB_LOG_DIR", "/app/job-logs/jobs")
).expanduser().resolve()


_CFG_LOCK = threading.Lock()
_CFG: WebPersistentConfig = WebPersistentConfig()


def _cfg_get() -> WebPersistentConfig:
    with _CFG_LOCK:
        return _CFG


def _cfg_set(cfg: WebPersistentConfig) -> None:
    global _CFG
    with _CFG_LOCK:
        _CFG = cfg


def _normalized_opencode_model_value(raw_model: object) -> str:
    value = str(raw_model or "").strip()
    if value in {"-", "auto", "AUTO", "none", "None", "null", "NULL"}:
        return ""
    if not value:
        return ""
    return normalize_model_for_opencode(value, cfg=_cfg_get())


def _normalized_plain_model_value(raw_model: object) -> str:
    value = str(raw_model or "").strip()
    if value in {"-", "auto", "AUTO", "none", "None", "null", "NULL"}:
        return ""
    return value


def _openai_model_env_value(raw_model: str, normalized_model: str) -> str:
    plain = _normalized_plain_model_value(raw_model)
    if plain:
        return plain
    normalized = str(normalized_model or "").strip()
    if "/" in normalized:
        return normalized.split("/", 1)[1]
    return normalized


def _track_job_future(job_id: str, future: Future) -> None:
    with _JOB_FUTURES_LOCK:
        _JOB_FUTURES[job_id] = future

    def _cleanup(_: Future) -> None:
        with _JOB_FUTURES_LOCK:
            if _JOB_FUTURES.get(job_id) is future:
                _JOB_FUTURES.pop(job_id, None)

    add_cb = getattr(future, "add_done_callback", None)
    if callable(add_cb):
        add_cb(_cleanup)
        return

    done_fn = getattr(future, "done", None)
    if callable(done_fn):
        try:
            if bool(done_fn()):
                _cleanup(future)
        except Exception:
            pass


def _cancel_job_future(job_id: str) -> bool:
    with _JOB_FUTURES_LOCK:
        fut = _JOB_FUTURES.get(job_id)
    if fut is None:
        return False
    cancel_fn = getattr(fut, "cancel", None)
    if not callable(cancel_fn):
        return False
    try:
        return bool(cancel_fn())
    except Exception:
        return False


def _read_text_if_exists(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _read_int_if_exists(path: str) -> int | None:
    raw = _read_text_if_exists(path)
    if not raw:
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


def _cgroup_memory_status() -> dict[str, object]:
    current = _read_int_if_exists("/sys/fs/cgroup/memory.current")
    limit_raw = _read_text_if_exists("/sys/fs/cgroup/memory.max")
    oom_kill_count = None
    events_raw = _read_text_if_exists("/sys/fs/cgroup/memory.events")

    if current is None:
        current = _read_int_if_exists("/sys/fs/cgroup/memory/memory.usage_in_bytes")
    if not limit_raw:
        limit_raw = _read_text_if_exists("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    if events_raw:
        for line in events_raw.splitlines():
            key, _, value = line.partition(" ")
            if key.strip() == "oom_kill":
                try:
                    oom_kill_count = int(value.strip())
                except (ValueError, TypeError):
                    pass
                break

    limit_bytes = None
    if limit_raw and limit_raw != "max":
        try:
            parsed_limit = int(limit_raw)
            if parsed_limit < (1 << 60):
                limit_bytes = parsed_limit
        except (ValueError, TypeError):
            pass

    usage_ratio = None
    if current is not None and limit_bytes and limit_bytes > 0:
        usage_ratio = current / limit_bytes

    return {
        "current_bytes": current,
        "limit_bytes": limit_bytes,
        "usage_ratio": usage_ratio,
        "oom_kill_count": oom_kill_count,
    }


def _process_rss_bytes() -> int | None:
    try:
        raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if raw > 0:
            return int(raw) * 1024
    except (OSError, ValueError):
        pass

    proc_status = _read_text_if_exists("/proc/self/status")
    for line in proc_status.splitlines():
        if not line.startswith("VmRSS:"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            try:
                return int(parts[1]) * 1024
            except (ValueError, TypeError):
                return None
    return None


def _memory_status() -> dict[str, object]:
    cgroup = _cgroup_memory_status()
    usage_ratio = cgroup.get("usage_ratio")
    pressure = "unknown"
    if isinstance(usage_ratio, (int, float)):
        if usage_ratio >= 0.95:
            pressure = "critical"
        elif usage_ratio >= 0.85:
            pressure = "high"
        elif usage_ratio >= 0.7:
            pressure = "elevated"
        else:
            pressure = "normal"

    return {
        "process_rss_bytes": _process_rss_bytes(),
        "cgroup_current_bytes": cgroup.get("current_bytes"),
        "cgroup_limit_bytes": cgroup.get("limit_bytes"),
        "cgroup_usage_ratio": usage_ratio,
        "oom_kill_count": cgroup.get("oom_kill_count"),
        "pressure": pressure,
    }


def _docker_cli(args: list[str], *, timeout: int = 20) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["docker", *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return int(proc.returncode), proc.stdout or "", proc.stderr or ""
    except (OSError, subprocess.SubprocessError) as e:
        return 1, "", str(e)


_SUPPORTED_EXECUTOR_MODES = {"docker"}

def _executor_mode() -> str:
    mode = (os.environ.get("SHERPA_EXECUTOR_MODE", "docker") or "").strip().lower()
    if mode and mode not in _SUPPORTED_EXECUTOR_MODES:
        raise RuntimeError(
            f"unsupported executor mode: {mode}. Supported: docker"
        )
    return mode


def _analysis_companion_status_for_job(job_id: str) -> dict[str, object]:
    jid = str(job_id or "").strip()
    if not jid:
        return {}
    base = Path(os.environ.get("SHERPA_OUTPUT_DIR", "/shared/output")).expanduser()
    status_path = base / "_jobs" / jid / "promefuzz" / "status.json"
    if not status_path.is_file():
        return {}
    try:
        raw = status_path.read_text(encoding="utf-8", errors="replace")
        parsed = json.loads(raw)
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    out: dict[str, object] = {}
    for key in (
        "state",
        "analysis_backend",
        "candidate_count",
        "updated_at",
        "repo_root",
        "error",
        "last_error",
        "preprocess_path",
        "coverage_hints_path",
        "rag_ok",
        "rag_knowledge_base_path",
        "rag_document_count",
        "rag_chunk_count",
        "embedding_provider",
        "embedding_model",
        "embedding_ok",
        "rag_degraded",
        "rag_degraded_reason",
        "semantic_query_count",
        "semantic_hit_count",
        "semantic_hit_rate",
        "cache_hit_rate",
        "mcp_url",
        "mcp_ready",
    ):
        if key in parsed:
            out[key] = parsed.get(key)
    if "mcp_url" not in out:
        out["mcp_url"] = ""
    if "mcp_ready" not in out:
        out["mcp_ready"] = False
    if "last_error" not in out:
        out["last_error"] = out.get("error")
    return out


def _analysis_context_path_for_repo(repo_root: str | None) -> Path | None:
    raw = str(repo_root or "").strip()
    if not raw:
        return None
    try:
        root = Path(raw).expanduser()
    except (OSError, RuntimeError):
        return None
    return root / "fuzz" / "analysis_context.json"


def _has_reusable_analysis_context(repo_root: str | None) -> bool:
    analysis_path = _analysis_context_path_for_repo(repo_root)
    return bool(analysis_path and analysis_path.is_file())


def _execute_docker_stage(
    *,
    job_id: str,
    payload: dict[str, object],
    wait_timeout: int,
) -> tuple[object, str]:
    """Run a single workflow stage directly (Docker executor mode).

    Calls fuzz_logic() in-process with stage-scoped parameters.
    Returns (result_dict, node_name).
    """
    def _int_param(key: str, default: int) -> int:
        v = payload.get(key)
        return int(v) if v is not None else default

    repo_url = str(payload.get("repo_url") or "").strip()
    if not repo_url:
        raise RuntimeError("repo_url is required for docker stage execution")

    result = fuzz_logic(
        repo_url=repo_url,
        max_len=_int_param("max_len", 0),
        time_budget=_int_param("time_budget", 900),
        run_time_budget=_int_param("run_time_budget", 900),
        coverage_loop_max_rounds=_int_param("coverage_loop_max_rounds", 0),
        max_fix_rounds=_int_param("max_fix_rounds", 0),
        same_error_max_retries=_int_param("same_error_max_retries", 0),
        email=(str(payload.get("email") or "").strip() or None),
        docker_image=(str(payload.get("docker_image") or "").strip() or None),
        ai_key_path=(Path(str(payload.get("ai_key_path") or "")).expanduser() if payload.get("ai_key_path") else None),
        oss_fuzz_dir=(str(payload.get("oss_fuzz_dir") or "").strip() or None),
        model=(str(payload.get("model") or "").strip() or None),
        resume_from_step=(str(payload.get("resume_from_step") or "").strip() or None),
        resume_repo_root=(str(payload.get("resume_repo_root") or "").strip() or None),
        stop_after_step=(str(payload.get("stop_after_step") or "").strip() or None),
        context_dir=(str(payload.get("context_dir") or "").strip() or None),
    )
    return result, ""


def _estimate_run_fuzzer_count(repo_root: str) -> int:
    raw = str(repo_root or "").strip()
    if not raw:
        return 1
    root = Path(raw)
    if not root.exists():
        return 1

    fuzz_out = root / "fuzz" / "out"
    try:
        if fuzz_out.is_dir():
            count = 0
            for p in fuzz_out.iterdir():
                if not p.is_file():
                    continue
                if os.access(str(p), os.X_OK) or p.suffix.lower() == ".exe":
                    count += 1
            if count > 0:
                return count
    except OSError:
        pass

    execution_plan = root / "fuzz" / "execution_plan.json"
    try:
        if execution_plan.is_file():
            doc = json.loads(execution_plan.read_text(encoding="utf-8", errors="replace"))
            targets = doc.get("execution_targets")
            if isinstance(targets, list):
                count = len([t for t in targets if isinstance(t, dict)])
                if count > 0:
                    return count
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return 1


def _estimate_run_parallelism(stage_ctx: dict[str, object]) -> int:
    raw = str(
        (stage_ctx or {}).get("run_parallel_fuzzers_override")
        or os.environ.get("SHERPA_PARALLEL_FUZZERS")
        or "3"
    ).strip()
    try:
        return max(1, min(int(raw), 64))
    except (ValueError, TypeError):
        return 3


def _list_runtime_containers_for_repo(repo_root: str) -> list[str]:
    root = str(repo_root or "").strip()
    if not root:
        return []

    repo_sha1 = hashlib.sha1(root.encode("utf-8", errors="ignore")).hexdigest()
    found: set[str] = set()
    filters = [
        ["ps", "-q", "--filter", f"label=sherpa.repo_root_sha1={repo_sha1}"],
        ["ps", "-q", "--filter", f"volume={root}"],
    ]
    for cmd in filters:
        rc, out, _ = _docker_cli(cmd, timeout=15)
        if rc != 0:
            continue
        for line in out.splitlines():
            cid = line.strip()
            if cid:
                found.add(cid)
    return sorted(found)


def _stop_runtime_containers_for_repo(repo_root: str) -> list[str]:
    killed: list[str] = []
    for cid in _list_runtime_containers_for_repo(repo_root):
        rc, _, _ = _docker_cli(["rm", "-f", cid], timeout=20)
        if rc == 0:
            killed.append(cid)
    return killed


def _is_cancel_requested(job_id: str) -> bool:
    snap = _job_snapshot(job_id)
    return bool(snap and snap.get("cancel_requested"))


def _ensure_job_logs_dir() -> None:
    _JOB_LOGS_DIR.mkdir(parents=True, exist_ok=True)


def _job_log_path(job_id: str) -> Path:
    return _JOB_LOGS_DIR / f"{job_id}.log"


def _delete_job_files(job_id: str) -> None:
    """Delete all filesystem artifacts for a job.

    Covers:
    - Log file:   _JOB_LOGS_DIR / {job_id}.log
    - Stage dir:  _JOB_LOGS_DIR / {job_id}/
    - Output dir: SHERPA_OUTPUT_DIR / _jobs / {job_id}/
    """
    jid = str(job_id or "").strip()
    if not jid:
        return
    # Guard against accidental traversal: only delete if the leaf name matches
    # the job_id exactly (no ".." or slashes).
    if jid != Path(jid).name or jid in (".", ".."):
        logger.warning("Refusing to delete job files for suspicious job_id: {}", jid)
        return

    _delete_dir_safe(_JOB_LOGS_DIR / jid, f"job stage dir for {jid}")
    _delete_file_safe(_JOB_LOGS_DIR / f"{jid}.log", f"job log for {jid}")

    base = Path(os.environ.get("SHERPA_OUTPUT_DIR", "/shared/output")).expanduser()
    _delete_dir_safe(base / "_jobs" / jid, f"job output dir for {jid}")


def _delete_file_safe(path: Path, label: str) -> None:
    try:
        if path.is_file() or path.is_symlink():
            path.unlink()
            logger.info("Deleted {}: {}", label, path)
    except OSError as exc:
        logger.warning("Failed to delete {} ({}): {}", label, path, exc)


def _delete_dir_safe(path: Path, label: str) -> None:
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=False)
            logger.info("Deleted {}: {}", label, path)
    except OSError as exc:
        logger.warning("Failed to delete {} ({}): {}", label, path, exc)


def _read_log_tail(path: Path, *, max_chars: int) -> str:
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if max_chars > 0:
        return text[-max_chars:]
    return text


def _hydrate_job_log_from_disk(job: dict) -> None:
    if (job.get("log") or "").strip():
        return
    raw = str(job.get("log_file") or "").strip()
    if not raw:
        return
    txt = _read_log_tail(Path(raw), max_chars=max(0, _JOB_RESTORE_LOG_MAX_CHARS))
    if txt:
        job["log"] = txt


def _job_store_database_url() -> str:
    return str(os.environ.get("DATABASE_URL", "") or "").strip()


def _persist_job_state(job: dict) -> None:
    store = _JOB_STORE
    if store is None:
        return
    try:
        store.upsert_job(job)
    except Exception:
        pass


def _restore_jobs_from_store() -> None:
    store = _JOB_STORE
    if store is None:
        return
    restored = store.load_jobs()
    if not restored:
        return

    now = time.time()
    changed_ids: list[str] = []
    for job_id, job in restored.items():
        status = str(job.get("status") or "").strip().lower()
        if status in {"queued", "running", "resuming"}:
            active_step = str(job.get("workflow_active_step") or "").strip().lower()
            last_step = str(job.get("workflow_last_step") or "").strip().lower()
            fallback = "plan" if status == "queued" else "build"
            resume_step_raw = active_step or last_step
            repo_root = str(job.get("workflow_repo_root") or "").strip()
            if not resume_step_raw or not repo_root:
                infer_step, infer_root = _infer_checkpoint_from_log_text(str(job.get("log") or ""))
                if infer_step and not resume_step_raw:
                    resume_step_raw = infer_step
                if infer_root and not repo_root:
                    repo_root = infer_root
            resume_step = _normalize_resume_step(resume_step_raw or fallback)
            job["status"] = "recoverable"
            job["recoverable"] = True
            job["last_interrupted_at"] = now
            job["last_resume_reason"] = "service_restart"
            job["error"] = str(job.get("error") or "").strip() or "job interrupted by service restart"
            if str(job.get("kind") or "") == "fuzz":
                job["resume_from_step"] = resume_step
                if repo_root:
                    job["resume_repo_root"] = repo_root
            job["updated_at"] = now
            changed_ids.append(job_id)
        _hydrate_job_log_from_disk(job)

    with _JOBS_LOCK:
        _JOBS.clear()
        _JOBS.update(restored)

    for job_id in changed_ids:
        job = restored.get(job_id)
        if job is not None:
            _persist_job_state(job)


def _init_job_store() -> None:
    global _JOB_STORE
    db_url = _job_store_database_url()
    if not db_url:
        raise RuntimeError("DATABASE_URL is required (Postgres-only job store)")
    store = PostgresJobStore(db_url)
    store.init_schema()
    _JOB_STORE = store
    _restore_jobs_from_store()


def _classify_log_level(line: str) -> str:
    txt = (line or "").lower()
    if any(k in txt for k in ["traceback", "exception", " fatal", "error", "failed", "cannot find"]):
        return "error"
    if any(k in txt for k in ["warn", "retry", "timeout", "deprecation"]):
        return "warn"
    return "info"


def _classify_log_category(line: str) -> str:
    txt = (line or "").lower()
    if "[wf" in txt:
        return "workflow"
    if "[opencodehelper]" in txt or "opencode" in txt:
        return "opencode"
    if "docker" in txt or "container" in txt:
        return "docker"
    if any(k in txt for k in ["cmake", "clang", "gcc", "linker", "ld:", "build"]):
        return "build"
    if "[task" in txt:
        return "task"
    if "[job" in txt:
        return "job"
    return "general"


_WF_STEP_ENTRY_RE = re.compile(r"\[wf[^\]]*\]\s*->\s*([a-z_]+)")
_WF_STEP_EXIT_RE = re.compile(r"\[wf[^\]]*\]\s*<-\s*([a-z_]+)")
_WF_REPO_ROOT_RE = re.compile(r"\brepo_root=(.+?)(?:\s+dt=|$)")
_WF_METRICS_RE = re.compile(r"\[wf-metrics\]\s*(\{.+)")


def _update_workflow_checkpoint_from_line(job_id: str, line: str) -> None:
    if not line:
        return
    entry = _WF_STEP_ENTRY_RE.search(line)
    if entry:
        step = entry.group(1).strip()
        _job_update(
            job_id,
            workflow_last_step=step,
            workflow_active_step=step,
            workflow_last_step_ts=time.time(),
        )

    exit_m = _WF_STEP_EXIT_RE.search(line)
    if exit_m:
        step = exit_m.group(1).strip()
        _job_update(
            job_id,
            workflow_last_step=step,
            workflow_last_completed_step=step,
            workflow_active_step="",
            workflow_last_step_ts=time.time(),
        )

    repo_m = _WF_REPO_ROOT_RE.search(line)
    if repo_m:
        repo_root = repo_m.group(1).strip()
        if repo_root:
            _job_update(job_id, workflow_repo_root=repo_root)

    # Parse structured per-fuzzer metrics emitted by workflow_graph.py
    metrics_m = _WF_METRICS_RE.search(line)
    if metrics_m:
        try:
            payload = json.loads(metrics_m.group(1))
            _job_update(
                job_id,
                fuzz_metrics=payload,
                fuzz_metrics_ts=payload.get("ts") or time.time(),
                fuzz_fuzzers=payload.get("fuzzers") or {},
                fuzz_max_cov=int(payload.get("max_cov") or 0),
                fuzz_max_ft=int(payload.get("max_ft") or 0),
                fuzz_total_execs_per_sec=int(payload.get("total_execs_per_sec") or 0),
                fuzz_crash_found=bool(payload.get("crash_found")),
                fuzz_coverage_history=payload.get("coverage_history") or [],
                fuzz_coverage_source_report=payload.get("coverage_source_report") or {},
                fuzz_coverage_loop_round=int(payload.get("coverage_loop_round") or 0),
                fuzz_coverage_loop_max_rounds=int(payload.get("coverage_loop_max_rounds") or 0),
                fuzz_coverage_plateau_streak=int(payload.get("coverage_plateau_streak") or 0),
                fuzz_coverage_seed_profile=str(payload.get("coverage_seed_profile") or ""),
                fuzz_coverage_quality_flags=payload.get("coverage_quality_flags") or [],
                fuzz_coverage_bottleneck_kind=str(payload.get("coverage_bottleneck_kind") or ""),
                analysis_evidence_count=int(payload.get("analysis_evidence_count") or 0),
                security_evidence_count=int(payload.get("security_evidence_count") or 0),
                vuln_candidate_count=int(payload.get("vuln_candidate_count") or 0),
                vuln_hunting_enabled=bool(payload.get("vuln_hunting_enabled") or False),
                security_priority_mode=bool(payload.get("security_priority_mode") or False),
                latest_vuln_decision_snapshot=dict(payload.get("latest_vuln_decision_snapshot") or {}),
                target_scoring_enabled=bool(payload.get("target_scoring_enabled") or False),
                target_score_breakdown_available=bool(payload.get("target_score_breakdown_available") or False),
                constraint_memory_count=int(payload.get("constraint_memory_count") or 0),
                decision_trace_count=int(payload.get("decision_trace_count") or 0),
                latest_decision_snapshot=dict(payload.get("latest_decision_snapshot") or {}),
                crash_signature_dedup_hit=bool(payload.get("crash_signature_dedup_hit") or False),
            )
        except Exception:
            pass


def _infer_checkpoint_from_log_text(text: str) -> tuple[str, str]:
    if not text:
        return "", ""
    active_step = ""
    last_step = ""
    repo_root = ""
    for line in text.splitlines():
        m1 = _WF_STEP_ENTRY_RE.search(line)
        if m1:
            step = m1.group(1).strip().lower()
            active_step = step
            last_step = step
        m2 = _WF_STEP_EXIT_RE.search(line)
        if m2:
            step = m2.group(1).strip().lower()
            last_step = step
            active_step = ""
        m3 = _WF_REPO_ROOT_RE.search(line)
        if m3:
            repo_root = m3.group(1).strip()
    step_out = active_step or last_step
    return step_out, repo_root


def _job_update(job_id: str, **fields: object) -> None:
    snapshot: dict | None = None
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job.update(fields)
        job["updated_at"] = time.time()
        snapshot = dict(job)
    if snapshot is not None:
        _persist_job_state(snapshot)


def _job_append_log(job_id: str, chunk: str) -> None:
    if not chunk:
        return
    snapshot: dict | None = None
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        buf = (job.get("log", "") or "") + chunk
        if _JOB_MEMORY_LOG_MAX_CHARS > 0:
            job["log"] = buf[-_JOB_MEMORY_LOG_MAX_CHARS:]
        else:
            job["log"] = buf
        job["updated_at"] = time.time()
        snapshot = dict(job)
    if snapshot is not None:
        _persist_job_state(snapshot)


class _Tee(StringIO):
    def __init__(self, job_id: str, *, log_file: Path | None = None) -> None:
        super().__init__()
        self._job_id = job_id
        self._fh = None
        self._split_fhs: dict[str, object] = {}
        self._base_path: Path | None = None
        if log_file is not None:
            try:
                _ensure_job_logs_dir()
                self._fh = open(log_file, "a", encoding="utf-8")
                self._base_path = log_file.with_suffix("")
            except Exception:
                # Best-effort: if we cannot write to disk, keep in-memory logs working.
                self._fh = None
                self._base_path = None

    def _split_write(self, line: str) -> None:
        if not line or self._base_path is None:
            return
        level = _classify_log_level(line)
        category = _classify_log_category(line)
        targets = [
            f"{self._base_path.name}.level.{level}.log",
            f"{self._base_path.name}.cat.{category}.log",
        ]
        for filename in targets:
            handle = self._split_fhs.get(filename)
            if handle is None:
                try:
                    handle = open(self._base_path.parent / filename, "a", encoding="utf-8")
                    self._split_fhs[filename] = handle
                except Exception:
                    continue
            try:
                handle.write(line)
                handle.flush()
            except Exception:
                pass

    def write(self, s: str) -> int:
        safe = _redact_sensitive_text(s) if s else s
        if self._fh is not None and safe:
            try:
                self._fh.write(safe)
                self._fh.flush()
            except Exception:
                # Do not break the job if disk logging fails mid-run.
                pass
        if safe:
            for line in safe.splitlines(keepends=True):
                self._split_write(line)
                _update_workflow_checkpoint_from_line(self._job_id, line)
        _job_append_log(self._job_id, safe)
        return super().write(safe)

    def close(self) -> None:
        try:
            if self._fh is not None:
                self._fh.close()
            for handle in self._split_fhs.values():
                try:
                    handle.close()
                except Exception:
                    pass
        finally:
            super().close()


class _JobAwareStream:
    def __init__(self, original, *, stream_kind: str) -> None:
        self._original = original
        self._stream_kind = stream_kind

    def _active_tee(self):
        if self._stream_kind == "stdout":
            return _ACTIVE_JOB_STDOUT_TEE.get()
        return _ACTIVE_JOB_STDERR_TEE.get()

    def write(self, s: str) -> int:
        txt = str(s or "")
        tee = self._active_tee()
        if tee is not None and txt:
            try:
                tee.write(txt)
            except Exception:
                pass
        try:
            return int(self._original.write(txt))
        except Exception:
            return len(txt)

    def flush(self) -> None:
        tee = self._active_tee()
        if tee is not None:
            try:
                tee.flush()
            except Exception:
                pass
        try:
            self._original.flush()
        except Exception:
            pass

    def __getattr__(self, name: str):
        return getattr(self._original, name)


if not isinstance(sys.stdout, _JobAwareStream):
    sys.stdout = _JobAwareStream(sys.stdout, stream_kind="stdout")
if not isinstance(sys.stderr, _JobAwareStream):
    sys.stderr = _JobAwareStream(sys.stderr, stream_kind="stderr")


def _iso_time(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _status_for_counter(raw: str | None) -> str:
    s = str(raw or "").strip().lower()
    if s in {"queued"}:
        return "queued"
    if s in {"running", "resuming"}:
        return "running"
    if s in {"success", "resumed"}:
        return "success"
    if s in {"error", "recoverable", "resume_failed"}:
        return "error"
    return "error"


def _status_for_parent(raw: str | None) -> str:
    s = str(raw or "").strip().lower()
    if s in {"queued"}:
        return "queued"
    if s in {"running", "resuming", "recoverable"}:
        return "running"
    if s in {"success", "resumed"}:
        return "success"
    if s in {"error", "resume_failed"}:
        return "error"
    return "error"


def _is_status_terminal(raw: str | None) -> bool:
    s = str(raw or "").strip().lower()
    return s in {"success", "resumed", "error", "resume_failed"}


_RESUMABLE_WORKFLOW_STEPS = {
    "analysis",
    "plan",
    "synthesize",
    "build",
    "run",
    "crash-triage",
    "coverage-analysis",
    "improve-harness",
    "re-build",
    "re-run",
    "crash-analysis",
}
_STAGED_WORKFLOW_STEPS = (
    "analysis",
    "plan",
    "synthesize",
    "build",
    "run",
    "crash-triage",
    "coverage-analysis",
    "improve-harness",
    "re-build",
    "re-run",
    "crash-analysis",
)


def _normalize_resume_step(raw: str | None) -> str:
    s = str(raw or "").strip().lower()
    if s == "stop":
        return "stop"
    if s == "repro_crash":
        return "re-build"
    if s in {"crash_triage", "crash-triage"}:
        return "crash-triage"
    if s in {"fix_harness", "fix-harness"}:
        return "plan"
    if s in {"crash_analysis", "crash-analysis"}:
        return "crash-analysis"
    if s in _RESUMABLE_WORKFLOW_STEPS:
        return s
    return "analysis"


def _staged_sequence_from(raw_start: str | None) -> list[str]:
    start = _normalize_resume_step(raw_start)
    try:
        idx = _STAGED_WORKFLOW_STEPS.index(start)
    except ValueError:
        idx = 0
    return list(_STAGED_WORKFLOW_STEPS[idx:])


def _legacy_error_code_for_job(job: dict | None) -> str:
    if not isinstance(job, dict):
        return ""
    direct = str(job.get("error_code") or "").strip()
    if direct:
        return direct
    resume = str(job.get("resume_error_code") or "").strip()
    if resume:
        return resume
    result = job.get("result")
    if isinstance(result, dict):
        for key in (
            "run_terminal_reason",
            "build_error_code",
            "run_error_kind",
            "build_error_kind",
            "error_code",
        ):
            val = str(result.get(key) or "").strip()
            if val:
                return val
    status = str(job.get("status") or "").strip().lower()
    if status in {"error", "resume_failed", "recoverable"}:
        return "unknown_error"
    return ""


def _legacy_error_kind_for_job(job: dict | None) -> str:
    if not isinstance(job, dict):
        return ""
    result = job.get("result")
    if isinstance(result, dict):
        for key in ("run_error_kind", "build_error_kind", "error_kind"):
            val = str(result.get(key) or "").strip()
            if val:
                return val
    status = str(job.get("status") or "").strip().lower()
    if status in {"error", "resume_failed", "recoverable"}:
        return "unknown"
    return ""


def _legacy_error_signature_for_job(job: dict | None) -> str:
    if not isinstance(job, dict):
        return ""
    result = job.get("result")
    if isinstance(result, dict):
        for key in (
            "build_error_signature_short",
            "build_error_signature",
            "timeout_signature",
            "crash_signature",
            "error_signature",
        ):
            val = str(result.get(key) or "").strip()
            if val:
                return val
    return ""


def _coerce_error_object(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        return {}
    stage = str(raw.get("stage") or "").strip().lower()
    kind = str(raw.get("kind") or "").strip().lower()
    code = str(raw.get("code") or "").strip().lower()
    message = str(raw.get("message") or "").strip()
    detail = str(raw.get("detail") or "").strip()
    signature = str(raw.get("signature") or "").strip()
    retryable = bool(raw.get("retryable"))
    terminal = bool(raw.get("terminal"))
    at = int(_safe_float(raw.get("at")) or 0)
    if not (code or message or signature or terminal):
        return {}
    if at <= 0:
        at = int(time.time())
    return {
        "stage": stage,
        "kind": kind,
        "code": code,
        "message": message,
        "detail": detail,
        "signature": signature,
        "retryable": retryable,
        "terminal": terminal,
        "at": at,
    }


def _error_object_for_job(job: dict | None) -> dict[str, object]:
    if not isinstance(job, dict):
        return {}
    result = job.get("result")
    result_dict = result if isinstance(result, dict) else {}
    for source in (job.get("error"), result_dict.get("error")):
        normalized = _coerce_error_object(source)
        if normalized:
            return normalized

    code = _legacy_error_code_for_job(job)
    kind = _legacy_error_kind_for_job(job)
    signature = _legacy_error_signature_for_job(job)
    message = str(
        job.get("last_error")
        or result_dict.get("last_error")
        or job.get("error")
        or ""
    ).strip()
    stage = str(
        job.get("workflow_active_step")
        or job.get("workflow_last_step")
        or result_dict.get("last_step")

        or ""
    ).strip().lower()
    terminal = bool(result_dict.get("failed")) or str(job.get("status") or "").strip().lower() in {
        "error",
        "resume_failed",
        "recoverable",
    }
    retryable = bool(code) and not terminal
    if not (code or kind or signature or message or terminal):
        return {}
    if not kind and code:
        if code.startswith("run_"):
            kind = "run"
        elif code.startswith("build_") or "build" in code:
            kind = "build"
        elif "crash" in code:
            kind = "crash"
        elif "timeout" in code:
            kind = "timeout"
        else:
            kind = "generic_failure"
    return {
        "stage": stage,
        "kind": kind,
        "code": code,
        "message": message,
        "detail": message,
        "signature": signature,
        "retryable": retryable,
        "terminal": terminal,
        "at": int(_safe_float(job.get("updated_at")) or _safe_float(job.get("finished_at")) or time.time()),
    }


def _error_code_for_job(job: dict | None) -> str:
    return str(_error_object_for_job(job).get("code") or "")


def _error_kind_for_job(job: dict | None) -> str:
    return str(_error_object_for_job(job).get("kind") or "")


def _error_signature_for_job(job: dict | None) -> str:
    return str(_error_object_for_job(job).get("signature") or "")


def _runtime_mode_for_job(job: dict | None) -> str:
    if isinstance(job, dict):
        v = str(job.get("runtime_mode") or "").strip().lower()
        if v in {"docker"}:
            return v
    return "docker"


def _phase_for_job(job: dict | None) -> str:
    if not isinstance(job, dict):
        return "unknown"
    for key in ("workflow_active_step", "workflow_last_step"):
        val = str(job.get(key) or "").strip()
        if val:
            return val
    status = str(job.get("status") or "").strip()
    return status or "unknown"


def _status_upper(status: str) -> str:
    lowered = str(status or "").strip().lower()
    mapping = {
        "queued": "QUEUED",
        "running": "RUNNING",
        "resuming": "RUNNING",
        "recoverable": "FAILED",
        "resume_failed": "FAILED",
        "success": "SUCCESS",
        "resumed": "COMPLETED",
        "error": "ERROR",
    }
    return mapping.get(lowered, (str(status or "").strip().upper() or "UNKNOWN"))


def _task_display_repo(job: dict | None) -> str | None:
    if not isinstance(job, dict):
        return None
    repo = str(job.get("repo") or "").strip()
    if repo and repo.lower() != "batch":
        return repo
    request = job.get("request") if isinstance(job.get("request"), dict) else {}
    jobs = request.get("jobs") if isinstance(request, dict) else []
    if isinstance(jobs, list):
        repos: list[str] = []
        for item in jobs:
            if not isinstance(item, dict):
                continue
            code_url = str(item.get("code_url") or "").strip()
            if code_url:
                parsed = urlparse(code_url)
                path = str(parsed.path or "").rstrip("/")
                slug = path.rsplit("/", 1)[-1] if path else ""
                if slug.endswith(".git"):
                    slug = slug[:-4]
                repos.append(slug or code_url)
        if repos:
            if len(set(repos)) == 1:
                return repos[0]
            return f"{repos[0]} (+{len(repos) - 1} more)"
    return repo or None


def _task_progress_from_children(derived_status: str, children_status: dict[str, int]) -> int:
    total = int(children_status.get("total") or 0)
    if total <= 0:
        return 100 if derived_status in {"success"} else 0
    success = int(children_status.get("success") or 0)
    error = int(children_status.get("error") or 0)
    done = max(0, min(total, success + error))
    pct = int(round((float(done) / float(total)) * 100.0))
    if derived_status in {"running", "queued"}:
        return max(0, min(99, pct))
    return max(0, min(100, pct if pct > 0 else (100 if derived_status == "success" else 0)))


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for child in path.glob("**/*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except Exception:
                continue
    return total


def _safe_float(raw: object) -> float | None:
    try:
        if raw is None:
            return None
        v = float(raw)
        if math.isfinite(v):
            return v
    except (ValueError, TypeError):
        return None
    return None


def _status_bucket(raw: str | None) -> str:
    return _status_for_counter(raw)


def _job_duration_seconds(job: dict) -> float | None:
    start = _safe_float(job.get("started_at"))
    end = _safe_float(job.get("finished_at"))
    if start is None or end is None:
        return None
    dur = end - start
    if dur < 0:
        return None
    return dur


def _format_duration_human(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    sec = max(0, int(round(seconds)))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h > 0:
        return f"{h}h {m}m"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def _format_percent(value: float | None, digits: int = 1) -> str | None:
    if value is None:
        return None
    return f"{value:.{digits}f}"


def _format_trend(current: float | None, previous: float | None, *, unit_suffix: str = "%") -> str | None:
    if current is None or previous is None:
        return None
    delta = current - previous
    arrow = "▲" if delta >= 0 else "▼"
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.1f}{unit_suffix} {arrow}"


def _extract_numeric_values_by_keys(obj: object, keys: set[str], *, max_count: int = 128) -> list[float]:
    out: list[float] = []
    stack: list[object] = [obj]
    while stack and len(out) < max_count:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if str(k) in keys:
                    fv = _safe_float(v)
                    if fv is not None:
                        out.append(fv)
                        if len(out) >= max_count:
                            break
                if isinstance(v, (dict, list, tuple)):
                    stack.append(v)
        elif isinstance(cur, (list, tuple)):
            for v in cur:
                if isinstance(v, (dict, list, tuple)):
                    stack.append(v)
    return out


def _count_jobs_in_window(jobs: list[dict], *, field: str, window_start: float, window_end: float) -> int:
    n = 0
    for job in jobs:
        ts = _safe_float(job.get(field))
        if ts is None:
            continue
        if window_start <= ts < window_end:
            n += 1
    return n


def _performance_series_from_jobs(now: float, fuzz_jobs: list[dict]) -> list[dict[str, object]]:
    points: list[dict[str, object]] = []
    # 6 x 4h windows over last 24h + current point.
    windows = [24, 20, 16, 12, 8, 4, 0]
    for h in windows:
        end_ts = now - float(h * 3600)
        start_ts = end_ts - float(4 * 3600)
        started = _count_jobs_in_window(
            fuzz_jobs, field="started_at", window_start=start_ts, window_end=end_ts
        )
        finished = [
            job for job in fuzz_jobs
            if (ts := _safe_float(job.get("finished_at"))) is not None and start_ts <= ts < end_ts
        ]
        durations = [d for d in (_job_duration_seconds(job) for job in finished) if d is not None]
        avg_latency = (sum(durations) / float(len(durations))) if durations else None
        points.append(
            {
                "time": datetime.fromtimestamp(end_ts, tz=timezone.utc).strftime("%H:%M"),
                "throughput": started,
                "latency": round(avg_latency, 2) if avg_latency is not None else None,
            }
        )
    return points


_RUN_EXEC_RATE_RE = re.compile(
    r"(?:stat::(?:average_)?execs?_per_sec|exec/s)\s*[:=]\s*(?P<value>\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _extract_execs_per_sec_from_text(text: str) -> float | None:
    if not text:
        return None
    latest: float | None = None
    for line in text.splitlines():
        m = _RUN_EXEC_RATE_RE.search(line)
        if not m:
            continue
        try:
            latest = float(m.group("value"))
        except Exception:
            continue
    if latest is None or latest <= 0:
        return None
    return latest


def _job_execs_per_sec(job: dict) -> float | None:
    result = job.get("result")
    if isinstance(result, dict):
        values = _extract_numeric_values_by_keys(
            result,
            {
                "final_execs_per_sec",
                "execs_per_sec",
                "average_exec_per_sec",
            },
            max_count=64,
        )
        positive_values = [float(v) for v in values if float(v) > 0]
        if positive_values:
            return sum(positive_values)
    text = str(job.get("log") or "")
    if not text:
        log_file = str(job.get("log_file") or "").strip()
        if log_file:
            text = _read_log_tail(Path(log_file), max_chars=65536)
    return _extract_execs_per_sec_from_text(text)

def _collect_exec_rates_for_system(fuzz_jobs: list[dict], now: float) -> list[float]:
    rates: list[float] = []

    # Always prefer currently running fuzz jobs when real run metrics are present.
    for j in fuzz_jobs:
        if _status_bucket(str(j.get("status") or "")) != "running":
            continue
        rate = _job_execs_per_sec(j)
        if rate is not None and rate > 0:
            rates.append(rate)
    if rates:
        return rates

    # If no running metrics are available, fall back to recent successful jobs
    # with progressively wider windows. Keep this real-data-only (no estimation).
    for window_sec in (300.0, 3600.0, 21600.0, 86400.0):
        cutoff = now - window_sec
        window_rates: list[float] = []
        for j in fuzz_jobs:
            if _status_bucket(str(j.get("status") or "")) != "success":
                continue
            finished_at = _safe_float(j.get("finished_at"))
            if finished_at is None or finished_at < cutoff:
                continue
            rate = _job_execs_per_sec(j)
            if rate is not None and rate > 0:
                window_rates.append(rate)
        if window_rates:
            return window_rates

    return rates
def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    seq = sorted(values)
    if len(seq) == 1:
        return seq[0]
    q_clamped = max(0.0, min(1.0, q))
    pos = q_clamped * float(len(seq) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return seq[lo]
    frac = pos - float(lo)
    return seq[lo] + (seq[hi] - seq[lo]) * frac


def _http_metrics_snapshot(*, now: float, window_sec: float = 300.0) -> dict[str, float | int | None]:
    cutoff = now - float(max(30.0, window_sec * 2.0))
    with _HTTP_METRICS_LOCK:
        while _HTTP_REQUEST_EVENTS and _HTTP_REQUEST_EVENTS[0][0] < cutoff:
            _HTTP_REQUEST_EVENTS.popleft()
        events = list(_HTTP_REQUEST_EVENTS)

    current_start = now - window_sec
    prev_start = now - (window_sec * 2.0)
    current = [e for e in events if current_start <= e[0] < now]
    previous = [e for e in events if prev_start <= e[0] < current_start]
    current_lat = [float(e[1]) for e in current]
    current_errors = sum(1 for e in current if int(e[2]) >= 500)
    previous_errors = sum(1 for e in previous if int(e[2]) >= 500)

    current_qps = (float(len(current)) / window_sec) if window_sec > 0 else None
    previous_qps = (float(len(previous)) / window_sec) if window_sec > 0 else None
    current_err_ratio = (float(current_errors) / float(len(current)) * 100.0) if current else 0.0
    previous_err_ratio = (float(previous_errors) / float(len(previous)) * 100.0) if previous else 0.0
    return {
        "qps": current_qps,
        "qps_prev": previous_qps,
        "lat_p95_ms": _percentile(current_lat, 0.95),
        "error_ratio_pct": current_err_ratio,
        "error_ratio_prev_pct": previous_err_ratio,
        "request_count": len(current),
    }


def _format_tokens_per_hour(tokens_per_hour: float | None) -> str | None:
    if tokens_per_hour is None:
        return None
    v = max(0.0, tokens_per_hour)
    if v >= 1_000_000.0:
        return f"{v / 1_000_000.0:.2f}M / hr"
    if v >= 1_000.0:
        return f"{v / 1_000.0:.1f}K / hr"
    return f"{int(round(v))} / hr"


def _job_token_estimate(job: dict) -> float | None:
    result = job.get("result")
    totals = _extract_numeric_values_by_keys(result, {"total_tokens"}, max_count=16)
    if totals:
        return max(0.0, max(totals))
    prompts = _extract_numeric_values_by_keys(result, {"prompt_tokens", "input_tokens"}, max_count=16)
    completions = _extract_numeric_values_by_keys(result, {"completion_tokens", "output_tokens"}, max_count=16)
    if prompts or completions:
        return max(0.0, (max(prompts) if prompts else 0.0) + (max(completions) if completions else 0.0))
    return None


def _extract_coverage_values(obj: object, *, max_count: int = 256) -> list[float]:
    keys = {
        "final_cov",
        "max_cov",
        "coverage",
        "cov",
        "coverage_percent",
        "line_coverage",
        "function_coverage",
        "branch_coverage",
    }
    raw_vals = _extract_numeric_values_by_keys(obj, keys, max_count=max_count)
    out: list[float] = []
    for value in raw_vals:
        if value < 0:
            continue
        if value <= 1.0:
            out.append(value * 100.0)
            continue
        if value <= 100.0:
            out.append(value)
    return out


def _system_status() -> dict:
    now = time.time()
    with _JOBS_LOCK:
        jobs = list(_JOBS.values())
    bucketed = [_status_for_counter(str(j.get("status") or "")) for j in jobs]
    counts = {
        "total": len(jobs),
        "queued": sum(1 for b in bucketed if b == "queued"),
        "running": sum(1 for b in bucketed if b == "running"),
        "success": sum(1 for b in bucketed if b == "success"),
        "error": sum(1 for b in bucketed if b == "error"),
    }
    counts_by_kind: dict[str, int] = {}
    for j in jobs:
        k = str(j.get("kind") or "unknown")
        counts_by_kind[k] = counts_by_kind.get(k, 0) + 1
    active = [
        {
            "job_id": j.get("job_id"),
            "status": j.get("status"),
            "repo": j.get("repo"),
            "updated_at": j.get("updated_at"),
            "kind": j.get("kind"),
        }
        for j in jobs
        if _status_for_counter(str(j.get("status") or "")) in {"queued", "running"}
    ]
    cfg = _cfg_get()
    log_dir = _JOB_LOGS_DIR
    memory = _memory_status()
    fuzz_jobs = [j for j in jobs if str(j.get("kind") or "") == "fuzz"]
    task_jobs = [j for j in jobs if str(j.get("kind") or "") == "task"]

    def _status_counts(rows: list[dict]) -> dict[str, int]:
        return {
            "total": len(rows),
            "queued": sum(1 for j in rows if _status_bucket(str(j.get("status") or "")) == "queued"),
            "running": sum(1 for j in rows if _status_bucket(str(j.get("status") or "")) == "running"),
            "success": sum(1 for j in rows if _status_bucket(str(j.get("status") or "")) == "success"),
            "error": sum(1 for j in rows if _status_bucket(str(j.get("status") or "")) == "error"),
        }

    task_counts = _status_counts(task_jobs)
    fuzz_counts = _status_counts(fuzz_jobs)

    finished_fuzz = [j for j in fuzz_jobs if _status_bucket(str(j.get("status") or "")) in {"success", "error"}]
    success_fuzz = [j for j in finished_fuzz if _status_bucket(str(j.get("status") or "")) == "success"]
    error_fuzz = [j for j in finished_fuzz if _status_bucket(str(j.get("status") or "")) == "error"]
    finished_total = len(finished_fuzz)
    success_rate = (float(len(success_fuzz)) / float(finished_total) * 100.0) if finished_total > 0 else None
    failure_rate = (float(len(error_fuzz)) / float(finished_total) * 100.0) if finished_total > 0 else None

    durations = [d for d in (_job_duration_seconds(j) for j in finished_fuzz) if d is not None]
    avg_fuzz_seconds = (sum(durations) / float(len(durations))) if durations else None

    window_sec = 3600.0
    curr_start = now - window_sec
    prev_start = now - (2.0 * window_sec)
    current_finished = [
        j for j in finished_fuzz
        if (ts := _safe_float(j.get("finished_at"))) is not None and curr_start <= ts < now
    ]
    previous_finished = [
        j for j in finished_fuzz
        if (ts := _safe_float(j.get("finished_at"))) is not None and prev_start <= ts < curr_start
    ]
    current_failure_rate = (
        float(sum(1 for j in current_finished if _status_bucket(str(j.get("status") or "")) == "error"))
        / float(len(current_finished))
        * 100.0
    ) if current_finished else None
    previous_failure_rate = (
        float(sum(1 for j in previous_finished if _status_bucket(str(j.get("status") or "")) == "error"))
        / float(len(previous_finished))
        * 100.0
    ) if previous_finished else None
    current_health = (100.0 - current_failure_rate) if current_failure_rate is not None else None
    previous_health = (100.0 - previous_failure_rate) if previous_failure_rate is not None else None

    current_errors = sum(
        1
        for j in error_fuzz
        if (ts := _safe_float(j.get("finished_at"))) is not None and curr_start <= ts < now
    )
    previous_errors = sum(
        1
        for j in error_fuzz
        if (ts := _safe_float(j.get("finished_at"))) is not None and prev_start <= ts < curr_start
    )

    now_24h = now - 86400.0
    success_24h = sum(
        1
        for j in success_fuzz
        if (ts := _safe_float(j.get("finished_at"))) is not None and ts >= now_24h
    )
    previous_success_24h = sum(
        1
        for j in success_fuzz
        if (ts := _safe_float(j.get("finished_at"))) is not None and (now_24h - 86400.0) <= ts < now_24h
    )

    coverage_values: list[float] = []
    for j in fuzz_jobs:
        coverage_values.extend(_extract_coverage_values(j.get("result"), max_count=24))
    avg_coverage = (sum(coverage_values) / float(len(coverage_values))) if coverage_values else None

    running_fuzz = sum(1 for j in fuzz_jobs if _status_bucket(str(j.get("status") or "")) == "running")

    cgroup_ratio = _safe_float(memory.get("cgroup_usage_ratio"))
    cluster_load_pct = (max(0.0, min(100.0, cgroup_ratio * 100.0)) if cgroup_ratio is not None else None)
    http_metrics = _http_metrics_snapshot(now=now, window_sec=300.0)
    http_error_ratio = _safe_float(http_metrics.get("error_ratio_pct"))
    http_error_ratio_prev = _safe_float(http_metrics.get("error_ratio_prev_pct"))
    http_qps = _safe_float(http_metrics.get("qps"))
    http_p95 = _safe_float(http_metrics.get("lat_p95_ms"))

    performance_series = _performance_series_from_jobs(now, fuzz_jobs)
    recent_exec_rates = _collect_exec_rates_for_system(fuzz_jobs, now)
    recent_jobs_per_sec = (sum(recent_exec_rates) / 1000.0) if recent_exec_rates else None

    token_window_sec = 3600.0
    token_cutoff = now - token_window_sec
    token_sum = 0.0
    token_count = 0
    for j in fuzz_jobs:
        ts = _safe_float(j.get("updated_at")) or _safe_float(j.get("finished_at")) or _safe_float(j.get("created_at"))
        if ts is None or ts < token_cutoff:
            continue
        est = _job_token_estimate(j)
        if est is None:
            continue
        token_sum += est
        token_count += 1
    tokens_per_hour = (token_sum / (token_window_sec / 3600.0)) if token_count > 0 else None

    agent_health_matrix: list[int] = []
    latest_fuzz = sorted(
        fuzz_jobs,
        key=lambda j: float(_safe_float(j.get("updated_at")) or 0.0),
        reverse=True,
    )[:32]
    for j in latest_fuzz:
        agent_health_matrix.append(0 if _status_bucket(str(j.get("status") or "")) == "error" else 1)

    signal_points: list[float] = []
    if current_health is not None:
        signal_points.append(current_health)
    if cluster_load_pct is not None:
        signal_points.append(max(0.0, 100.0 - cluster_load_pct))
    if http_error_ratio is not None:
        signal_points.append(max(0.0, 100.0 - http_error_ratio))
    composite_health = (sum(signal_points) / float(len(signal_points))) if signal_points else None
    previous_signal_points: list[float] = []
    if previous_health is not None:
        previous_signal_points.append(previous_health)
    if cluster_load_pct is not None:
        previous_signal_points.append(max(0.0, 100.0 - cluster_load_pct))
    if http_error_ratio_prev is not None:
        previous_signal_points.append(max(0.0, 100.0 - http_error_ratio_prev))
    composite_health_prev = (
        (sum(previous_signal_points) / float(len(previous_signal_points))) if previous_signal_points else None
    )

    gateway_sli = None
    if http_error_ratio is not None:
        gateway_sli = max(0.0, min(100.0, 100.0 - http_error_ratio))
    fastapi_status = "UP"
    if http_error_ratio is not None and http_error_ratio >= 5.0:
        fastapi_status = "DEGRADED"
    if http_error_ratio is not None and http_error_ratio >= 20.0:
        fastapi_status = "ERROR"

    overview = {
        "avg_fuzz_time": _format_duration_human(avg_fuzz_seconds),
        "active_agents": str(running_fuzz),
        "cluster_health": _format_percent(composite_health, 1),
        "cluster_health_trend": _format_trend(composite_health, composite_health_prev, unit_suffix="%"),
        "crash_triage_rate": str(current_errors),
        "crash_triage_rate_trend": _format_trend(float(current_errors), float(previous_errors), unit_suffix=""),
        "harnesses_synthesized": str(success_24h),
        "harnesses_synthesized_trend": _format_trend(float(success_24h), float(previous_success_24h), unit_suffix=""),
        "avg_coverage": _format_percent(avg_coverage, 2),
        "avg_coverage_trend": None,
        "main_tasks_running": str(task_counts["running"]),
        "main_tasks_queued": str(task_counts["queued"]),
        "child_jobs_running": str(fuzz_counts["running"]),
        "child_jobs_queued": str(fuzz_counts["queued"]),
    }
    telemetry = {
        "llm_token_usage": _format_tokens_per_hour(tokens_per_hour),
        "llm_token_status": ("Active" if token_count > 0 else "--"),
        "fastapi_gateway": (f"{gateway_sli:.2f}% SLI" if gateway_sli is not None else None),
        "fastapi_status": fastapi_status,
        "agent_health_matrix": agent_health_matrix,
        "performance_series": performance_series,
    }
    execution_summary = {
        "failure_rate": (f"{failure_rate:.2f}%" if failure_rate is not None else None),
        "fuzzing_jobs_24h": str(
            sum(
                1
                for j in fuzz_jobs
                if (ts := _safe_float(j.get("created_at"))) is not None and ts >= now_24h
            )
        ),
        "cluster_load_peak": (f"{cluster_load_pct:.0f}%" if cluster_load_pct is not None else None),
        "repos_queued": str(task_counts["queued"]),
        "avg_triage_time_ms": None,
        "success_ratio": (f"{success_rate:.2f}" if success_rate is not None else None),
        "main_tasks_running": str(task_counts["running"]),
        "main_tasks_queued": str(task_counts["queued"]),
        "child_jobs_running": str(fuzz_counts["running"]),
        "child_jobs_queued": str(fuzz_counts["queued"]),
    }
    task_finished = [
        j for j in task_jobs
        if _status_bucket(str(j.get("status") or "")) in {"success", "error"}
    ]
    task_success = sum(1 for j in task_finished if _status_bucket(str(j.get("status") or "")) == "success")
    task_success_rate = (
        float(task_success) / float(len(task_finished)) * 100.0 if task_finished else None
    )
    task_failed = sum(1 for j in task_jobs if _status_bucket(str(j.get("status") or "")) == "error")
    tasks_tab_metrics = {
        "total_jobs": str(len(task_jobs)),
        "execs_per_sec": (f"{recent_jobs_per_sec:.1f}" if recent_jobs_per_sec is not None else None),
        "success_rate": (f"{task_success_rate:.1f}" if task_success_rate is not None else None),
        "failed_tasks": str(task_failed),
    }
    return {
        "ok": True,
        "server_time": now,
        "server_time_iso": _iso_time(now),
        "uptime_sec": now - _APP_START,
        "jobs": counts,
        "jobs_by_kind": counts_by_kind,
        "workers": {
            "max": _MAX_WORKERS,
        },
        "active_jobs": active[:8],
        "logs": {
            "dir": str(log_dir),
            "exists": log_dir.exists(),
            "size_bytes": _dir_size(log_dir),
        },
        "memory": memory,
        "config": {
            "runtime_mode": "docker",
            "openai_base_url": cfg.openai_base_url,
            "openai_api_key_set": bool(cfg.openai_api_key),
            "openrouter_model": cfg.openrouter_model,
        },
        "overview": overview,
        "telemetry": telemetry,
        "execution": {"summary": execution_summary},
        "tasks_tab_metrics": tasks_tab_metrics,
    }


def _metrics_payload() -> str:
    now = time.time()
    window_sec = max(60, int(os.environ.get("SHERPA_METRICS_FAILURE_WINDOW_SEC", "3600")))
    cutoff = now - float(window_sec)
    with _JOBS_LOCK:
        jobs = [dict(j) for j in _JOBS.values()]

    bucketed = [_status_for_counter(str(j.get("status") or "")) for j in jobs]
    status_counts = {
        "queued": sum(1 for b in bucketed if b == "queued"),
        "running": sum(1 for b in bucketed if b == "running"),
        "success": sum(1 for b in bucketed if b == "success"),
        "error": sum(1 for b in bucketed if b == "error"),
    }
    recoverable = sum(1 for j in jobs if str(j.get("status") or "").strip().lower() == "recoverable")

    finished_in_window = []
    for j in jobs:
        ts_raw = j.get("finished_at")
        try:
            ts = float(ts_raw)
        except Exception:
            continue
        if ts >= cutoff:
            finished_in_window.append(j)

    failed_in_window = [
        j
        for j in finished_in_window
        if _status_for_counter(str(j.get("status") or "")) == "error"
    ]
    finished_total = len(finished_in_window)
    failed_total = len(failed_in_window)
    failure_rate = (failed_total / finished_total) if finished_total > 0 else 0.0
    memory = _memory_status()

    lines = [
        "# HELP sherpa_jobs_total Total jobs in memory.",
        "# TYPE sherpa_jobs_total gauge",
        f"sherpa_jobs_total {len(jobs)}",
        "# HELP sherpa_jobs_status Jobs by status bucket.",
        "# TYPE sherpa_jobs_status gauge",
        f'sherpa_jobs_status{{status="queued"}} {status_counts["queued"]}',
        f'sherpa_jobs_status{{status="running"}} {status_counts["running"]}',
        f'sherpa_jobs_status{{status="success"}} {status_counts["success"]}',
        f'sherpa_jobs_status{{status="error"}} {status_counts["error"]}',
        "# HELP sherpa_jobs_recoverable_total Recoverable jobs.",
        "# TYPE sherpa_jobs_recoverable_total gauge",
        f"sherpa_jobs_recoverable_total {recoverable}",
        f"# HELP sherpa_jobs_finished_window_total Jobs finished in last {window_sec} seconds.",
        "# TYPE sherpa_jobs_finished_window_total gauge",
        f"sherpa_jobs_finished_window_total {finished_total}",
        f"# HELP sherpa_jobs_failed_window_total Failed jobs finished in last {window_sec} seconds.",
        "# TYPE sherpa_jobs_failed_window_total gauge",
        f"sherpa_jobs_failed_window_total {failed_total}",
        f"# HELP sherpa_jobs_failure_rate_window Failure rate in last {window_sec} seconds.",
        "# TYPE sherpa_jobs_failure_rate_window gauge",
        f"sherpa_jobs_failure_rate_window {failure_rate:.6f}",
    ]
    rss_bytes = memory.get("process_rss_bytes")
    if isinstance(rss_bytes, int):
        lines.extend(
            [
                "# HELP sherpa_process_resident_memory_bytes Resident memory size of the web process.",
                "# TYPE sherpa_process_resident_memory_bytes gauge",
                f"sherpa_process_resident_memory_bytes {rss_bytes}",
            ]
        )
    cgroup_current = memory.get("cgroup_current_bytes")
    if isinstance(cgroup_current, int):
        lines.extend(
            [
                "# HELP sherpa_cgroup_memory_current_bytes Current cgroup memory usage.",
                "# TYPE sherpa_cgroup_memory_current_bytes gauge",
                f"sherpa_cgroup_memory_current_bytes {cgroup_current}",
            ]
        )
    cgroup_limit = memory.get("cgroup_limit_bytes")
    if isinstance(cgroup_limit, int):
        lines.extend(
            [
                "# HELP sherpa_cgroup_memory_limit_bytes Effective cgroup memory limit.",
                "# TYPE sherpa_cgroup_memory_limit_bytes gauge",
                f"sherpa_cgroup_memory_limit_bytes {cgroup_limit}",
            ]
        )
    usage_ratio = memory.get("cgroup_usage_ratio")
    if isinstance(usage_ratio, (int, float)):
        lines.extend(
            [
                "# HELP sherpa_cgroup_memory_usage_ratio Current cgroup memory usage divided by limit.",
                "# TYPE sherpa_cgroup_memory_usage_ratio gauge",
                f"sherpa_cgroup_memory_usage_ratio {usage_ratio:.6f}",
            ]
        )
    oom_kill_count = memory.get("oom_kill_count")
    if isinstance(oom_kill_count, int):
        lines.extend(
            [
                "# HELP sherpa_cgroup_memory_oom_kill_total Total OOM kills reported by the current cgroup.",
                "# TYPE sherpa_cgroup_memory_oom_kill_total gauge",
                f"sherpa_cgroup_memory_oom_kill_total {oom_kill_count}",
            ]
        )
    return "\n".join(lines) + "\n"

class fuzz_model(BaseModel):
    code_url: str
    email: str | None = None
    model: str | None = None
    temperature: float = 0.5
    timeout: int = 10
    max_tokens: int = 0
    time_budget: int | None = None
    total_time_budget: int | None = None
    run_time_budget: int | None = None
    # Frontend-local compatibility fields
    total_duration: int | None = None
    single_duration: int | None = None
    unlimited_round_limit: int | None = None
    docker: bool | None = None
    docker_image: str | None = None


class task_model(BaseModel):
    jobs: list[fuzz_model]
    auto_init: bool = True
    build_images: bool = True
    images: list[str] | None = None
    force_build: bool = False
    oss_fuzz_repo_url: str | None = None
    force_clone: bool = False


class provider_models_request(BaseModel):
    api_key: str | None = None
    base_url: str | None = None


def _resolve_job_docker_policy(request: fuzz_model, cfg: WebPersistentConfig) -> tuple[bool, str]:
    docker_enabled = request.docker if request.docker is not None else cfg.fuzz_use_docker
    docker_image_value = (
        (request.docker_image or "").strip()
        or (cfg.fuzz_docker_image or "").strip()
        or "auto"
    )
    return bool(docker_enabled), docker_image_value


def _normalize_budget_value(raw: int | None, *, field_name: str) -> int:
    if raw is None:
        raise RuntimeError(f"{field_name} is required")
    value = int(raw)
    if value == -1:
        return 0
    if value < 0:
        raise RuntimeError(f"{field_name} must be >= 0 or -1 for unlimited")
    return value


def _normalize_round_limit_value(raw: int | None, *, fallback: int) -> int:
    if raw is None:
        value = int(fallback)
    else:
        value = int(raw)
    if value == -1:
        return 0
    if value < 0:
        raise RuntimeError("unlimited_round_limit must be >= 0 or -1 for unlimited")
    return value


def _enforce_docker_only(jobs: list[fuzz_model], cfg: WebPersistentConfig) -> None:
    # Native runtime baseline: keep for compatibility hook, no hard enforcement.
    return None


@app.get("/api/config")
def get_config():
    cfg = _cfg_get()
    return as_public_dict(cfg)


@app.get("/api/opencode/providers/{provider}/models")
def get_opencode_provider_models(provider: str):
    cfg = _cfg_get()
    normalized, models, source, warning = list_opencode_provider_models_resolved(provider, cfg)
    if not normalized:
        raise HTTPException(status_code=400, detail="provider is required")
    if not models:
        raise HTTPException(status_code=404, detail=f"unsupported provider: {provider}")
    payload: dict[str, object] = {
        "provider": normalized,
        "models": models,
        "source": source,
    }
    if warning:
        payload["warning"] = warning
    return payload


@app.post("/api/opencode/providers/{provider}/models")
def post_opencode_provider_models(provider: str, request: provider_models_request = Body(...)):
    cfg = _cfg_get()
    normalized, models, source, warning = list_opencode_provider_models_resolved(
        provider,
        cfg,
        api_key_override=request.api_key,
        base_url_override=request.base_url,
    )
    if not normalized:
        raise HTTPException(status_code=400, detail="provider is required")
    if not models:
        raise HTTPException(status_code=404, detail=f"unsupported provider: {provider}")
    payload: dict[str, object] = {
        "provider": normalized,
        "models": models,
        "source": source,
    }
    if warning:
        payload["warning"] = warning
    return payload


@app.put("/api/config")
def put_config(request: dict = Body(...)):
    if not isinstance(request, dict):
        raise HTTPException(status_code=400, detail="config payload must be a JSON object")

    current = _cfg_get()
    payload = current.model_dump()
    lightweight_only_keys = {
        "apiBaseUrl",
        "api_base_url",
        "sherpa_run_plateau_idle_growth_sec",
    }
    request_keys = set(request.keys())
    is_lightweight_update = bool(request_keys) and request_keys.issubset(lightweight_only_keys)

    if is_lightweight_update:
        api_base_url = str(request.get("apiBaseUrl") or request.get("api_base_url") or "").strip()
        payload["api_base_url"] = api_base_url
        if "sherpa_run_plateau_idle_growth_sec" in request:
            payload["sherpa_run_plateau_idle_growth_sec"] = request.get("sherpa_run_plateau_idle_growth_sec")
    else:
        merged = dict(payload)
        for key, value in request.items():
            if key == "apiBaseUrl":
                merged["api_base_url"] = value
            else:
                merged[key] = value
        try:
            validated = WebPersistentConfig(**merged)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"invalid config payload: {exc}") from exc
        payload = validated.model_dump()

    for model_key in ("openai_model", "opencode_model", "openrouter_model"):
        if model_key in request:
            model_val = _normalized_plain_model_value(request.get(model_key))
            if not model_val:
                raise HTTPException(status_code=400, detail=f"{model_key} is invalid")

    candidate = WebPersistentConfig(**payload)
    if int(candidate.fuzz_time_budget) < 0:
        raise HTTPException(
            status_code=400,
            detail="fuzz_time_budget must be >= 0 (0 means unlimited).",
        )
    if int(candidate.sherpa_run_unlimited_round_budget_sec) < 0:
        raise HTTPException(
            status_code=400,
            detail="sherpa_run_unlimited_round_budget_sec must be >= 0 (0 means fully unlimited).",
        )
    plateau_idle = int(candidate.sherpa_run_plateau_idle_growth_sec)
    if plateau_idle < 30 or plateau_idle > 86_400:
        raise HTTPException(
            status_code=400,
            detail="sherpa_run_plateau_idle_growth_sec must be in [30, 86400].",
        )

    # Frontend no longer controls provider/API fields.
    controlled_fields = (
        "openai_api_key",
        "openai_base_url",
        "openai_model",
        "opencode_model",
        "opencode_providers",
        "openrouter_api_key",
        "openrouter_base_url",
        "openrouter_model",
    )
    for key in controlled_fields:
        payload[key] = getattr(current, key)

    # Docker runtime baseline; keep fields for API compatibility only.
    payload["fuzz_use_docker"] = False
    payload["fuzz_docker_image"] = ""
    runtime_cfg = apply_llm_env_source(WebPersistentConfig(**payload))

    # Keep persisted config free of API secrets; runtime values come from environment.
    persisted_cfg = WebPersistentConfig(**runtime_cfg.model_dump())
    persisted_cfg.openai_api_key = None
    persisted_cfg.openrouter_api_key = None
    for item in persisted_cfg.opencode_providers:
        item.api_key = None
        item.clear_api_key = False

    try:
        save_config(persisted_cfg)
        _cfg_set(runtime_cfg)
        apply_config_to_env(runtime_cfg)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"保存配置失败: {exc}") from exc
    return {"ok": True}


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


@app.get("/api/system")
def get_system_status():
    return _system_status()


@app.get("/api/metrics")
def get_metrics():
    return Response(content=_metrics_payload(), media_type="text/plain; version=0.0.4; charset=utf-8")


@app.get("/api/health")
def health_check():
    return {"ok": True}


def _healthz_db_status() -> dict[str, object]:
    db_url = _job_store_database_url()
    if not db_url:
        return {"ok": False, "error": "DATABASE_URL missing"}
    try:
        import psycopg  # type: ignore

        with psycopg.connect(db_url, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": _redact_sensitive_text(str(exc))[:300]}


@app.get("/healthz")
def healthz():
    db = _healthz_db_status()
    return {
        "ok": bool(db.get("ok")),
        "service": "up",
        "db": db,
    }


def _create_job(kind: str, repo: str | None = None) -> str:
    job_id = uuid.uuid4().hex
    now = time.time()
    job_payload: dict | None = None
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "job_id": job_id,
            "kind": kind,
            "status": "queued",
            "repo": repo,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
            "error": None,
            "result": None,
            "log": "",
            "log_file": None,
            "cancel_requested": False,
            "last_cancel_requested_at": None,
            "runtime_mode": "docker",
        }
        job_payload = dict(_JOBS[job_id])
    if job_payload is not None:
        _persist_job_state(job_payload)
    return job_id



def _ensure_docker_image(image: str, dockerfile: Path, *, force: bool) -> None:
    if not force:
        try:
            probe = subprocess.run(
                ["docker", "image", "inspect", image],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                text=True,
            )
            if probe.returncode == 0:
                return
        except FileNotFoundError:
            raise RuntimeError("docker not found in PATH")
        except Exception:
            pass

    if not dockerfile.is_file():
        raise RuntimeError(f"Dockerfile not found: {dockerfile}")

    def _wait_for_docker_daemon() -> None:
        max_wait_s = 45
        deadline = time.time() + max_wait_s
        while True:
            try:
                probe = subprocess.run(
                    ["docker", "info"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    text=True,
                )
                if probe.returncode == 0:
                    return
            except Exception:
                pass
            if time.time() >= deadline:
                raise RuntimeError("docker daemon not ready")
            time.sleep(2)

    def _docker_daemon_unreachable(output: str) -> bool:
        needles = [
            "Cannot connect to the Docker daemon",
            "dial tcp",
            "no such host",
            "Error response from daemon: dial tcp",
        ]
        return any(n in output for n in needles)

    def _buildkit_unavailable(output: str) -> bool:
        needles = [
            "BuildKit is enabled but the buildx component is missing",
            "buildx component is missing or broken",
        ]
        return any(n in output for n in needles)

    def _run_build(cmd: list[str], *, buildkit: str | None = None) -> tuple[int, str]:
        logger.info("[init] " + " ".join(cmd))
        env = os.environ.copy()
        if buildkit is not None:
            env["DOCKER_BUILDKIT"] = buildkit
        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
        )

        output_chunks: list[str] = []
        line_q: queue.Queue[str | None] = queue.Queue()

        def _reader() -> None:
            try:
                if proc.stdout is None:
                    return
                for line in proc.stdout:
                    line_q.put(line)
            finally:
                line_q.put(None)

        th = threading.Thread(target=_reader, daemon=True)
        th.start()

        last_heartbeat = time.monotonic()
        while True:
            try:
                item = line_q.get(timeout=0.2)
            except queue.Empty:
                item = ""

            if item is None:
                break

            if item:
                output_chunks.append(item)
                logger.info(item.rstrip())

            now = time.monotonic()
            if now - last_heartbeat >= 10:
                logger.info("[init] docker build still running...")
                last_heartbeat = now

            if proc.poll() is not None and line_q.empty():
                break

        try:
            th.join(timeout=1)
        except Exception:
            pass

        rc = proc.wait() if proc.poll() is None else int(proc.returncode or 0)
        return rc, "".join(output_chunks)

    build_cmds = [
        ["docker", "build", "--progress=plain", "-t", image, "-f", str(dockerfile), str(_REPO_ROOT)],
        ["docker", "build", "-t", image, "-f", str(dockerfile), str(_REPO_ROOT)],
    ]

    max_attempts = 5
    backoff = 3.0
    last_output = ""
    last_rc = 1

    for attempt in range(1, max_attempts + 1):
        try:
            _wait_for_docker_daemon()
        except Exception:
            if attempt == max_attempts:
                raise
        retry_outer = False
        for cmd in build_cmds:
            rc, output = _run_build(cmd)
            last_rc = rc
            last_output = output
            if rc == 0:
                return
            if "unknown flag: --progress" in output:
                # Try without --progress on older Docker.
                continue
            if _buildkit_unavailable(output):
                logger.info("[init] buildx unavailable; retrying docker build with classic builder (DOCKER_BUILDKIT=0)")
                legacy_cmd = [arg for arg in cmd if not arg.startswith("--progress=")]
                rc2, output2 = _run_build(legacy_cmd, buildkit="0")
                last_rc = rc2
                last_output = output2
                if rc2 == 0:
                    return
                if _docker_daemon_unreachable(output2) and attempt < max_attempts:
                    logger.info(f"[init] docker daemon not ready; retrying in {backoff:.0f}s (attempt {attempt}/{max_attempts})")
                    time.sleep(backoff)
                    backoff *= 2
                    retry_outer = True
                    break
                # Keep trying other build command variants before failing.
                continue
            if _docker_daemon_unreachable(output) and attempt < max_attempts:
                logger.info(f"[init] docker daemon not ready; retrying in {backoff:.0f}s (attempt {attempt}/{max_attempts})")
                time.sleep(backoff)
                backoff *= 2
                retry_outer = True
                break
        if retry_outer:
            continue
        raise RuntimeError(f"docker build failed (rc={last_rc}) for {image}")

    raise RuntimeError(f"docker build failed after retries for {image}. Last output:\n{last_output}")


def _job_snapshot(job_id: str) -> dict | None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        view = dict(job)
    _hydrate_job_log_from_disk(view)
    return view


def _enrich_job_view(view: dict) -> None:
    """Add workflow/resume/cancel tracking fields and fuzz metrics to a job API view."""
    # -- workflow & resume tracking --
    view.setdefault("cancel_requested", False)
    view.setdefault("last_cancel_requested_at", None)
    view.setdefault("workflow_active_step", None)
    view.setdefault("workflow_last_step", None)
    view.setdefault("workflow_last_step_ts", None)
    view.setdefault("parent_id", None)
    view.setdefault("recoverable", None)
    view.setdefault("resume_attempts", 0)
    view.setdefault("resume_error_code", None)
    view.setdefault("resume_from_step", None)
    view.setdefault("last_resume_reason", None)
    view.setdefault("last_resume_requested_at", None)
    view.setdefault("last_resume_started_at", None)
    view.setdefault("last_resume_finished_at", None)
    view.setdefault("last_interrupted_at", None)
    view.setdefault("request", None)
    view.setdefault("analysis_companion_url", "")
    view.setdefault("analysis_companion_ready", False)
    view.setdefault("analysis_companion_active", False)
    view.setdefault("analysis_companion_error", None)
    view.setdefault("analysis_companion_last_error", None)
    view.setdefault("analysis_companion_stopped_at", None)
    view.setdefault("analysis_companion_state", "")
    view.setdefault("analysis_companion_backend", "")
    view.setdefault("analysis_companion_candidate_count", 0)
    view.setdefault("analysis_companion_updated_at", "")
    view.setdefault("analysis_companion_repo_root", "")
    view.setdefault("analysis_companion_status_error", "")
    view.setdefault("analysis_companion_preprocess_path", "")
    view.setdefault("analysis_companion_coverage_hints_path", "")
    view.setdefault("analysis_companion_rag_ok", False)
    view.setdefault("analysis_companion_rag_knowledge_base_path", "")
    view.setdefault("analysis_companion_rag_document_count", 0)
    view.setdefault("analysis_companion_rag_chunk_count", 0)
    view.setdefault("analysis_companion_embedding_provider", "openrouter")
    view.setdefault("analysis_companion_embedding_model", "")
    view.setdefault("analysis_companion_embedding_ok", False)
    view.setdefault("analysis_companion_rag_degraded", False)
    view.setdefault("analysis_companion_rag_degraded_reason", "")
    view.setdefault("analysis_companion_semantic_query_count", 0)
    view.setdefault("analysis_companion_semantic_hit_count", 0)
    view.setdefault("analysis_companion_semantic_hit_rate", 0.0)
    view.setdefault("analysis_companion_cache_hit_rate", 0.0)
    # -- per-fuzzer performance metrics --
    view.setdefault("fuzz_metrics", None)
    view.setdefault("fuzz_metrics_ts", None)
    view.setdefault("fuzz_fuzzers", {})
    view.setdefault("fuzz_max_cov", 0)
    view.setdefault("fuzz_max_ft", 0)
    view.setdefault("fuzz_total_execs_per_sec", 0)
    view.setdefault("fuzz_crash_found", False)
    view.setdefault("fuzz_coverage_history", [])
    view.setdefault("fuzz_coverage_source_report", {})
    view.setdefault("fuzz_coverage_loop_round", 0)
    view.setdefault("fuzz_coverage_loop_max_rounds", 0)
    view.setdefault("fuzz_coverage_plateau_streak", 0)
    view.setdefault("fuzz_coverage_seed_profile", "")
    view.setdefault("fuzz_coverage_quality_flags", [])
    view.setdefault("fuzz_coverage_bottleneck_kind", "")
    view.setdefault("analysis_evidence_count", 0)
    view.setdefault("security_evidence_count", 0)
    view.setdefault("vuln_candidate_count", 0)
    view.setdefault("vuln_hunting_enabled", False)
    view.setdefault("security_priority_mode", False)
    view.setdefault("latest_vuln_decision_snapshot", {})
    view.setdefault("target_scoring_enabled", False)
    view.setdefault("target_score_breakdown_available", False)
    view.setdefault("constraint_memory_count", 0)
    view.setdefault("decision_trace_count", 0)
    view.setdefault("latest_decision_snapshot", {})
    view.setdefault("crash_signature_dedup_hit", False)

    companion_status = _analysis_companion_status_for_job(str(view.get("id") or ""))
    if companion_status:
        view["analysis_companion_state"] = str(companion_status.get("state") or "")
        view["analysis_companion_backend"] = str(companion_status.get("analysis_backend") or "")
        view["analysis_companion_url"] = str(companion_status.get("mcp_url") or view.get("analysis_companion_url") or "")
        view["analysis_companion_ready"] = bool(companion_status.get("mcp_ready"))
        try:
            view["analysis_companion_candidate_count"] = int(companion_status.get("candidate_count") or 0)
        except Exception:
            view["analysis_companion_candidate_count"] = 0
        view["analysis_companion_updated_at"] = str(companion_status.get("updated_at") or "")
        view["analysis_companion_repo_root"] = str(companion_status.get("repo_root") or "")
        view["analysis_companion_status_error"] = str(companion_status.get("error") or "")
        view["analysis_companion_last_error"] = str(
            companion_status.get("last_error")
            or companion_status.get("error")
            or ""
        )
        view["analysis_companion_preprocess_path"] = str(companion_status.get("preprocess_path") or "")
        view["analysis_companion_coverage_hints_path"] = str(companion_status.get("coverage_hints_path") or "")
        view["analysis_companion_rag_ok"] = bool(companion_status.get("rag_ok"))
        view["analysis_companion_rag_knowledge_base_path"] = str(companion_status.get("rag_knowledge_base_path") or "")
        try:
            view["analysis_companion_rag_document_count"] = int(companion_status.get("rag_document_count") or 0)
        except Exception:
            view["analysis_companion_rag_document_count"] = 0
        try:
            view["analysis_companion_rag_chunk_count"] = int(companion_status.get("rag_chunk_count") or 0)
        except Exception:
            view["analysis_companion_rag_chunk_count"] = 0
        view["analysis_companion_embedding_provider"] = str(
            companion_status.get("embedding_provider") or "openrouter"
        )
        view["analysis_companion_embedding_model"] = str(companion_status.get("embedding_model") or "")
        view["analysis_companion_embedding_ok"] = bool(companion_status.get("embedding_ok"))
        view["analysis_companion_rag_degraded"] = bool(companion_status.get("rag_degraded"))
        view["analysis_companion_rag_degraded_reason"] = str(
            companion_status.get("rag_degraded_reason") or ""
        )
        try:
            view["analysis_companion_semantic_query_count"] = int(companion_status.get("semantic_query_count") or 0)
        except Exception:
            view["analysis_companion_semantic_query_count"] = 0
        try:
            view["analysis_companion_semantic_hit_count"] = int(companion_status.get("semantic_hit_count") or 0)
        except Exception:
            view["analysis_companion_semantic_hit_count"] = 0
        try:
            view["analysis_companion_semantic_hit_rate"] = float(companion_status.get("semantic_hit_rate") or 0.0)
        except Exception:
            view["analysis_companion_semantic_hit_rate"] = 0.0
        try:
            view["analysis_companion_cache_hit_rate"] = float(companion_status.get("cache_hit_rate") or 0.0)
        except Exception:
            view["analysis_companion_cache_hit_rate"] = 0.0


def _derive_task_status(job: dict) -> dict:
    children = list(job.get("children") or [])
    if not children:
        view = dict(job)
        err = _error_object_for_job(view)
        view["error"] = err
        view["error_code"] = str(err.get("code") or "")
        view["error_kind"] = str(err.get("kind") or "")
        view["error_signature"] = str(err.get("signature") or "")
        view["phase"] = _phase_for_job(view)
        view["runtime_mode"] = _runtime_mode_for_job(view)
        _enrich_job_view(view)
        return view
    child_jobs = []
    with _JOBS_LOCK:
        for cid in children:
            cjob = _JOBS.get(cid)
            if cjob:
                child_view = dict(cjob)
                _hydrate_job_log_from_disk(child_view)
                child_jobs.append(child_view)
    total = len(child_jobs)
    buckets = [_status_for_parent(str(j.get("status") or "")) for j in child_jobs]
    queued = sum(1 for b in buckets if b == "queued")
    running = sum(1 for b in buckets if b == "running")
    success = sum(1 for b in buckets if b == "success")
    error = sum(1 for b in buckets if b == "error")
    if total == 0:
        derived = str(job.get("status") or "queued")
    elif queued or running:
        derived = "running"
    elif error:
        derived = "error"
    else:
        derived = "success"
    view = dict(job)
    view["status"] = derived
    view["children_status"] = {
        "total": total,
        "queued": queued,
        "running": running,
        "success": success,
        "error": error,
    }
    for c in child_jobs:
        cerr = _error_object_for_job(c)
        c["error"] = cerr
        c["error_code"] = str(cerr.get("code") or "")
        c["error_kind"] = str(cerr.get("kind") or "")
        c["error_signature"] = str(cerr.get("signature") or "")
        c["phase"] = _phase_for_job(c)
        c["runtime_mode"] = _runtime_mode_for_job(c)
        _enrich_job_view(c)
    view["children"] = child_jobs
    err = _error_object_for_job(view)
    view["error"] = err
    view["error_code"] = str(err.get("code") or "")
    view["error_kind"] = str(err.get("kind") or "")
    view["error_signature"] = str(err.get("signature") or "")
    view["phase"] = _phase_for_job(view)
    view["runtime_mode"] = _runtime_mode_for_job(view)
    _enrich_job_view(view)
    if derived in {"success", "error"} and not job.get("finished_at"):
        done_ts = time.time()
        _job_update(job.get("job_id"), finished_at=done_ts, status=derived)
        view["finished_at"] = done_ts
        view["status"] = derived
    return view


def _derive_task_status_from_snapshot(job: dict, jobs_snapshot: dict[str, dict]) -> tuple[str, dict, list[dict]]:
    child_ids = list(job.get("children") or [])
    child_jobs = [dict(jobs_snapshot[cid]) for cid in child_ids if cid in jobs_snapshot]
    total = len(child_jobs)
    buckets = [_status_for_parent(str(j.get("status") or "")) for j in child_jobs]
    queued = sum(1 for b in buckets if b == "queued")
    running = sum(1 for b in buckets if b == "running")
    success = sum(1 for b in buckets if b == "success")
    error = sum(1 for b in buckets if b == "error")
    if total == 0:
        derived = str(job.get("status") or "queued")
    elif queued or running:
        derived = "running"
    elif error:
        derived = "error"
    else:
        derived = "success"
    return (
        derived,
        {
            "total": total,
            "queued": queued,
            "running": running,
            "success": success,
            "error": error,
        },
        child_jobs,
    )


def _list_tasks(limit: int = 50) -> list[dict]:
    capped_limit = max(1, min(int(limit), 200))
    with _JOBS_LOCK:
        jobs_snapshot = {job_id: dict(job) for job_id, job in _JOBS.items()}

    tasks: list[dict] = []
    for job in jobs_snapshot.values():
        if job.get("kind") != "task":
            continue
        derived_status, children_status, child_jobs = _derive_task_status_from_snapshot(job, jobs_snapshot)
        active_child = next(
            (c for c in child_jobs if _status_for_parent(str(c.get("status") or "")) in {"running", "queued"}),
            child_jobs[0] if child_jobs else None,
        )
        stage_value = _phase_for_job(active_child) if active_child else _phase_for_job(job)
        progress_value = _task_progress_from_children(derived_status, children_status)
        status_upper = _status_upper(derived_status)
        tasks.append(
            {
                "job_id": job.get("job_id"),
                "id": job.get("job_id"),
                "status": status_upper,
                "status_raw": derived_status,
                "stage": str(stage_value or "").upper() or "UNKNOWN",
                "repo": _task_display_repo(job),
                "repo_raw": job.get("repo"),
                "created_at": job.get("created_at"),
                "created_at_iso": _iso_time(job.get("created_at")),
                "updated_at": job.get("updated_at"),
                "updated_at_iso": _iso_time(job.get("updated_at")),
                "started_at": job.get("started_at"),
                "started_at_iso": _iso_time(job.get("started_at")),
                "finished_at": job.get("finished_at"),
                "finished_at_iso": _iso_time(job.get("finished_at")),
                "error": _error_object_for_job(job),
                "error_code": _error_code_for_job(job),
                "error_kind": _error_kind_for_job(job),
                "error_signature": _error_signature_for_job(job),
                "phase": _phase_for_job(job),
                "runtime_mode": _runtime_mode_for_job(job),
                "result": job.get("result"),
                "children_status": children_status,
                "child_count": children_status.get("total", 0),
                "progress": progress_value,
                "active_child_id": active_child.get("job_id") if active_child else None,
                "active_child_status": _status_upper(str(active_child.get("status") or "")) if active_child else None,
                "active_child_phase": _phase_for_job(active_child) if active_child else None,
                "cancel_requested": job.get("cancel_requested", False),
                "last_cancel_requested_at": job.get("last_cancel_requested_at"),
                "workflow_active_step": job.get("workflow_active_step"),
                "workflow_last_step": job.get("workflow_last_step"),
                "workflow_last_step_ts": job.get("workflow_last_step_ts"),
                "recoverable": job.get("recoverable"),
                "resume_attempts": job.get("resume_attempts", 0),
                "resume_error_code": job.get("resume_error_code"),
                "last_resume_reason": job.get("last_resume_reason"),
                "last_interrupted_at": job.get("last_interrupted_at"),
                "request": job.get("request"),
                # Per-fuzzer metrics from active child (or self for fuzz jobs)
                "fuzz_fuzzers": (active_child or job).get("fuzz_fuzzers", {}),
                "fuzz_max_cov": (active_child or job).get("fuzz_max_cov", 0),
                "fuzz_max_ft": (active_child or job).get("fuzz_max_ft", 0),
                "fuzz_total_execs_per_sec": (active_child or job).get("fuzz_total_execs_per_sec", 0),
                "fuzz_crash_found": (active_child or job).get("fuzz_crash_found", False),
                "fuzz_coverage_loop_round": (active_child or job).get("fuzz_coverage_loop_round", 0),
                "fuzz_coverage_loop_max_rounds": (active_child or job).get("fuzz_coverage_loop_max_rounds", 0),
                "fuzz_coverage_plateau_streak": (active_child or job).get("fuzz_coverage_plateau_streak", 0),
                "fuzz_coverage_seed_profile": (active_child or job).get("fuzz_coverage_seed_profile", ""),
                "fuzz_coverage_quality_flags": (active_child or job).get("fuzz_coverage_quality_flags", []),
                "fuzz_coverage_bottleneck_kind": (active_child or job).get("fuzz_coverage_bottleneck_kind", ""),
                "analysis_evidence_count": int((active_child or job).get("analysis_evidence_count", 0) or 0),
                "security_evidence_count": int((active_child or job).get("security_evidence_count", 0) or 0),
                "vuln_candidate_count": int((active_child or job).get("vuln_candidate_count", 0) or 0),
                "vuln_hunting_enabled": bool((active_child or job).get("vuln_hunting_enabled", False)),
                "security_priority_mode": bool((active_child or job).get("security_priority_mode", False)),
                "latest_vuln_decision_snapshot": dict((active_child or job).get("latest_vuln_decision_snapshot") or {}),
                "target_scoring_enabled": bool((active_child or job).get("target_scoring_enabled", False)),
                "target_score_breakdown_available": bool((active_child or job).get("target_score_breakdown_available", False)),
                "constraint_memory_count": int((active_child or job).get("constraint_memory_count", 0) or 0),
                "decision_trace_count": int((active_child or job).get("decision_trace_count", 0) or 0),
                "latest_decision_snapshot": dict((active_child or job).get("latest_decision_snapshot") or {}),
                "crash_signature_dedup_hit": bool((active_child or job).get("crash_signature_dedup_hit", False)),
            }
        )
    tasks.sort(key=lambda item: float(item.get("created_at") or 0.0), reverse=True)
    return tasks[:capped_limit]


def _mark_resume_failed(job_id: str, *, code: str, message: str) -> None:
    _job_update(
        job_id,
        status="resume_failed",
        recoverable=False,
        resume_error_code=code,
        error=message,
        finished_at=time.time(),
    )


def _run_fuzz_job(
    job_id: str,
    request: fuzz_model,
    cfg: WebPersistentConfig,
    *,
    resumed: bool,
    trigger: str,
    resume_from_step: str | None = None,
    resume_repo_root: str | None = None,
) -> None:
    cancel_error = "cancelled by user"
    if _is_cancel_requested(job_id):
        _job_update(
            job_id,
            status="error",
            error=cancel_error,
            recoverable=False,
            finished_at=time.time(),
        )
        return
    start_ts = time.time()
    next_status = "resuming" if resumed else "running"
    _job_update(
        job_id,
        status=next_status,
        started_at=start_ts,
        finished_at=None,
        recoverable=False,
        error=None,
        request=request.model_dump(),
        resume_from_step=(_normalize_resume_step(resume_from_step) if resumed else ""),
        resume_repo_root=(resume_repo_root or ""),
        last_resume_reason=trigger if resumed else None,
        last_resume_started_at=start_ts if resumed else None,
    )
    log_file = _job_log_path(job_id)
    _job_update(job_id, log_file=str(log_file))
    tee = _Tee(job_id, log_file=log_file)
    out_token = _ACTIVE_JOB_STDOUT_TEE.set(tee)
    err_token = _ACTIVE_JOB_STDERR_TEE.set(tee)
    log_sink_id: int | None = None
    try:
        # Ensure per-job logs are persisted even when loguru writes directly to
        # process stderr/stdout instead of the job-aware stream wrappers.
        current_thread_id = threading.get_ident()
        log_sink_id = logger.add(
            tee,
            level="DEBUG",
            format="{message}",
            filter=lambda record, tid=current_thread_id: record["thread"].id == tid,
        )
        logger.info(f"[job {job_id}] start repo={request.code_url} resumed={int(resumed)} trigger={trigger}")
        # ── Set job ID in environment so sub-modules can check cancel signals ──
        os.environ["SHERPA_CURRENT_JOB_ID"] = str(job_id)
        os.environ["SHERPA_JOB_ID"] = str(job_id)
        if _is_cancel_requested(job_id):
            raise RuntimeError(cancel_error)
        logger.info(f"[job {job_id}] about to dispatch worker...")
        docker_enabled, docker_image_value = _resolve_job_docker_policy(request, cfg)
        total_budget_src = (
            request.total_time_budget
            if request.total_time_budget is not None
            else (
                request.total_duration
                if request.total_duration is not None
                else (request.time_budget if request.time_budget is not None else cfg.fuzz_time_budget)
            )
        )
        run_budget_src = (
            request.run_time_budget
            if request.run_time_budget is not None
            else (
                request.single_duration
                if request.single_duration is not None
                else total_budget_src
            )
        )
        total_time_budget_value = _normalize_budget_value(total_budget_src, field_name="total_time_budget")
        run_time_budget_value = _normalize_budget_value(run_budget_src, field_name="run_time_budget")
        unlimited_round_limit_value = _normalize_round_limit_value(
            request.unlimited_round_limit,
            fallback=int(cfg.sherpa_run_unlimited_round_budget_sec),
        )
        coverage_loop_max_rounds = 0
        max_fix_rounds = 0
        same_error_max_retries = 0
        total_budget_log = "unlimited" if total_time_budget_value == 0 else f"{total_time_budget_value}s"
        run_budget_log = "unlimited" if run_time_budget_value == 0 else f"{run_time_budget_value}s"
        openai_key = (
            os.environ.get("OPENAI_API_KEY")
            or cfg.openai_api_key
            or ""
        ).strip()
        opencode_model_env = _normalized_plain_model_value(os.environ.get("OPENCODE_MODEL") or "")
        openai_model = _normalized_plain_model_value(
            os.environ.get("OPENAI_MODEL")
            or opencode_model_env
            or cfg.openai_model
            or "deepseek-reasoner"
        )
        requested_model = _normalized_plain_model_value(request.model or "")
        if openai_key:
            model_value = requested_model or opencode_model_env or openai_model
        else:
            model_value = requested_model or _normalized_plain_model_value(cfg.openrouter_model)
        runtime_mode = "docker"
        logger.info(
            f"[job {job_id}] params runtime={runtime_mode} "
            f"time_budget={total_budget_log} run_time_budget={run_budget_log} "
            f"unlimited_round_limit={unlimited_round_limit_value if unlimited_round_limit_value > 0 else 'unlimited'} "
            f"max_tokens={request.max_tokens} model={model_value} "
            f"coverage_loop_max_rounds={coverage_loop_max_rounds} "
            f"max_fix_rounds={max_fix_rounds} "
            f"same_error_max_retries={same_error_max_retries}"
        )
        logger.info(f"[job {job_id}] log_file={log_file}")
        mode = _executor_mode()
        docker_image = docker_image_value
        logger.info(
            f"[job {job_id}] executor_mode={mode} "
            f"docker_image={docker_image if docker_image else '(native)'}"
        )
        if _is_cancel_requested(job_id):
            raise RuntimeError(cancel_error)
        try:
                start_step = _normalize_resume_step(resume_from_step) if resumed else "analysis"
                stage_results: list[dict[str, object]] = []
                stage_job_names: list[str] = []
                current_repo_root = str(resume_repo_root or "").strip()
                current_node_name = ""
                last_result: object = {}
                context_dir = str(context_dir_for_repo_root(current_repo_root) or "").strip()
                control_doc, workflow_doc = read_context_docs(
                    context_dir or None,
                    job_id=job_id,
                )
                control_ctx: dict[str, object] = strip_meta(control_doc)
                workflow_ctx: dict[str, object] = strip_meta(workflow_doc)
                control_ctx["time_budget"] = int(total_time_budget_value)
                control_ctx["run_time_budget"] = int(run_time_budget_value)
                control_ctx["coverage_loop_max_rounds"] = int(coverage_loop_max_rounds)
                control_ctx["max_fix_rounds"] = int(max_fix_rounds)
                control_ctx["same_error_max_retries"] = int(same_error_max_retries)
                current_stage = start_step
                if current_stage not in _STAGED_WORKFLOW_STEPS:
                    current_stage = "analysis"
                try:
                    max_stage_dispatches = int((os.environ.get("SHERPA_STAGE_DISPATCH_MAX") or "0").strip())
                except Exception:
                    max_stage_dispatches = 0
                dispatch_count = 0
                companion_mcp_ready = False
                try:
                    from promefuzz_companion import _run_once as _companion_run_once
                    companion_root = (Path(os.environ.get("SHERPA_OUTPUT_DIR", "/shared/output")) / "_jobs" / job_id / "promefuzz").resolve()
                    companion_root.mkdir(parents=True, exist_ok=True)
                    companion_status = _companion_run_once(
                        job_id=job_id,
                        output_root=Path(os.environ.get("SHERPA_OUTPUT_DIR", "/shared/output")),
                        companion_root=companion_root,
                    )
                    companion_mcp_ready = bool(companion_status.get("mcp_ready") or companion_status.get("state") == "ready")
                    logger.info(
                        f"[job {job_id}] companion in-process init: "
                        f"state={companion_status.get('state', '-')} "
                        f"backend={companion_status.get('analysis_backend', '-')}"
                    )
                except Exception as e:
                    logger.info(f"[job {job_id}] companion in-process init failed (continuing): {e}")
                    companion_mcp_ready = False
                while current_stage:
                    stage = current_stage
                    dispatch_count += 1
                    if max_stage_dispatches > 0 and dispatch_count > max_stage_dispatches:
                        raise RuntimeError("staged_workflow_dispatch_limit_exceeded")
                    idx = dispatch_count
                    if _is_cancel_requested(job_id):
                        raise RuntimeError(cancel_error)
                    if stage == "analysis" and _has_reusable_analysis_context(current_repo_root):
                        analysis_context_path = _analysis_context_path_for_repo(current_repo_root)
                        reusable_path = str(analysis_context_path or "")
                        stage_result = {
                            "message": "analysis skipped: reuse existing analysis context",
                            "repo_root": current_repo_root,
                            "workflow_last_step": "analysis",
                            "workflow_recommended_next": "plan",
                            "restart_to_plan": False,
                            "analysis_done": True,
                            "analysis_degraded": False,
                            "analysis_context_path": reusable_path,
                            "analysis_report_path": reusable_path,
                            "analysis_reused": True,
                        }
                        stage_results.append(
                            {
                                "stage": stage,
                                "job_name": "",
                                "ok": True,
                                "repo_root": current_repo_root,
                                "control_context": dict(control_ctx),
                                "workflow_context": dict(workflow_ctx),
                                "result": stage_result,
                            }
                        )
                        _job_update(
                            job_id,
                            workflow_last_step=stage,
                            workflow_active_step="",
                        )
                        logger.info(
                            f"[job {job_id}] stage {stage} reused existing analysis context: "
                            f"{reusable_path or '(unknown path)'}"
                        )
                        last_result = stage_result
                        current_stage = "plan"
                        continue
                    if current_repo_root:
                        context_dir = str(context_dir_for_repo_root(current_repo_root) or context_dir).strip()
                    job_name = f"docker-{job_id}-{stage}-{idx}"
                    result_path = _JOB_LOGS_DIR / job_id / f"stage-{stage}.json"
                    error_path = _JOB_LOGS_DIR / job_id / f"stage-{stage}-error.txt"
                    stage_job_names.append(job_name)
                    _job_update(
                        job_id,
                        workflow_active_step=stage,
                    )
                    can_pin_node = False

                    payload = {
                        "job_id": job_id,
                        "repo_url": request.code_url,
                        "max_len": int(request.max_tokens),
                        "time_budget": int(total_time_budget_value),
                        "run_time_budget": int(run_time_budget_value),
                        "coverage_loop_max_rounds": int(coverage_loop_max_rounds),
                        "max_fix_rounds": int(max_fix_rounds),
                        "same_error_max_retries": int(same_error_max_retries),
                        "email": request.email,
                        "docker_image": docker_image,
                        "ai_key_path": str(opencode_env_path()),
                        "model": model_value,
                        "resume_from_step": stage,
                        "resume_repo_root": (current_repo_root or None),
                        "stop_after_step": stage,
                        "context_dir": (context_dir or None),
                        "run_unlimited_round_budget_sec": int(
                            control_ctx.get("run_timeout_budget_sec_override") or unlimited_round_limit_value
                        ),
                        "analysis_companion_url": None if not companion_mcp_ready else "",
                        "analysis_companion_ready": bool(companion_mcp_ready),
                        "result_path": str(result_path),
                        "error_path": str(error_path),
                        "target_node_name": (current_node_name if can_pin_node else None),
                    }
                    control_ctx["target_node_name"] = (current_node_name if can_pin_node else "")
                    run_fuzzer_count = 1
                    run_parallelism = 1
                    if stage == "run":
                        run_fuzzer_count = _estimate_run_fuzzer_count(current_repo_root or "")
                        run_parallelism = _estimate_run_parallelism(control_ctx)
                    effective_round_budget = int(
                        control_ctx.get("run_timeout_budget_sec_override") or unlimited_round_limit_value
                    )
                    wait_timeout = max(300, total_time_budget_value + 180)
                    stage_result: object
                    stage_node_name: str = ""
                    stage_failed = False
                    stage_fail_error = ""
                    stage_fail_reason = ""
                    try:
                        stage_result, stage_node_name = _execute_docker_stage(
                            job_id=job_id,
                            payload=payload,
                            wait_timeout=wait_timeout,
                        )
                    except Exception as e:
                        stage_failed = True
                        stage_fail_error = _redact_sensitive_text(str(e))
                        stage_fail_reason = "stage_dispatch_exception"
                        stage_result = {
                            "message": f"stage {stage} dispatch failed; restarting from plan",
                            "repo_root": current_repo_root,
                            "workflow_last_step": stage,
                            "workflow_recommended_next": "plan",
                            "restart_to_plan": True,
                            "restart_to_plan_reason": stage_fail_reason,
                            "restart_to_plan_stage": stage,
                            "restart_to_plan_error_text": stage_fail_error,
                            "restart_to_plan_report_path": "",
                            "error": stage_fail_error,
                        }
                    if stage_node_name:
                        if current_node_name and stage_node_name != current_node_name:
                            logger.info(
                                f"[job {job_id}] stage {stage} node drift {current_node_name} -> {stage_node_name}, updating pin"
                            )
                        elif not current_node_name:
                            logger.info(f"[job {job_id}] stage {stage} node selected: {stage_node_name}")
                        current_node_name = stage_node_name
                    else:
                        logger.info(f"[job {job_id}] stage {stage} node unknown, continue without updating pin")

                    if isinstance(stage_result, dict):
                        current_repo_root = str(stage_result.get("repo_root") or current_repo_root).strip()
                        next_context_dir = str(context_dir_for_repo_root(current_repo_root) or "").strip()
                        if next_context_dir and next_context_dir != context_dir:
                            context_dir = next_context_dir
                            control_doc, workflow_doc = read_context_docs(
                                context_dir,
                                job_id=job_id,
                            )
                            control_ctx = strip_meta(control_doc)
                            workflow_ctx = strip_meta(workflow_doc)
                        control_ctx, workflow_ctx = merge_result_into_contexts(
                            stage_result,
                            control=control_ctx,
                            workflow=workflow_ctx,
                        )
                        if not bool(stage_result.get("restart_to_plan")):
                            workflow_ctx["restart_to_plan_reason"] = ""
                            workflow_ctx["restart_to_plan_stage"] = ""
                            workflow_ctx["restart_to_plan_error_text"] = ""
                            workflow_ctx["restart_to_plan_report_path"] = ""
                        if context_dir:
                            write_context_docs(
                                context_dir,
                                control=control_ctx,
                                workflow=workflow_ctx,
                                job_id=job_id,
                            )
                        stage_results.append(
                            {
                                "stage": stage,
                                "job_name": job_name,
                                "ok": (not stage_failed),
                                "repo_root": current_repo_root,
                                "control_context": dict(control_ctx),
                                "workflow_context": dict(workflow_ctx),
                                "result": stage_result,
                            }
                        )
                        if current_repo_root:
                            _job_update(job_id, workflow_repo_root=current_repo_root, resume_repo_root=current_repo_root)
                    else:
                        stage_results.append(
                            {
                                "stage": stage,
                                "job_name": job_name,
                                "ok": True,
                                "repo_root": current_repo_root,
                            }
                        )
                    _job_update(
                        job_id,
                        workflow_last_step=stage,
                        workflow_active_step="",
                    )
                    last_result = stage_result
                    if stage_failed:
                        logger.info(
                            f"[job {job_id}] stage {stage} failed ({stage_fail_reason}): "
                            f"{stage_fail_error} -> fallback to plan"
                        )
                    else:
                        logger.info(f"[job {job_id}] stage {stage} completed via job {job_name}")
                    next_stage = ""
                    if isinstance(stage_result, dict):
                        next_raw = str(stage_result.get("workflow_recommended_next") or "").strip()
                        if next_raw:
                            next_stage = _normalize_resume_step(next_raw)
                    if next_stage in {"", "stop"}:
                        break
                    current_stage = next_stage

                res = dict(last_result) if isinstance(last_result, dict) else {"message": str(last_result or "")}
                res["stage_results"] = stage_results
                res["stage_job_names"] = stage_job_names
                logger.info(f"[job {job_id}] staged workflow finished ({len(stage_results)} stages)")
        except (
            RuntimeError,
            ValueError,
            OSError,
            subprocess.SubprocessError,
            json.JSONDecodeError,
        ) as fuzz_err:
            logger.info(f"[job {job_id}] worker failed: {fuzz_err}")
            import traceback
            traceback.print_exc()
            raise
        if _is_cancel_requested(job_id):
            _job_update(
                job_id,
                status="error",
                error=cancel_error,
                result=None,
                recoverable=False,
                last_resume_finished_at=time.time() if resumed else None,
            )
            return
        res_failed = bool(isinstance(res, dict) and res.get("failed"))
        run_terminal_reason = str((res.get("run_terminal_reason") if isinstance(res, dict) else "") or "").strip()
        final_status = ("resumed" if resumed else "success")
        final_error = None
        if res_failed:
            final_status = "error"
            final_error = str(
                (
                    res.get("last_error")
                    if isinstance(res, dict)
                    else ""
                )
                or run_terminal_reason
                or "workflow_failed"
            ).strip()
        final_metric_fields: dict[str, object] = {}
        if isinstance(res, dict):
            final_metric_fields = {
                "analysis_evidence_count": int(res.get("analysis_evidence_count") or 0),
                "security_evidence_count": int(res.get("security_evidence_count") or 0),
                "vuln_candidate_count": int(res.get("vuln_candidate_count") or 0),
                "vuln_hunting_enabled": bool(res.get("vuln_hunting_enabled") or False),
                "security_priority_mode": bool(res.get("security_priority_mode") or False),
                "latest_vuln_decision_snapshot": dict(res.get("latest_vuln_decision_snapshot") or {}),
                "target_scoring_enabled": bool(res.get("target_scoring_enabled") or False),
                "target_score_breakdown_available": bool(res.get("target_score_breakdown_available") or False),
                "decision_trace_count": int(res.get("decision_trace_count") or 0),
                "latest_decision_snapshot": dict(res.get("latest_decision_snapshot") or {}),
                "crash_signature_dedup_hit": bool(res.get("crash_signature_dedup_hit") or False),
            }
        _job_update(
            job_id,
            status=final_status,
            error=final_error,
            result=res,
            recoverable=False,
            resume_error_code=None,
            last_resume_finished_at=time.time() if resumed else None,
            **final_metric_fields,
        )
    except (
        RuntimeError,
        ValueError,
        OSError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ) as e:
        if _is_cancel_requested(job_id):
            fail_status = "error"
            err_text = cancel_error
        else:
            fail_status = "resume_failed" if resumed else "error"
            err_text = _redact_sensitive_text(str(e))
        fail_result = None
        if isinstance(err_text, str) and ":" in err_text:
            reason = err_text.split(":", 1)[0].strip()
            if fail_result is None and reason.startswith("run_"):
                fail_result = {"run_terminal_reason": reason}
        _job_update(
            job_id,
            status=fail_status,
            error=err_text,
            result=fail_result,
            recoverable=False,
            last_resume_finished_at=time.time() if resumed else None,
        )
    finally:
        # ── Clean up job-scoped environment variables ──
        if os.environ.get("SHERPA_CURRENT_JOB_ID") == str(job_id):
            os.environ.pop("SHERPA_CURRENT_JOB_ID", None)
        if os.environ.get("SHERPA_JOB_ID") == str(job_id):
            os.environ.pop("SHERPA_JOB_ID", None)
        if log_sink_id is not None:
            try:
                logger.remove(log_sink_id)
            except Exception:
                pass
        _job_update(
            job_id,
            analysis_companion_active=False,
            analysis_companion_ready=False,
            analysis_companion_stopped_at=time.time(),
        )
        _ACTIVE_JOB_STDOUT_TEE.reset(out_token)
        _ACTIVE_JOB_STDERR_TEE.reset(err_token)
        try:
            tee.close()
        except Exception:
            pass
        _job_update(job_id, finished_at=time.time())


def _submit_fuzz_job(request: fuzz_model, cfg: WebPersistentConfig) -> str:
    job_id = _create_job("fuzz", request.code_url)
    _job_update(
        job_id,
        request=request.model_dump(),
        recoverable=True,
        resume_attempts=0,
        resume_error_code=None,
    )
    fut = executor.submit(_run_fuzz_job, job_id, request, cfg, resumed=False, trigger="new")
    _track_job_future(job_id, fut)
    return job_id


def _resume_fuzz_job(job_id: str, cfg: WebPersistentConfig, *, trigger: str) -> dict[str, object]:
    job = _job_snapshot(job_id)
    if not job:
        return {"accepted": False, "reason": "job_not_found"}
    if str(job.get("kind") or "") != "fuzz":
        return {"accepted": False, "reason": "job_not_fuzz"}

    status = str(job.get("status") or "").strip().lower()
    if status in {"queued", "running", "resuming"}:
        return {"accepted": False, "reason": "already_in_progress"}
    if status in {"success", "resumed"}:
        return {"accepted": False, "reason": "already_completed"}

    raw_request = job.get("request")
    if not isinstance(raw_request, dict):
        _mark_resume_failed(job_id, code="missing_resume_context", message="missing request payload for resume")
        return {"accepted": False, "reason": "missing_resume_context"}

    try:
        req = fuzz_model.model_validate(raw_request)
    except (ValueError, TypeError) as e:
        _mark_resume_failed(job_id, code="invalid_resume_context", message=f"invalid request payload for resume: {e}")
        return {"accepted": False, "reason": "invalid_resume_context"}

    attempts = int(job.get("resume_attempts") or 0) + 1
    resume_step = _normalize_resume_step(
        str(job.get("resume_from_step") or "")
        or str(job.get("workflow_active_step") or "")
        or str(job.get("workflow_last_step") or "")
        or "build"
    )
    resume_repo_root = str(job.get("resume_repo_root") or job.get("workflow_repo_root") or "").strip()
    if resume_step not in {"analysis", "plan"} and not resume_repo_root:
        _mark_resume_failed(
            job_id,
            code="missing_resume_workspace",
            message=f"cannot resume from step `{resume_step}` without saved repo_root",
        )
        return {"accepted": False, "reason": "missing_resume_workspace"}
    _job_update(
        job_id,
        status="resuming",
        recoverable=False,
        error=None,
        result=None,
        finished_at=None,
        resume_attempts=attempts,
        resume_from_step=resume_step,
        resume_repo_root=resume_repo_root,
        last_resume_reason=trigger,
        last_resume_requested_at=time.time(),
    )
    fut = executor.submit(
        _run_fuzz_job,
        job_id,
        req,
        cfg,
        resumed=True,
        trigger=trigger,
        resume_from_step=resume_step,
        resume_repo_root=resume_repo_root,
    )
    _track_job_future(job_id, fut)
    return {"accepted": True, "reason": "resuming", "resume_attempts": attempts}


def _resume_task_job(job_id: str, cfg: WebPersistentConfig, *, trigger: str) -> dict[str, object]:
    job = _job_snapshot(job_id)
    if not job:
        return {"accepted": False, "reason": "job_not_found"}
    if str(job.get("kind") or "") != "task":
        return {"accepted": False, "reason": "job_not_task"}

    status = str(job.get("status") or "").strip().lower()
    if status in {"queued", "running", "resuming"}:
        return {"accepted": False, "reason": "already_in_progress"}
    if status in {"success", "resumed"}:
        return {"accepted": False, "reason": "already_completed"}

    child_ids = [str(x) for x in (job.get("children") or []) if str(x).strip()]
    if not child_ids:
        _mark_resume_failed(job_id, code="missing_resume_children", message="missing child jobs for task resume")
        return {"accepted": False, "reason": "missing_resume_children"}

    resumed_any = False
    for cid in child_ids:
        child = _job_snapshot(cid)
        if not child:
            continue
        child_status = str(child.get("status") or "").strip().lower()
        if child_status in {"success", "resumed"}:
            continue
        if child_status in {"queued", "running", "resuming"}:
            resumed_any = True
            continue
        out = _resume_fuzz_job(cid, cfg, trigger=f"{trigger}:task:{job_id}")
        if bool(out.get("accepted")):
            resumed_any = True

    if resumed_any:
        attempts = int(job.get("resume_attempts") or 0) + 1
        _job_update(
            job_id,
            status="resuming",
            recoverable=False,
            error=None,
            finished_at=None,
            resume_attempts=attempts,
            last_resume_reason=trigger,
            last_resume_requested_at=time.time(),
        )
        return {"accepted": True, "reason": "resuming", "resume_attempts": attempts}

    refreshed = _job_snapshot(job_id) or job
    derived = _derive_task_status(refreshed)
    final_status = str(derived.get("status") or "").strip().lower()
    if final_status in {"success", "error"} and not _is_status_terminal(job.get("status")):
        _job_update(job_id, status=final_status, finished_at=float(derived.get("finished_at") or time.time()))
    return {"accepted": False, "reason": "no_resumable_children"}


def _stop_fuzz_job(job_id: str, *, reason: str, trigger: str) -> dict[str, object]:
    snap = _job_snapshot(job_id)
    if not snap:
        return {"accepted": False, "reason": "job_not_found"}
    if str(snap.get("kind") or "") != "fuzz":
        return {"accepted": False, "reason": "job_not_fuzz"}

    status = str(snap.get("status") or "").strip().lower()
    now = time.time()
    _job_update(
        job_id,
        cancel_requested=True,
        last_cancel_requested_at=now,
        last_cancel_reason=trigger,
        recoverable=False,
    )

    # ── Signal the running fuzz logic to abort at its next check ──
    try:
        from fuzz_unharnessed_repo import request_cancel as _signal_cancel
        _signal_cancel(job_id)
    except Exception:
        pass

    # ── Kill the OpenCode subprocess if one is running for this job ──
    try:
        from codex_helper import kill_opencode_for_job as _kill_opencode
        _kill_opencode(job_id)
    except Exception:
        pass

    future_cancelled = _cancel_job_future(job_id)
    repo_root = str(snap.get("workflow_repo_root") or snap.get("resume_repo_root") or "").strip()

    # ── Kill running Docker containers for this repo ──
    killed_containers = _stop_runtime_containers_for_repo(repo_root) if repo_root else []
    # Also kill any pooled containers related to this job
    try:
        rc, out, _ = _docker_cli(["ps", "-q", "--filter", f"name=sherpa-pool-"], timeout=10)
        if rc == 0:
            for cid in out.splitlines():
                cid = cid.strip()
                if cid:
                    _docker_cli(["rm", "-f", cid], timeout=15)
                    killed_containers.append(cid)
    except Exception:
        pass

    # ── Delete the job's output workdir ──
    cleaned_workdir = False
    if repo_root:
        try:
            root_path = Path(repo_root).expanduser().resolve()
            if root_path.exists():
                shutil.rmtree(str(root_path), ignore_errors=True)
                cleaned_workdir = True
                logger.info(f"[job {job_id}] cleaned workdir: {root_path}")
        except Exception:
            pass

    # ── Clear the cancel signal after cleanup ──
    try:
        from fuzz_unharnessed_repo import clear_cancel as _clear_cancel
        _clear_cancel(job_id)
    except Exception:
        pass

    if status not in {"success", "resumed", "error", "resume_failed"}:
        _job_update(
            job_id,
            status="error",
            error=reason,
            result=None,
            recoverable=False,
            finished_at=now,
        )

    current = _job_snapshot(job_id) or snap
    return {
        "accepted": True,
        "reason": "stopped",
        "status": str(current.get("status") or ""),
        "future_cancelled": bool(future_cancelled),
        "killed_containers": killed_containers,
        "repo_root": repo_root or None,
        "cleaned_workdir": cleaned_workdir,
    }


def _stop_task_job(job_id: str, *, reason: str, trigger: str) -> dict[str, object]:
    snap = _job_snapshot(job_id)
    if not snap:
        return {"accepted": False, "reason": "job_not_found"}
    if str(snap.get("kind") or "") != "task":
        return {"accepted": False, "reason": "job_not_task"}

    now = time.time()
    _job_update(
        job_id,
        cancel_requested=True,
        last_cancel_requested_at=now,
        last_cancel_reason=trigger,
        recoverable=False,
    )

    # ── Signal the running task logic to abort ──
    try:
        from fuzz_unharnessed_repo import request_cancel as _signal_cancel
        _signal_cancel(job_id)
    except Exception:
        pass

    # ── Kill the OpenCode subprocess if one is running ──
    try:
        from codex_helper import kill_opencode_for_job as _kill_opencode
        _kill_opencode(job_id)
    except Exception:
        pass

    parent_future_cancelled = _cancel_job_future(job_id)

    child_ids = [str(x) for x in (snap.get("children") or []) if str(x).strip()]
    child_results: list[dict[str, object]] = []
    for cid in child_ids:
        child_results.append(_stop_fuzz_job(cid, reason=reason, trigger=f"{trigger}:task:{job_id}"))

    _job_update(
        job_id,
        status="error",
        error=reason,
        recoverable=False,
        finished_at=now,
    )
    refreshed = _job_snapshot(job_id) or snap
    derived = _derive_task_status(refreshed)
    _job_update(
        job_id,
        status="error",
        error=reason,
        recoverable=False,
        finished_at=time.time(),
    )

    return {
        "accepted": True,
        "reason": "stopped",
        "status": "error",
        "children_status": derived.get("children_status"),
        "stopped_children": child_results,
        "parent_future_cancelled": bool(parent_future_cancelled),
    }


def _auto_resume_enabled() -> bool:
    raw = (os.environ.get("SHERPA_WEB_AUTO_RESUME_ON_START", "0") or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _auto_resume_recoverable_jobs(cfg: WebPersistentConfig) -> None:
    if not _auto_resume_enabled():
        return
    with _JOBS_LOCK:
        snapshot = {job_id: dict(job) for job_id, job in _JOBS.items()}

    task_ids = [
        job_id
        for job_id, job in snapshot.items()
        if str(job.get("kind") or "") == "task"
        and str(job.get("status") or "").strip().lower() == "recoverable"
    ]
    for tid in task_ids:
        _resume_task_job(tid, cfg, trigger="auto_startup")

    with _JOBS_LOCK:
        snapshot2 = {job_id: dict(job) for job_id, job in _JOBS.items()}
    for job_id, job in snapshot2.items():
        if str(job.get("kind") or "") != "fuzz":
            continue
        if str(job.get("status") or "").strip().lower() != "recoverable":
            continue
        parent_id = str(job.get("parent_id") or "").strip()
        if parent_id and parent_id in snapshot2:
            continue
        _resume_fuzz_job(job_id, cfg, trigger="auto_startup")


@app.post("/api/task")
async def task_api(request: task_model = Body(...)):
    cfg = _cfg_get()
    _enforce_docker_only(request.jobs, cfg)
    job_id = _create_job("task", "batch")
    _job_update(
        job_id,
        request=request.model_dump(),
        recoverable=True,
        resume_attempts=0,
        resume_error_code=None,
    )

    def _runner() -> None:
        cancel_error = "cancelled by user"
        if _is_cancel_requested(job_id):
            _job_update(
                job_id,
                status="error",
                error=cancel_error,
                recoverable=False,
                finished_at=time.time(),
            )
            return
        _job_update(job_id, status="running", started_at=time.time())
        log_file = _job_log_path(job_id)
        _job_update(job_id, log_file=str(log_file))
        tee = _Tee(job_id, log_file=log_file)
        out_token = _ACTIVE_JOB_STDOUT_TEE.set(tee)
        err_token = _ACTIVE_JOB_STDERR_TEE.set(tee)
        had_error = False
        child_ids: list[str] = []
        try:
            logger.info(f"[task {job_id}] start (jobs={len(request.jobs)})")
            if _is_cancel_requested(job_id):
                raise RuntimeError(cancel_error)
            if request.auto_init:
                with _INIT_LOCK:
                    if _is_cancel_requested(job_id):
                        raise RuntimeError(cancel_error)
                    should_build_images = request.build_images
                    if should_build_images:
                        # Only build if any job uses Docker (explicit or default config).
                        use_docker_jobs = any(
                            (j.docker if j.docker is not None else cfg.fuzz_use_docker)
                            for j in request.jobs
                        )
                        if use_docker_jobs:
                            from fuzz_unharnessed_repo import DOCKERFILE_FUZZ_CPP, DOCKERFILE_FUZZ_JAVA
                            images = request.images
                            if not images:
                                # Only prebuild explicitly requested non-auto images.
                                # 'auto' images are built lazily by the workflow once language is known.
                                inferred: set[str] = set()
                                for j in request.jobs:
                                    img = (j.docker_image or "").strip().lower()
                                    if img in {"cpp", "c", "cxx"}:
                                        inferred.add("cpp")
                                    elif img in {"java", "jazzer"}:
                                        inferred.add("java")
                                images = sorted(inferred)
                            if not images:
                                logger.info("[task] skip prebuild images (no explicit image hints); lazy-build on demand")
                            for img in images:
                                name = (img or "").strip().lower()
                                if name in {"cpp", "c", "cxx"}:
                                    tag = os.environ.get("SHERPA_DOCKER_IMAGE_CPP", "sherpa-fuzz-cpp:latest")
                                    logger.info(f"[task] ensure image {tag}")
                                    _ensure_docker_image(tag, DOCKERFILE_FUZZ_CPP, force=request.force_build)
                                elif name in {"java", "jazzer"}:
                                    tag = os.environ.get("SHERPA_DOCKER_IMAGE_JAVA", "sherpa-fuzz-java:latest")
                                    logger.info(f"[task] ensure image {tag}")
                                    _ensure_docker_image(tag, DOCKERFILE_FUZZ_JAVA, force=request.force_build)
                                else:
                                    logger.info(f"[task] skip unknown image hint: {img}")
            # Submit child jobs after parent setup logs are written.
            # Each job now uses ContextVar-based log routing, so concurrent jobs
            # remain isolated without process-global stdout/stderr switching.
            for job in request.jobs:
                if _is_cancel_requested(job_id):
                    break
                child_id = _submit_fuzz_job(job, cfg)
                child_ids.append(child_id)
                _job_update(child_id, parent_id=job_id)
            if _is_cancel_requested(job_id):
                _job_update(
                    job_id,
                    status="error",
                    error=cancel_error,
                    recoverable=False,
                    finished_at=time.time(),
                )
            elif child_ids:
                _job_update(job_id, result="submitted", children=child_ids)
            else:
                _job_update(job_id, status="success", result="submitted (0 jobs)", finished_at=time.time())
            tee.write(f"[task {job_id}] submitted {len(child_ids)} fuzz jobs\n")
        except Exception as e:
            had_error = True
            _job_update(job_id, status="error", error=(cancel_error if _is_cancel_requested(job_id) else str(e)))
        finally:
            _ACTIVE_JOB_STDOUT_TEE.reset(out_token)
            _ACTIVE_JOB_STDERR_TEE.reset(err_token)
            try:
                tee.close()
            except Exception:
                pass
            if had_error:
                _job_update(job_id, finished_at=time.time())

    fut = executor.submit(_runner)
    _track_job_future(job_id, fut)
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/task/{job_id}")
def get_task(job_id: str):
    job = _job_snapshot(job_id)
    if not job:
        return {"error": "job_not_found"}
    if job.get("kind") != "task":
        return {"error": "job_not_task"}
    return _derive_task_status(job)


@app.post("/api/task/{job_id}/resume")
def resume_task(job_id: str):
    cfg = _cfg_get()
    snap0 = _job_snapshot(job_id) or {}
    kind = str(snap0.get("kind") or "")
    if kind == "fuzz":
        out = _resume_fuzz_job(job_id, cfg, trigger="manual_api")
    else:
        out = _resume_task_job(job_id, cfg, trigger="manual_api")
    snap = _job_snapshot(job_id)
    return {
        "job_id": job_id,
        "kind": kind or str((snap or {}).get("kind") or ""),
        "accepted": bool(out.get("accepted")),
        "reason": str(out.get("reason") or ""),
        "resume_attempts": int(out.get("resume_attempts") or (snap or {}).get("resume_attempts") or 0),
        "status": str((snap or {}).get("status") or ""),
    }


@app.post("/api/task/{job_id}/stop")
def stop_task(job_id: str):
    snap0 = _job_snapshot(job_id) or {}
    kind = str(snap0.get("kind") or "")
    reason = "cancelled by user"
    trigger = "manual_api"

    if kind == "fuzz":
        out = _stop_fuzz_job(job_id, reason=reason, trigger=trigger)
    else:
        out = _stop_task_job(job_id, reason=reason, trigger=trigger)

    snap = _job_snapshot(job_id)
    return {
        "job_id": job_id,
        "kind": kind or str((snap or {}).get("kind") or ""),
        "accepted": bool(out.get("accepted")),
        "reason": str(out.get("reason") or ""),
        "status": str((snap or {}).get("status") or ""),
        "details": out,
    }


@app.get("/api/tasks")
def list_tasks(limit: int = 50):
    return {
        "items": _list_tasks(limit=limit),
    }


@app.delete("/api/task/{job_id}")
def delete_task(job_id: str):
    """Delete a task and all its child jobs from memory, persistent store, and disk."""
    with _JOBS_LOCK:
        if job_id not in _JOBS:
            raise HTTPException(status_code=404, detail=f"Task not found: {job_id}")
        snap = dict(_JOBS[job_id])
        child_ids = list(snap.get("children") or [])

    # ── Stop all running children first (kills containers, cleans workdirs) ──
    kind = str(snap.get("kind") or "")
    if kind == "task":
        _stop_task_job(job_id, reason="deleted by user", trigger="manual_delete")
    else:
        _stop_fuzz_job(job_id, reason="deleted by user", trigger="manual_delete")

    # Remove from memory store
    with _JOBS_LOCK:
        if job_id in _JOBS:
            del _JOBS[job_id]
        for cid in child_ids:
            if cid in _JOBS:
                del _JOBS[cid]

    # Cancel running futures for parent and children
    with _JOB_FUTURES_LOCK:
        for jid in [job_id] + child_ids:
            future = _JOB_FUTURES.pop(jid, None)
            if future is not None and not future.done():
                future.cancel()

    # Remove from persistent store (best-effort)
    if _JOB_STORE is not None:
        for jid in [job_id] + child_ids:
            try:
                _JOB_STORE.delete_job(jid)
            except Exception as exc:
                logger.warning("Failed to delete job {} from persistent store: {}", jid, exc)

    # Delete all filesystem artifacts for parent and children
    for jid in [job_id] + child_ids:
        _delete_job_files(jid)

    logger.info("Task {} deleted (kind={}, children={})", job_id, snap.get("kind", ""), len(child_ids))
    return {"ok": True, "job_id": job_id}


@app.get("/")
def service_root():
    return {
        "service": "sherpa-web",
        "role": "api-backend-only",
        "entrypoint": "Use Ingress at / for UI and /api/* for API",
    }


@app.get("/api/memory/search")
async def memory_search(q: str = "", type: str = ""):
    """Full-text search across memory pages, optionally filtered by type."""
    adapter = getattr(app.state, "memory_adapter", None)
    if adapter is None:
        return {"enabled": False, "results": [], "total": 0}

    query_text = q.strip()
    if type:
        prefix = _MEMORY_TYPE_PREFIX.get(type, "")
        if prefix and query_text:
            query_text = f"type:{prefix} {query_text}"
        elif prefix:
            query_text = f"type:{prefix}"

    try:
        raw = await adapter.query_experience(query_text, timeout=5.0)
    except Exception as exc:
        logger.warning("memory_search error: {}", exc)
        return {"enabled": True, "results": [], "total": 0, "error": str(exc)}

    results = []
    for r in raw:
        slug = r.get("slug", "")
        page_type = _page_type_key_from_slug(slug)
        results.append({
            "slug": slug,
            "type": page_type,
            "title": r.get("title", slug.rsplit("/", 1)[-1] if "/" in slug else slug),
            "score": r.get("score", r.get("relevance", 0.0)),
            "snippet": r.get("snippet", r.get("summary", "")),
        })
    return {"enabled": True, "results": results, "total": len(results)}


@app.get("/api/memory/pages")
async def memory_pages(type: str = "", limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)):
    """List memory pages by type."""
    adapter = getattr(app.state, "memory_adapter", None)
    if adapter is None:
        return {"enabled": False, "healthy": False, "status": {}, "results": [], "total": 0}

    prefix = _MEMORY_TYPE_PREFIX.get(type, "")
    try:
        raw = await adapter.list_pages(type_prefix=prefix, limit=limit, offset=offset)
    except Exception as exc:
        logger.warning("memory_pages error: {}", exc)
        return {
            "enabled": True, "healthy": False, "status": adapter.status(),
            "results": [], "total": 0, "error": str(exc),
        }

    results = []
    for r in raw:
        slug = r.get("slug", "")
        page_type = _page_type_key_from_slug(slug)
        results.append({
            "slug": slug,
            "type": page_type,
            "title": r.get("title", slug.rsplit("/", 1)[-1] if "/" in slug else slug),
            "score": 0.0,
            "snippet": r.get("summary", r.get("snippet", "")),
        })
    return {
        "enabled": True,
        "healthy": adapter.status()["healthy"],
        "status": adapter.status(),
        "results": results,
        "total": len(results),
    }


@app.get("/api/memory/stats")
async def memory_stats():
    """Return memory page counts grouped by type."""
    adapter = getattr(app.state, "memory_adapter", None)
    if adapter is None:
        return {"enabled": False, "healthy": False, "total": 0, "by_type": {}}

    try:
        raw = await adapter.list_pages(type_prefix="", limit=500)
    except Exception as exc:
        logger.warning("memory_stats error: {}", exc)
        return {
            "enabled": True, "healthy": False,
            "total": 0, "by_type": {}, "error": str(exc),
        }

    by_type: dict[str, int] = {}
    for r in raw:
        slug = r.get("slug", "")
        key = _page_type_key_from_slug(slug)
        by_type[key] = by_type.get(key, 0) + 1

    return {
        "enabled": True,
        "healthy": adapter.status()["healthy"],
        "total": sum(by_type.values()),
        "by_type": by_type,
    }


@app.post("/api/memory/batch-delete")
async def memory_batch_delete(body: dict = Body(...)):
    """Delete multiple memory pages in one request."""
    adapter = getattr(app.state, "memory_adapter", None)
    if adapter is None:
        raise HTTPException(status_code=503, detail="Memory service not available")

    slugs = body.get("slugs")
    if not isinstance(slugs, list) or not slugs:
        raise HTTPException(status_code=400, detail="slugs must be a non-empty list")

    ok_count = 0
    failed: dict[str, str] = {}
    for slug in slugs:
        try:
            deleted = await adapter.delete_page(str(slug))
        except Exception as exc:
            deleted = False
            failed[str(slug)] = str(exc)
        if deleted:
            ok_count += 1
        else:
            failed[str(slug)] = failed.get(str(slug), "delete returned false")

    return {"ok": ok_count, "failed": len(failed), "errors": failed}


@app.post("/api/memory/batch-retype")
async def memory_batch_retype(body: dict = Body(...)):
    """Reclassify multiple memory pages by updating their frontmatter type."""
    adapter = getattr(app.state, "memory_adapter", None)
    if adapter is None:
        raise HTTPException(status_code=503, detail="Memory service not available")

    changes = body.get("changes")
    if not isinstance(changes, list) or not changes:
        raise HTTPException(status_code=400, detail="changes must be a non-empty list")

    ok_count = 0
    failed: dict[str, str] = {}
    for ch in changes:
        slug = str(ch.get("slug", ""))
        new_type = str(ch.get("new_type", ""))
        if not slug or not new_type:
            failed[slug or "(empty)"] = "slug and new_type are required"
            continue
        try:
            page = await adapter.get_page(slug)
        except Exception as exc:
            failed[slug] = f"get_page error: {exc}"
            continue
        if page is None:
            failed[slug] = "page not found"
            continue

        existing_fm = page.get("frontmatter", {})
        if not isinstance(existing_fm, dict):
            existing_fm = {}
        existing_fm["type"] = new_type
        compiled_truth = page.get("compiled_truth", page.get("content", ""))
        timeline = page.get("timeline", [])

        try:
            ok = await adapter.write_page(slug, existing_fm, compiled_truth, timeline)
        except Exception as exc:
            ok = False
            failed[slug] = str(exc)
        if ok:
            ok_count += 1
        else:
            failed[slug] = failed.get(slug, "write_page returned false")

    return {"ok": ok_count, "failed": len(failed), "errors": failed}


@app.get("/api/memory/health")
async def memory_health():
    """Report GBrain memory service health status.

    Triggers lazy gbrain startup on first call so the reported health
    reflects the actual state rather than \"never tried\".
    """
    adapter = getattr(app.state, "memory_adapter", None)
    if adapter is None:
        return {"enabled": False, "healthy": False, "status": {}}
    # Trigger lazy startup if gbrain hasn't been started yet
    await adapter._ensure_running()
    return {
        "enabled": True,
        **adapter.status(),
    }


@app.get("/api/memory/page/{slug:path}")
async def memory_get_page(slug: str):
    """Get a single memory page by slug."""
    adapter = getattr(app.state, "memory_adapter", None)
    if adapter is None:
        raise HTTPException(status_code=503, detail="Memory service not available")

    try:
        page = await adapter.get_page(slug)
    except Exception as exc:
        logger.warning("memory_get_page({}) error: {}", slug, exc)
        raise HTTPException(status_code=502, detail="Memory service error")

    if page is None:
        raise HTTPException(status_code=404, detail=f"Page not found: {slug}")

    return {"enabled": True, "page": page}


@app.put("/api/memory/page/{slug:path}")
async def memory_update_page(slug: str, frontmatter: dict = Body(...)):
    """Update a memory page's frontmatter."""
    adapter = getattr(app.state, "memory_adapter", None)
    if adapter is None:
        raise HTTPException(status_code=503, detail="Memory service not available")

    try:
        page = await adapter.get_page(slug)
    except Exception:
        raise HTTPException(status_code=502, detail="Memory service error")

    if page is None:
        raise HTTPException(status_code=404, detail=f"Page not found: {slug}")

    existing_fm = page.get("frontmatter", {})
    compiled_truth = page.get("compiled_truth", page.get("content", ""))
    timeline = page.get("timeline", [])

    existing_fm.update(frontmatter)

    ok = await adapter.write_page(slug, existing_fm, compiled_truth, timeline)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update page")

    return {"ok": True, "slug": slug}


@app.delete("/api/memory/page/{slug:path}")
async def memory_delete_page(slug: str):
    """Delete a memory page."""
    adapter = getattr(app.state, "memory_adapter", None)
    if adapter is None:
        raise HTTPException(status_code=503, detail="Memory service not available")

    ok = await adapter.delete_page(slug)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to delete page")

    return {"ok": True, "slug": slug}


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
