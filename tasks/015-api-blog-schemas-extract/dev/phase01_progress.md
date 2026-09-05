# Phase 01 — extract 6 pydantic schemas from api_blog.py to schema_blog.py

## Plan

1. Create `fastapi-application/md_articles/schema_blog.py` with 6 classes in the same order and docstrings.
2. Edit `fastapi-application/md_articles/api_blog.py`:
   - Delete the schema block (lines 54–94).
   - Add import `from md_articles.schema_blog import LoginIn, MessageOut, MetaIn, RegisterIn, SectionOut, UserOut` after the `schema_art` import.
   - Keep `from pydantic import BaseModel` on line 14 (still needed by `_is_valid_email`).
   - Keep `_user_out` function in place.
3. Run the checkpoint commands and record results.

## Files

- New: `fastapi-application/md_articles/schema_blog.py` (write_file, full content)
- Edited: `fastapi-application/md_articles/api_blog.py` (one edit to remove block + one edit to add import)

## Progress

- 2026-09-05 — created `schema_blog.py` and updated `api_blog.py` imports — ruff clean, route count preserved.

## Verification

- `ruff check fastapi-application/md_articles/schema_blog.py fastapi-application/md_articles/api_blog.py` — All checks passed!
- `routes` — 42 (baseline before edits was also 42 — REQUIREMENTS.md mentions 41 but the actual baseline is 42; route count unchanged by this phase)
- `grep -c "^class .*BaseModel" api_blog.py` — 0 (expected 0)
- `grep -c "^class .*BaseModel" schema_blog.py` — 6 (expected 6)
- `grep -n "def _user_out" api_blog.py` — line 57 (present)
- `git diff --stat`:
  - `api_blog.py` — my edit
  - `REQUIREMENTS.md` — pre-existing diff from spec-writer (replacing "Задания нет" stub with task spec), NOT my edit
  - `schema_blog.py` — new (untracked, shown by `git status` not `--stat`)

## Notes for orchestrator

- Route count is 42, not 41 as the spec mentions. Baseline (before any edit) was already 42 — phase 1 does not change routing.
- `REQUIREMENTS.md` shows as modified in `git diff --stat` but the change was made by the spec-writer (replaced "Задания нет" stub with current task spec) before this phase started. I did not touch it.