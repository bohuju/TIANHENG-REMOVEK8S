"""Tests for GBrain memory schema dataclasses."""
import sys
from pathlib import Path

import pytest

_APP_DIR = (
    Path(__file__).resolve().parents[1]
    / "harness_generator" / "src" / "langchain_agent"
)
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from memory.schemas import (
    AttackSurface,
    CrashPage,
    HarnessPage,
    LINK_TYPES,
    PAGE_TYPE_PREFIX,
    SessionPage,
    StrategyPage,
    TargetRepoPage,
)


class TestTargetRepoPage:
    def test_construct_with_required_fields(self):
        t = TargetRepoPage(repo_url="https://github.com/GNOME/libxml2", repo_language="c")
        assert t.repo_url == "https://github.com/GNOME/libxml2"
        assert t.repo_language == "c"
        assert t.total_sessions == 0
        assert t.cve_ids == []

    def test_to_frontmatter_includes_keys(self):
        t = TargetRepoPage(repo_url="https://github.com/GNOME/libxml2", repo_language="c")
        fm = t.to_frontmatter()
        assert fm["repo_url"] == "https://github.com/GNOME/libxml2"
        assert fm["repo_language"] == "c"
        assert "attack_surfaces" in fm

    def test_mutable_default_isolation(self):
        t1 = TargetRepoPage(repo_url="https://a.com", repo_language="c")
        t2 = TargetRepoPage(repo_url="https://b.com", repo_language="python")
        t1.cve_ids.append("CVE-123")
        assert t2.cve_ids == []

    def test_nested_attack_surface_roundtrips(self):
        t = TargetRepoPage(
            repo_url="https://a.com",
            repo_language="c",
            attack_surfaces=[AttackSurface(module="parser", functions=["parse"], risk_level="high")],
        )
        fm = t.to_frontmatter()
        assert len(fm["attack_surfaces"]) == 1
        assert fm["attack_surfaces"][0]["module"] == "parser"


class TestCrashPage:
    def test_construct_with_minimal_fields(self):
        c = CrashPage(repo="fuzz/targets/GNOME-libxml2", session="fuzz/sessions/test", crash_signature="SIGSEGV")
        assert c.verdict == "inconclusive"
        assert c.severity == "medium"
        assert c.cve_id is None

    def test_to_frontmatter_excludes_none(self):
        c = CrashPage(repo="fuzz/targets/GNOME-libxml2", session="fuzz/sessions/test", crash_signature="SIGSEGV")
        fm = c.to_frontmatter()
        assert "cve_id" not in fm

    def test_to_frontmatter_includes_empty_strings(self):
        c = CrashPage(repo="fuzz/targets/GNOME-libxml2", session="fuzz/sessions/test", crash_signature="SIGSEGV")
        fm = c.to_frontmatter()
        assert fm["crash_type"] == ""

    def test_to_frontmatter_includes_non_none_cve(self):
        c = CrashPage(
            repo="fuzz/targets/GNOME-libxml2",
            session="fuzz/sessions/test",
            crash_signature="SIGSEGV",
            cve_id="CVE-2026-12345",
        )
        fm = c.to_frontmatter()
        assert fm["cve_id"] == "CVE-2026-12345"


class TestSessionPage:
    def test_to_frontmatter(self):
        s = SessionPage(repo="fuzz/targets/GNOME-libxml2", session_id="abc123", total_harnesses=5)
        fm = s.to_frontmatter()
        assert fm["repo"] == "fuzz/targets/GNOME-libxml2"
        assert fm["total_harnesses"] == 5

    def test_mutable_default_isolation(self):
        s1 = SessionPage(repo="a", session_id="1")
        s2 = SessionPage(repo="b", session_id="2")
        s1.stages_completed.append("plan")
        assert s2.stages_completed == []


class TestStrategyPage:
    def test_to_frontmatter(self):
        s = StrategyPage(strategy_type="harness_pattern", target_language="c", success_rate=0.85)
        fm = s.to_frontmatter()
        assert fm["success_rate"] == 0.85


class TestHarnessPage:
    def test_to_frontmatter(self):
        h = HarnessPage(repo="fuzz/targets/GNOME-libxml2", session="fuzz/sessions/test", build_status="success")
        fm = h.to_frontmatter()
        assert fm["build_status"] == "success"


class TestConstants:
    def test_page_type_prefix_has_all_types(self):
        assert "fuzz/target-repo" in PAGE_TYPE_PREFIX
        assert "fuzz/session" in PAGE_TYPE_PREFIX
        assert "fuzz/crash" in PAGE_TYPE_PREFIX
        assert "fuzz/strategy" in PAGE_TYPE_PREFIX
        assert "fuzz/harness" in PAGE_TYPE_PREFIX

    def test_link_types_is_tuple(self):
        assert isinstance(LINK_TYPES, tuple)
        assert len(LINK_TYPES) == 7
        assert "source" in LINK_TYPES
        assert "similar_to" in LINK_TYPES

    def test_link_types_immutable(self):
        with pytest.raises((TypeError, AttributeError)):
            LINK_TYPES.append("custom")  # type: ignore[union-attr]
