"""Tests for the /api/memory endpoints."""
import sys
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

# Add the langchain_agent directory to sys.path so that bare imports in main.py
# (e.g. "from fuzz_relative_functions import fuzz_logic") resolve correctly.
_APP_DIR = (
    Path(__file__).resolve().parents[1]
    / "harness_generator" / "src" / "langchain_agent"
)
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import main as web_main


@pytest.fixture
def mock_adapter():
    """Create a mock MemoryAdapter."""
    adapter = MagicMock()
    adapter.query_experience = AsyncMock(return_value=[
        {
            "slug": "fuzz/targets/test-lib",
            "title": "test-lib",
            "score": 0.95,
            "snippet": "A test library",
        }
    ])
    adapter.list_pages = AsyncMock(return_value=[
        {
            "slug": "fuzz/targets/test-lib",
            "title": "test-lib",
            "summary": "A test library",
        }
    ])
    adapter.get_page = AsyncMock(return_value={
        "slug": "fuzz/targets/test-lib",
        "frontmatter": {"repo_url": "https://github.com/test/lib", "repo_language": "C"},
        "compiled_truth": "## Overview\nTest library",
        "timeline": [],
    })
    adapter.write_page = AsyncMock(return_value=True)
    adapter.delete_page = AsyncMock(return_value=True)
    return adapter


@pytest.fixture(autouse=True)
def memory_adapter_state():
    """Save and restore app.state.memory_adapter to prevent cross-test contamination."""
    app = web_main.app
    original = getattr(app.state, "memory_adapter", None)
    yield
    app.state.memory_adapter = original


@pytest.fixture
def client(mock_adapter):
    """Create a TestClient with mock adapter on app.state."""
    app = web_main.app
    app.state.memory_adapter = mock_adapter
    return TestClient(app)


class TestMemorySearch:
    def test_search_returns_results(self, client, mock_adapter):
        resp = client.get("/api/memory/search?q=fuzz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["total"] == 1
        assert data["results"][0]["slug"] == "fuzz/targets/test-lib"
        mock_adapter.query_experience.assert_called_once()

    def test_search_with_type_filter(self, client, mock_adapter):
        resp = client.get("/api/memory/search?q=fuzz&type=targets")
        assert resp.status_code == 200
        mock_adapter.query_experience.assert_called_once()


class TestMemoryPages:
    def test_pages_returns_results(self, client, mock_adapter):
        resp = client.get("/api/memory/pages?type=targets")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert len(data["results"]) == 1
        mock_adapter.list_pages.assert_called_once_with(
            type_prefix="fuzz/targets", limit=50, offset=0
        )


class TestMemoryGetPage:
    def test_get_page_returns_page(self, client, mock_adapter):
        url = "/api/memory/page/fuzz/targets/test-lib"
        resp = client.get(url)
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert "page" in data
        assert data["page"]["slug"] == "fuzz/targets/test-lib"
        assert data["page"]["frontmatter"]["repo_url"] == "https://github.com/test/lib"

    def test_get_page_not_found(self, client, mock_adapter):
        mock_adapter.get_page.return_value = None
        url = "/api/memory/page/fuzz/targets/nonexistent"
        resp = client.get(url)
        assert resp.status_code == 404


class TestMemoryUpdatePage:
    def test_update_page(self, client, mock_adapter):
        url = "/api/memory/page/fuzz/targets/test-lib"
        resp = client.put(url, json={"repo_language": "C++"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        mock_adapter.write_page.assert_called_once()

    def test_update_page_not_found(self, client, mock_adapter):
        mock_adapter.get_page.return_value = None
        url = "/api/memory/page/fuzz/targets/nonexistent"
        resp = client.put(url, json={})
        assert resp.status_code == 404
        mock_adapter.get_page.assert_called_once()


class TestMemoryDeletePage:
    def test_delete_page(self, client, mock_adapter):
        url = "/api/memory/page/fuzz/targets/test-lib"
        resp = client.delete(url)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestMemoryDisabled:
    def test_search_when_disabled(self):
        web_main.app.state.memory_adapter = None
        client = TestClient(web_main.app)
        resp = client.get("/api/memory/search")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False
        assert data["results"] == []

    def test_page_when_disabled(self):
        web_main.app.state.memory_adapter = None
        client = TestClient(web_main.app)
        url = "/api/memory/page/fuzz/targets/test"
        resp = client.get(url)
        assert resp.status_code == 503
