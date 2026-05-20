from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "harness_generator" / "src" / "langchain_agent" / "main.py"


def test_stage_payload_includes_restart_and_runtime_override_fields() -> None:
    text = MAIN.read_text(encoding="utf-8")
    required = [
        '"context_dir": (context_dir or None)',
        '"run_unlimited_round_budget_sec": int(',
        '"target_node_name": (current_node_name if can_pin_node else None)',
    ]
    for marker in required:
        assert marker in text
