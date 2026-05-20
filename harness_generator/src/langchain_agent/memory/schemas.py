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
        return asdict(self)


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
LINK_TYPES = (
    "source",           # session → target-repo
    "discovered_in",    # crash → session
    "found_in_repo",    # crash → target-repo
    "generated_in",     # harness → session
    "follows_pattern",  # harness → strategy
    "applied_to",       # strategy → target-repo
    "similar_to",       # crash → crash
)
