# Database Changes by Jira Ticket

Author: CJ Shane
Status: Historical reference; not the current source of truth.

This document groups the database changes from this session by Jira task. It references the technical changes described in `DATABASE_CHANGES.md`.

---

## GT-93 — Normalize `courses.offered_terms` into `course_offerings`

**Schema/Data**
- Backfilled `public.course_offerings` from `public.courses.offered_terms` into normalized term codes:
  - `FALL`, `SPRING`, `SUMMER`, `WINTERIM`
  - `FALL_ODD`, `FALL_EVEN`, `SPRING_ODD`, `SPRING_EVEN`
  - `YEARLY`, `OCCASIONALLY`
- Dropped `public.courses.offered_terms`

**Notes**
- `course_offerings` now holds normalized term codes; any UI must use it instead of `offered_terms`.

---

## GT-94 — Parse remaining `prereq_text` into structured prerequisite tables

**Schema/Data**
- Parsed `courses.prereq_text` into:
  - `course_req_sets`
  - `course_req_nodes`
  - `course_req_atoms`
- Logged unparseable entries in `prereq_parse_log`
- Dropped `courses.prereq_text`

**Parser coverage**
- Course lists, consent, program admission, standing, minimum GPA, minimum credits, minimum grade.
- Unparseable requirements logged for manual review.

---

## GT-95 — Convert `programs.program_type` to enum

**Schema**
- Created `program_type_enum` and migrated `programs.program_type` from `text` to enum.
- Added enum value `GRADUATE` later for graduate programs.

---

## Name Split — Students `name` → `first_name` / `last_name`

**Schema/Data**
- Added `students.first_name` and `students.last_name` (NOT NULL).
- Migrated from `students.name` (split on first space).
- Dropped `students.name`.

**Side effect**
- Updated `handle_new_user()` to insert into `students.first_name`/`students.last_name`.

---

## Drop Dead Tables — Course requirement legacy tables

**Schema**
- Dropped:
  - `course_requirement_groups`
  - `course_requirement_items`

---

## Add `term_id` + FK for `student_course_history`

**Schema/Data**
- Added `student_course_history.term_id` FK → `terms.id`.
- Added FK `student_id → students.id`.
- Inserted missing term rows for `Spring 2026`, `Fall 2026`.
- Backfilled `term_id` randomly to Spring/Fall 2026 (per request).

---

## RLS — Course Tables + Terms Policy

**Schema/Policies**
- Enabled RLS and read-only `SELECT` on:
  - `course_req_nodes`, `course_req_sets`, `course_req_atoms`
  - `course_offerings`, `course_crosslistings`
- `terms` INSERT policy restricted to admins only.

---

## Program Requirements Scraping + Completion

**Schema**
- Added:
  - `program_requirement_block_flags`
  - `program_req_sets`
  - `program_req_nodes`
  - `program_req_atoms`

**Views**
- `course_equivalents` — crosslist-aware course equivalence
- `student_block_completion` — per-student per-block status (tree-aware)
- `student_program_summary` — percent complete per program

**RLS**
- Enabled RLS on `program_req_sets`, `program_req_nodes`, `program_req_atoms`
  - Read-only for authenticated
  - Admin full write via `public.is_admin(auth.uid())`
- `program_requirement_block_flags` read-only SELECT for authenticated

**Data**
- Scraped undergraduate and graduate program requirements.
- Populated:
  - `programs`, `program_requirement_blocks`, `program_requirement_courses`
  - `program_requirement_block_flags`
  - `program_req_*` trees for nested OR/AND options

---

## Admin RLS Recursion Fix

**Schema/Policies**
- Recreated `public.is_admin(uuid)` as `SECURITY DEFINER`
- Rewrote `staff_*_own` and `students_*_own` policies to call `public.is_admin(auth.uid())`

---

## Miscellaneous Data Cleanup

**Data**
- Trailing whitespace and trailing period cleanup for all `text` columns in `public` except `staff` and `students`.
- Optional logging via `trailing_cleanup_log`.
