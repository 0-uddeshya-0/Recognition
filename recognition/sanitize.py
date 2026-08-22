"""Formatting safeguards for values copied from IFC models."""
from __future__ import annotations

import unicodedata

_DANGEROUS_CSV_PREFIXES = frozenset("=+-@\t\r")


def _strip_control_characters(value: str) -> str:
    return "".join(ch for ch in value if unicodedata.category(ch) != "Cc")


def sanitize_csv_cell(value: object) -> object:
    if not isinstance(value, str):
        return value
    if not value.strip():
        return value
    cleaned = _strip_control_characters(value)
    if value[:1] in _DANGEROUS_CSV_PREFIXES or cleaned[:1] in _DANGEROUS_CSV_PREFIXES:
        cleaned = "'" + cleaned
    return cleaned


def sanitize_markdown_cell(value: object) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r", " ").replace("\n", " ")
    return _strip_control_characters(text).replace("|", r"\|")
