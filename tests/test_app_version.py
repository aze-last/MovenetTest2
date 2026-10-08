"""Slice 1 RED tests: version parse/compare + current version sanitization."""

import monitor_app
from monitor_app.app_version import get_current_version, try_parse_version


def test_parse_orders_correctly():
    """Numeric dotted ordering; pre-release/build suffixes are stripped.

    Choice: ``try_parse_version`` strips anything from the first ``'-'`` or
    ``'+'`` before numeric parsing, so ``"1.2.3-rc1"`` and ``"1.2.3+build"``
    both parse as ``(1, 2, 3)`` and compare EQUAL to ``"1.2.3"``. Full semver
    precedence (rc < release) is out of scope for Slice 1; ordering is pure
    numeric tuple comparison, so ``1.10.0 > 1.9.0`` (no lexicographic bug).
    A leading ``v`` (``"v1.2.3"``) is treated as unparseable -> None, and
    different-length tuples compare naturally with no zero-padding.
    """
    assert try_parse_version("1.10.0") > try_parse_version("1.9.0")
    assert try_parse_version("1.2.3") == try_parse_version("1.2.3")
    assert try_parse_version("1.2.3-rc1") == try_parse_version("1.2.3")
    assert try_parse_version("1.2.3+build") == try_parse_version("1.2.3")


def test_parse_invalid_returns_none():
    """Garbage/empty/None inputs return None and never raise."""
    for bad in (None, "", "   ", "garbage", "1..2", "1.2.x", "v1.2.3", "1.2-"):
        assert try_parse_version(bad) is None


def test_current_version_sanitized(monkeypatch):
    """Current version has suffixes stripped; missing source falls back."""
    monkeypatch.setattr(monitor_app, "__version__", "0.1.0+build123", raising=False)
    assert get_current_version() == "0.1.0"

    monkeypatch.setattr(monitor_app, "__version__", "0.2.0-rc1", raising=False)
    assert get_current_version() == "0.2.0"

    monkeypatch.delattr(monitor_app, "__version__", raising=False)
    assert get_current_version() == "0.1.0"


def test_parse_unicode_digits_returns_none_never_raises():
    """Unicode digits (fullwidth/Arabic/superscript) -> None, never raises."""
    for bad in (
        "１.２.３",  # fullwidth digits
        "١.٢.٣",  # arabic-indic digits
        "²",  # superscript (isdigit True, int() raises)
        "1.²",
        "½",
        "1.2.٣",
        "５.0.0",
    ):
        assert try_parse_version(bad) is None
