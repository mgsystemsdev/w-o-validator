# WORKFLOW.md — wo_standalone
# Instruction file for all AI tools
# Read this file before starting any work
# Applies to: Claude, Cursor, Copilot, Codex, Windsurf, and any AI working in this project

---

## What This File Is

This is the operating procedure for this project.
Every AI tool working here follows this workflow.
It exists so that switching between Claude, Cursor, Copilot, or any other tool feels like
the same system is running.

---

## Session Start — Every Tool, Every Time

Before doing anything:
1. Read `~/.claude/memory/user.md`
2. Read `~/.claude/memory/preferences.md`
3. Read `~/.claude/memory/decisions.md`
4. Read this project's `CLAUDE.md`
5. Read `AGENTS.md`
6. Confirm what the current task is
7. Do not start work until steps 1–6 complete

---

## How to Work in This Project

**PLAN BEFORE YOU BUILD**
- State what you are about to do
- Break it into steps
- Get confirmation before executing

**ONE THING AT A TIME**
- Complete one task fully before starting the next
- Do not scope creep mid-task
- If you discover something new — log it, finish current task first

**DECISIONS GET LOGGED**
Any architectural decision made during work must be appended to:
`~/.claude/memory/decisions.md`

Format: date, decision, reasoning, expected outcome, 30-day review date

**BEFORE SHIPPING ANYTHING**
Run this mental checklist:
- [ ] Does this match the original request?
- [ ] Are there hardcoded secrets?
- [ ] Is input validated?
- [ ] Are auth checks present?
- [ ] Does this contradict any past decision?
- [ ] Would a senior engineer approve this?

If any box is unchecked — fix before shipping.

---

## Run Commands

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Test Commands

No automated tests defined. Manual QA only.

## Deploy Commands

Streamlit Community Cloud — set main file to `wo_standalone/app.py`.
On IPv4-only networks, use Supabase pooler URI (port 6543).

## Database Migrations

Migrations are applied **manually** — never run automatically.
Apply in order via Supabase SQL Editor:
```
db/migrations/001_schema.sql
db/migrations/002_unit_movings.sql
db/migrations/003_unit_occupancy_global.sql
db/migrations/004_users.sql
```
Migration runner at startup is **read-only** (verifies tables exist, does not apply changes).

---

## Tool-Specific Notes

**CLAUDE CODE**
- Skills available: /research /review /swarm /create /debug /plan
- Hooks active: lint-on-save, pre-commit, init-project-files
- Memory loads automatically via hook

**CURSOR**
- Read `.cursor/rules/` — memory.mdc loads `~/.claude/memory/`
- Follow AGENTS.md for agent simulation

**COPILOT**
- Read `CLAUDE.md` and this file before suggesting
- Follow the rules in `AGENTS.md`
- When in doubt: suggest, don't auto-apply

**CODEX**
- Read all memory files before executing
- Follow AGENTS.md agent simulation rules
- Log decisions after execution

**WINDSURF**
- Read `CLAUDE.md` and memory files at session start
- Follow workflow steps above
- Apply `preferences.md` coding standards

---

## When Something Goes Wrong

1. Stop — do not continue building on a mistake
2. Read `decisions.md` — did this contradict a past decision?
3. Log what went wrong to `~/.claude/gotchas.md`
4. Fix the root cause — not just the symptom
5. Continue
