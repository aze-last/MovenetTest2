"""Synchronous update availability check (Milestone 1, Slice 2).

Synchronous by design — no asyncio in this repo (GEMINI Rule 1, thread-based);
the caller runs :func:`check_for_updates` off the UI thread. Stdlib only.

Never raises on bad input: malformed payloads, unparseable versions, and
fetcher errors all collapse to a ``Failed`` result.
"""

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

from monitor_app.app_version import try_parse_version

FETCH_TIMEOUT_SECONDS = 15
MAX_MANIFEST_BYTES = 256 * 1024  # 256 KiB response body cap
MAX_NOTES = 50
MAX_NOTE_CHARS = 500

_STATIC_USER_AGENT = "CellWatchAI/update-check"


def _user_agent() -> str:
    return _STATIC_USER_AGENT


def _is_allowed_https_url(url: Any) -> bool:
    """True only for well-formed https:// URLs with a host and no userinfo."""
    try:
        if not isinstance(url, str):
            return False
        text = url.strip()
        if not text:
            return False
        parsed = urllib.parse.urlsplit(text)
        if parsed.scheme.lower() != "https":
            return False
        if not parsed.hostname:
            return False
        if parsed.username is not None or parsed.password is not None:
            return False
        if "@" in (parsed.netloc or ""):
            return False
        return True
    except Exception:
        return False


def _resolve_timeout(explicit: Any) -> float:
    """Explicit arg -> config `update.fetch_timeout_s` -> 15. Never raises."""
    if explicit is not None:
        try:
            value = float(explicit)
            if math.isfinite(value) and value > 0:
                return value
        except (TypeError, ValueError, OverflowError):
            pass
        return float(FETCH_TIMEOUT_SECONDS)
    try:
        from monitor_app.config import get_config

        configured = get_config("update", "fetch_timeout_s", FETCH_TIMEOUT_SECONDS)
        value = float(configured)
        if math.isfinite(value) and value > 0:
            return value
    except Exception:
        pass
    return float(FETCH_TIMEOUT_SECONDS)


def _default_fetch(url: str, timeout_s: Any = None) -> str:
    """Default stdlib fetcher: https-only, 15s timeout, static UA, size cap.

    Raises ``ValueError`` for disallowed URLs (non-https, userinfo, missing
    host), redirect targets that leave https, and oversized bodies. Never
    opens non-https schemes (file:// local files included).
    """
    if not _is_allowed_https_url(url):
        raise ValueError("disallowed manifest URL")
    timeout = _resolve_timeout(timeout_s)
    target = url.strip() if isinstance(url, str) else url
    request = urllib.request.Request(target, headers={"User-Agent": _user_agent()})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final_url = target
        try:
            getter = getattr(response, "geturl", None)
            if callable(getter):
                candidate = getter()
                if isinstance(candidate, str) and candidate.strip():
                    final_url = candidate
        except Exception:
            final_url = target
        if not _is_allowed_https_url(final_url):
            raise ValueError("redirect target is not allowed")
        try:
            getter = getattr(response, "getheader", None)
            length_raw = getter("Content-Length") if callable(getter) else None
            if length_raw is None:
                headers = getattr(response, "headers", None)
                if headers is not None:
                    try:
                        length_raw = headers.get("Content-Length")
                    except Exception:
                        length_raw = None
            if length_raw is not None and str(length_raw).strip() != "":
                if int(str(length_raw).strip()) > MAX_MANIFEST_BYTES:
                    raise ValueError("manifest response is too large")
        except ValueError:
            raise
        except Exception:
            pass
        chunks: list[bytes] = []
        total = 0
        while True:
            try:
                chunk = response.read(16384)
            except Exception as exc:
                raise ValueError("manifest read failed") from exc
            if not chunk:
                break
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8")
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_MANIFEST_BYTES:
                raise ValueError("manifest response is too large")
        raw = b"".join(chunks)
    if isinstance(raw, bytes):
        return raw.decode("utf-8")
    return str(raw)


class Status:
    """Update-check status constants."""

    NotChecked = "NotChecked"
    NotConfigured = "NotConfigured"
    UpToDate = "UpToDate"
    UpdateAvailable = "UpdateAvailable"
    Failed = "Failed"


def _as_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _clean_notes(raw: Any) -> list:
    """Trim whitespace; drop empties/non-strings; cap 50 notes x 500 chars."""
    if not isinstance(raw, list):
        return []
    cleaned = []
    for item in raw:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text:
            cleaned.append(text[:MAX_NOTE_CHARS])
        if len(cleaned) >= MAX_NOTES:
            break
    return cleaned


def _validate_sha256(value: str) -> str:
    """Normalize sha256 (lowercase); empty allowed, else 64 hex chars."""
    text = value.strip().lower() if isinstance(value, str) else ""
    if not text:
        return ""
    if len(text) != 64:
        raise ValueError("bad sha256")
    if any(c not in "0123456789abcdef" for c in text):
        raise ValueError("bad sha256")
    return text


@dataclass
class UpdateManifest:
    """Parsed manifest payload (published ``version.json`` shape)."""

    version: str = ""
    notes: list = field(default_factory=list)
    published_at: str = ""
    release_url: str = ""
    installer_name: str = ""
    installer_url: str = ""
    sha256: str = ""

    @classmethod
    def from_dict(cls, payload: dict) -> "UpdateManifest":
        data = payload if isinstance(payload, dict) else {}
        installer_url = _as_str(data.get("installerUrl")).strip()
        if installer_url and not _is_allowed_https_url(installer_url):
            raise ValueError("bad installer URL")
        return cls(
            version=_as_str(data.get("version")).strip(),
            notes=_clean_notes(data.get("notes")),
            published_at=_as_str(data.get("publishedAt")),
            release_url=_as_str(data.get("releasePageUrl")),
            installer_name=_as_str(data.get("installerFileName")),
            installer_url=installer_url,
            sha256=_validate_sha256(_as_str(data.get("sha256"))),
        )


@dataclass
class UpdateCheckResult:
    """Outcome of :func:`check_for_updates`."""

    status: str = Status.NotChecked
    current: str = ""
    latest: str = ""
    published_at: str = ""
    release_url: str = ""
    installer_name: str = ""
    installer_url: str = ""
    sha256: str = ""
    notes: list = field(default_factory=list)
    message: str = ""
    detail: str = ""

    @property
    def is_update_available(self) -> bool:
        return self.status == Status.UpdateAvailable


def _failed(current: str, message: str, detail: str = "") -> UpdateCheckResult:
    return UpdateCheckResult(
        status=Status.Failed, current=current, message=message, detail=detail
    )


def _body_size(body: Any) -> int | None:
    """Byte size of a fetcher body; None for non str/bytes (e.g. dict)."""
    try:
        if isinstance(body, bytes):
            return len(body)
        if isinstance(body, str):
            return len(body.encode("utf-8"))
    except Exception:
        return None
    return None


def check_for_updates(
    manifest_url: Any,
    current_version: Any,
    fetcher: Callable[[str], Any] | None = None,
    timeout_s: Any = None,
) -> UpdateCheckResult:
    """Check the published manifest for a newer version (synchronous).

    ``fetcher`` is an injectable callable taking the URL and returning the
    raw body (``str``/``bytes``) or an already-decoded ``dict``; it defaults
    to a stdlib ``urllib`` implementation (https-only, size-capped). Only
    https:// manifest URLs with a host and no userinfo are accepted.
    ``timeout_s`` overrides config ``update.fetch_timeout_s`` (default 15).
    Never raises — all bad input and fetcher errors become a ``Failed``
    result with a generic message (no URL/exception echo).
    """
    if not isinstance(manifest_url, str) or not manifest_url.strip():
        current_text = current_version if isinstance(current_version, str) else ""
        return UpdateCheckResult(
            status=Status.NotConfigured,
            current=current_text,
            message="Update manifest URL is not configured.",
        )
    current_text = current_version if isinstance(current_version, str) else ""
    cleaned_url = manifest_url.strip()
    if not _is_allowed_https_url(cleaned_url):
        return _failed(
            current_text,
            "Update manifest URL is invalid.",
            detail="bad-url",
        )
    try:
        current_parsed = try_parse_version(current_version)
        if current_parsed is None:
            return _failed(current_text, "Invalid current version.", detail="bad-version")
        timeout = _resolve_timeout(timeout_s)
        try:
            if fetcher is not None:
                body = fetcher(cleaned_url)
            else:
                body = _default_fetch(cleaned_url, timeout)
        except Exception:
            return _failed(
                current_text,
                "Update check failed (network).",
                detail="fetch-error",
            )
        size = _body_size(body)
        if size is not None and size > MAX_MANIFEST_BYTES:
            return _failed(
                current_text,
                "Update check failed (bad manifest).",
                detail="oversized",
            )
        try:
            if isinstance(body, bytes):
                body = body.decode("utf-8")
            if isinstance(body, str):
                payload = json.loads(body)
            elif isinstance(body, dict):
                payload = body
            else:
                return _failed(
                    current_text,
                    "Update check failed (bad manifest).",
                    detail="bad-payload",
                )
        except Exception:
            return _failed(
                current_text,
                "Update check failed (bad manifest).",
                detail="bad-payload",
            )
        if not isinstance(payload, dict):
            return _failed(
                current_text,
                "Update check failed (bad manifest).",
                detail="bad-payload",
            )
        try:
            manifest = UpdateManifest.from_dict(payload)
        except ValueError:
            return _failed(
                current_text,
                "Update check failed (bad manifest).",
                detail="bad-manifest",
            )
        latest_parsed = try_parse_version(manifest.version)
        if latest_parsed is None:
            return _failed(
                current_text,
                "Update check failed (bad manifest).",
                detail="bad-version",
            )
        if latest_parsed > current_parsed:
            return UpdateCheckResult(
                status=Status.UpdateAvailable,
                current=current_text,
                latest=manifest.version,
                published_at=manifest.published_at,
                release_url=manifest.release_url,
                installer_name=manifest.installer_name,
                installer_url=manifest.installer_url,
                sha256=manifest.sha256,
                notes=list(manifest.notes),
                message=f"Update available: {manifest.version}.",
            )
        return UpdateCheckResult(
            status=Status.UpToDate,
            current=current_text,
            latest=manifest.version,
            published_at=manifest.published_at,
            release_url=manifest.release_url,
            installer_name=manifest.installer_name,
            installer_url=manifest.installer_url,
            sha256=manifest.sha256,
            notes=list(manifest.notes),
            message="Already up to date.",
        )
    except Exception:
        return _failed(
            current_text,
            "Update check failed (network).",
            detail="fetch-error",
        )
