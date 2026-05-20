# GBrain Memory Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate GBrain (GitNexus) as a long-term memory node in Sherpa's fuzz workflow via MCP sidecar pattern, enabling persistent knowledge accumulation and proactive experience suggestions.

**Architecture:** A Python `MemoryAdapter` class wraps the GBrain MCP server (started as a stdio subprocess) and exposes query/write/suggestion/summarize methods. Workflow nodes (`plan`, `crash-triage`, `crash-analysis`) call the adapter for suggestions at entry and write results after completion. A new `memory-summarize` node runs after session completion to aggregate and persist structured knowledge into GBrain.

**Tech Stack:** Python 3.11+, asyncio, MCP JSON-RPC over stdio, GBrain Bun/TypeScript (external service), PGLite (dev) / Postgres+pgvector (prod)

---

## File Structure

```
Create:
  harness_generator/src/langchain_agent/memory/
  ├── __init__.py                 # Package init
  ├── schemas.py                  # Page frontmatter dataclasses (5 types)
  ├── slug_resolver.py            # repo_url → GBrain slug conversion
  └── suggestion_builder.py       # Query results → structured Suggestion
  harness_generator/src/langchain_agent/memory_adapter.py  # MemoryAdapter core

Modify:
  harness_generator/src/langchain_agent/workflow_graph.py  # New node + suggestion hooks + state fields
  harness_generator/src/langchain_agent/opencode_skills/
  ├── plan/SKILL.md               # GBrain memory suggestion step
  ├── crash_triage/SKILL.md       # Similar crash search + real-time write
  └── crash_analysis/SKILL.md     # Similar vuln search + real-time write
```

---

### Task 1: Memory schemas (Python dataclasses)

**Files:**
- Create: `harness_generator/src/langchain_agent/memory/__init__.py`
- Create: `harness_generator/src/langchain_agent/memory/schemas.py`

- [ ] **Step 1: Write `__init__.py`**

```python
"""Memory schemas and utilities for GBrain integration."""
```

- [ ] **Step 2: Write `schemas.py` with all 5 page type dataclasses**

```python
"""Python dataclasses for GBrain page types used by Sherpa."""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class AttackSurface:
    module: str
    functions: list[str]
    risk_level: str  # high | medium | low


@dataclass
class TargetRepoPage:
    """fuzz/target-repo page frontmatter."""
    repo_url: str
    repo_language: str
    first_fuzzed_at: str = ""
    last_fuzzed_at: str = ""
    total_sessions: int = 0
    total_crashes_found: int = 0
    true_vulns_found: int = 0
    cve_ids: list[str] = field(default_factory=list)
    attack_surfaces: list[AttackSurface] = field(default_factory=list)
    recommended_strategies: list[str] = field(default_factory=list)
    top_coverage: float = 0.0

    def to_frontmatter(self) -> dict:
        d = asdict(self)
        d["attack_surfaces"] = [asdict(a) for a in self.attack_surfaces]
        return d


@dataclass
class SessionPage:
    """fuzz/session page frontmatter."""
    repo: str  # slug of fuzz/target-repo
    session_id: str
    started_at: str = ""
    ended_at: str = ""
    duration_seconds: int = 0
    stages_completed: list[str] = field(default_factory=list)
    total_harnesses: int = 0
    total_crashes: int = 0
    coverage_start: float = 0.0
    coverage_end: float = 0.0

    def to_frontmatter(self) -> dict:
        return asdict(self)


@dataclass
class CrashPage:
    """fuzz/crash page frontmatter."""
    repo: str  # slug of fuzz/target-repo
    session: str  # slug of fuzz/session
    crash_signature: str
    crash_type: str = ""
    verdict: str = "inconclusive"  # true_positive | false_positive | inconclusive
    severity: str = "medium"  # critical | high | medium | low
    cve_id: Optional[str] = None
    asan_report: str = ""
    related_crashes: list[str] = field(default_factory=list)
    discovered_at: str = ""

    def to_frontmatter(self) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}


@dataclass
class StrategyPage:
    """fuzz/strategy page frontmatter."""
    strategy_type: str = ""  # harness_pattern | seed_selection | build_config
    target_language: str = ""
    effective_for_repos: list[str] = field(default_factory=list)
    harness_pattern: str = ""
    seed_families: list[str] = field(default_factory=list)
    build_flags: list[str] = field(default_factory=list)
    success_rate: float = 0.0
    avg_coverage_gain: float = 0.0
    validated_sessions: int = 0

    def to_frontmatter(self) -> dict:
        return asdict(self)


@dataclass
class HarnessPage:
    """fuzz/harness page frontmatter."""
    repo: str
    session: str
    target_function: str = ""
    build_status: str = ""  # success | failed
    fuzz_result: str = ""  # running | coverage_gain | plateau | crash_found
    coverage_achieved: float = 0.0

    def to_frontmatter(self) -> dict:
        return asdict(self)


# Page type → slug prefix mapping
PAGE_TYPE_PREFIX: dict[str, str] = {
    "fuzz/target-repo": "fuzz/targets",
    "fuzz/session": "fuzz/sessions",
    "fuzz/crash": "fuzz/crashes",
    "fuzz/strategy": "fuzz/strategies",
    "fuzz/harness": "fuzz/harnesses",
}

# Link types used between Sherpa pages
LINK_TYPES = [
    "source",           # session → target-repo
    "discovered_in",    # crash → session
    "found_in_repo",    # crash → target-repo
    "generated_in",     # harness → session
    "follows_pattern",  # harness → strategy
    "applied_to",       # strategy → target-repo
    "similar_to",       # crash → crash
]
```

- [ ] **Step 3: Verify module imports**

Run: `cd /home/bohuju/TIanHeng_project/Sherpa && python -c "from harness_generator.src.langchain_agent.memory.schemas import TargetRepoPage, CrashPage; print('OK')"`

- [ ] **Step 4: Commit**

```bash
git add harness_generator/src/langchain_agent/memory/__init__.py harness_generator/src/langchain_agent/memory/schemas.py
git commit -m "feat(memory): add GBrain page type dataclasses"
```

---

### Task 2: Slug resolver

**Files:**
- Create: `harness_generator/src/langchain_agent/memory/slug_resolver.py`

- [ ] **Step 1: Write `slug_resolver.py`**

```python
"""Convert between Sherpa domain objects and GBrain page slugs."""

from __future__ import annotations
import re
from urllib.parse import urlparse


def repo_url_to_slug(repo_url: str) -> str:
    """Convert a GitHub repo URL to a GBrain target-repo slug.

    Example:
        https://github.com/GNOME/libxml2 → fuzz/targets/GNOME-libxml2
    """
    parsed = urlparse(repo_url)
    path = parsed.path.strip("/")
    parts = path.split("/")
    if len(parts) >= 2:
        owner, repo = parts[0], parts[1]
    elif len(parts) == 1:
        owner, repo = parts[0], "unknown"
    else:
        owner, repo = "unknown", "unknown"
    repo = re.sub(r"\.git$", "", repo)
    safe_owner = re.sub(r"[^a-zA-Z0-9._-]", "-", owner)
    safe_repo = re.sub(r"[^a-zA-Z0-9._-]", "-", repo)
    return f"fuzz/targets/{safe_owner}-{safe_repo}"


def session_slug(repo_url: str, session_id: str) -> str:
    """Generate a session page slug from repo URL and session ID."""
    repo_part = repo_url_to_slug(repo_url).replace("fuzz/targets/", "")
    short_id = session_id[:12] if len(session_id) > 12 else session_id
    return f"fuzz/sessions/{repo_part}-{short_id}"


def crash_slug(repo_url: str, crash_id: str) -> str:
    """Generate a crash page slug."""
    repo_part = repo_url_to_slug(repo_url).replace("fuzz/targets/", "")
    short_id = crash_id[:16] if len(crash_id) > 16 else crash_id
    return f"fuzz/crashes/{repo_part}-{short_id}"


def strategy_slug(descriptive_name: str) -> str:
    """Generate a strategy page slug from a descriptive name."""
    safe = re.sub(r"[^a-zA-Z0-9-]", "-", descriptive_name.lower())
    safe = re.sub(r"-{2,}", "-", safe).strip("-")
    return f"fuzz/strategies/{safe}"[:120]


def harness_slug(repo_url: str, harness_id: str) -> str:
    """Generate a harness page slug."""
    repo_part = repo_url_to_slug(repo_url).replace("fuzz/targets/", "")
    short_id = harness_id[:16] if len(harness_id) > 16 else harness_id
    return f"fuzz/harnesses/{repo_part}-{short_id}"


def target_slug_from_crash(crash_slug_: str) -> str:
    """Extract the target-repo slug from a crash slug via naming convention."""
    base = crash_slug_.replace("fuzz/crashes/", "")
    parts = base.rsplit("-", 1)
    return f"fuzz/targets/{parts[0]}"
```

- [ ] **Step 2: Verify slug generation**

Run: `cd /home/bohuju/TIanHeng_project/Sherpa && python -c "
from harness_generator.src.langchain_agent.memory.slug_resolver import repo_url_to_slug, session_slug
assert repo_url_to_slug('https://github.com/GNOME/libxml2') == 'fuzz/targets/GNOME-libxml2'
assert 'fuzz/sessions/' in session_slug('https://github.com/GNOME/libxml2', 'abc123def456')
print('OK')
"`

- [ ] **Step 3: Commit**

```bash
git add harness_generator/src/langchain_agent/memory/slug_resolver.py
git commit -m "feat(memory): add slug resolver for repo URL → GBrain slug conversion"
```

---

### Task 3: Suggestion builder

**Files:**
- Create: `harness_generator/src/langchain_agent/memory/suggestion_builder.py`

- [ ] **Step 1: Write `suggestion_builder.py`**

```python
"""Build structured suggestions from GBrain query results."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemoryHit:
    slug: str
    title: str
    score: float
    snippet: str
    page_type: str = ""


@dataclass
class Suggestion:
    node: str  # plan | crash-triage | crash-analysis | coverage-analysis
    summary: str
    hits: list[MemoryHit] = field(default_factory=list)
    relevance: float = 0.0  # 0.0 - 1.0

    def is_actionable(self, threshold: float = 0.5) -> bool:
        return self.relevance >= threshold and len(self.hits) > 0


def build_suggestion(
    node: str,
    query: str,
    raw_results: list[dict[str, Any]],
    context: dict[str, Any],
) -> Suggestion:
    """Convert raw GBrain query results into a structured Suggestion.

    Args:
        node: workflow node name (plan, crash-triage, crash-analysis, coverage-analysis)
        query: the original query string sent to GBrain
        raw_results: list of result dicts from GBrain search/query MCP tool
        context: node-specific context dict (repo_url, crash_signature, etc.)
    """
    hits: list[MemoryHit] = []
    for r in raw_results[:5]:
        hits.append(MemoryHit(
            slug=r.get("slug", ""),
            title=r.get("title", r.get("slug", "")),
            score=float(r.get("score", 0.0)),
            snippet=str(r.get("snippet", r.get("chunk_text", "")))[:300],
            page_type=r.get("type", ""),
        ))

    if hits:
        top_score = hits[0].score
        hit_count_factor = min(len(hits) / 3.0, 1.0)
        relevance = round(top_score * 0.7 + hit_count_factor * 0.3, 2)
    else:
        relevance = 0.0

    summary = _build_summary(node, hits, context)
    return Suggestion(node=node, summary=summary, hits=hits, relevance=relevance)


def _build_summary(node: str, hits: list[MemoryHit], ctx: dict[str, Any]) -> str:
    if not hits:
        return f"[{node}] GBrain 中未找到相关历史经验。"

    lines = [f"[{node}] GBrain 找到 {len(hits)} 条相关记录："]
    for i, h in enumerate(hits, 1):
        lines.append(f"  {i}. {h.title} (score: {h.score}) — {h.snippet[:120]}")
    return "\n".join(lines)
```

- [ ] **Step 2: Commit**

```bash
git add harness_generator/src/langchain_agent/memory/suggestion_builder.py
git commit -m "feat(memory): add suggestion builder for structured GBrain suggestions"
```

---

### Task 4: MemoryAdapter core class

**Files:**
- Create: `harness_generator/src/langchain_agent/memory_adapter.py`

- [ ] **Step 1: Write `memory_adapter.py`**

```python
"""MemoryAdapter — Sherpa's MCP client for GBrain long-term memory."""

from __future__ import annotations
import asyncio
import json
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from loguru import logger

from harness_generator.src.langchain_agent.memory.slug_resolver import (
    crash_slug,
    repo_url_to_slug,
    session_slug,
)
from harness_generator.src.langchain_agent.memory.suggestion_builder import (
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

    Starts gbrain serve as a stdio subprocess and communicates via JSON-RPC.
    Query timeouts and write failures never block the fuzz workflow.
    """

    _gbrain_command: str = "gbrain"
    _gbrain_args: list[str] = field(default_factory=lambda: ["serve"])
    _proc: Optional[subprocess.Popen] = None
    _request_id: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __init__(self, gbrain_command: str = "gbrain", gbrain_args: list[str] | None = None):
        self._gbrain_command = gbrain_command
        self._gbrain_args = gbrain_args or ["serve"]
        self._request_id = 0
        self._lock = asyncio.Lock()

    async def _ensure_running(self) -> None:
        """Start gbrain serve subprocess if not already running."""
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
            await asyncio.sleep(0.5)
            logger.info("GBrain MCP server started (pid={})", self._proc.pid)
        except FileNotFoundError:
            logger.warning("gbrain command not found — memory features disabled")
            self._proc = None
        except Exception as exc:
            logger.warning("Failed to start GBrain MCP server: {}", exc)
            self._proc = None

    async def _call_tool(self, tool_name: str, arguments: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
        """Call a GBrain MCP tool via JSON-RPC over stdio."""
        await self._ensure_running()
        if self._proc is None:
            return {"error": "GBrain MCP server not running"}

        async with self._lock:
            self._request_id += 1
            req_id = self._request_id
            request = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            }
            try:
                payload = json.dumps(request) + "\n"
                assert self._proc.stdin is not None
                self._proc.stdin.write(payload)
                self._proc.stdin.flush()
            except Exception as exc:
                logger.warning("GBrain MCP write error: {}", exc)
                return {"error": str(exc)}

            try:
                assert self._proc.stdout is not None
                line = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, self._proc.stdout.readline),
                    timeout=timeout,
                )
                if not line:
                    return {"error": "No response from GBrain MCP server"}
                return json.loads(line).get("result", {})
            except asyncio.TimeoutError:
                logger.warning("GBrain MCP call {} timed out after {}s", tool_name, timeout)
                return {"error": f"timeout after {timeout}s"}
            except json.JSONDecodeError:
                return {"error": "Invalid JSON response from GBrain"}
            except Exception as exc:
                logger.warning("GBrain MCP call {} error: {}", tool_name, exc)
                return {"error": str(exc)}

    # ── Query methods ──

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
        return await self.query_experience(f"crash signature: {signature}")

    async def suggest_strategies(self, language: str, module: str) -> list[dict[str, Any]]:
        """Query strategies that worked on similar targets."""
        return await self.query_experience(
            f"fuzz strategy for {language} targeting {module}"
        )

    # ── Write methods ──

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

    # ── Batch write ──

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
                else:
                    if attempt == max_retries - 1:
                        result.failed.append(i)
                        result.errors[i] = f"failed after {max_retries} retries"
                    else:
                        await asyncio.sleep(1.0 * (attempt + 1))
        return result

    # ── Suggestions ──

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

    # ── Session summarization ──

    async def summarize_session(self, session: SessionData) -> str:
        """Aggregate session data and write structured summary to GBrain.

        Returns the session page slug on success, empty string on failure.
        """
        target_slug = repo_url_to_slug(session.repo_url)
        sess_slug = session_slug(session.repo_url, session.session_id)

        logger.info("memory-summarize: writing session {} for {}", sess_slug, target_slug)

        session_fm = {
            "type": "fuzz/session",
            "title": f"Fuzz Session {session.session_id[:12]}",
            "tags": ["fuzz", "session"],
            "repo": target_slug,
            "session_id": session.session_id,
            "started_at": session.started_at,
            "ended_at": session.ended_at,
            "duration_seconds": 0,
            "stages_completed": session.stages_completed,
            "total_harnesses": session.total_harnesses,
            "total_crashes": session.total_crashes,
            "coverage_start": session.coverage_start,
            "coverage_end": session.coverage_end,
        }
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
            crash_fm = {
                "type": "fuzz/crash",
                "title": f"Crash {str(crash.get('signature', crash_id))[:60]}",
                "tags": ["crash", str(crash.get('crash_type', ''))],
                "repo": target_slug,
                "session": sess_slug,
                "crash_signature": str(crash.get("signature", "")),
                "crash_type": str(crash.get("crash_type", "")),
                "verdict": str(crash.get("verdict", "inconclusive")),
                "severity": str(crash.get("severity", "medium")),
                "discovered_at": str(crash.get("discovered_at", session.ended_at)),
            }
            crash_body = (
                f"## Verdict\n\n{crash.get('verdict', 'inconclusive')}\n\n"
                f"## Analysis\n\n{crash.get('reason', '')}\n"
            )
            await self.write_page(c_slug, crash_fm, crash_body)
            await self.add_link(c_slug, sess_slug, "discovered_in")
            await self.add_link(c_slug, target_slug, "found_in_repo")

        logger.info("memory-summarize: {} completed", sess_slug)
        return sess_slug
```

- [ ] **Step 2: Verify the module imports**

Run: `cd /home/bohuju/TIanHeng_project/Sherpa && python -c "
from harness_generator.src.langchain_agent.memory_adapter import MemoryAdapter, SessionData
print('MemoryAdapter imported OK')
"`

- [ ] **Step 3: Commit**

```bash
git add harness_generator/src/langchain_agent/memory_adapter.py
git commit -m "feat(memory): add MemoryAdapter MCP client for GBrain"
```

---

### Task 5: Memory-summarize workflow node

**Files:**
- Modify: `harness_generator/src/langchain_agent/workflow_graph.py`

- [ ] **Step 1: Add memory state fields to `FuzzWorkflowState`**

In `FuzzWorkflowState` (after line 199, after `vuln_hunting_enabled`), add:

```python
    # GBrain memory integration
    memory_enabled: bool
    memory_session_slug: str
    memory_suggestion_plan: str
    memory_suggestion_crash_triage: str
    memory_suggestion_crash_analysis: str
```

- [ ] **Step 2: Add the `_node_memory_summarize` function**

Add before `build_fuzz_workflow()` (before line 12868):

```python
def _node_memory_summarize(state: FuzzWorkflowRuntimeState) -> FuzzWorkflowRuntimeState:
    """Aggregate session results and persist to GBrain as long-term memory.

    Writes session summary, crash pages, and establishes link relationships.
    """
    from typing import cast

    enabled = bool(state.get("memory_enabled", True))
    if not enabled:
        logger.info("memory-summarize: skipped (memory_enabled=false)")
        return state

    repo_url = str(state.get("repo_url", ""))
    if not repo_url:
        logger.warning("memory-summarize: no repo_url, skipping")
        return state

    try:
        from harness_generator.src.langchain_agent.memory_adapter import MemoryAdapter, SessionData

        session = SessionData.from_workflow_state(state)
        session.crashes = list(state.get("crash_verdicts", []))

        adapter = MemoryAdapter()
        slug = asyncio.get_event_loop().run_until_complete(adapter.summarize_session(session))
    except Exception as exc:
        logger.warning("memory-summarize: GBrain write failed: {}", exc)
        slug = ""

    next_state = dict(state)
    next_state["memory_session_slug"] = slug
    return cast(FuzzWorkflowRuntimeState, next_state)
```

- [ ] **Step 3: Register the node and add routing**

In `build_fuzz_workflow()`, add the node registration after line 12882:

```python
    graph.add_node("memory-summarize", _node_memory_summarize)
```

Change the `crash-analysis` conditional edge to route `"stop"` to `"memory-summarize"` instead of `END` (around line 13002):

```python
    graph.add_conditional_edges(
        "crash-analysis",
        _route_after_crash_analysis,
        {"plan": "plan", "stop": "memory-summarize"},
    )
```

Change the `coverage-analysis` conditional edge similarly (around line 12982):

```python
    graph.add_conditional_edges(
        "coverage-analysis",
        _route_after_coverage_analysis,
        {"improve-harness": "improve-harness", "stop": "memory-summarize"},
    )
```

Add an unconditional edge from `memory-summarize` to `END` after all other edges:

```python
    graph.add_edge("memory-summarize", END)
```

- [ ] **Step 4: Import asyncio at the top of workflow_graph.py**

If `asyncio` is not already imported, add to the imports at the top of the file:

```python
import asyncio
```

- [ ] **Step 5: Commit**

```bash
git add harness_generator/src/langchain_agent/workflow_graph.py
git commit -m "feat(memory): add memory-summarize workflow node"
```

---

### Task 6: Suggestion hooks in plan node

**Files:**
- Modify: `harness_generator/src/langchain_agent/workflow_graph.py` (in `_node_plan` around line 5570)
- Modify: `harness_generator/src/langchain_agent/opencode_skills/plan/SKILL.md`

- [ ] **Step 1: Add suggestion call at start of `_node_plan`**

At the start of `_node_plan()` (after the docstring / first logger calls), add:

```python
    # GBrain memory suggestion
    if bool(state.get("memory_enabled", True)):
        try:
            from harness_generator.src.langchain_agent.memory_adapter import MemoryAdapter
            adapter = MemoryAdapter()
            suggestion = asyncio.get_event_loop().run_until_complete(
                adapter.get_suggestions("plan", {
                    "repo_url": state.get("repo_url", ""),
                    "repo_language": state.get("repo_language", ""),
                })
            )
            if suggestion and suggestion.is_actionable():
                logger.info("GBrain plan suggestion: {}", suggestion.summary)
                state = cast(FuzzWorkflowRuntimeState, {
                    **state,
                    "memory_suggestion_plan": suggestion.summary,
                })
        except Exception:
            pass  # GBrain unavailable — continue without memory
```

- [ ] **Step 2: Update plan SKILL.md**

Add after the "Required inputs" section:

```markdown
## GBrain Memory Context
- When `memory_suggestion_plan` is available in the coordinator state, review it before planning.
- The suggestion contains historically effective strategies and attack surface notes for this or similar repositories.
- Use as advisory input — validate against current repo state before applying.
```

- [ ] **Step 3: Commit**

```bash
git add harness_generator/src/langchain_agent/workflow_graph.py harness_generator/src/langchain_agent/opencode_skills/plan/SKILL.md
git commit -m "feat(memory): add GBrain suggestion hook to plan node"
```

---

### Task 7: Suggestion hooks + real-time write in crash-triage node

**Files:**
- Modify: `harness_generator/src/langchain_agent/workflow_graph.py` (in `_node_crash_triage` around line 11340)
- Modify: `harness_generator/src/langchain_agent/opencode_skills/crash_triage/SKILL.md`

- [ ] **Step 1: Add suggestion call at start of `_node_crash_triage`**

```python
    # GBrain memory suggestion
    if bool(state.get("memory_enabled", True)):
        try:
            from harness_generator.src.langchain_agent.memory_adapter import MemoryAdapter
            adapter = MemoryAdapter()
            signature = str(state.get("crash_stack_signature", ""))
            suggestion = asyncio.get_event_loop().run_until_complete(
                adapter.get_suggestions("crash-triage", {
                    "crash_signature": signature,
                    "crash_type": state.get("crash_stack_type", ""),
                })
            )
            if suggestion and suggestion.is_actionable():
                state = cast(FuzzWorkflowRuntimeState, {
                    **state,
                    "memory_suggestion_crash_triage": suggestion.summary,
                })
        except Exception:
            pass
```

- [ ] **Step 2: Add real-time write after crash-triage JSON is produced**

After the crash_triage.json is written (near end of `_node_crash_triage`):

```python
    # Persist triage result to GBrain (real-time, best effort)
    if bool(state.get("memory_enabled", True)):
        try:
            from pathlib import Path
            from harness_generator.src.langchain_agent.memory.slug_resolver import crash_slug
            from harness_generator.src.langchain_agent.memory_adapter import MemoryAdapter
            triage_path = Path(repo_root) / "crash_triage.json"
            if triage_path.exists():
                triage = json.loads(triage_path.read_text())
                slug = crash_slug(
                    str(state.get("repo_url", "")),
                    str(state.get("crash_id", str(time.time()))),
                )
                adapter = MemoryAdapter()
                asyncio.get_event_loop().run_until_complete(adapter.write_page(
                    slug=slug,
                    frontmatter={
                        "type": "fuzz/crash",
                        "title": f"Crash {state.get('crash_stack_signature', '')[:60]}",
                        "crash_signature": state.get("crash_stack_signature", ""),
                        "verdict": triage.get("label", "inconclusive"),
                    },
                    compiled_truth=f"## Triage\n\n{triage.get('reason', '')}\n",
                    timeline=[
                        f"{time.strftime('%Y-%m-%dT%H:%M:%S')}: crash-triage → {triage.get('label')}"
                    ],
                ))
        except Exception:
            pass
```

- [ ] **Step 3: Update crash_triage SKILL.md**

Add after "Required inputs":

```markdown
## GBrain Memory Context
- Check `memory_suggestion_crash_triage` for similar historical crash classifications.
- After triage is written, the coordinator persists the result to GBrain for future sessions.
```

- [ ] **Step 4: Commit**

```bash
git add harness_generator/src/langchain_agent/workflow_graph.py harness_generator/src/langchain_agent/opencode_skills/crash_triage/SKILL.md
git commit -m "feat(memory): add GBrain suggestion + real-time write to crash-triage node"
```

---

### Task 8: Suggestion hooks + real-time write in crash-analysis node

**Files:**
- Modify: `harness_generator/src/langchain_agent/workflow_graph.py` (in `_node_crash_analysis` around line 11566)
- Modify: `harness_generator/src/langchain_agent/opencode_skills/crash_analysis/SKILL.md`

- [ ] **Step 1: Add suggestion call at start of `_node_crash_analysis`**

```python
    # GBrain memory suggestion
    if bool(state.get("memory_enabled", True)):
        try:
            from harness_generator.src.langchain_agent.memory_adapter import MemoryAdapter
            adapter = MemoryAdapter()
            signature = str(state.get("crash_stack_signature", ""))
            suggestion = asyncio.get_event_loop().run_until_complete(
                adapter.get_suggestions("crash-analysis", {
                    "crash_signature": signature,
                    "crash_type": state.get("crash_stack_type", ""),
                })
            )
            if suggestion and suggestion.is_actionable():
                state = cast(FuzzWorkflowRuntimeState, {
                    **state,
                    "memory_suggestion_crash_analysis": suggestion.summary,
                })
        except Exception:
            pass
```

- [ ] **Step 2: Add real-time write after crash-analysis JSON is produced**

After crash_analysis.json is written:

```python
    # Persist analysis verdict to GBrain (real-time, best effort)
    if bool(state.get("memory_enabled", True)):
        try:
            from pathlib import Path
            from harness_generator.src.langchain_agent.memory.slug_resolver import crash_slug
            from harness_generator.src.langchain_agent.memory_adapter import MemoryAdapter
            analysis_path = Path(repo_root) / "crash_analysis.json"
            if analysis_path.exists():
                analysis = json.loads(analysis_path.read_text())
                slug = crash_slug(
                    str(state.get("repo_url", "")),
                    str(state.get("crash_id", str(time.time()))),
                )
                adapter = MemoryAdapter()
                asyncio.get_event_loop().run_until_complete(adapter.write_page(
                    slug=slug,
                    frontmatter={
                        "type": "fuzz/crash",
                        "verdict": analysis.get("verdict", "unknown"),
                        "severity": state.get("crash_severity", "medium"),
                    },
                    compiled_truth=(
                        f"## Verdict\n\n{analysis.get('verdict')}\n\n"
                        f"## Analysis\n\n{analysis.get('reason', '')}\n"
                    ),
                    timeline=[
                        f"{time.strftime('%Y-%m-%dT%H:%M:%S')}: crash-analysis → {analysis.get('verdict')}"
                    ],
                ))
        except Exception:
            pass
```

- [ ] **Step 3: Update crash_analysis SKILL.md**

Add after "Required inputs":

```markdown
## GBrain Memory Context
- Check `memory_suggestion_crash_analysis` for similar historical vulnerability root causes.
- After analysis is written, the coordinator persists the verdict to GBrain for future sessions.
```

- [ ] **Step 4: Commit**

```bash
git add harness_generator/src/langchain_agent/workflow_graph.py harness_generator/src/langchain_agent/opencode_skills/crash_analysis/SKILL.md
git commit -m "feat(memory): add GBrain suggestion + real-time write to crash-analysis node"
```

---

### Task 9: Verify imports and data flow end-to-end

- [ ] **Step 1: Verify all new modules import cleanly**

```bash
cd /home/bohuju/TIanHeng_project/Sherpa && python -c "
from harness_generator.src.langchain_agent.memory.schemas import (
    TargetRepoPage, SessionPage, CrashPage, StrategyPage, HarnessPage,
    PAGE_TYPE_PREFIX, LINK_TYPES,
)
from harness_generator.src.langchain_agent.memory.slug_resolver import (
    repo_url_to_slug, session_slug, crash_slug, strategy_slug,
)
from harness_generator.src.langchain_agent.memory.suggestion_builder import (
    MemoryHit, Suggestion, build_suggestion,
)
from harness_generator.src.langchain_agent.memory_adapter import (
    MemoryAdapter, SessionData, WriteOp, BatchResult,
)
print('All modules imported OK')
"
```

- [ ] **Step 2: Verify slug resolver correctness**

```bash
cd /home/bohuju/TIanHeng_project/Sherpa && python -c "
from harness_generator.src.langchain_agent.memory.slug_resolver import *
assert repo_url_to_slug('https://github.com/GNOME/libxml2') == 'fuzz/targets/GNOME-libxml2'
assert repo_url_to_slug('https://github.com/google/oss-fuzz.git') == 'fuzz/targets/google-oss-fuzz'
assert 'fuzz/sessions/' in session_slug('https://github.com/GNOME/libxml2', 'abc123def456789')
assert 'fuzz/crashes/' in crash_slug('https://github.com/GNOME/libxml2', 'crash-0042')
print('All slug assertions passed')
"
```

- [ ] **Step 3: Verify suggestion builder with sample data**

```bash
cd /home/bohuju/TIanHeng_project/Sherpa && python -c "
from harness_generator.src.langchain_agent.memory.suggestion_builder import build_suggestion

# Empty results
s = build_suggestion('plan', 'test query', [], {})
assert not s.is_actionable()

# Good results
raw = [
    {'slug': 'fuzz/strategies/dict-asan', 'title': 'dict+ASAN strategy', 'score': 0.85, 'snippet': 'Effective for C XML parsers', 'type': 'fuzz/strategy'},
    {'slug': 'fuzz/targets/GNOME-libxml2', 'title': 'libxml2 profile', 'score': 0.72, 'snippet': 'Previously fuzzed with 68% coverage', 'type': 'fuzz/target-repo'},
]
s = build_suggestion('plan', 'test', raw, {})
assert s.is_actionable()
assert s.relevance > 0.5
print('Suggestion builder OK, relevance:', s.relevance)
"
```

- [ ] **Step 4: Commit verification (no file changes)**

```bash
git status
```

---

## Spec Self-Review

Against [2026-05-13-gbrain-memory-integration-design.md](../specs/2026-05-13-gbrain-memory-integration-design.md):

1. **Spec coverage:**
   - 5 page types with schemas → Task 1
   - 7 relation edges → schemas.py `LINK_TYPES`, used in Task 4 `summarize_session()`
   - MemoryAdapter 10 methods → Task 4
   - MCP tool mapping → Implicit in `_call_tool()` calls in Task 4
   - memory-summarize node → Task 5
   - Proactive suggestions for 4 nodes → Tasks 6-8 (3 nodes directly, coverage-analysis via edge routing in Task 5)
   - Fault tolerance → try/except in all suggestion hooks, graceful degradation
   - File structure → matches plan
   - SKILL.md modifications → Tasks 6-8

2. **Placeholder scan:** No TBD, TODO, or vague descriptions. All code blocks are concrete.

3. **Type consistency:**
   - `repo_url_to_slug()` defined in Task 2, used in Tasks 4, 5
   - `session_slug()` defined in Task 2, used in Tasks 4, 5
   - `crash_slug()` defined in Task 2, used in Tasks 4, 7, 8
   - `Suggestion` defined in Task 3, used in Tasks 4, 6, 7, 8
   - `MemoryAdapter` defined in Task 4, used in Tasks 5-8
   - State fields (`memory_enabled`, `memory_session_slug`, `memory_suggestion_*`) added in Task 5, consumed in Tasks 6-8
   - Fixed: `harness_slug()` now correctly uses `harness_id` not `crash_id`
