# Self-Updating Desktop App Workflow

## Problem
Maintainers shipping a Python desktop app must distribute every fix as a manual full-reinstaller handoff. Users run stale versions, version drift grows across sites, and each release costs maintainer support time. Leaving it unsolved keeps release friction high and delays fixes reaching users.

## Evidence
- Assumption — needs validation via maintainer report (time spent per manual reinstall, support threads per release, count of sites on stale versions).

## Users
- **Primary**: Maintainer/dev shipping releases for a Python desktop app — triggered when a new version is ready and users must move off the old one.
- **Not for**: End-users seeking silent/auto background updates; operators on fully offline sites with no download path.

## Hypothesis
We believe **a consent-gated self-update workflow (check on startup, user-confirmed download with integrity verification, guided install)** will **remove manual reinstall handoffs** for **maintainers**.
We'll know we're right when **a new release reaches installed users without a manual EXE copy (update adoption within N days, zero manual-copy support requests per release)**.

## Success Metrics
| Metric | Target | How measured |
|---|---|---|
| Release adoption without manual copy | TBD — needs validation via maintainer baseline | % installs on latest within N days of publish |
| Support burden per release | TBD — needs validation via support log | Manual-update help requests per release |

## Scope
**MVP** — Full consent-gated flow: app learns a newer version exists, user chooses to download it, integrity is verified before install, and install only runs after an explicit Yes. Includes a release-publish path so a new version can be announced with notes.

**Out of scope**
- Silent/auto-install without explicit user consent — excluded for safety/trust; every install requires Yes + verification.
- Installer build automation until asked — per source-prompt constraint; release artifacts are assumed to exist before publish.
- Delta/patch updates — full installer only for MVP.

## Delivery Milestones
<!-- Business outcomes, not engineering tasks. /plan turns each into a plan. -->
<!-- Status: pending | in-progress | complete -->

| # | Milestone | Outcome | Status | Plan |
|---|---|---|---|---|
| 1 | Update availability known | User sees a new version is available with its release notes | pending | — |
| 2 | Verified package in hand | User downloads the new installer with integrity confirmed, resumable across sessions | pending | — |
| 3 | Guided install | User confirms install, app hands off to installer and exits cleanly | pending | — |

## Open Questions
- [ ] Which target repo/GUI framework/packager does this apply to? (brackets unfilled: GUI, PyInstaller mode + setup maker, version source, manifest host, local data dir)
- [ ] Where are the manifest and installer hosted, and what is the single source of the current version?
- [ ] What counts as "adopted" (time window, offline-site handling)?

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Target stack unknown — requirements shift per GUI/packager | High | High | Fill brackets before /plan; keep PRD stack-agnostic |
| Users distrust update prompts (phishing-like) | Medium | High | Consent-gated wording + verified publisher/installer identity |
| Corrupt/tampered download installed | Low | High | Mandatory hash verification; failed verify blocks install |
| Offline sites never see updates | Medium | Medium | Keep manual-installer fallback; PRD success excludes offline cohort |

---
*Status: DRAFT — requirements only. Implementation planning pending via /plan.*
