"""Prompt loading utilities for analysis agents."""
from pathlib import Path

_PROMPT_DIR = Path(__file__).parent / "v1"  # versioned prompts

def load_prompt(name: str) -> str:
    """Load a prompt template from the active version directory."""
    return (_PROMPT_DIR / name).read_text(encoding="utf-8")


def list_prompts() -> list[str]:
    """List available prompt files in the active version."""
    return [p.name for p in _PROMPT_DIR.glob("*.md")]