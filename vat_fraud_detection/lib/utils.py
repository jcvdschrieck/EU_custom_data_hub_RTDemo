"""Shared utilities."""
from __future__ import annotations
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

def load_prompt(filename: str) -> str:
    """Load a prompt template from the prompts/ directory."""
    path = _PROMPTS_DIR / filename
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()
