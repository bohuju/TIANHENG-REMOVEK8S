"""Convert between Sherpa domain objects and GBrain page slugs.

Note: This module produces GBrain knowledge-base page slugs (fuzz/targets/...).
For filesystem-safe repo directory slugs, see workflow_common.slug_from_repo_url.
"""

from __future__ import annotations
import re
from urllib.parse import urlparse

# GBrain page slug prefix constants
_PREFIX_TARGET = "fuzz/targets/"
_PREFIX_SESSION = "fuzz/sessions/"
_PREFIX_CRASH = "fuzz/crashes/"
_PREFIX_STRATEGY = "fuzz/strategies/"
_PREFIX_HARNESS = "fuzz/harnesses/"

# Max slug length (GBrain page path limit)
_MAX_SLUG_LENGTH = 120


def _sanitize_id(id_str: str, max_len: int) -> str:
    """Truncate and strip non-alphanumeric characters from an ID for safe slug use.

    Hyphens are stripped to guarantee that rsplit('-', 1) in target_slug_from_crash
    always splits at the owner-repo/id boundary, even for UUID-formatted IDs.
    """
    stripped = re.sub(r"[^a-zA-Z0-9]", "", id_str)
    return stripped[:max_len] if len(stripped) > max_len else stripped


def _repo_part(repo_url: str) -> str:
    """Extract the {owner}-{repo} portion from a repo URL."""
    slug = repo_url_to_slug(repo_url)
    if slug.startswith(_PREFIX_TARGET):
        return slug[len(_PREFIX_TARGET):]
    return slug


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
        owner, repo = "unknown", parts[0]
    else:
        owner, repo = "unknown", "unknown"
    repo = re.sub(r"\.git$", "", repo)
    safe_owner = re.sub(r"[^a-zA-Z0-9._-]", "-", owner)
    safe_repo = re.sub(r"[^a-zA-Z0-9._-]", "-", repo)
    return f"{_PREFIX_TARGET}{safe_owner}-{safe_repo}"


def session_slug(repo_url: str, session_id: str) -> str:
    """Generate a session page slug from repo URL and session ID."""
    short_id = _sanitize_id(session_id, 12)
    return f"{_PREFIX_SESSION}{_repo_part(repo_url)}-{short_id}"


def crash_slug(repo_url: str, crash_id: str) -> str:
    """Generate a crash page slug."""
    short_id = _sanitize_id(crash_id, 16)
    return f"{_PREFIX_CRASH}{_repo_part(repo_url)}-{short_id}"


def strategy_slug(descriptive_name: str) -> str:
    """Generate a strategy page slug from a descriptive name."""
    safe = re.sub(r"[^a-zA-Z0-9-]", "-", descriptive_name.lower())
    safe = re.sub(r"-{2,}", "-", safe).strip("-")
    if not safe:
        safe = "unnamed"
    return f"{_PREFIX_STRATEGY}{safe}"[:_MAX_SLUG_LENGTH]


def harness_slug(repo_url: str, harness_id: str) -> str:
    """Generate a harness page slug."""
    short_id = _sanitize_id(harness_id, 16)
    return f"{_PREFIX_HARNESS}{_repo_part(repo_url)}-{short_id}"


def target_slug_from_crash(crash_slug_: str) -> str:
    """Extract the target-repo slug from a crash slug via naming convention.

    Relies on _sanitize_id having stripped hyphens from the ID portion, so the
    rightmost hyphen always delimits the repo-part from the ID.
    """
    base = crash_slug_.replace(_PREFIX_CRASH, "", 1)
    parts = base.rsplit("-", 1)
    return f"{_PREFIX_TARGET}{parts[0]}"
