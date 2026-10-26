---
name: obsidian-second-brain
description: Second-brain bootstrap and knowledge routing for the whole crew. Scaffolds an Obsidian-compatible Markdown vault (Notes/) in any project on first contact, defines the note taxonomy and templates (task cards, instinct notes, decision records), and routes task cards, decision logs, instinct notes, briefs, and research dossiers into it via wikilinks. Use when creating or maintaining the project second brain, filing task cards or instinct notes for humans, saving research to Obsidian, or when asked to route agent output into a vault / Obsidian.
---

# Obsidian Second Brain

You scaffold and operate the project's **second brain**: an Obsidian-compatible Markdown vault in `<project-root>/Notes/`. Plain Markdown + `[[wikilinks]]` is the format so that **every AI agent in the crew can read and write it with the file tools it already has**, while the human browses, links, and expands it inside Obsidian with graph view and templates.

Do not duplicate `.agents/rules.md` rules here — this skill defines *where knowledge lives*; `rules.md` remains the single source of behavioral truth.

## 1. Non-Negotiable Rules

1. **Harness-agnostic format**: Every note is plain Markdown with `[[wikilinks]]`, YAML frontmatter, and headings an agent can parse without Obsidian itself.
2. **Archive, never delete**: Superseded or finished notes move to `Notes/90-Archive/` (rules.md §4 — no hard deletes).
3. **No secrets**: Never write credential values, `.env` contents, or DB binaries into notes (rules.md §4). Mentioning file *names* like `.env` in prose is fine.
4. **Recall before write**: Before creating a note, scan the relevant folder / `Notes/Home.md` MOC. One idea = one note. Update instead of duplicating.
5. **Wiki-keeper owns structure**: Content may be written by the routing table (§4), but folder taxonomy, MOC upkeep, and deduplication are the wiki-keeper's job.

## 2. Vault Bootstrap (run once per project)

Create exactly this tree:

```text
Notes/
├─ .obsidian/app.json        ← content: {} (lets Obsidian trust the folder instantly)
├─ Home.md                   ← MOC: project index + status table
├─ 00-Inbox/                 ← raw captures; wiki-keeper trims within 48h
├─ 10-Projects/<slug>/       ← slug = kebab-case initiative name
│   ├─ brief.md              ← short mission statement, links to PLAN.md
│   ├─ TODO-<task-id>.md     ← task cards (wiki-keeper template)
│   └─ Decision-Log.md       ← decision records
├─ 20-Learning/<trigger-slug>.md  ← instinct notes (trigger/action/evidence/scope)
├─ 30-Templates/             ← the six templates below, one file each
└─ 90-Archive/               ← soft-delete destination (append-only)
```

After scaffolding: create `Notes/Home.md` from the MOC template, seed the project's `10-Projects/<slug>/brief.md`, and report the vault path back to the coordinator.

## 3. Templates (place each in `Notes/30-Templates/`)

### `Home.md` — Master Content of Contents (MOC)

```markdown
# Project Home
Updated: <date>

## Status
| Area | Notes (wikilinks) | Status |
|---|---|---|

## Directories
- [[49-Projects]] — briefs, task cards, decision logs
- [[Learning]] — instinct notes
```

### `brief.md` — Project Brief

```markdown
---
tags: [brief, project]
---
# <Project Name>
Objective: <one paragraph>
Source of truth: `PLAN.md` (build contract) + `.agents/rules.md` (behavior contract)
Open questions:
-
```

### `task-card.md` — Task Card (wiki-keeper format)

```markdown
---
tags: [task, status/todo]
---
# <Task Title>
Owner: <Role / Subagent>
Plan Reference: `PLAN.md` — <Task ID>
Scope: <file paths touched>
Status: TODO | DOING | DONE
Exit Gate: <criteria verified by diff-scan.ps1 + verifier>
Related: [[brief]] · [[Decision-Log]]
```

### `instinct-note.md` — Instinct Note (rules.md §3 format)

```markdown
---
tags: [instinct, project]
---
# <trigger-slug>
trigger: when <condition>
action: <one-sentence actionable rule or mitigation>
evidence: <what broke, file:line, counts>
scope: project | global
Origin: fix report for `PLAN.md` <Task ID> · <date>
```

### `Decision-Log.md` — Decision Record

```markdown
---
tags: [decision]
---
## <date> — <title>
- Context: <why this decision was needed>
- Decision: <what was chosen>
- Consequence: <what changes / what code this affects>
- Reversal path: [[<counter-note>]] | none
```

### `research-dossier.md` — Web / Code-base Dossier

```markdown
---
tags: [research]
---
# <Source / Target>
Crawled: <date> · By: <agent> · Source: <URL or path>
## Findings
-
## Extracted interactions
-
```

## 4. Routing Table (who writes where)

| Agent | Writes to | What |
|---|---|---|
| Planner (`kiro-planner.md`) | `10-Projects/<slug>/brief.md` | mission brief per initiative |
| Wiki-keeper | `10-Projects/<slug>/TODO-*.md`, `Decision-Log.md` | task cards, status transitions, decisions |
| Coder (`coder-worker.md`) | `20-Learning/<trigger-slug>.md` | instinct note per fix (rules.md §3) |
| Verifier (`subagents/verifier.md`) | task card `Status:` + verifier section | verdicts, blocking findings |
| Web-crawler (`subagents/web-crawler.md`) | `10-Projects/<slug>/research-*.md` | design dossiers |
| Checker (`subagents/checklist-auditor.md`) | `Notes/00-Inbox/` | gap reports to be triaged |
| Coordinator | `Home.md` status table | roll-up in trip reports |

## 5. Optional Machine Mirror

- **mcp-obsidian** (if the harness supports MCP): expose the vault for live search/append by any agent.
- **ECC Memory Vault** (`ecc memory` from `unified-memory`, if installed): mirror `10-Projects/` briefs and `20-Learning` instinct notes into project-scope memories for cross-harness recall. The Obsidian vault stays the human layer; the memory vault is the machine layer. Mirror is **best-effort and optional** — never let it block TDD gates.
