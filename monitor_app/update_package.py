"""Pending update state (Milestone 2, Slice T1 — pending-state only).

Synchronous by design — no asyncio in this repo (GEMINI Rule 1,
thread-based); the caller runs these helpers off the UI thread.
Stdlib only.

State lives in ``<updates_dir>/pending.json`` where ``updates_dir``
defaults to ``data_path("updates")``. Every public function takes an
injectable ``updates_dir`` so tests stay hermetic (tmp_path, no real
network, no default-dir writes).

Never raises on bad state: corrupt JSON, missing fields, traversal
paths, and missing files all collapse to ``None`` + cleanup.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import os
import urllib.parse
from concurrent.futures import CancelledError
from dataclasses import dataclass, field
from typing import Any

from monitor_app.app_version import try_parse_version
from monitor_app.update_check import _is_allowed_https_url, _resolve_timeout

try:
    from monitor_app.utils import data_path as _data_path

    UPDATES_DIR = _data_path("updates")
except Exception:
    UPDATES_DIR = os.path.abspath("updates")

PENDING_FILENAME = "pending.json"
TRANSIENT_SUFFIX = ".download"

MAX_INSTALLER_BYTES = 134217728  # 128 MiB default; override via update.max_installer_bytes
MAX_FILENAME_LEN = 255


def _resolve_updates_dir(updates_dir: Any = None) -> str:
    """Return the effective updates dir; default via ``data_path``."""
    if updates_dir is not None:
        return str(updates_dir)
    try:
        from monitor_app.utils import data_path

        return data_path("updates")
    except Exception:
        return str(UPDATES_DIR)


def _pending_path(updates_dir: Any = None) -> str:
    return os.path.join(_resolve_updates_dir(updates_dir), PENDING_FILENAME)


def _as_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _validate_sha256_required(value: Any) -> str:
    text = value.strip().lower() if isinstance(value, str) else ""
    if len(text) != 64:
        raise ValueError("bad sha256")
    if any(c not in "0123456789abcdef" for c in text):
        raise ValueError("bad sha256")
    return text


def _clean_notes(raw: Any) -> list:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("bad notes")
    cleaned: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text:
            cleaned.append(text[:500])
        if len(cleaned) >= 50:
            break
    return cleaned


def _is_contained(base_dir: str, target_path: str) -> bool:
    """True iff ``target_path`` resolves inside ``base_dir``.

    First containment check in this repo — ``abspath`` + ``commonpath``.
    Returns False (never raises) on any irregular input, including
    different Windows drives (``commonpath`` raises ``ValueError``).
    """
    try:
        if not isinstance(base_dir, str) or not isinstance(target_path, str):
            return False
        if not base_dir.strip() or not target_path.strip():
            return False
        base = os.path.abspath(base_dir)
        target = target_path.strip()
        if not os.path.isabs(target):
            target = os.path.join(base, target)
        target_abs = os.path.abspath(target)
        return os.path.commonpath([base, target_abs]) == base
    except Exception:
        return False


def _contained_abs(base_dir: str, target_path: str) -> str | None:
    """Absolute target if contained, else None. Never raises."""
    try:
        if not _is_contained(base_dir, target_path):
            return None
        base = os.path.abspath(base_dir)
        target = target_path.strip()
        if not os.path.isabs(target):
            target = os.path.join(base, target)
        return os.path.abspath(target)
    except Exception:
        return None


_RESERVED_WINDOWS_STEMS = frozenset({"CON", "PRN", "AUX", "NUL"})


def _is_reserved_windows_name(base: str) -> bool:
    """True for Windows reserved device names (CON, PRN, AUX, NUL, COM1-9, LPT1-9)."""
    try:
        stem = base.split(".")[0].upper()
        if stem in _RESERVED_WINDOWS_STEMS:
            return True
        if len(stem) == 4 and stem[:3] in ("COM", "LPT") and stem[3] in "123456789":
            return True
        return False
    except Exception:
        return True


def _is_allowed_filename(base: str) -> bool:
    """Allowlist for installer filenames (robustness on top of containment).

    Rejects NUL/control chars, illegal ``<>:"|?*`` chars, reserved Windows
    device names, trailing dot/space, and over-long names. Never raises.
    """
    try:
        if not isinstance(base, str):
            return False
        if not base or base in (".", ".."):
            return False
        if len(base) > MAX_FILENAME_LEN:
            return False
        if "/" in base or "\\" in base:
            return False
        if os.path.basename(base) != base:
            return False
        for ch in base:
            code = ord(ch)
            if code < 32 or code == 127:
                return False
        if any(c in '<>:"|?*' for c in base):
            return False
        if base.endswith(".") or base.endswith(" "):
            return False
        if _is_reserved_windows_name(base):
            return False
        return True
    except Exception:
        return False


@dataclass
class PendingUpdate:
    """Durable pending-update record (downloaded installer awaiting install)."""

    version: str = ""
    installer_filename: str = ""
    installer_path: str = ""
    installer_url: str = ""
    sha256: str = ""
    release_url: str = ""
    published_at: str = ""
    notes: list = field(default_factory=list)
    downloaded_at_utc: str = ""

    @classmethod
    def from_dict(cls, payload: dict) -> "PendingUpdate":
        if not isinstance(payload, dict):
            raise ValueError("bad pending payload")
        version = _as_str(payload.get("version")).strip()
        if try_parse_version(version) is None:
            raise ValueError("bad version")
        installer_filename = _as_str(payload.get("installer_filename")).strip()
        if not installer_filename:
            raise ValueError("bad installer_filename")
        if not _is_allowed_filename(installer_filename):
            raise ValueError("bad installer_filename")
        installer_path = _as_str(payload.get("installer_path")).strip()
        if not installer_path:
            raise ValueError("bad installer_path")
        installer_url = _as_str(payload.get("installer_url")).strip()
        if not _is_allowed_https_url(installer_url):
            raise ValueError("bad installer_url")
        sha256 = _validate_sha256_required(_as_str(payload.get("sha256")))
        release_raw = _as_str(payload.get("release_url")).strip()
        if release_raw and not _is_allowed_https_url(release_raw):
            release_raw = ""
        release_url = release_raw
        published_at = _as_str(payload.get("published_at"))
        downloaded_at = _as_str(payload.get("downloaded_at_utc")).strip()
        if not downloaded_at:
            raise ValueError("bad downloaded_at_utc")
        notes = _clean_notes(
            payload.get("notes") if "notes" in payload else []
        )
        return cls(
            version=version,
            installer_filename=installer_filename,
            installer_path=installer_path,
            installer_url=installer_url,
            sha256=sha256,
            release_url=release_url,
            published_at=published_at,
            notes=list(notes),
            downloaded_at_utc=downloaded_at,
        )

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "installer_filename": self.installer_filename,
            "installer_path": self.installer_path,
            "installer_url": self.installer_url,
            "sha256": self.sha256,
            "release_url": self.release_url,
            "published_at": self.published_at,
            "notes": list(self.notes),
            "downloaded_at_utc": self.downloaded_at_utc,
        }


def _save_pending(pending: PendingUpdate, updates_dir: Any = None) -> str:
    """Persist ``pending`` atomically (tmp file + ``os.replace``).

    Creates the updates dir as needed. Returns the pending.json path.
    Filesystem ``OSError`` (makedirs/open/replace) is wrapped into the
    ``ValueError`` contract. Never leaves a stray ``.tmp`` on failure.
    """
    resolved = _resolve_updates_dir(updates_dir)
    try:
        os.makedirs(resolved, exist_ok=True)
    except OSError as exc:
        raise ValueError("pending save failed") from exc
    path = os.path.join(resolved, PENDING_FILENAME)
    payload = pending.to_dict() if isinstance(pending, PendingUpdate) else {}
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
            try:
                f.flush()
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp_path, path)
    except OSError as exc:
        _remove_quietly(tmp_path)
        raise ValueError("pending save failed") from exc
    return path


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except Exception:
        pass


def load_pending(updates_dir: Any = None) -> PendingUpdate | None:
    """Load the pending update, or None when absent/invalid. Never raises.

    Any bad state (unreadable file, non-dict JSON, ``from_dict`` failure,
    traversal outside the updates dir, missing installer file) removes
    ``pending.json`` and returns None.
    """
    try:
        resolved = _resolve_updates_dir(updates_dir)
        path = os.path.join(resolved, PENDING_FILENAME)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            _remove_quietly(path)
            return None
        if not isinstance(payload, dict):
            _remove_quietly(path)
            return None
        try:
            pending = PendingUpdate.from_dict(payload)
        except Exception:
            _remove_quietly(path)
            return None
        contained = _contained_abs(resolved, pending.installer_path)
        if contained is None:
            _remove_quietly(path)
            return None
        if not os.path.isfile(contained):
            _remove_quietly(path)
            return None
        return pending
    except Exception:
        try:
            _remove_quietly(_pending_path(updates_dir))
        except Exception:
            pass
        return None


def clear_pending(updates_dir: Any = None) -> None:
    """Remove pending state and its contained installer file. Never raises."""
    try:
        resolved = _resolve_updates_dir(updates_dir)
        path = os.path.join(resolved, PENDING_FILENAME)
        installer_abs: str | None = None
        try:
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    payload = json.load(f)
                try:
                    pending = PendingUpdate.from_dict(payload)
                    installer_abs = _contained_abs(resolved, pending.installer_path)
                except Exception:
                    installer_abs = None
        except Exception:
            installer_abs = None
        if installer_abs is not None:
            try:
                if os.path.isfile(installer_abs):
                    os.remove(installer_abs)
            except Exception:
                pass
        _remove_quietly(path)
    except Exception:
        pass


def perform_startup_maintenance(
    current_version: Any, updates_dir: Any = None
) -> None:
    """Startup cleanup: drop stale pending + ``*.download``/``*.tmp`` transients.

    Clears pending when the installer file is missing or when
    ``current_version >= pending.version`` (both parsed via
    ``try_parse_version``). Unparseable current versions never clear.
    Never raises.
    """
    try:
        resolved = _resolve_updates_dir(updates_dir)
        try:
            os.makedirs(resolved, exist_ok=True)
        except Exception:
            pass
        try:
            for name in os.listdir(resolved):
                if name.endswith(TRANSIENT_SUFFIX) or name.endswith(".tmp"):
                    _remove_quietly(os.path.join(resolved, name))
        except Exception:
            pass
        pending = load_pending(updates_dir=resolved)
        if pending is None:
            try:
                leftover = os.path.join(resolved, PENDING_FILENAME)
                if os.path.isfile(leftover):
                    _remove_quietly(leftover)
            except Exception:
                pass
            return
        contained = _contained_abs(resolved, pending.installer_path)
        if contained is None or not os.path.isfile(contained):
            clear_pending(updates_dir=resolved)
            return
        try:
            current_parsed = try_parse_version(current_version)
            pending_parsed = try_parse_version(pending.version)
            if (
                current_parsed is not None
                and pending_parsed is not None
                and current_parsed >= pending_parsed
            ):
                clear_pending(updates_dir=resolved)
        except Exception:
            pass
    except Exception:
        pass


_DOWNLOAD_CHUNK_BYTES = 64 * 1024
_FALLBACK_FILENAME = "installer.bin"


def _normalize_sha256_hex(value: Any) -> str:
    """Normalize expected sha256: strip/lowercase, drop dashes/spaces."""
    text = value.strip().lower() if isinstance(value, str) else ""
    text = text.replace("-", "").replace(" ", "")
    if len(text) != 64:
        raise ValueError("bad sha256")
    if any(c not in "0123456789abcdef" for c in text):
        raise ValueError("bad sha256")
    return text


def _sanitize_filename(raw: Any) -> str | None:
    """Basename-sanitize a filename; None when unusable. Never raises.

    Applies the shared allowlist (NUL/control, ``<>:"|?*``, reserved
    Windows names, trailing dot/space, length cap) on top of the
    containment check in :func:`download_update`.
    """
    try:
        if not isinstance(raw, str):
            return None
        text = raw.strip()
        if not text:
            return None
        text = text.replace("\\", "/")
        base = text.split("/")[-1].strip()
        if not _is_allowed_filename(base):
            return None
        return base
    except Exception:
        return None


def _result_field(result: Any, name: str, default: Any = "") -> Any:
    try:
        if isinstance(result, dict):
            return result.get(name, default)
        value = getattr(result, name, default)
        return default if value is None else value
    except Exception:
        return default


def _cancel_requested(cancel_event: Any) -> bool:
    try:
        if cancel_event is None:
            return False
        checker = getattr(cancel_event, "is_set", None)
        if not callable(checker):
            return False
        return bool(checker())
    except Exception:
        return False


def _parse_content_total(response: Any) -> int | None:
    try:
        getter = getattr(response, "getheader", None)
        raw = getter("Content-Length") if callable(getter) else None
        if raw is None:
            headers = getattr(response, "headers", None)
            if headers is not None:
                try:
                    raw = headers.get("Content-Length")
                except Exception:
                    raw = None
        if raw is None or str(raw).strip() == "":
            return None
        total = int(str(raw).strip())
        if total < 0:
            return None
        return total
    except Exception:
        return None


def _resolve_max_installer_bytes(explicit: Any = None) -> int:
    """Resolve the installer size cap: explicit -> config -> default.

    Explicit arg wins when it is a finite number > 0 (int-cast); invalid
    explicit values collapse to the default (mirrors ``_resolve_timeout``).
    Otherwise reads config ``update.max_installer_bytes`` (default
    ``MAX_INSTALLER_BYTES`` = 128 MiB), sanitized the same way. Never raises.
    """
    if explicit is not None:
        try:
            if isinstance(explicit, bool):
                raise ValueError("bool")
            value = float(explicit)
            if math.isfinite(value) and value > 0:
                as_int = int(value)
                if as_int > 0:
                    return as_int
        except Exception:
            pass
        return int(MAX_INSTALLER_BYTES)
    try:
        from monitor_app.config import get_config

        configured = get_config(
            "update", "max_installer_bytes", MAX_INSTALLER_BYTES
        )
        if isinstance(configured, bool):
            raise ValueError("bool")
        value = float(configured)
        if math.isfinite(value) and value > 0:
            as_int = int(value)
            if as_int > 0:
                return as_int
    except Exception:
        pass
    return int(MAX_INSTALLER_BYTES)


def verify_installer_file(path: Any, sha256: Any) -> bool:
    """Re-hash ``path`` bytes and compare to ``sha256``. Never raises.

    Normalizes the expected hex (strip/lowercase, dashes/spaces dropped);
    any problem (bad hex shape, missing/unreadable file, directory,
    read error, mismatch) returns ``False``.
    """
    try:
        expected = _normalize_sha256_hex(sha256)
    except Exception:
        return False
    try:
        if not isinstance(path, str):
            return False
        if not path.strip():
            return False
        if not os.path.isfile(path):
            return False
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(_DOWNLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest() == expected
    except Exception:
        return False


def _default_opener(url: str, timeout_s: Any = None):
    """Stdlib https-only opener returning a binary file-like.

    Re-validates the ``geturl()`` final target after redirects (mirrors
    ``update_check._default_fetch``); a non-https final URL closes the
    response and raises ``ValueError``.
    """
    import urllib.request

    if not _is_allowed_https_url(url):
        raise ValueError("disallowed installer URL")
    timeout = _resolve_timeout(timeout_s)
    target = url.strip() if isinstance(url, str) else url
    request = urllib.request.Request(
        target, headers={"User-Agent": "CellWatchAI/update-check"}
    )
    response = urllib.request.urlopen(request, timeout=timeout)
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
        try:
            closer = getattr(response, "close", None)
            if callable(closer):
                closer()
        except Exception:
            pass
        raise ValueError("redirect target is not allowed")
    return response


def download_update(
    result: Any,
    updates_dir: Any = None,
    opener: Any = None,
    progress_cb: Any = None,
    cancel_event: Any = None,
    timeout_s: Any = None,
    max_installer_bytes: Any = None,
) -> PendingUpdate:
    """Download + SHA-256-verify an available update (synchronous).

    ``result`` must look like an ``UpdateAvailable`` check result (valid
    https ``installer_url`` + valid sha256 + parseable ``latest``
    version); anything else raises ``ValueError`` before any I/O.
    ``opener(url, timeout_s)`` returns a binary file-like with optional
    ``getheader("Content-Length")`` and defaults to a stdlib https-only
    implementation that re-validates redirect targets. Streams 64KB chunks
    to ``<filename>.download`` with incremental ``hashlib.sha256`` plus
    progress/cancel checks, compares normalized hex (strip/lowercase,
    dashes/spaces dropped) — mismatch deletes the temp and raises
    ``ValueError`` — then ``os.replace`` to the final file,
    ``_save_pending``, and returns the ``PendingUpdate``.
    Cancel (``cancel_event.is_set()``) deletes the temp and raises
    ``CancelledError``. Sync only; stdlib only.

    Size cap (F3): ``max_installer_bytes`` explicit arg, else config
    ``update.max_installer_bytes``, else 128 MiB. Both the
    ``Content-Length`` pre-check and the mid-stream byte count abort with
    ``ValueError`` and temp cleanup when over the cap.

    Worker-thread contract: this function runs off the UI thread;
    ``progress_cb(received, total)`` is invoked on that worker thread, must
    be thread-safe, and its exceptions are isolated (never fail the
    download). Filesystem ``OSError`` (makedirs/open/replace) is wrapped
    into the ``ValueError`` contract.
    """
    status = _result_field(result, "status", "")
    if status != "UpdateAvailable":
        raise ValueError("not an available update")
    installer_url = _result_field(result, "installer_url", "")
    installer_url = installer_url.strip() if isinstance(installer_url, str) else ""
    if not _is_allowed_https_url(installer_url):
        raise ValueError("bad installer URL")
    expected_sha = _normalize_sha256_hex(_result_field(result, "sha256", ""))
    version_raw = _result_field(result, "latest", "")
    if not isinstance(version_raw, str) or try_parse_version(version_raw) is None:
        version_raw = _result_field(result, "version", "")
        if not isinstance(version_raw, str) or try_parse_version(version_raw) is None:
            raise ValueError("bad version")
    version = version_raw.strip()
    filename = _sanitize_filename(_result_field(result, "installer_name", ""))
    if filename is None:
        try:
            url_path = urllib.parse.urlsplit(installer_url).path
            candidate = url_path.split("/")[-1] if isinstance(url_path, str) else ""
            filename = _sanitize_filename(candidate)
        except Exception:
            filename = None
    if filename is None:
        filename = _FALLBACK_FILENAME
    if _cancel_requested(cancel_event):
        raise CancelledError("cancelled")
    resolved = _resolve_updates_dir(updates_dir)
    try:
        os.makedirs(resolved, exist_ok=True)
    except OSError as exc:
        raise ValueError("download failed") from exc
    final_path = os.path.join(resolved, filename)
    if not _is_contained(resolved, final_path):
        raise ValueError("bad installer filename")
    final_path = os.path.abspath(final_path)
    if not _is_contained(resolved, final_path):
        raise ValueError("bad installer filename")
    temp_path = final_path + TRANSIENT_SUFFIX
    timeout = _resolve_timeout(timeout_s)
    limit = _resolve_max_installer_bytes(max_installer_bytes)
    open_fn = opener if callable(opener) else _default_opener
    release_raw = _result_field(result, "release_url", "")
    release_raw = release_raw.strip() if isinstance(release_raw, str) else ""
    if release_raw and not _is_allowed_https_url(release_raw):
        release_raw = ""
    release_url = release_raw
    published_at = _result_field(result, "published_at", "")
    if not isinstance(published_at, str):
        published_at = ""
    notes_raw = _result_field(result, "notes", [])
    try:
        notes = _clean_notes(notes_raw if notes_raw is not None else [])
    except Exception:
        notes = []
    try:
        response = open_fn(installer_url, timeout)
    except (CancelledError, ValueError):
        raise
    except OSError as exc:
        raise ValueError("download failed") from exc
    total = _parse_content_total(response)
    if total is not None and total > limit:
        try:
            closer = getattr(response, "close", None)
            if callable(closer):
                closer()
        except Exception:
            pass
        raise ValueError("installer too large")
    digest = hashlib.sha256()
    received = 0
    try:
        with open(temp_path, "wb") as f:
            while True:
                if _cancel_requested(cancel_event):
                    raise CancelledError("cancelled")
                try:
                    chunk = response.read(_DOWNLOAD_CHUNK_BYTES)
                except CancelledError:
                    raise
                except Exception as exc:
                    raise ValueError("download failed") from exc
                if not chunk:
                    break
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8")
                digest.update(chunk)
                try:
                    f.write(chunk)
                except OSError as exc:
                    raise ValueError("download failed") from exc
                received += len(chunk)
                if received > limit:
                    raise ValueError("installer too large")
                if _cancel_requested(cancel_event):
                    raise CancelledError("cancelled")
                if progress_cb is not None:
                    try:
                        progress_cb(received, total)
                    except Exception:
                        pass
        try:
            closer = getattr(response, "close", None)
            if callable(closer):
                closer()
        except Exception:
            pass
    except (CancelledError, ValueError):
        _remove_quietly(temp_path)
        try:
            closer = getattr(response, "close", None)
            if callable(closer):
                closer()
        except Exception:
            pass
        raise
    except OSError as exc:
        _remove_quietly(temp_path)
        try:
            closer = getattr(response, "close", None)
            if callable(closer):
                closer()
        except Exception:
            pass
        raise ValueError("download failed") from exc
    except BaseException:
        _remove_quietly(temp_path)
        try:
            closer = getattr(response, "close", None)
            if callable(closer):
                closer()
        except Exception:
            pass
        raise
    if _cancel_requested(cancel_event):
        _remove_quietly(temp_path)
        raise CancelledError("cancelled")
    actual_sha = digest.hexdigest()
    if actual_sha != expected_sha:
        _remove_quietly(temp_path)
        raise ValueError("sha256 mismatch")
    try:
        os.replace(temp_path, final_path)
    except OSError as exc:
        _remove_quietly(temp_path)
        raise ValueError("download failed") from exc
    try:
        downloaded_at = (
            datetime.datetime.now(datetime.timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except Exception:
        downloaded_at = "1970-01-01T00:00:00Z"
    pending = PendingUpdate(
        version=version,
        installer_filename=filename,
        installer_path=final_path,
        installer_url=installer_url,
        sha256=expected_sha,
        release_url=release_url,
        published_at=published_at,
        notes=list(notes),
        downloaded_at_utc=downloaded_at,
    )
    _save_pending(pending, updates_dir=resolved)
    return pending
