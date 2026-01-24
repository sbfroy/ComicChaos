"""Simple prompt loader.

Usage:
    from pathlib import Path
    from src.prompt_loader import load_prompt

    prompt = load_prompt(Path(__file__).parent / "system_prompt.md", title="My Comic")
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Union


@lru_cache(maxsize=32)
def _read_file(filepath: str) -> str:
    """Read and cache file contents."""
    return Path(filepath).read_text(encoding="utf-8").strip()


def load_prompt(filepath: Union[str, Path], **kwargs: Any) -> str:
    """Load a prompt from a file.

    Args:
        filepath: Path to the prompt file.
        **kwargs: Variables to substitute.

    Returns:
        The prompt content.
    """
    content = _read_file(str(filepath))
    return content.format(**kwargs) if kwargs else content


def load_json(filepath: Union[str, Path]) -> Dict[str, Any]:
    """Load JSON from a file."""
    content = _read_file(str(filepath))
    return json.loads(content)


def clear_cache() -> None:
    """Clear the file cache."""
    _read_file.cache_clear()
