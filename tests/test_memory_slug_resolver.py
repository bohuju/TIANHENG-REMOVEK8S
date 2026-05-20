"""Tests for GBrain memory slug resolver."""

import pytest
import sys
import importlib.util

# Load module directly to avoid package-level loguru dependency
spec = importlib.util.spec_from_file_location(
    "slug_resolver",
    "harness_generator/src/langchain_agent/memory/slug_resolver.py",
)
mod = importlib.util.module_from_spec(spec)
# Bypass __future__ annotations issue by injecting __module__
mod.__module__ = "slug_resolver"
sys.modules["slug_resolver"] = mod
spec.loader.exec_module(mod)


class TestRepoUrlToSlug:
    def test_standard_github_url(self):
        result = mod.repo_url_to_slug("https://github.com/GNOME/libxml2")
        assert result == "fuzz/targets/GNOME-libxml2"

    def test_git_suffix_stripped(self):
        result = mod.repo_url_to_slug("https://github.com/google/oss-fuzz.git")
        assert result == "fuzz/targets/google-oss-fuzz"

    def test_single_path_segment(self):
        result = mod.repo_url_to_slug("https://github.com/explore")
        assert result == "fuzz/targets/unknown-explore"

    def test_special_chars_sanitized(self):
        result = mod.repo_url_to_slug("https://github.com/foo!/bar@baz")
        assert "!" not in result
        assert "@" not in result

    def test_hyphen_in_owner(self):
        result = mod.repo_url_to_slug("https://github.com/my-org/my-repo")
        assert result == "fuzz/targets/my-org-my-repo"


class TestSanitizeId:
    def test_strips_hyphens_from_uuid(self):
        result = mod._sanitize_id("550e8400-e29b-41d4-a716-446655440000", 16)
        assert "-" not in result
        assert len(result) == 16

    def test_short_id_preserved(self):
        result = mod._sanitize_id("abc123", 12)
        assert result == "abc123"


class TestRoundTrip:
    def test_crash_slug_roundtrip(self):
        url = "https://github.com/GNOME/libxml2"
        crash = mod.crash_slug(url, "crash-0042")
        target = mod.target_slug_from_crash(crash)
        assert target == mod.repo_url_to_slug(url)

    def test_crash_slug_roundtrip_with_uuid(self):
        url = "https://github.com/GNOME/libxml2"
        crash = mod.crash_slug(url, "550e8400-e29b-41d4-a716-446655440000")
        target = mod.target_slug_from_crash(crash)
        assert target == mod.repo_url_to_slug(url)

    def test_session_slug_roundtrip(self):
        url = "https://github.com/GNOME/libxml2"
        sess = mod.session_slug(url, "550e8400-e29b-41d4-a716-446655440000")
        # session slug shouldn't break target extraction
        target = mod.target_slug_from_crash(sess.replace("fuzz/sessions/", "fuzz/crashes/"))
        assert target == mod.repo_url_to_slug(url)


class TestStrategySlug:
    def test_normal_name(self):
        result = mod.strategy_slug("dict+ASAN for C XML parsers")
        assert result.startswith("fuzz/strategies/")

    def test_empty_name_fallback(self):
        result = mod.strategy_slug("!!!")
        assert result.endswith("unnamed")

    def test_truncation(self):
        long_name = "a" * 200
        result = mod.strategy_slug(long_name)
        assert len(result) <= 120
