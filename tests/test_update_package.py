"""Slice T1 RED tests: pending-state only (no download).

Hermetic: inject tmp updates_dir, no real network, no default-dir writes.
"""

import hashlib
import json
import os
import threading
from concurrent.futures import CancelledError

import pytest

from monitor_app.update_check import Status, UpdateCheckResult
from monitor_app.update_package import (
    PendingUpdate,
    _save_pending,
    clear_pending,
    download_update,
    load_pending,
    perform_startup_maintenance,
)

_VALID_SHA = "a" * 64


def _valid_payload(updates_dir, version="0.2.0", filename="CellWatchAI-Setup-0.2.0.exe"):
    installer_path = os.path.join(str(updates_dir), filename)
    return {
        "version": version,
        "installer_filename": filename,
        "installer_path": installer_path,
        "installer_url": "https://example.com/dl/" + filename,
        "sha256": _VALID_SHA,
        "release_url": "https://example.com/releases/v" + version,
        "published_at": "2026-01-01T00:00:00Z",
        "notes": ["Bug fixes"],
        "downloaded_at_utc": "2026-01-02T00:00:00Z",
    }


def _write_pending_json(updates_dir, payload):
    os.makedirs(str(updates_dir), exist_ok=True)
    path = os.path.join(str(updates_dir), "pending.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    return path


def _touch_installer(updates_dir, filename="CellWatchAI-Setup-0.2.0.exe"):
    os.makedirs(str(updates_dir), exist_ok=True)
    path = os.path.join(str(updates_dir), filename)
    with open(path, "wb") as f:
        f.write(b"fake-installer-bytes")
    return path


def test_save_and_load_roundtrip(tmp_path):
    """_save_pending is atomic (tmp+replace) and round-trips via load."""
    updates_dir = tmp_path / "updates"
    _touch_installer(updates_dir)
    payload = _valid_payload(updates_dir)
    pending = PendingUpdate.from_dict(payload)
    _save_pending(pending, updates_dir=str(updates_dir))
    pending_path = os.path.join(str(updates_dir), "pending.json")
    assert os.path.isfile(pending_path)
    loaded = load_pending(updates_dir=str(updates_dir))
    assert loaded is not None
    assert loaded.version == "0.2.0"
    assert loaded.installer_filename == payload["installer_filename"]
    assert os.path.abspath(loaded.installer_path) == os.path.abspath(
        payload["installer_path"]
    )
    assert loaded.sha256 == _VALID_SHA
    assert loaded.notes == ["Bug fixes"]


def test_corrupt_state_returns_none_and_deletes(tmp_path):
    """Garbage JSON in pending.json -> None and the file is removed."""
    updates_dir = tmp_path / "updates"
    os.makedirs(str(updates_dir), exist_ok=True)
    pending_path = os.path.join(str(updates_dir), "pending.json")
    with open(pending_path, "w", encoding="utf-8") as f:
        f.write("{not valid json {{{")
    assert load_pending(updates_dir=str(updates_dir)) is None
    assert not os.path.exists(pending_path)


def test_missing_fields_returns_none(tmp_path):
    """Pending payload missing installer_path / sha256 -> None."""
    updates_dir = tmp_path / "updates"
    _touch_installer(updates_dir)
    for drop in ("installer_path", "sha256"):
        payload = _valid_payload(updates_dir)
        del payload[drop]
        _write_pending_json(updates_dir, payload)
        assert load_pending(updates_dir=str(updates_dir)) is None


def test_traversal_path_rejected(tmp_path):
    """installer_path escaping the updates dir via ../ -> None + file removed."""
    updates_dir = tmp_path / "updates"
    os.makedirs(str(updates_dir), exist_ok=True)
    outside = os.path.abspath(
        os.path.join(str(updates_dir), "..", "evil-setup.exe")
    )
    assert os.path.abspath(str(updates_dir)) not in outside or True
    payload = _valid_payload(updates_dir)
    payload["installer_path"] = outside
    pending_path = _write_pending_json(updates_dir, payload)
    assert load_pending(updates_dir=str(updates_dir)) is None
    assert not os.path.exists(pending_path)


def test_missing_file_returns_none(tmp_path):
    """No pending.json on disk -> None, never raises."""
    updates_dir = tmp_path / "updates"
    os.makedirs(str(updates_dir), exist_ok=True)
    assert load_pending(updates_dir=str(updates_dir)) is None


def test_maintenance_clears_when_current_ge_pending(tmp_path):
    """Pending 0.2.0 with current 0.2.0 (or newer) -> pending cleared."""
    updates_dir = tmp_path / "updates"
    _touch_installer(updates_dir)
    _write_pending_json(updates_dir, _valid_payload(updates_dir, version="0.2.0"))
    perform_startup_maintenance("0.2.0", updates_dir=str(updates_dir))
    assert load_pending(updates_dir=str(updates_dir)) is None
    assert not os.path.exists(os.path.join(str(updates_dir), "pending.json"))


def test_maintenance_clears_when_file_missing(tmp_path):
    """Pending whose installer file is missing -> cleared; *.download removed."""
    updates_dir = tmp_path / "updates"
    os.makedirs(str(updates_dir), exist_ok=True)
    # Valid pending payload but installer file NOT created.
    _write_pending_json(updates_dir, _valid_payload(updates_dir, version="0.2.0"))
    transient = os.path.join(str(updates_dir), "partial.download")
    with open(transient, "w", encoding="utf-8") as f:
        f.write("partial")
    perform_startup_maintenance("0.1.0", updates_dir=str(updates_dir))
    assert load_pending(updates_dir=str(updates_dir)) is None
    assert not os.path.exists(os.path.join(str(updates_dir), "pending.json"))
    assert not os.path.exists(transient)


def test_clear_pending_removes_state(tmp_path):
    """clear_pending removes pending.json (used by maintenance path)."""
    updates_dir = tmp_path / "updates"
    installer_path = _touch_installer(updates_dir)
    _write_pending_json(updates_dir, _valid_payload(updates_dir))
    assert os.path.isfile(installer_path)
    clear_pending(updates_dir=str(updates_dir))
    assert not os.path.exists(os.path.join(str(updates_dir), "pending.json"))
    assert not os.path.exists(installer_path)
    assert load_pending(updates_dir=str(updates_dir)) is None


# --- Slice T2 RED: download + SHA-256 verify (hermetic, injectable opener) ---


def _available_result(version="0.2.0", filename="CellWatchAI-Setup-0.2.0.exe",
                      url=None, sha=None):
    installer_url = url if url is not None else "https://example.com/dl/" + filename
    return UpdateCheckResult(
        status=Status.UpdateAvailable,
        current="0.1.0",
        latest=version,
        published_at="2026-01-01T00:00:00Z",
        release_url="https://example.com/releases/v" + version,
        installer_name=filename,
        installer_url=installer_url,
        sha256=sha if sha is not None else _VALID_SHA,
        notes=["Bug fixes"],
        message="Update available: %s." % version,
    )


class _FakeBody:
    """Binary file-like mirroring urllib response subset for tests."""

    def __init__(self, data: bytes):
        self._data = bytes(data)
        self._pos = 0

    def getheader(self, name):
        if isinstance(name, str) and name.lower() == "content-length":
            return str(len(self._data))
        return None

    def read(self, n=-1):
        if self._pos >= len(self._data):
            return b""
        if n is None or n < 0:
            chunk = self._data[self._pos:]
            self._pos = len(self._data)
            return chunk
        chunk = self._data[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _payload_bytes(n=75000):
    return (b"installer-bytes-" * (n // 16 + 1))[:n]


def test_valid_download_writes_file_and_state(tmp_path):
    """Fake opener yields exact bytes + total; file + pending state match."""
    data = _payload_bytes(75000)
    sha = hashlib.sha256(data).hexdigest()
    filename = "CellWatchAI-Setup-0.2.0.exe"
    result = _available_result(filename=filename, sha=sha)
    seen = {}

    def opener(url, timeout_s=None):
        seen["url"] = url
        seen["timeout"] = timeout_s
        return _FakeBody(data)

    updates_dir = tmp_path / "updates"
    pending = download_update(result, updates_dir=str(updates_dir), opener=opener)
    assert seen["url"] == result.installer_url
    final_path = os.path.join(str(updates_dir), filename)
    assert os.path.isfile(final_path)
    with open(final_path, "rb") as f:
        assert f.read() == data
    assert not os.path.exists(final_path + ".download")
    assert pending.version == "0.2.0"
    assert pending.sha256 == sha
    assert pending.installer_filename == filename
    loaded = load_pending(updates_dir=str(updates_dir))
    assert loaded is not None
    assert loaded.version == "0.2.0"
    assert loaded.sha256 == sha
    with open(loaded.installer_path, "rb") as f:
        assert f.read() == data


def test_sha_mismatch_deletes_temp_and_raises(tmp_path):
    """One flipped byte -> ValueError, no final file, no state, temp gone."""
    data = _payload_bytes(70000)
    sha = hashlib.sha256(data).hexdigest()
    bad = bytearray(data)
    bad[100] ^= 0xFF
    bad = bytes(bad)
    assert hashlib.sha256(bad).hexdigest() != sha
    filename = "CellWatchAI-Setup-0.2.0.exe"
    result = _available_result(filename=filename, sha=sha)

    def opener(url, timeout_s=None):
        return _FakeBody(bad)

    updates_dir = tmp_path / "updates"
    with pytest.raises(ValueError):
        download_update(result, updates_dir=str(updates_dir), opener=opener)
    final_path = os.path.join(str(updates_dir), filename)
    assert not os.path.exists(final_path)
    assert not os.path.exists(final_path + ".download")
    assert not os.path.exists(os.path.join(str(updates_dir), "pending.json"))
    assert load_pending(updates_dir=str(updates_dir)) is None


def test_cancel_aborts_and_cleans(tmp_path):
    """cancel_event set mid-stream -> CancelledError/ValueError, temp gone."""
    data = _payload_bytes(200000)
    sha = hashlib.sha256(data).hexdigest()
    filename = "CellWatchAI-Setup-0.2.0.exe"
    result = _available_result(filename=filename, sha=sha)
    cancel_event = threading.Event()

    class _CancellingBody(_FakeBody):
        def read(self, n=-1):
            chunk = super().read(n)
            if chunk:
                cancel_event.set()
            return chunk

    def opener(url, timeout_s=None):
        return _CancellingBody(data)

    updates_dir = tmp_path / "updates"
    with pytest.raises(CancelledError):
        download_update(
            result, updates_dir=str(updates_dir), opener=opener,
            cancel_event=cancel_event,
        )
    final_path = os.path.join(str(updates_dir), filename)
    assert not os.path.exists(final_path)
    assert not os.path.exists(final_path + ".download")
    assert load_pending(updates_dir=str(updates_dir)) is None


def test_progress_reports_received_total(tmp_path):
    """progress_cb calls monotonic, final == total == len(bytes)."""
    data = _payload_bytes(150000)
    sha = hashlib.sha256(data).hexdigest()
    filename = "CellWatchAI-Setup-0.2.0.exe"
    result = _available_result(filename=filename, sha=sha)
    calls = []

    def opener(url, timeout_s=None):
        return _FakeBody(data)

    def progress_cb(received, total):
        calls.append((received, total))

    updates_dir = tmp_path / "updates"
    download_update(
        result, updates_dir=str(updates_dir), opener=opener,
        progress_cb=progress_cb,
    )
    assert calls, "expected progress callbacks"
    totals = {total for _, total in calls}
    assert totals == {len(data)}
    received_list = [received for received, _ in calls]
    assert received_list[-1] == len(data)
    assert all(b > a for a, b in zip(received_list, received_list[1:]))
    assert all(0 < r <= len(data) for r in received_list)


def test_nondownloadable_result_raises_before_network(tmp_path):
    """Bad sha shape / http installer URL -> raises, opener never called."""
    data = _payload_bytes(1000)
    updates_dir = tmp_path / "updates"

    for bad_result in (
        _available_result(sha="not-a-sha"),
        _available_result(sha="a" * 63),
        _available_result(url="http://example.com/dl/setup.exe"),
    ):
        called = {"n": 0}

        def opener(url, timeout_s=None):
            called["n"] += 1
            return _FakeBody(data)

        with pytest.raises(ValueError):
            download_update(
                bad_result, updates_dir=str(updates_dir), opener=opener
            )
        assert called["n"] == 0


def test_filename_traversal_sanitized(tmp_path):
    """installer_name '../../evil.exe' -> file lands inside updates dir."""
    data = _payload_bytes(5000)
    sha = hashlib.sha256(data).hexdigest()
    result = _available_result(filename="../../evil.exe", sha=sha)

    def opener(url, timeout_s=None):
        return _FakeBody(data)

    updates_dir = tmp_path / "updates"
    pending = download_update(result, updates_dir=str(updates_dir), opener=opener)
    assert "/" not in pending.installer_filename
    assert "\\" not in pending.installer_filename
    assert pending.installer_filename == "evil.exe"
    base = os.path.abspath(str(updates_dir))
    target = os.path.abspath(pending.installer_path)
    assert os.path.commonpath([base, target]) == base
    assert os.path.isfile(target)
    with open(target, "rb") as f:
        assert f.read() == data
    outside = os.path.abspath(os.path.join(str(updates_dir), "..", "evil.exe"))
    assert not os.path.exists(outside)
    assert load_pending(updates_dir=str(updates_dir)) is not None


# --- Security review fix-first (F2/F3/F1 + MEDIUMs): RED first ---


def test_default_opener_rejects_http_redirect(monkeypatch):
    """F2: _default_opener must re-validate geturl() final target (http -> ValueError)."""
    import urllib.request

    from monitor_app import update_package as upkg

    class _RedirBody:
        def geturl(self):
            return "http://evil.example/payload.exe"

        def getheader(self, name):
            return None

        def read(self, n=-1):
            return b""

        def close(self):
            pass

    def _fake_urlopen(request, timeout=None):
        return _RedirBody()

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    with pytest.raises(ValueError):
        upkg._default_opener("https://example.com/dl/setup.exe", 5)


def test_download_rejects_oversized_content_length(tmp_path):
    """F3 pre-check: Content-Length over limit -> ValueError, temp cleaned."""
    from monitor_app import update_package as upkg

    data = _payload_bytes(2000)
    sha = hashlib.sha256(data).hexdigest()
    result = _available_result(sha=sha)

    class _BigLenBody(_FakeBody):
        def getheader(self, name):
            if isinstance(name, str) and name.lower() == "content-length":
                return str(len(self._data) * 10)
            return None

    def opener(url, timeout_s=None):
        return _BigLenBody(data)

    updates_dir = tmp_path / "updates"
    with pytest.raises(ValueError):
        upkg.download_update(
            result,
            updates_dir=str(updates_dir),
            opener=opener,
            max_installer_bytes=1024,
        )
    final_path = os.path.join(
        str(updates_dir), "CellWatchAI-Setup-0.2.0.exe"
    )
    assert not os.path.exists(final_path)
    assert not os.path.exists(final_path + ".download")
    assert upkg.load_pending(updates_dir=str(updates_dir)) is None


def test_download_aborts_midstream_when_over_limit(tmp_path):
    """F3 mid-stream: hidden length but bytes over limit -> ValueError + cleanup."""
    from monitor_app import update_package as upkg

    data = _payload_bytes(5000)
    sha = hashlib.sha256(data).hexdigest()
    result = _available_result(sha=sha)

    class _NoLenBody(_FakeBody):
        def getheader(self, name):
            return None

        @property
        def headers(self):
            return {}

    def opener(url, timeout_s=None):
        return _NoLenBody(data)

    updates_dir = tmp_path / "updates"
    with pytest.raises(ValueError):
        upkg.download_update(
            result,
            updates_dir=str(updates_dir),
            opener=opener,
            max_installer_bytes=1000,
        )
    final_path = os.path.join(
        str(updates_dir), "CellWatchAI-Setup-0.2.0.exe"
    )
    assert not os.path.exists(final_path)
    assert not os.path.exists(final_path + ".download")
    assert upkg.load_pending(updates_dir=str(updates_dir)) is None


def test_resolve_max_installer_bytes_sanitized(monkeypatch):
    """F3 helper: explicit -> config -> default (134217728), sanitized."""
    from monitor_app import update_package as upkg

    assert upkg._resolve_max_installer_bytes(1234) == 1234
    assert upkg._resolve_max_installer_bytes(None) == 134217728
    for bad in (-5, 0, "not-a-number", float("nan"), float("inf"), None.__class__):
        # invalid explicit values collapse to default (never raise)
        if bad is None.__class__:
            continue
        assert upkg._resolve_max_installer_bytes(bad) == 134217728


def test_verify_installer_file_true_on_match(tmp_path):
    """F1: verify_installer_file re-hashes bytes, True on match (normalized)."""
    from monitor_app.update_package import verify_installer_file

    data = _payload_bytes(4096)
    sha = hashlib.sha256(data).hexdigest()
    target = tmp_path / "setup.exe"
    with open(str(target), "wb") as f:
        f.write(data)
    assert verify_installer_file(str(target), sha) is True
    # normalize: uppercase + dashes/spaces are dropped
    decorated = "-".join([sha[i:i + 8] for i in range(0, 64, 8)]).upper()
    assert verify_installer_file(str(target), "  " + decorated + "  ") is True


def test_verify_installer_file_false_on_mismatch(tmp_path):
    """F1: one flipped byte -> False (never raises)."""
    from monitor_app.update_package import verify_installer_file

    data = _payload_bytes(4096)
    sha = hashlib.sha256(data).hexdigest()
    bad = bytearray(data)
    bad[10] ^= 0xFF
    target = tmp_path / "setup.exe"
    with open(str(target), "wb") as f:
        f.write(bytes(bad))
    assert verify_installer_file(str(target), sha) is False


def test_verify_installer_file_false_on_missing_and_bad_sha(tmp_path):
    """F1: missing file / bad sha / dir -> False, never raises."""
    from monitor_app.update_package import verify_installer_file

    missing = os.path.join(str(tmp_path), "nope.exe")
    assert verify_installer_file(missing, "a" * 64) is False
    assert verify_installer_file(missing, "not-a-sha") is False
    assert verify_installer_file(str(tmp_path), "a" * 64) is False
    assert verify_installer_file(None, "a" * 64) is False
    assert verify_installer_file("", "a" * 64) is False


def test_sanitize_rejects_allowlist():
    """MEDIUM filename allowlist: NUL/control/illegal/reserved/long -> None/ValueError."""
    from monitor_app import update_package as upkg

    for bad in (
        "bad\x00name.exe",
        "bad\x01name.exe",
        "bad\x1fname.exe",
        "bad\x7fname.exe",
        "a<b>.exe",
        "a|b.exe",
        'a"b.exe',
        "a?b.exe",
        "a*b.exe",
        "CON.exe",
        "con.exe",
        "NUL.exe",
        "COM1.exe",
        "LPT9.exe",
        "trailingdot.",
        "A" * 300 + ".exe",
    ):
        assert upkg._sanitize_filename(bad) is None, bad
        payload = _valid_payload(".", filename="CellWatchAI-Setup-0.2.0.exe")
        payload["installer_filename"] = bad
        with pytest.raises(ValueError):
            upkg.PendingUpdate.from_dict(payload)


def test_progress_cb_exception_isolated(tmp_path):
    """MEDIUM: progress_cb throw must never fail the download."""
    data = _payload_bytes(80000)
    sha = hashlib.sha256(data).hexdigest()
    result = _available_result(sha=sha)

    def opener(url, timeout_s=None):
        return _FakeBody(data)

    def bad_progress(received, total):
        raise RuntimeError("boom-from-ui-thread")

    updates_dir = tmp_path / "updates"
    pending = download_update(
        result,
        updates_dir=str(updates_dir),
        opener=opener,
        progress_cb=bad_progress,
    )
    assert pending.version == "0.2.0"
    final_path = os.path.join(str(updates_dir), pending.installer_filename)
    with open(final_path, "rb") as f:
        assert f.read() == data


def test_release_url_non_https_becomes_blank(tmp_path):
    """MEDIUM: from_dict https-gates release_url (non-https -> blank, no raise)."""
    from monitor_app import update_package as upkg

    updates_dir = tmp_path / "updates"
    _touch_installer(updates_dir)
    payload = _valid_payload(updates_dir)
    payload["release_url"] = "http://example.com/releases/v0.2.0"
    pending = upkg.PendingUpdate.from_dict(payload)
    assert pending.release_url == ""
    payload["release_url"] = "https://example.com/releases/v0.2.0"
    assert upkg.PendingUpdate.from_dict(payload).release_url.startswith("https://")
    payload["release_url"] = ""
    assert upkg.PendingUpdate.from_dict(payload).release_url == ""


def test_download_makedirs_open_oserror_becomes_valueerror(tmp_path, monkeypatch):
    """MEDIUM: makedirs/open OSError collapses into ValueError contract."""
    import monitor_app.update_package as upkg

    data = _payload_bytes(2000)
    sha = hashlib.sha256(data).hexdigest()
    result = _available_result(sha=sha)

    def opener(url, timeout_s=None):
        return _FakeBody(data)

    def _boom(path, exist_ok=False):
        raise OSError("disk-readonly")

    monkeypatch.setattr(upkg.os, "makedirs", _boom)
    with pytest.raises(ValueError):
        upkg.download_update(
            result, updates_dir=str(tmp_path / "updates"), opener=opener
        )


def test_maintenance_sweeps_tmp_alongside_download(tmp_path):
    """MEDIUM: startup maintenance removes *.tmp as well as *.download."""
    updates_dir = tmp_path / "updates"
    os.makedirs(str(updates_dir), exist_ok=True)
    stale_tmp = os.path.join(str(updates_dir), "partial.tmp")
    stale_dl = os.path.join(str(updates_dir), "partial.download")
    with open(stale_tmp, "w", encoding="utf-8") as f:
        f.write("tmp")
    with open(stale_dl, "w", encoding="utf-8") as f:
        f.write("partial")
    perform_startup_maintenance("0.1.0", updates_dir=str(updates_dir))
    assert not os.path.exists(stale_tmp)
    assert not os.path.exists(stale_dl)
