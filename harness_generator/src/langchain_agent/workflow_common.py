from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from persistent_config import load_config

_DEFAULT_TIME_BUDGET_SEC = 900
_UNLIMITED_TIME_BUDGET_SENTINEL_SEC = 2_147_483_647
ALLOWED_TARGET_TYPES = {
    "parser",
    "decoder",
    "archive",
    "image",
    "document",
    "network",
    "database",
    "serializer",
    "interpreter",
    "generic",
}
ALLOWED_SEED_PROFILES = {
    "parser-structure",
    "parser-token",
    "parser-format",
    "parser-numeric",
    "decoder-binary",
    "archive-container",
    "serializer-structured",
    "document-text",
    "network-message",
    "generic",
}


def parse_budget_value(raw: Any, *, default: int = _DEFAULT_TIME_BUDGET_SEC) -> int:
    """Parse a budget field while preserving explicit 0 (unlimited)."""
    if raw is None:
        return int(default)
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return int(default)
    try:
        return int(raw)
    except Exception:
        return int(default)


def is_unlimited_budget(raw: Any, *, default: int = _DEFAULT_TIME_BUDGET_SEC) -> bool:
    return parse_budget_value(raw, default=default) <= 0


def wf_log(state: dict[str, Any] | None, msg: str) -> None:
    step_count = ""
    last_step = ""
    nxt = ""
    if state:
        step_count = str(state.get("step_count") or "")
        last_step = str(state.get("last_step") or "")
        nxt = str(state.get("next") or "")
    prefix = "[wf]"
    if step_count or last_step or nxt:
        prefix = f"[wf step={step_count or '-'} last={last_step or '-'} next={nxt or '-'}]"
    print(f"{prefix} {msg}", flush=True)


def fmt_dt(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds*1000:.0f}ms"
    return f"{seconds:.2f}s"


def extract_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    blob = m.group(0)
    try:
        val = json.loads(blob)
    except Exception:
        return None
    return val if isinstance(val, dict) else None


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def validate_targets_json(repo_root: Path) -> tuple[bool, str]:
    targets = repo_root / "fuzz" / "targets.json"
    if not targets.is_file():
        return False, "missing fuzz/targets.json"
    try:
        data = json.loads(targets.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        return False, f"invalid json in fuzz/targets.json: {e}"

    if not isinstance(data, list) or not data:
        return False, "targets.json must be a non-empty JSON array"

    allowed_lang = {"c-cpp", "cpp", "c", "c++", "java"}
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            return False, f"targets[{i}] must be an object"
        for key in ("name", "api", "lang", "target_type", "seed_profile"):
            val = item.get(key)
            if not isinstance(val, str) or not val.strip():
                return False, f"targets[{i}].{key} must be a non-empty string"
        lang = str(item.get("lang") or "").strip().lower()
        if lang not in allowed_lang:
            return False, f"targets[{i}].lang unsupported: {item.get('lang')}"
        target_type = str(item.get("target_type") or "").strip().lower()
        if target_type not in ALLOWED_TARGET_TYPES:
            return False, f"targets[{i}].target_type unsupported: {item.get('target_type')}"
        seed_profile = str(item.get("seed_profile") or "").strip().lower()
        if seed_profile not in ALLOWED_SEED_PROFILES:
            return False, f"targets[{i}].seed_profile unsupported: {item.get('seed_profile')}"
    return True, ""


def summarize_build_error(last_error: str, stdout_tail: str, stderr_tail: str) -> dict[str, str]:
    combined = "\n".join(x for x in [last_error, stdout_tail, stderr_tail] if x).strip()
    low = combined.lower()
    error_type = "build_failure_generic"
    if any(k in low for k in ["missing fuzz/build.py", "no such file", "file not found"]):
        error_type = "missing_file"
    elif any(k in low for k in ["undefined reference", "ld:", "linker", "collect2"]):
        error_type = "link_error"
    elif any(k in low for k in ["error:", "fatal error:", "compilation terminated", "clang", "gcc"]):
        error_type = "compile_error"
    elif any(k in low for k in ["traceback", "exception", "module not found", "syntaxerror"]):
        error_type = "script_error"

    evidence_lines = [ln.strip() for ln in combined.splitlines() if ln.strip()]
    evidence = "\n".join(evidence_lines[-12:])
    return {
        "error_type": error_type,
        "evidence": evidence,
    }


def classify_build_failure(
    last_error: str,
    stdout_tail: str,
    stderr_tail: str,
    *,
    build_rc: int,
    has_fuzzer_binaries: bool,
) -> tuple[str, str]:
    combined = "\n".join(x for x in [last_error, stdout_tail, stderr_tail] if x).strip()
    low = combined.lower()

    infra_checks: list[tuple[str, list[str]]] = [
        (
            "docker_daemon_unavailable",
            [
                "cannot connect to the docker daemon",
                "is the docker daemon running",
                "lookup sherpa-docker",
                "permission denied while trying to connect to the docker daemon",
                "error during connect",
            ],
        ),
        (
            "buildkit_unavailable",
            [
                "buildx component is missing or broken",
                "buildkit is enabled but the buildx component is missing or broken",
                "docker buildx",
            ],
        ),
        (
            "registry_dns_resolution_failed",
            [
                "temporary failure in name resolution",
                "lookup registry-1.docker.io",
                "server misbehaving",
            ],
        ),
        (
            "registry_tls_handshake_timeout",
            [
                "tls handshake timeout",
                "tls: handshake failure",
                "x509: certificate",
            ],
        ),
        (
            "registry_or_network_unavailable",
            [
                "failed to resolve source metadata",
                "dial tcp",
                "proxyconnect tcp",
                "connection refused",
                "i/o timeout",
                "connection reset by peer",
                "context deadline exceeded",
            ],
        ),
        (
            "resource_exhausted",
            [
                "no space left on device",
                "cannot allocate memory",
                "out of memory",
                "killed",
            ],
        ),
        (
            "build_command_timeout",
            [
                "[timeout] process exceeded limit and was killed",
                "process exceeded limit and was killed",
                "time budget exceeded",
            ],
        ),
    ]
    for code, needles in infra_checks:
        if any(n in low for n in needles):
            return "infra", code

    if build_rc == 0 and not has_fuzzer_binaries:
        return "source", "no_fuzzer_binaries"

    if "no rule to make target" in low:
        return "source", "build_strategy_mismatch"
    if "undefined reference to `main'" in low or "undefined reference to main" in low:
        return "source", "missing_fuzzer_main"
    if "undefined reference to `llvmfuzzertestoneinput" in low:
        return "source", "missing_llvmfuzzer_entrypoint"
    if "cannot find -lz" in low or "cannot find -l" in low:
        return "source", "missing_link_library"
    if "undefined reference to `gz" in low or "undefined reference to `inflate" in low:
        return "source", "missing_link_library"
    if "missing fuzz/build.py" in low:
        return "source", "missing_build_script"
    if any(k in low for k in ["no such file", "cannot find", "not found"]):
        return "source", "missing_source_file"
    if any(k in low for k in ["undefined reference", "ld:", "linker", "collect2"]):
        return "source", "link_error"
    if any(k in low for k in ["error:", "fatal error:", "compilation terminated", "clang", "gcc"]):
        return "source", "compile_error"
    if any(k in low for k in ["traceback", "exception", "module not found", "syntaxerror"]):
        return "source", "script_error"

    return "unknown", "unknown_build_failure"


def build_failure_recovery_advice(error_kind: str, error_code: str) -> str:
    if error_kind == "source":
        source_recovery: dict[str, str] = {
            "build_strategy_mismatch": (
                "Generated build scaffold appears to depend on a repository-provided fuzz target. "
                "Regenerate or repair fuzz/build.py to build the repository library/objects and "
                "link the generated harness externally instead of invoking a guessed fuzz target."
            ),
            "insufficient_repo_understanding": (
                "Generated scaffold lacks grounded repository-understanding metadata. "
                "Fill fuzz/repo_understanding.json with concrete build facts/evidence first, then "
                "align fuzz/build.py and build_strategy.json to that understanding."
            ),
            "missing_fuzzer_main": (
                "Fuzzer main/entrypoint is missing. Add `-fsanitize=fuzzer` or explicitly link a "
                "repo-provided main source as a normal source input, not as a repository fuzz target."
            ),
        }
        return source_recovery.get(error_code, "")
    if error_kind != "infra":
        return ""

    common = (
        "You can tune/disable retries via SHERPA_WORKFLOW_BUILD_LOCAL_RETRIES "
        "and SHERPA_DOCKER_BUILD_RETRIES if runtime becomes too long."
    )
    recovery: dict[str, str] = {
        "docker_daemon_unavailable": (
            "Docker daemon appears unreachable. Verify docker service is running, "
            "current user has permission to access /var/run/docker.sock, and retry. "
            + common
        ),
        "buildkit_unavailable": (
            "BuildKit/buildx is unavailable. Install/repair docker buildx plugin or "
            "temporarily set DOCKER_BUILDKIT=0 for classic builder fallback. "
            + common
        ),
        "registry_dns_resolution_failed": (
            "Registry DNS resolution failed. Check host/container DNS settings, "
            "configure stable resolvers (for example 8.8.8.8/1.1.1.1), and retry. "
            + common
        ),
        "registry_tls_handshake_timeout": (
            "Registry TLS handshake timed out. Check outbound HTTPS path/proxy, "
            "verify system clock/cert trust chain, and retry with network backoff. "
            + common
        ),
        "registry_or_network_unavailable": (
            "Container registry/network is unstable. Check proxy/firewall rules and "
            "egress connectivity to registry endpoints before retrying. "
            + common
        ),
        "resource_exhausted": (
            "Build host resources are exhausted. Free disk/memory (e.g., docker system prune) "
            "and retry. "
            + common
        ),
        "build_command_timeout": (
            "Build command timed out. Increase time budget or reduce retry counts for this run. "
            + common
        ),
    }
    return recovery.get(error_code, f"Infrastructure build failure detected ({error_code}). {common}")


def collect_key_artifact_hashes(repo_root: Path) -> dict[str, str]:
    pairs = [
        ("fuzz/targets.json", repo_root / "fuzz" / "targets.json"),
        ("fuzz/build.py", repo_root / "fuzz" / "build.py"),
        ("fuzz/PLAN.md", repo_root / "fuzz" / "PLAN.md"),
    ]
    out: dict[str, str] = {}
    for name, path in pairs:
        if not path.is_file():
            continue
        try:
            out[name] = sha256_text(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
    return out


def has_codex_key() -> bool:
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key and openai_key.strip():
        return True
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_key and openrouter_key.strip():
        return True
    try:
        cfg = load_config()
        if cfg.openai_api_key and cfg.openai_api_key.strip():
            return True
        if cfg.openrouter_api_key and cfg.openrouter_api_key.strip():
            return True
    except Exception:
        pass
    opencode_key = os.environ.get("OPENCODE_API_KEY")
    if opencode_key and opencode_key.strip():
        return True
    return False


def slug_from_repo_url(repo_url: str) -> str:
    base = repo_url.rstrip("/").split("/")[-1]
    if base.endswith(".git"):
        base = base[: -len(".git")]
    base = re.sub(r"[^a-zA-Z0-9._-]+", "-", base).strip("-")
    return base or "repo"


def alloc_output_workdir(repo_url: str) -> Path | None:
    out_root = os.environ.get("SHERPA_OUTPUT_DIR", "").strip()
    if not out_root:
        return None
    base = Path(out_root).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    slug = slug_from_repo_url(repo_url)
    return base / f"{slug}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Disk quota & cleanup helpers
# ---------------------------------------------------------------------------

def _output_root() -> Path | None:
    out_root = os.environ.get("SHERPA_OUTPUT_DIR", "").strip()
    if not out_root:
        return None
    return Path(out_root).expanduser().resolve()


def _get_output_dir_mtime(d: Path) -> float:
    try:
        return d.stat().st_mtime
    except OSError:
        return 0.0


def cleanup_old_output_dirs(
    *,
    retention_days: int | None = None,
    max_dirs: int | None = None,
    max_total_bytes: int | None = None,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Delete old output directories in ``SHERPA_OUTPUT_DIR``.

    Returns ``(deleted_count, freed_bytes)``.
    """
    root = _output_root()
    if root is None or not root.is_dir():
        return 0, 0

    if retention_days is None:
        try:
            retention_days = int(os.environ.get("SHERPA_OUTPUT_RETENTION_DAYS", "7"))
        except (ValueError, TypeError):
            retention_days = 7
    if max_dirs is None:
        try:
            max_dirs = int(os.environ.get("SHERPA_OUTPUT_MAX_DIRS", "0"))
        except (ValueError, TypeError):
            max_dirs = 0
    if max_total_bytes is None:
        try:
            max_total_gb = float(os.environ.get("SHERPA_OUTPUT_MAX_SIZE_GB", "0"))
            max_total_bytes = int(max_total_gb * 1024**3) if max_total_gb > 0 else 0
        except (ValueError, TypeError):
            max_total_bytes = 0

    # Collect directories with mtime and size
    entries: list[tuple[Path, float, int]] = []
    try:
        for p in root.iterdir():
            if not p.is_dir():
                continue
            try:
                mtime = _get_output_dir_mtime(p)
                # Fast size estimate: sum of st_size for top-level files only
                size = 0
                try:
                    for child in p.iterdir():
                        try:
                            if child.is_file():
                                size += child.stat().st_size
                            elif child.is_dir():
                                # One level deeper for dirs like "fuzz", "build"
                                try:
                                    for sub in child.iterdir():
                                        try:
                                            size += sub.stat().st_size
                                        except OSError:
                                            pass
                                except OSError:
                                    pass
                        except OSError:
                            pass
                except OSError:
                    pass
                entries.append((p, mtime, size))
            except OSError:
                pass
    except OSError:
        return 0, 0

    if not entries:
        return 0, 0

    now = time.time()
    cutoff = now - retention_days * 86400
    to_delete: set[Path] = set()

    # TTL-based: delete dirs older than retention_days
    for p, mtime, _size in entries:
        if mtime > 0 and mtime < cutoff:
            to_delete.add(p)

    # Count-based: keep only the most recent max_dirs
    if max_dirs > 0:
        entries_by_mtime = sorted(entries, key=lambda x: x[1], reverse=True)
        for p, _mtime, _size in entries_by_mtime[max_dirs:]:
            to_delete.add(p)

    # Size-based: delete oldest until under max_total_bytes
    if max_total_bytes > 0:
        total = sum(sz for _p, _mt, sz in entries)
        if total > max_total_bytes:
            entries_by_mtime = sorted(entries, key=lambda x: x[1])
            for p, _mtime, sz in entries_by_mtime:
                if total <= max_total_bytes:
                    break
                to_delete.add(p)
                total -= sz

    deleted_count = 0
    freed_bytes = 0
    for p in to_delete:
        if dry_run:
            deleted_count += 1
            continue
        try:
            # Estimate freed bytes before deletion (coarse)
            est = 0
            try:
                est = sum(
                    f.stat().st_size
                    for f in p.rglob("*")
                    if f.is_file()
                )
            except OSError:
                pass
            shutil.rmtree(p, ignore_errors=True)
            deleted_count += 1
            freed_bytes += est
        except OSError:
            pass

    return deleted_count, freed_bytes


def enforce_output_quota(
    *,
    min_free_bytes: int | None = None,
    max_total_bytes: int | None = None,
) -> None:
    """Check disk quota before starting a new job.

    Raises ``RuntimeError`` if disk is critically low even after cleanup.
    """
    if min_free_bytes is None:
        try:
            min_free_gb = float(os.environ.get("SHERPA_OUTPUT_MIN_FREE_GB", "5"))
            min_free_bytes = int(min_free_gb * 1024**3)
        except (ValueError, TypeError):
            min_free_bytes = 5 * 1024**3
    if max_total_bytes is None:
        try:
            max_total_gb = float(os.environ.get("SHERPA_OUTPUT_MAX_SIZE_GB", "50"))
            max_total_bytes = int(max_total_gb * 1024**3) if max_total_gb > 0 else 0
        except (ValueError, TypeError):
            max_total_bytes = 50 * 1024**3

    root = _output_root()
    if root is None:
        return  # No output dir configured, skip quota enforcement

    # Check free space on the filesystem
    try:
        usage = shutil.disk_usage(str(root))
        free_bytes = usage.free
    except OSError:
        return  # Can't check, skip

    # If free space is critically low, do an aggressive age-based cleanup first
    if free_bytes < min_free_bytes:
        cleanup_old_output_dirs(retention_days=1, max_dirs=0, max_total_bytes=0)

        # Re-check free space
        try:
            usage = shutil.disk_usage(str(root))
            free_bytes = usage.free
        except OSError:
            pass

    # If still critically low, do size-based cleanup
    if free_bytes < min_free_bytes and max_total_bytes > 0:
        cleanup_old_output_dirs(retention_days=0, max_dirs=0, max_total_bytes=max_total_bytes)

        try:
            usage = shutil.disk_usage(str(root))
            free_bytes = usage.free
        except OSError:
            pass

    if free_bytes < min_free_bytes:
        raise RuntimeError(
            f"Output disk quota exceeded: only {free_bytes / 1024**3:.1f} GB free "
            f"(minimum: {min_free_bytes / 1024**3:.1f} GB). "
            f"Please free disk space or adjust SHERPA_OUTPUT_MIN_FREE_GB."
        )


def prune_dind_resources(
    *,
    image_until: str = "2h",
    builder_until: str = "2h",
) -> tuple[int, int]:
    """Prune dangling Docker images and build cache inside the dind daemon.

    Returns ``(images_pruned_count, builder_pruned_bytes)``.

    This is safe to call from any workflow stage — it only removes
    *dangling* images (no tag) and expired build cache.
    """
    images_removed = 0
    builder_freed = 0

    # Prune dangling images (images with <none>:<none> tag)
    try:
        proc = subprocess.run(
            [
                "docker", "image", "prune", "--force",
                "--filter", f"until={image_until}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=120,
            check=False,
        )
        for line in (proc.stdout or "").splitlines():
            if "Total reclaimed space:" in line:
                # Parse the size from docker output
                import re as _re
                m = _re.search(r"Total reclaimed space:\s*([\d.]+[GMk]?B)", line)
                if m:
                    pass  # size is informational
        if proc.returncode == 0:
            # Count removed images from output lines like "deleted: sha256:..."
            images_removed = (proc.stdout or "").count("deleted:")
    except Exception:
        pass

    # Prune build cache
    try:
        proc = subprocess.run(
            [
                "docker", "builder", "prune", "--force",
                "--filter", f"until={builder_until}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=120,
            check=False,
        )
        if proc.returncode == 0:
            for line in (proc.stdout or "").splitlines():
                if "Total:" in line:
                    import re as _re
                    m = _re.search(r"Total:\s*([\d.]+[GMk]?B)", line)
                    if m:
                        val = m.group(1)
                        try:
                            if val.endswith("GB"):
                                builder_freed = int(float(val[:-2]) * 1024**3)
                            elif val.endswith("MB"):
                                builder_freed = int(float(val[:-2]) * 1024**2)
                            elif val.endswith("kB"):
                                builder_freed = int(float(val[:-2]) * 1024)
                            elif val.endswith("B"):
                                builder_freed = int(float(val[:-1]))
                        except (ValueError, TypeError):
                            pass
    except Exception:
        pass

    return images_removed, builder_freed


def _stop_runtime_containers_for_repo_root(repo_root: str) -> list[str]:
    """Stop (rm -f) all Docker containers associated with a repo root directory.

    Returns list of killed container IDs.
    """
    root = str(repo_root or "").strip()
    if not root:
        return []

    repo_sha1 = hashlib.sha1(root.encode("utf-8", errors="ignore")).hexdigest()
    killed: list[str] = []

    # Find containers by label or volume mount
    for filter_cmd in (
        ["ps", "-q", "--filter", f"label=sherpa.repo_root_sha1={repo_sha1}"],
        ["ps", "-q", "--filter", f"volume={root}"],
    ):
        try:
            proc = subprocess.run(
                ["docker", *filter_cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                errors="replace",
                timeout=15,
                check=False,
            )
            for line in (proc.stdout or "").splitlines():
                cid = line.strip()
                if cid:
                    try:
                        rc, _, _ = _docker_cli_inline(["rm", "-f", cid], timeout=20)
                        if rc == 0:
                            killed.append(cid)
                    except Exception:
                        pass
        except Exception:
            pass

    return killed


def _docker_cli_inline(args: list[str], *, timeout: int = 20) -> tuple[int, str, str]:
    """Minimal inline docker CLI runner (avoids circular import from main.py)."""
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


def enter_step(state: dict[str, Any], step_name: str) -> tuple[dict[str, Any], bool]:
    started_at = float(state.get("workflow_started_at") or time.time())
    time_budget = parse_budget_value(state.get("time_budget"), default=_DEFAULT_TIME_BUDGET_SEC)
    elapsed = time.time() - started_at
    if time_budget > 0 and elapsed >= time_budget:
        out = {
            **state,
            "last_step": step_name,
            "failed": True,
            "last_error": f"time budget exceeded: elapsed={elapsed:.1f}s budget={time_budget}s",
            "message": "workflow stopped (time budget exceeded)",
        }
        wf_log(out, f"<- {step_name} stop=time_budget elapsed={elapsed:.1f}s budget={time_budget}s")
        return out, True

    step_count = int(state.get("step_count") or 0) + 1
    raw_max_steps = state.get("max_steps")
    max_steps = int(raw_max_steps) if raw_max_steps is not None else 0
    next_state = {**state, "step_count": step_count}
    # max_steps <= 0 means unlimited workflow steps.
    if max_steps > 0 and step_count >= max_steps:
        failed = bool(next_state.get("last_error")) and not bool(next_state.get("crash_found"))
        out = {
            **next_state,
            "last_step": step_name,
            "failed": failed,
            "message": "workflow stopped (max steps reached)",
        }
        wf_log(out, f"<- {step_name} stop=max_steps")
        return out, True
    return next_state, False


def remaining_time_budget_sec(state: dict[str, Any], *, min_timeout: int = 5) -> int:
    _ = min_timeout
    started_at = float(state.get("workflow_started_at") or time.time())
    total_budget = parse_budget_value(state.get("time_budget"), default=_DEFAULT_TIME_BUDGET_SEC)
    if total_budget <= 0:
        return _UNLIMITED_TIME_BUDGET_SENTINEL_SEC
    elapsed = max(0.0, time.time() - started_at)
    remaining = int(total_budget - elapsed)
    if remaining <= 0:
        return 0
    return remaining


def time_budget_exceeded_state(state: dict[str, Any], *, step_name: str) -> dict[str, Any]:
    started_at = float(state.get("workflow_started_at") or time.time())
    time_budget = parse_budget_value(state.get("time_budget"), default=_DEFAULT_TIME_BUDGET_SEC)
    elapsed = max(0.0, time.time() - started_at)
    out = {
        **state,
        "last_step": step_name,
        "failed": True,
        "last_error": f"time budget exceeded: elapsed={elapsed:.1f}s budget={time_budget}s",
        "message": "workflow stopped (time budget exceeded)",
    }
    wf_log(out, f"<- {step_name} stop=time_budget elapsed={elapsed:.1f}s budget={time_budget}s")
    return out


def make_plan_hint(repo_root: Path) -> str:
    hints: list[str] = []
    plan_path = repo_root / "fuzz" / "PLAN.md"
    targets_path = repo_root / "fuzz" / "targets.json"

    if targets_path.is_file():
        try:
            raw = json.loads(targets_path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(raw, list) and raw:
                names = [str(it.get("name") or "").strip() for it in raw if isinstance(it, dict)]
                names = [n for n in names if n]
                if names:
                    hints.append(f"Prioritize targets in fuzz/targets.json: {', '.join(names[:3])}.")
        except Exception:
            pass

    if plan_path.is_file():
        try:
            for line in plan_path.read_text(encoding="utf-8", errors="replace").splitlines():
                s = line.strip()
                if s.startswith(("Primary fuzzer:", "Target:")):
                    hints.append(s)
                if len(hints) >= 3:
                    break
        except Exception:
            pass

    hints.extend(
        [
            "Keep harness deterministic and only touch fuzz/ plus minimal build glue.",
            "Ensure fuzz/build.py leaves at least one runnable fuzzer under fuzz/out/.",
        ]
    )
    return "\n".join(hints[:6])


def derive_plan_policy(repo_root: Path) -> tuple[bool, int]:
    fix_on_crash = True
    max_fix_rounds = 1
    plan_path = repo_root / "fuzz" / "PLAN.md"
    if not plan_path.is_file():
        return fix_on_crash, max_fix_rounds

    try:
        text = plan_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return fix_on_crash, max_fix_rounds

    m_policy = re.search(r"crash\s*policy\s*:\s*([^\n\r]+)", text, re.IGNORECASE)
    if m_policy:
        val = m_policy.group(1).strip().lower()
        if "report" in val or "triage" in val:
            fix_on_crash = False
        elif "fix" in val:
            fix_on_crash = True

    m_rounds = re.search(r"max\s*fix\s*rounds\s*:\s*(\d+)", text, re.IGNORECASE)
    if m_rounds:
        try:
            max_fix_rounds = max(0, int(m_rounds.group(1)))
        except Exception:
            pass

    return fix_on_crash, max_fix_rounds


_OPENCODE_PROMPT_FILE = Path(__file__).resolve().parent / "prompts" / "opencode_prompts.md"


@lru_cache(maxsize=1)
def load_opencode_prompt_templates() -> dict[str, str]:
    if not _OPENCODE_PROMPT_FILE.is_file():
        raise RuntimeError(f"OpenCode prompt template file not found: {_OPENCODE_PROMPT_FILE}")
    text = _OPENCODE_PROMPT_FILE.read_text(encoding="utf-8", errors="replace")
    pattern = re.compile(
        r"<!--\s*TEMPLATE:\s*([a-zA-Z0-9_]+)\s*-->\s*(.*?)\s*<!--\s*END TEMPLATE\s*-->",
        re.DOTALL,
    )
    templates: dict[str, str] = {}
    for name, body in pattern.findall(text):
        templates[name.strip().lower()] = body.strip()
    if not templates:
        raise RuntimeError(f"No templates found in {_OPENCODE_PROMPT_FILE}")
    return templates


def render_opencode_prompt(name: str, **kwargs: object) -> str:
    templates = load_opencode_prompt_templates()
    key = name.strip().lower()
    if key not in templates:
        raise RuntimeError(f"OpenCode prompt template '{name}' not found in {_OPENCODE_PROMPT_FILE}")
    out = templates[key]
    for k, v in kwargs.items():
        out = out.replace("{{" + k + "}}", str(v))
    return out.strip() + "\n"
