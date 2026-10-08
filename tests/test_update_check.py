"""Slice 2 RED tests: synchronous update availability check (Milestone 1).

Synchronous by design (no asyncio in this repo; GEMINI Rule 1) — the caller
runs ``check_for_updates`` off the UI thread. HTTP is mocked at the fetcher
boundary; no real network in tests.
"""

import json

from monitor_app.update_check import Status, _default_fetch, _user_agent, check_for_updates


def _make_manifest(version, notes=None):
    """Build a manifest dict in the published shape."""
    return {
        "version": version,
        "notes": list(notes) if notes is not None else ["Initial notes"],
        "publishedAt": "2026-01-01T00:00:00Z",
        "releasePageUrl": "https://example.com/releases/vX",
        "installerFileName": "CellWatchAI-Setup.exe",
        "installerUrl": "https://example.com/dl/CellWatchAI-Setup.exe",
        "sha256": "a" * 64,
    }


def test_empty_url_not_configured():
    """Empty/whitespace URL -> NotConfigured, no HTTP fetch attempted."""

    def _must_not_be_called(url):
        raise AssertionError("fetcher must not be called for empty URL")

    for bad_url in ("", "   "):
        result = check_for_updates(bad_url, "0.1.0", fetcher=_must_not_be_called)
        assert result.status == Status.NotConfigured
        assert result.is_update_available is False


def test_bad_payload_or_timeout_failed():
    """Malformed JSON / missing / invalid version / timeout -> Failed, never throws."""
    cases = [
        lambda url: "not json{{{",  # malformed JSON
        lambda url: json.dumps({"notes": ["x"]}),  # missing version field
        lambda url: json.dumps(_make_manifest("garbage!!")),  # invalid version
        lambda url: json.dumps(_make_manifest("")),  # empty version
    ]

    def _timeout(url):
        raise TimeoutError("timed out")

    for fetcher in cases + [_timeout]:
        result = check_for_updates(
            "https://example.com/version.json", "0.1.0", fetcher=fetcher
        )
        assert result.status == Status.Failed
        assert result.is_update_available is False


def test_newer_manifest_available():
    """Manifest version > current -> UpdateAvailable with latest version + notes."""
    manifest = _make_manifest("0.2.0", notes=["Bug fixes", "New feature"])
    result = check_for_updates(
        "https://example.com/version.json", "0.1.0", fetcher=lambda url: manifest
    )
    assert result.status == Status.UpdateAvailable
    assert result.is_update_available is True
    assert result.latest == "0.2.0"
    assert result.notes == ["Bug fixes", "New feature"]


def test_same_or_older_uptodate():
    """Equal and older manifest versions -> UpToDate."""
    same = check_for_updates(
        "https://example.com/version.json",
        "0.1.0",
        fetcher=lambda url: _make_manifest("0.1.0"),
    )
    assert same.status == Status.UpToDate
    assert same.is_update_available is False

    older = check_for_updates(
        "https://example.com/version.json",
        "0.1.0",
        fetcher=lambda url: _make_manifest("0.0.9"),
    )
    assert older.status == Status.UpToDate
    assert older.is_update_available is False


def test_notes_trimmed():
    """Notes are whitespace-trimmed; empty strings are dropped."""
    manifest = _make_manifest("0.2.0", notes=["  hello  ", "   ", "", "world\n"])
    result = check_for_updates(
        "https://example.com/version.json", "0.1.0", fetcher=lambda url: manifest
    )
    assert result.status == Status.UpdateAvailable
    assert result.notes == ["hello", "world"]


# --- Security hardening RED tests (TDD fix pass; stdlib only) ---

_VALID_SHA = "a" * 64


def _valid_manifest(version="0.2.0", **overrides):
    base = _make_manifest(version)
    base["sha256"] = _VALID_SHA
    base.update(overrides)
    return base


def test_manifest_url_non_https_rejected():
    """http/file/ftp/userinfo manifest URLs -> Failed, fetcher never called."""
    bad_urls = [
        "http://example.com/version.json",
        "file:///C:/Windows/win.ini",
        "ftp://example.com/version.json",
        "https://user:pass@example.com/version.json",
        "https://example.com@evil.com/version.json",
        "HTTP://example.com/version.json",
    ]
    for bad_url in bad_urls:
        called = []

        def _tracker(url):
            called.append(url)
            return _valid_manifest("0.2.0")

        result = check_for_updates(bad_url, "0.1.0", fetcher=_tracker)
        assert result.status == Status.Failed
        assert called == []


def test_default_fetch_rejects_bad_input():
    """_default_fetch enforces https-only; non-string/empty/bad scheme raises."""
    import pytest

    for bad in (None, 123, "", "   ", "http://example.com/x.json",
                "file:///etc/passwd", "ftp://example.com/x.json",
                "https://user@example.com/x.json"):
        with pytest.raises(ValueError):
            _default_fetch(bad)


def test_default_fetch_never_opens_local_files(tmp_path):
    """file:// must raise before any local file is opened (no content leak)."""
    import pytest

    sentinel = tmp_path / "secret.txt"
    sentinel.write_text("TOP-SECRET-CONTENT", encoding="utf-8")
    file_url = sentinel.as_uri()
    assert file_url.startswith("file://")
    with pytest.raises(ValueError):
        _default_fetch(file_url)


def test_default_fetch_revalidates_redirect_target(monkeypatch):
    """Post-redirect final URL must still be https+host, else raise."""
    import urllib.request

    import pytest

    from monitor_app import update_check as uc

    class _FakeRedirect:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def geturl(self):
            return "http://evil.example.com/version.json"

        def getheader(self, name, default=None):
            return None

        def read(self, size=-1):
            return b'{"version": "0.2.0"}'

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _FakeRedirect())
    with pytest.raises(ValueError):
        uc._default_fetch("https://example.com/version.json")


def test_default_fetch_size_cap(monkeypatch):
    """Oversized Content-Length or body -> _default_fetch raises ValueError."""
    import urllib.request

    import pytest

    from monitor_app import update_check as uc

    cap = 256 * 1024

    class _FakeBigLength:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def geturl(self):
            return "https://example.com/version.json"

        def getheader(self, name, default=None):
            if name.lower() == "content-length":
                return str(cap + 1)
            return None

        def read(self, size=-1):
            return b"x"

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _FakeBigLength())
    with pytest.raises(ValueError):
        uc._default_fetch("https://example.com/version.json")

    class _FakeBigBody:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def geturl(self):
            return "https://example.com/version.json"

        def getheader(self, name, default=None):
            return None

        def __init__(self):
            self._left = cap + 16

        def read(self, size=-1):
            if self._left <= 0:
                return b""
            chunk = b"x" * min(self._left, 16384)
            self._left -= len(chunk)
            return chunk

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _FakeBigBody())
    with pytest.raises(ValueError):
        uc._default_fetch("https://example.com/version.json")


def test_oversized_manifest_body_rejected():
    """Oversized fake body via injected fetcher -> Failed (size cap)."""
    big_notes = ["y" * 1000 for _ in range(300)]  # ~300 KiB valid JSON
    manifest = _valid_manifest("0.2.0", notes=big_notes)
    body = json.dumps(manifest)
    assert len(body.encode("utf-8")) > 256 * 1024
    result = check_for_updates(
        "https://example.com/version.json", "0.1.0", fetcher=lambda url: body
    )
    assert result.status == Status.Failed


def test_manifest_trust_root_rejects_bad_sha_and_installer():
    """Malformed sha256 ('abc123') or non-https installer URL -> Failed."""
    bad_sha = _valid_manifest("0.2.0", sha256="abc123")
    result = check_for_updates(
        "https://example.com/version.json", "0.1.0", fetcher=lambda url: bad_sha
    )
    assert result.status == Status.Failed

    bad_url = _valid_manifest(
        "0.2.0", installerUrl="http://example.com/dl/Setup.exe"
    )
    result = check_for_updates(
        "https://example.com/version.json", "0.1.0", fetcher=lambda url: bad_url
    )
    assert result.status == Status.Failed


def test_notes_caps_and_truncation():
    """Max 50 notes, 500 chars each (truncate), non-list -> []."""
    many = [f"note-{i}" for i in range(60)]
    manifest = _valid_manifest("0.2.0", notes=many)
    result = check_for_updates(
        "https://example.com/version.json", "0.1.0", fetcher=lambda url: manifest
    )
    assert result.status == Status.UpdateAvailable
    assert len(result.notes) == 50

    long_note = "z" * 600
    manifest = _valid_manifest("0.2.0", notes=[long_note])
    result = check_for_updates(
        "https://example.com/version.json", "0.1.0", fetcher=lambda url: manifest
    )
    assert len(result.notes[0]) == 500

    for raw in ("not-a-list", None, {"a": 1}, 123):
        manifest = _valid_manifest("0.2.0", notes=raw)
        result = check_for_updates(
            "https://example.com/version.json", "0.1.0", fetcher=lambda url: manifest
        )
        assert result.notes == []


def test_message_hygiene_no_url_or_exception_leak():
    """User-facing message must not echo raw exception text or manifest URL."""
    secret_url = "https://secret-host-xyz-unique.example.com/version.json"

    def _boom(url):
        raise RuntimeError("SECRET-XYZ-123-BOOM")

    result = check_for_updates(secret_url, "0.1.0", fetcher=_boom)
    assert result.status == Status.Failed
    assert "SECRET-XYZ-123-BOOM" not in result.message
    assert "secret-host-xyz-unique" not in result.message

    result = check_for_updates(secret_url, "0.1.0", fetcher=lambda url: "not json{{{")
    assert result.status == Status.Failed
    assert "secret-host-xyz-unique" not in result.message


def test_user_agent_static_without_version(monkeypatch):
    """User-Agent is static and never embeds the app version."""
    import monitor_app

    monkeypatch.setattr(monitor_app, "__version__", "9.9.9", raising=False)
    ua = _user_agent()
    assert "9.9.9" not in ua
    assert "0.1.0" not in ua
    assert isinstance(ua, str) and ua.strip() != ""


def test_explicit_timeout_s_keeps_check_hermetic():
    """Explicit timeout_s path works without touching config (hermetic)."""
    manifest = _valid_manifest("0.2.0")
    result = check_for_updates(
        "https://example.com/version.json",
        "0.1.0",
        fetcher=lambda url: manifest,
        timeout_s=5,
    )
    assert result.status == Status.UpdateAvailable
