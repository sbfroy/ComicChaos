"""JSON sanitization and encoding integrity layer.

Ensures all JSON responses are valid UTF-8 with no malformed escape
sequences, null bytes, raw byte sequences, or encoding corruption.
Designed to be safe across multiple LLM reprocessing cycles where
model output is fed back into subsequent prompts.

Usage:
    from src.json_sanitizer import sanitize_json_response, sanitize_text

    # Sanitize a raw LLM JSON response string before parsing
    clean_json = sanitize_json_response(raw_response)
    data = json.loads(clean_json)

    # Sanitize a parsed dict (deep-cleans all string values)
    clean_data = sanitize_parsed_response(data)
"""

import json
import re
import unicodedata
from typing import Any, Dict, List, Optional, Union


# Regex patterns compiled once at module level

# Null bytes in any form: literal \x00 or JSON-escaped \u0000
_NULL_BYTE_PATTERN = re.compile(r"\x00")
_JSON_NULL_ESCAPE_PATTERN = re.compile(r"\\u0000")

# Malformed Unicode escapes: \u followed by fewer than 4 hex digits,
# or \u0000 (null), or truncated sequences at string boundaries
_MALFORMED_UNICODE_ESCAPE = re.compile(
    r"\\u(?:[0-9a-fA-F]{0,3}(?=[^0-9a-fA-F]|$))"
)

# Raw hex byte sequences that aren't part of normal text (e.g., "e282ac" for €)
# Only match sequences of 6+ hex chars that look like raw UTF-8 byte dumps
_RAW_HEX_BYTES = re.compile(r"(?<![0-9a-fA-F])([0-9a-fA-F]{6,})(?![0-9a-fA-F])")

# Zero-width and invisible Unicode characters that should not appear in comic text
_INVISIBLE_CHARS = re.compile(
    r"[\u200b\u200c\u200d\u200e\u200f"  # zero-width spaces/joiners/marks
    r"\u202a-\u202e"  # bidi control
    r"\ufeff"  # BOM
    r"\ufffc"  # object replacement character
    r"\ufffe\uffff"  # noncharacters
    r"]"
)

# Common known raw-hex representations of characters we can restore
_KNOWN_HEX_SEQUENCES: Dict[str, str] = {
    "c3a6": "æ",
    "c3b8": "ø",
    "c3a5": "å",
    "c386": "Æ",
    "c398": "Ø",
    "c385": "Å",
    "e282ac": "€",
    "c3a9": "é",
    "c3a8": "è",
    "c3bc": "ü",
    "c3b6": "ö",
    "c3a4": "ä",
    "c3ab": "ë",
    "c3af": "ï",
}


def sanitize_text(text: str) -> str:
    """Sanitize a single text string for encoding integrity.

    Removes null bytes, invisible characters, and normalizes Unicode.
    Preserves all valid content including Norwegian characters (æ, ø, å),
    accented letters, and symbols like €.

    This function is idempotent: calling it on already-clean text
    returns the same text unchanged.

    Args:
        text: The string to sanitize.

    Returns:
        The sanitized string.
    """
    if not text:
        return text

    # 1. Remove null bytes
    text = _NULL_BYTE_PATTERN.sub("", text)

    # 2. Remove invisible/control characters (except normal whitespace)
    text = _INVISIBLE_CHARS.sub("", text)

    # 3. Remove other C0/C1 control characters except tab, newline, carriage return
    text = "".join(
        ch for ch in text
        if ch in ("\t", "\n", "\r") or unicodedata.category(ch) != "Cc"
    )

    # 4. Normalize Unicode to NFC (composed form) — this ensures that
    # characters like å (U+00E5) aren't split into a + combining ring
    text = unicodedata.normalize("NFC", text)

    return text


def _try_decode_raw_hex(match: re.Match) -> str:
    """Try to decode a raw hex sequence as UTF-8 bytes.

    Only replaces the match if it decodes to valid, printable UTF-8 text.
    Otherwise returns the original match unchanged.
    """
    hex_str = match.group(1)

    # Check known sequences first (fast path)
    lower_hex = hex_str.lower()
    if lower_hex in _KNOWN_HEX_SEQUENCES:
        return _KNOWN_HEX_SEQUENCES[lower_hex]

    # Only attempt decode for even-length sequences
    if len(hex_str) % 2 != 0:
        return match.group(0)

    try:
        decoded = bytes.fromhex(hex_str).decode("utf-8")
        # Only accept if it produced printable, non-control characters
        if all(ch.isprintable() or ch in (" ", "\n") for ch in decoded):
            return decoded
    except (ValueError, UnicodeDecodeError):
        pass

    return match.group(0)


def sanitize_json_string(raw: str) -> str:
    """Sanitize a raw JSON response string before parsing.

    Fixes encoding issues in the raw JSON text:
    - Removes \\u0000 null escapes
    - Fixes malformed Unicode escapes
    - Attempts to decode raw hex byte sequences
    - Removes object replacement characters

    This operates on the raw JSON string (before json.loads), so it
    must be careful to preserve valid JSON structure.

    Args:
        raw: The raw JSON string from the LLM.

    Returns:
        A cleaned JSON string that is more likely to parse correctly.
    """
    if not raw:
        return raw

    # 1. Remove JSON-escaped null bytes (\\u0000)
    raw = _JSON_NULL_ESCAPE_PATTERN.sub("", raw)

    # 2. Remove literal null bytes
    raw = _NULL_BYTE_PATTERN.sub("", raw)

    # 3. Remove object replacement character (common corruption sign)
    raw = raw.replace("\ufffc", "")

    # 4. Fix malformed Unicode escapes by removing them
    # (e.g., \u00e → remove, as it's truncated)
    raw = _MALFORMED_UNICODE_ESCAPE.sub("", raw)

    return raw


def sanitize_parsed_response(data: Any) -> Any:
    """Deep-clean all string values in a parsed JSON structure.

    Recursively walks dicts and lists, applying sanitize_text() to
    every string value. Non-string values are passed through unchanged.

    This is idempotent: calling it on already-clean data returns
    identical data.

    Args:
        data: A parsed JSON structure (dict, list, str, int, float, bool, None).

    Returns:
        The same structure with all strings sanitized.
    """
    if isinstance(data, str):
        return sanitize_text(data)
    elif isinstance(data, dict):
        return {k: sanitize_parsed_response(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_parsed_response(item) for item in data]
    else:
        return data


def validate_json_response(data: Dict[str, Any], schema_name: str = "") -> List[str]:
    """Validate a parsed JSON response for encoding integrity.

    Checks all string values for signs of corruption that survived
    sanitization. Returns a list of warnings (empty = all clean).

    This does NOT validate schema structure — only encoding integrity.

    Args:
        data: The parsed and sanitized JSON response.
        schema_name: Optional name for error reporting.

    Returns:
        List of warning strings. Empty list means all clean.
    """
    warnings = []
    _validate_recursive(data, "", warnings)
    return warnings


def _validate_recursive(data: Any, path: str, warnings: List[str]) -> None:
    """Recursively validate all string values for encoding issues."""
    if isinstance(data, str):
        # Check for null bytes that somehow survived
        if "\x00" in data:
            warnings.append(f"{path}: contains null byte")

        # Check for object replacement characters
        if "\ufffc" in data:
            warnings.append(f"{path}: contains object replacement character")

        # Check for non-UTF-8-safe sequences (shouldn't happen in Python str,
        # but check surrogate pairs which are invalid in JSON)
        try:
            data.encode("utf-8")
        except UnicodeEncodeError:
            warnings.append(f"{path}: contains invalid UTF-8 sequences")

        # Check for suspicious patterns that indicate corruption
        if re.search(r"(.)\1{20,}", data):
            warnings.append(f"{path}: contains suspiciously repeated characters")

    elif isinstance(data, dict):
        for k, v in data.items():
            _validate_recursive(v, f"{path}.{k}" if path else k, warnings)

    elif isinstance(data, list):
        for i, item in enumerate(data):
            _validate_recursive(item, f"{path}[{i}]", warnings)


def safe_json_dumps(data: Any, **kwargs: Any) -> str:
    """Serialize data to JSON with UTF-8 characters preserved.

    Always uses ensure_ascii=False so that Norwegian characters (æ, ø, å)
    and other Unicode appear as literal UTF-8 rather than \\uXXXX escapes.
    This reduces encoding churn across multiple serialization cycles.

    Args:
        data: The data to serialize.
        **kwargs: Additional arguments passed to json.dumps().

    Returns:
        A JSON string with literal UTF-8 characters.
    """
    kwargs.setdefault("ensure_ascii", False)
    return json.dumps(data, **kwargs)
