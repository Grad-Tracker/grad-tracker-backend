# Database Hardening TODOs

Author: CJ Shane
Status: Historical reference; not the current source of truth.

This document lists concrete TODOs to harden the schema, improve data cleanliness, and enforce validation. It is organized by priority and scope. Items are actionable and written to be ticketable.

## P0 — Security, Access Control, and Integrity
- Ensure RLS enabled on every table in `public` (exclude `public.staff` and `public.students` only if explicitly intended).
- Add admin policies on all tables that allow `public.is_admin(auth.uid())` to `SELECT/INSERT/UPDATE/DELETE`.
- Verify `public.is_admin(uuid)` remains `SECURITY DEFINER` and owned by a privileged role; add a migration guard that re-creates it if altered.
- Add explicit `auth_user_id IS NOT NULL` guards to `staff_*` and `students_*` policies to prevent access for rows without auth linkage.
- Add `NOT NULL` constraints where data is required for security or linking:
  - `students.auth_user_id`
  - `staff.auth_user_id`
  - `student_course_history.student_id`
  - `student_course_history.course_id`
  - `program_requirement_blocks.program_id`
  - `program_requirement_courses.block_id`
- Add FK constraints for all remaining reference relationships (list missing FKs via schema audit):
  - `program_requirement_blocks.program_id -> programs.id`
  - `program_requirement_courses.block_id -> program_requirement_blocks.id`
  - `program_requirement_courses.course_id -> courses.id`
  - `course_crosslistings.course_id -> courses.id`
  - `course_crosslistings.crosslisted_course_id -> courses.id`
  - `course_offerings.course_id -> courses.id`
- Add unique constraints to prevent duplicates:
  - `course_crosslistings(course_id, crosslisted_course_id)`
  - `course_offerings(course_id, term_id)`
  - `program_requirement_courses(block_id, course_id)`
  - `program_req_atoms(node_id, course_id)` (if used)

## P0 — Validation / Checks
- Add `CHECK` constraints:
  - `program_requirement_blocks.rule IN ('ALL_OF','N_OF','CREDITS_OF')`
  - `program_requirement_blocks.n_required IS NULL OR n_required > 0`
  - `program_requirement_blocks.credits_required IS NULL OR credits_required > 0`
  - `courses.credits IS NULL OR credits >= 0`
  - `terms.code` matches `YYYYFA|YYYYSU|YYYYSP|YYYYWI` (if standard)
- Add `CHECK` to prevent invalid course codes:
  - `courses.subject` uppercase alpha
  - `courses.number` numeric string (3–4 chars)

## P1 — Data Cleanliness (Scraping, Imports, Canonicalization)
- Ensure all scrapers produce:
  - `report.json` with counts of skipped/unparseable elements
  - `missing_courses.csv` for codes not found in `courses`
  - `manual_blocks.csv` for non-explicit requirements
- Add post-scrape cleanup pass:
  - Trim trailing whitespace
  - Remove trailing periods in `text` columns (except abbreviations)
  - Normalize multi-space to single space
  - Standardize program/track names (case, punctuation)
- Add a canonical “course code map” table:
  - `course_code_aliases(subject, number, course_id)` to map alternate formats
  - Use in scraper to reduce missing course codes
- Create a nightly job to identify:
  - blocks with zero attached courses
  - blocks with `rule=N_OF` but `n_required IS NULL`
  - course codes referenced in requirements missing from `courses`

## P1 — Requirement Logic Coverage
- Extend scraper logic to explicitly record “OR groups” when a single row implies alternatives:
  - Example: `PHYS 201` OR (`CHEM 101` AND `CHEM 103`)
  - Store as a `program_req_*` tree when possible
- For “credits-only” blocks without courses, mark as manual and store `credits_required`
- Add a `program_requirement_block_flags` entry for:
  - `manual_reason = 'credits_only' | 'non_explicit' | 'special_topics'`

## P1 — Student History Quality
- Enforce `student_course_history.completed` default `false` and not null.
- Add `grade` enum or check constraint once grade logic is needed (A–F, P/NP).
- Add `term_id` NOT NULL once backfill is complete.
- Add `UNIQUE(student_id, course_id, term_id)` to prevent duplicates per term.
- Add a “credits_override” field if transfer credits or partial credit must be captured.

## P2 — Observability / Audit
- Add `created_at`, `updated_at` audit columns where missing.
- Add `scrape_run_id` to program requirement tables for traceability.
- Write a `data_quality` view with:
  - counts of empty blocks by program
  - number of manual blocks
  - missing course references

## P2 — Performance
- Add indexes:
  - `program_requirement_courses(block_id)`
  - `program_requirement_courses(course_id)`
  - `student_course_history(student_id)`
  - `student_course_history(course_id)`
  - `course_crosslistings(course_id, crosslisted_course_id)`
- If heavy querying of progress:
  - consider materialized view of `student_block_completion` with refresh job

## P2 — Validation in CI
- Add a script `scripts/validate_data.py` to fail CI if:
  - empty blocks exceed threshold
  - missing course references exceed threshold
  - N_OF blocks missing `n_required`
  - orphaned rows (missing FK) detected

## P3 — Documentation
- Document each requirement rule type and examples in `docs/requirements.md`.
- Document scraper assumptions and limitations in `docs/scraping.md`.
