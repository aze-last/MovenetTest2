"""Application version helpers (Milestone 1, Slice 1).

Single source of truth is ``monitor_app.__version__``; this module only
sanitizes and parses it. No new dependencies (stdlib only).
"""

from __future__ import annotations

FALLBACK_VERSION = "0.1.0"


def get_current_version() -> str:
    """Return the sanitized current app version.

    Strips build/pre-release suffixes (anything from the first ``'+'`` or
    ``'-'``) and surrounding whitespace. Falls back to ``"0.1.0"`` when the
    ``monitor_app.__version__`` source is missing, empty, or blank.
    """
    try:
        import monitor_app

        raw = getattr(monitor_app, "__version__", None)
    except Exception:
        raw = None
    if not isinstance(raw, str) or not raw.strip():
        return FALLBACK_VERSION
    sanitized = raw.strip().split("+", 1)[0].split("-", 1)[0].strip()
    if not sanitized:
        return FALLBACK_VERSION
    return sanitized


def try_parse_version(s) -> tuple[int, ...] | None:
    """Parse a dotted numeric version into a comparable tuple.

    Strips pre-release/build suffixes (first ``'-'``/``'+'``) before parsing.
    Returns ``None`` for anything unparseable (None, non-str, empty,
    non-numeric components) and never raises.
    """
    if not isinstance(s, str):
        return None
    text = s.strip()
    if not text:
        return None
    if text[-1] in ".-+":
        # Dangling delimiter ("1.2-", "1.2.", "1.2+") is malformed even
        # though suffix-stripping would otherwise salvage a core.
        return None
    text = text.split("+", 1)[0].split("-", 1)[0].strip()
    if not text:
        return None
    parts = text.split(".")
    numbers: list[int] = []
    for part in parts:
        part = part.strip()
        if not part or not part.isascii() or not part.isdigit():
            return None
        try:
            numbers.append(int(part))
        except (ValueError, OverflowError):
            return None
    if not numbers:
        return None
    return tuple(numbers)
