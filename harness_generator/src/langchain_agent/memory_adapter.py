"""MemoryAdapter — Sherpa's MCP client for GBrain long-term memory."""

from __future__ import annotations
import asyncio
import json
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from loguru import logger

from memory.schemas import CrashPage, SessionPage
from memory.slug_resolver import (
    crash_slug,
    repo_url_to_slug,
    session_slug,
)
from memory.suggestion_builder import (
    Suggestion,
    build_suggestion,
)


@dataclass
class WriteOp:
    """A single batch write operation."""
    kind: str  # "put_page" | "add_link" | "add_timeline"
    payload: dict[str, Any]


@dataclass
class BatchResult:
    ok: list[int] = field(default_factory=list)
    failed: list[int] = field(default_factory=list)
    errors: dict[int, str] = field(default_factory=dict)

    @property
    def all_ok(self) -> bool:
        return len(self.failed) == 0


@dataclass
class SessionData:
    """Aggregated data for memory-summarize node."""
    repo_url: str = ""
    session_id: str = ""
    started_at: str = ""
    ended_at: str = ""
    stages_completed: list[str] = field(default_factory=list)
    total_harnesses: int = 0
    total_crashes: int = 0
    coverage_start: float = 0.0
    coverage_end: float = 0.0
    crashes: list[dict[str, Any]] = field(default_factory=list)
    harnesses: list[dict[str, Any]] = field(default_factory=list)
    strategies_used: list[str] = field(default_factory=list)

    @classmethod
    def from_workflow_state(cls, state: dict[str, Any]) -> "SessionData":
        return cls(
            repo_url=str(state.get("repo_url", "")),
            session_id=str(state.get("job_id", state.get("session_id", ""))),
            started_at=str(state.get("workflow_started_at", "")),
            ended_at=str(time.time()),
            stages_completed=list(state.get("completed_stages", [])),
            total_harnesses=int(state.get("total_harnesses", 0)),
            total_crashes=int(state.get("total_crashes", 0)),
            coverage_start=float(state.get("coverage_start", 0.0)),
            coverage_end=float(state.get("coverage_last_max_cov", 0.0)),
        )


class MemoryAdapter:
    """MCP client for GBrain long-term memory.

    Starts gbrain serve as a stdio subprocess on first use and communicates
    via JSON-RPC.  Query timeouts and write failures never block the fuzz
    workflow — every error path returns a safe sentinel.

    Call ``await adapter.close()`` to terminate the subprocess, or let the
    event loop call the synchronous ``_cleanup()`` fallback via ``__del__``.
    """

    def __init__(self, gbrain_command: str = "gbrain", gbrain_args: list[str] | None = None):
        self._gbrain_command: str = gbrain_command
        self._gbrain_args: list[str] = gbrain_args or ["serve"]
        self._proc: Optional[subprocess.Popen] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._request_id: int = 0
        self._call_lock: asyncio.Lock = asyncio.Lock()
        self._start_lock: asyncio.Lock = asyncio.Lock()

    # ── process lifecycle ────────────────────────────────────────────

    async def _ensure_running(self) -> None:
        """Start gbrain serve subprocess if not already running (thread-safe)."""
        if self._proc is not None and self._proc.poll() is None:
            return

        async with self._start_lock:
            # Double-check under the lock
            if self._proc is not None and self._proc.poll() is None:
                return

            logger.info("Starting GBrain MCP server: {} {}", self._gbrain_command, " ".join(self._gbrain_args))
            try:
                self._proc = subprocess.Popen(
                    [self._gbrain_command] + self._gbrain_args,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                # Drain stderr in a daemon thread to prevent pipe-buffer deadlock
                self._stderr_thread = threading.Thread(
                    target=self._drain_stderr,
                    daemon=True,
                )
                self._stderr_thread.start()

                await asyncio.sleep(0.5)
                logger.info("GBrain MCP server started (pid={})", self._proc.pid)
            except FileNotFoundError:
                logger.warning("gbrain command not found — memory features disabled")
                self._proc = None
            except Exception as exc:
                logger.warning("Failed to start GBrain MCP server: {}", exc)
                self._proc = None

    def _drain_stderr(self) -> None:
        """Continuously read and discard stderr lines to prevent buffer deadlock."""
        if self._proc is None or self._proc.stderr is None:
            return
        try:
            for _line in self._proc.stderr:
                pass
        except Exception:
            pass

    async def close(self) -> None:
        """Terminate the gbrain subprocess and release resources."""
        async with self._start_lock:
            proc, self._proc = self._proc, None
            if proc is not None:
                try:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
                except Exception as exc:
                    logger.warning("Error terminating GBrain subprocess: {}", exc)
                finally:
                    try:
                        if proc.stdin:
                            proc.stdin.close()
                        if proc.stdout:
                            proc.stdout.close()
                        if proc.stderr:
                            proc.stderr.close()
                    except Exception:
                        pass

    def __del__(self) -> None:
        """Best-effort cleanup — prefer explicit ``await adapter.close()``."""
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    # ── JSON-RPC core ────────────────────────────────────────────────

    async def _call_tool(self, tool_name: str, arguments: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
        """Call a GBrain MCP tool via JSON-RPC over stdio."""
        await self._ensure_running()
        if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
            return {"error": "GBrain MCP server not running"}

        async with self._call_lock:
            self._request_id += 1
            request = {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            }
            try:
                payload = json.dumps(request) + "\n"
                self._proc.stdin.write(payload)
                self._proc.stdin.flush()
            except Exception as exc:
                logger.warning("GBrain MCP write error: {}", exc)
                return {"error": str(exc)}

            try:
                line = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, self._proc.stdout.readline),
                    timeout=timeout,
                )
                if not line:
                    return {"error": "No response from GBrain MCP server"}
                resp = json.loads(line)
                # Propagate JSON-RPC protocol-level errors
                if "error" in resp:
                    err = resp["error"]
                    return {"error": f"JSON-RPC error {err.get('code', '')}: {err.get('message', '')}"}
                return resp.get("result", {})
            except asyncio.TimeoutError:
                logger.warning("GBrain MCP call {} timed out after {}s", tool_name, timeout)
                return {"error": f"timeout after {timeout}s"}
            except json.JSONDecodeError:
                return {"error": "Invalid JSON response from GBrain"}
            except Exception as exc:
                logger.warning("GBrain MCP call {} error: {}", tool_name, exc)
                return {"error": str(exc)}

    # ── Query methods ────────────────────────────────────────────────

    async def query_experience(self, query: str, timeout: float = 5.0) -> list[dict[str, Any]]:
        """Hybrid search GBrain for relevant past experience."""
        result = await self._call_tool("query", {
            "query": query,
            "max_results": 5,
        }, timeout=timeout)
        if "error" in result:
            logger.warning("query_experience failed: {}", result["error"])
            return []
        return result.get("results", result.get("hits", []))

    async def list_pages(self, type_prefix: str = "", limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """List pages by type prefix. Falls back to query_experience if gbrain lacks list_pages tool."""
        result = await self._call_tool("list_pages", {
            "prefix": type_prefix,
            "limit": limit,
            "offset": offset,
        })
        if "error" in result:
            logger.debug("list_pages tool not available, falling back to query_experience: {}", result["error"])
            return await self.query_experience(f"type:{type_prefix}" if type_prefix else "", timeout=5.0)
        return result.get("pages", result.get("results", []))

    async def delete_page(self, slug: str) -> bool:
        """Delete a page by slug. Falls back to writing empty content if gbrain lacks delete_page tool."""
        result = await self._call_tool("delete_page", {"slug": slug})
        if "error" in result:
            logger.debug("delete_page tool not available, falling back to soft-delete: {}", result["error"])
            return await self.write_page(slug, {"deleted": True, "type": "fuzz/deleted"}, "")
        return "error" not in result

    async def get_page(self, slug: str) -> dict[str, Any] | None:
        """Read a single page by slug."""
        result = await self._call_tool("get_page", {"slug": slug})
        if "error" in result:
            return None
        return result

    async def get_target_profile(self, repo_url: str) -> dict[str, Any] | None:
        """Read the accumulated target-repo profile page."""
        slug = repo_url_to_slug(repo_url)
        return await self.get_page(slug)

    async def find_similar_crashes(self, signature: str) -> list[dict[str, Any]]:
        """Search for historically similar crashes by signature."""
        if not signature.strip():
            return []
        return await self.query_experience(f"crash signature: {signature}")

    async def suggest_strategies(self, language: str, module: str) -> list[dict[str, Any]]:
        """Query strategies that worked on similar targets."""
        if not language.strip() and not module.strip():
            return []
        return await self.query_experience(
            f"fuzz strategy for {language} targeting {module}"
        )

    # ── Write methods ────────────────────────────────────────────────

    async def write_page(
        self, slug: str, frontmatter: dict[str, Any],
        compiled_truth: str, timeline: list[str] | None = None,
    ) -> bool:
        """Write (upsert) a page to GBrain."""
        content = compiled_truth
        if timeline:
            content += "\n\n---\n\n" + "\n".join(f"- {t}" for t in timeline)

        result = await self._call_tool("put_page", {
            "slug": slug,
            "content": content,
            "frontmatter": frontmatter,
        })
        if "error" in result:
            logger.warning("write_page({}) failed: {}", slug, result["error"])
            return False
        return True

    async def add_timeline(self, slug: str, entry: str) -> bool:
        """Append a timeline entry to a page."""
        result = await self._call_tool("add_timeline_entry", {
            "slug": slug,
            "date": time.strftime("%Y-%m-%d"),
            "summary": entry,
        })
        return "error" not in result

    async def add_link(self, from_slug: str, to_slug: str, link_type: str, source: str = "sherpa") -> bool:
        """Create a typed link between two pages."""
        result = await self._call_tool("add_link", {
            "from": from_slug,
            "to": to_slug,
            "link_type": link_type,
            "source": source,
        })
        return "error" not in result

    # ── Batch write ──────────────────────────────────────────────────

    async def batch_write(self, ops: list[WriteOp], max_retries: int = 3) -> BatchResult:
        """Execute multiple write operations sequentially with retry."""
        result = BatchResult()
        for i, op in enumerate(ops):
            for attempt in range(max_retries):
                ok = False
                if op.kind == "put_page":
                    ok = await self.write_page(**op.payload)
                elif op.kind == "add_link":
                    ok = await self.add_link(**op.payload)
                elif op.kind == "add_timeline":
                    ok = await self.add_timeline(**op.payload)

                if ok:
                    result.ok.append(i)
                    break
                if attempt == max_retries - 1:
                    result.failed.append(i)
                    result.errors[i] = f"failed after {max_retries} retries"
                else:
                    await asyncio.sleep(1.0 * (attempt + 1))
        return result

    # ── Suggestions ──────────────────────────────────────────────────

    async def get_suggestions(self, node: str, ctx: dict[str, Any]) -> Suggestion | None:
        """Query GBrain and build a structured suggestion for a workflow node."""
        queries: dict[str, str] = {
            "plan": f"fuzz strategy and attack surface for {ctx.get('repo_url', '')} language {ctx.get('repo_language', '')}",
            "crash-triage": f"crash classification {ctx.get('crash_signature', '')}",
            "crash-analysis": f"vulnerability root cause analysis {ctx.get('crash_signature', '')}",
            "coverage-analysis": f"coverage improvement strategy for {ctx.get('repo_url', '')}",
        }
        query = queries.get(node)
        if not query:
            return None

        try:
            raw = await self.query_experience(query, timeout=5.0)
        except Exception as exc:
            logger.warning("get_suggestions({}) error: {}", node, exc)
            return None

        suggestion = build_suggestion(node, query, raw, ctx)
        if suggestion.is_actionable():
            logger.info("GBrain suggestion for {}: relevance={}", node, suggestion.relevance)
            return suggestion
        return None

    # ── Session summarization ────────────────────────────────────────

    async def summarize_session(self, session: SessionData) -> str:
        """Aggregate session data and write structured summary to GBrain.

        Returns the session page slug on success, empty string on failure.
        """
        target_slug = repo_url_to_slug(session.repo_url)
        sess_slug = session_slug(session.repo_url, session.session_id)

        logger.info("memory-summarize: writing session {} for {}", sess_slug, target_slug)

        # Build frontmatter via the canonical schemas dataclass
        session_page = SessionPage(
            repo=target_slug,
            session_id=session.session_id,
            started_at=session.started_at,
            ended_at=session.ended_at,
            stages_completed=session.stages_completed,
            total_harnesses=session.total_harnesses,
            total_crashes=session.total_crashes,
            coverage_start=session.coverage_start,
            coverage_end=session.coverage_end,
        )
        session_fm = session_page.to_frontmatter()
        session_fm["type"] = "fuzz/session"
        session_fm["title"] = f"Fuzz Session {session.session_id[:12]}"
        session_fm["tags"] = ["fuzz", "session"]

        compiled_truth = (
            f"## Session Overview\n\n"
            f"- Target: {session.repo_url}\n"
            f"- Stages completed: {', '.join(session.stages_completed)}\n"
            f"- Harnesses generated: {session.total_harnesses}\n"
            f"- Crashes found: {session.total_crashes}\n"
            f"- Coverage: {session.coverage_start:.1f}% → {session.coverage_end:.1f}%\n"
        )
        ok = await self.write_page(sess_slug, session_fm, compiled_truth)
        if not ok:
            logger.error("Failed to write session page {}", sess_slug)
            return ""

        await self.add_link(sess_slug, target_slug, "source")

        for crash in session.crashes:
            crash_id = str(crash.get("id", ""))
            if not crash_id:
                continue
            c_slug = crash_slug(session.repo_url, crash_id)
            crash_page = CrashPage(
                repo=target_slug,
                session=sess_slug,
                crash_signature=str(crash.get("signature", "")),
                crash_type=str(crash.get("crash_type", "")),
                verdict=str(crash.get("verdict", "inconclusive")),
                severity=str(crash.get("severity", "medium")),
                discovered_at=str(crash.get("discovered_at", session.ended_at)),
            )
            crash_fm = crash_page.to_frontmatter()
            crash_fm["type"] = "fuzz/crash"
            crash_fm["title"] = f"Crash {str(crash.get('signature', crash_id))[:60]}"
            crash_fm["tags"] = ["crash", str(crash.get('crash_type', ''))]

            crash_body = (
                f"## Verdict\n\n{crash.get('verdict', 'inconclusive')}\n\n"
                f"## Analysis\n\n{crash.get('reason', '')}\n"
            )
            await self.write_page(c_slug, crash_fm, crash_body)
            await self.add_link(c_slug, sess_slug, "discovered_in")
            await self.add_link(c_slug, target_slug, "found_in_repo")

        logger.info("memory-summarize: {} completed", sess_slug)
        return sess_slug
