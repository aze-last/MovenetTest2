# Plan — Milestone 1: Update availability known

Source PRD: `.claude/prds/self-updating-desktop-workflow.prd.md` (Milestone 1 of 3).
TDD: RED → GREEN → refactor, 80%+ coverage on new code. Two checkpoint commits (`test:`, `fix:`).

## Goal
Installed app can determine, from a published manifest, whether a newer version exists —
and present version + notes. No download, no install, no UI banner in this milestone.

## User journeys
1. As maintainer, I publish `version.json` so installed apps can detect a newer version.
2. As user, I learn a new version exists (version + notes) so I can choose to update.

## Test runner (Step 0)
- Python/pytest: `.venv310\Scripts\python.exe -m pytest tests/ -q`
- Coverage: `-m pytest --cov=<pkg> --cov-report=term` (threshold 80% on new modules)

## Test spec (write first — RED gate)
| # | Guarantee | Test | Type |
|---|---|---|---|
| 1 | Valid semver parses to comparable tuple; `1.10.0 > 1.9.0` | `test_app_version.py::test_parse_orders_correctly` | unit |
| 2 | Garbage/empty version → None, never throws | `test_app_version.py::test_parse_invalid_returns_none` | unit |
| 3 | Current version sanitized (`+build`/`-suffix` stripped), fallback `1.0.0` | `test_app_version.py::test_current_version_sanitized` | unit |
| 4 | Empty manifest URL → NotConfigured, no HTTP call | `test_update_check.py::test_empty_url_not_configured` | unit |
| 5 | Malformed JSON / missing version / timeout → Failed | `test_update_check.py::test_bad_payload_or_timeout_failed` | unit |
| 6 | latest > current → UpdateAvailable with version + notes | `test_update_check.py::test_newer_manifest_available` | unit |
| 7 | latest <= current → UpToDate | `test_update_check.py::test_same_or_older_uptodate` | unit |
| 8 | Notes trimmed, empties dropped | `test_update_check.py::test_notes_trimmed` | unit |

Mock HTTP at the client boundary; no real network in tests.

## Minimal implementation (GREEN gate)
- `app_version.py`: `get_current_version() -> str`, `try_parse_version(s) -> tuple | None`
- `update_check.py`: `UpdateManifest`, `UpdateCheckResult(status, current, latest, published_at, release_url, installer_name/url, sha256, notes[], message)` + `is_update_available`, `async check_for_updates(manifest_url, http_client, current_version)`; `Status = NotChecked|NotConfigured|UpToDate|UpdateAvailable|Failed`
- Rules: 15s timeout, custom UA; invalid JSON/version → Failed; compare parsed tuples.

## Validation
1. New tests fail before prod code (RED evidence).
2. Same target passes after (GREEN evidence).
3. Full suite: no regressions. Coverage ≥80% on new modules.
4. Evidence report (tdd-workflow Step 8) with RED/GREEN logs.

## Out of scope (Milestones 2–3)
Download, hash verify, pending-state, installer launch, dashboard banner, Settings tab, WhatsNew modal, release tooling.

## TBD by implementer (fill at start)
Version single-source, manifest host URL, HTTP client (`httpx` vs `requests`), package path for new modules.
