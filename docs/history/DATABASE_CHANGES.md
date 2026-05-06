# Database Changes (Technical Detail)

Author: CJ Shane
Status: Historical reference; not the current source of truth.

This document records schema, data, and policy changes applied during this session. It is organized by area and includes technical details suitable for audit or migration replay.

---

## 1) Schema Additions

### 1.1 `program_requirement_block_flags`
Purpose: capture manual/non-explicit requirement notes per block.

Columns:
- `id bigserial` PK
- `block_id bigint` FK → `program_requirement_blocks.id` (ON DELETE CASCADE)
- `flag_type text` (e.g., `MANUAL_REQUIREMENT`)
- `note text`
- `created_at timestamptz` default `now()`

Constraint:
- `unique (block_id, flag_type, note)`

### 1.2 Program requirement tree tables
Purpose: represent nested AND/OR requirement groups (e.g., “PHYS 201 OR (CHEM 101 + CHEM 103)”).

`program_req_sets`
- `id bigserial` PK
- `block_id bigint` FK → `program_requirement_blocks.id` (ON DELETE CASCADE), UNIQUE
- `use_count boolean` default `false` (if true, use count-based logic; if false, use tree logic)

`program_req_nodes`
- `id bigserial` PK
- `req_set_id bigint` FK → `program_req_sets.id` (ON DELETE CASCADE)
- `node_type req_node_type` (`AND`, `OR`, `ATOM`)
- `parent_id bigint` FK → `program_req_nodes.id`
- `sort_order int` default `0`

`program_req_atoms`
- `node_id bigint` PK, FK → `program_req_nodes.id` (ON DELETE CASCADE)
- `atom_type req_atom_type` (currently `COURSE`)
- `required_course_id bigint` FK → `courses.id`

### 1.3 `prereq_parse_log`
Purpose: log unparseable prerequisite text during `courses.prereq_text` normalization.

Columns:
- `id bigserial` PK
- `course_id bigint` FK → `courses.id` (ON DELETE CASCADE)
- `prereq_text text`
- `reason text` (`unparseable`, `missing_course`)
- `logged_at timestamptz` default `now()`

### 1.4 `trailing_cleanup_log`
Purpose: optional audit log for trailing punctuation/whitespace cleanup.

Columns:
- `id bigserial` PK
- `run_at timestamptz` default `now()`
- `table_schema text`, `table_name text`, `column_name text`
- `rows_affected bigint`

---

## 2) Schema Changes / Table Modifications

### 2.1 `programs.program_type` enum
- Converted `programs.program_type` from `text` to `program_type_enum`.
- Added enum value `GRADUATE`.

### 2.2 `students` name split
- Added `first_name text NOT NULL`
- Added `last_name text NOT NULL`
- Dropped `name`

### 2.3 `student_course_history`
- Added `term_id bigint` FK → `terms.id`
- Added FK `student_id → students.id`

### 2.4 `courses`
- Dropped `offered_terms`
- Dropped `prereq_text`

### 2.5 Dropped legacy tables
- `course_requirement_groups`
- `course_requirement_items`

---

## 3) Data Migrations / Backfills

### 3.1 Normalize `courses.offered_terms` → `course_offerings`
- Parsed free-text terms into normalized codes and inserted into `course_offerings`:
  - `FALL`, `SPRING`, `SUMMER`, `WINTERIM`
  - `FALL_ODD`, `FALL_EVEN`, `SPRING_ODD`, `SPRING_EVEN`
  - `YEARLY`, `OCCASIONALLY`
- Dropped `courses.offered_terms` afterward.

### 3.2 Normalize `courses.prereq_text` → prerequisite trees
- Parsed common patterns into:
  - `course_req_sets`
  - `course_req_nodes`
  - `course_req_atoms`
- Unparseable entries logged to `prereq_parse_log`.
- Dropped `courses.prereq_text` afterward.

### 3.3 `student_course_history.term_id` backfill
- Inserted term rows if missing:
  - `Spring 2026`, `Fall 2026`
- Backfilled `term_id` randomly to either Spring/Fall 2026 (per request).

### 3.4 Program requirements scraping
- Re-scraped undergraduate and graduate program requirements.
- Populated:
  - `programs`
  - `program_requirement_blocks`
  - `program_requirement_courses`
  - `program_requirement_block_flags`
- Added tree entries for nested OR/AND blocks into:
  - `program_req_sets`
  - `program_req_nodes`
  - `program_req_atoms`

### 3.5 Trailing punctuation cleanup (public schema)
- For all `text` columns in `public` except `staff` and `students`:
  - Trimmed trailing whitespace
  - Removed trailing period (`.`) if present
- Optional log via `trailing_cleanup_log`.

---

## 4) Views Added / Updated

### 4.1 `course_equivalents`
- Provides crosslist-aware equivalence mapping (course ↔ cross-listed course).
- Supports completion checks using either the listed course or its cross-list.

### 4.2 `student_block_completion`
- Returns per-student, per-block completion status:
  - `COMPLETE`, `INCOMPLETE`, `MANUAL`
- Uses:
  - Crosslisted equivalence (`course_equivalents`)
  - Requirement trees (`program_req_*`) for nested OR/AND options
  - Count-based logic for `N_OF` when `use_count=true`
- Manual blocks are determined by either:
  - No courses in block, or
  - `program_requirement_block_flags.flag_type = 'MANUAL_REQUIREMENT'`

### 4.3 `student_program_summary`
- Aggregates block completion per program:
  - `blocks_complete`, `blocks_incomplete`, `blocks_manual`
  - `percent_complete` (manual blocks excluded)

---

## 5) RLS / Policies

### 5.1 Course tables
- RLS enabled + read-only SELECT for `authenticated`:
  - `course_req_nodes`, `course_req_sets`, `course_req_atoms`
  - `course_offerings`, `course_crosslistings`

### 5.2 Program requirement flags
- RLS enabled + read-only SELECT for `authenticated`:
  - `program_requirement_block_flags`

### 5.3 Program requirement trees
- RLS enabled on:
  - `program_req_sets`, `program_req_nodes`, `program_req_atoms`
- Policies:
  - `authenticated` read-only SELECT
  - Admin full write (INSERT/UPDATE/DELETE) using `public.is_admin(auth.uid())`

### 5.4 Admin recursion fix
- Recreated `public.is_admin(uuid)` as **SECURITY DEFINER** to avoid recursive RLS on `staff`.
- Rewrote `staff_*_own` and `students_*_own` policies to use `public.is_admin(auth.uid())` instead of subqueries on `staff`.

---

## 6) Script Changes (DB-impacting behavior)

### 6.1 `src/scrape_program_requirements.py`
- Adds manual requirement detection and writes `program_requirement_block_flags`.
- Extracts table section headers into distinct blocks.
- Adds option-group detection for “Select 1 of the following” blocks.
- Inserts requirement trees into `program_req_*`.
- Uses bulk upserts and retry logic for network stability.

### 6.2 `src/scrape_masters_programs.py`
- Same features as undergrad script.
- Default program type set to `GRADUATE`.
- Supports `--reset-graduate` to remove existing graduate programs before insert.

---

## 7) Known Data Limitations (Post-change)

### 7.1 Missing course references during scrape
- Some scraped course codes are not present in `courses`.
- These are skipped during block-course insertion and should be reviewed separately.

### 7.2 Manual/Unknown requirements
- Textual requirements (e.g., “Varies by topic,” “300-level courses,” “placement”) are flagged and excluded from completion percentage.

---

## 8) Artifacts Generated
- `program_requirements_report.json`
- `masters_program_requirements_report.json`
- `masters_programs_skipped.txt`

---

If you want this document broken down per Jira ticket or migration file names, say the word.

## 9) Advisor Role / Program-Scoped RLS Update (2026-03-16)

### 9.1 Migration applied
- Applied migration: `add_advisor_role_policies_using_existing_staff_and_program_advisors`.
- This update was adapted to the existing schema (no new `advisors` table created).

### 9.2 Schema alignment used
- Reused existing `public.program_advisors` table.
- Confirmed `public.programs.id` is `bigint`, so advisor-program function uses `bigint`.
- Existing `program_advisors` data was preserved.

### 9.3 RLS/function changes
- Enabled RLS on `public.program_advisors`.
- Created/updated helper functions as `SECURITY DEFINER`:
  - `public.is_advisor()`
  - `public.is_advisor_for_program(p_program_id bigint)`
- Added advisor-scoped `SELECT` policy on `public.program_advisors`:
  - Advisors can read their own assignments.
  - Admins can also read via `public.is_admin(auth.uid())`.

### 9.4 Advisor-scoped write policies added
- `public.programs`
  - `programs_update_assigned_advisor`
  - `programs_delete_assigned_advisor`
- `public.program_requirement_blocks`
  - `req_blocks_insert_assigned_advisor`
  - `req_blocks_update_assigned_advisor`
  - `req_blocks_delete_assigned_advisor`
- `public.program_requirement_courses`
  - `req_courses_insert_assigned_advisor`
  - `req_courses_update_assigned_advisor`
  - `req_courses_delete_assigned_advisor`
- `public.gen_ed_buckets`
  - `gen_ed_buckets_insert_advisor`
  - `gen_ed_buckets_update_advisor`
  - `gen_ed_buckets_delete_advisor`
- `public.gen_ed_bucket_courses`
  - `gen_ed_bucket_courses_insert_advisor`
  - `gen_ed_bucket_courses_update_advisor`
  - `gen_ed_bucket_courses_delete_advisor`

### 9.5 Security cleanup
- Dropped permissive policy from `public.courses`:
  - `allow_authenticated_insert_courses`
- Result: authenticated users no longer have open insert access to courses.

### 9.6 Verification summary
- `public.program_advisors` now has RLS enabled.
- `public.is_advisor` and `public.is_advisor_for_program(bigint)` exist and are `SECURITY DEFINER`.
- Advisor policies listed above are present.

## 10) Advisor Course Catalog Support (2026-03-16)

### 10.1 Courses schema updates
- Added `public.courses.prereq_text` (`text`, nullable) for advisor-entered prerequisite text in admin course workflows.
- Added `public.courses.is_active` (`boolean NOT NULL DEFAULT true`) to support course deactivation without hard delete.

### 10.2 Advisor role check update
- Replaced `public.is_advisor()` logic to allow advisor access when the authenticated staff user:
  - has `staff.role = 'advisor'` (case-insensitive), OR
  - has at least one assignment in `public.program_advisors`.
- Function remains `SECURITY DEFINER`.

### 10.3 Courses RLS policies for advisors
- Added advisor-capable policies on `public.courses`:
  - `courses_select_advisor`
  - `courses_insert_advisor`
  - `courses_update_advisor`
  - `courses_delete_advisor`
- Each policy allows access for `authenticated` users where:
  - `public.is_advisor()` OR `public.is_admin(auth.uid())`.

### 10.4 Existing validation support relevant to this story
- `courses.subject` and `courses.number` are required and constrained.
- `courses.title` and `courses.credits` are required.
- `(subject, number)` uniqueness already enforced by unique constraints.

### 10.5 Note on credits validation
- Current DB check enforces non-negative credits (`credits >= 0`), not strictly positive.
- Existing catalog contains non-positive values, so strict `> 0` should be enforced in UI/service layer first, then migrated at DB level after data cleanup.

## 11) Planner Breadth Package Persistence (2026-03-16)

### 11.1 Students schema change
- Added `students.breadth_package_id` (`text`, nullable).
- Added constraint `chk_students_breadth_package_id` restricting values to:
  - `math`, `math-physics`, `chemistry`, `project-mgmt`,
  - `business`, `economics`, `geography`, `criminal-justice`, `art-design`
  - or `NULL`.

### 11.2 RLS compatibility
- No RLS policy changes were required.
- Existing `students_select_own` and `students_update_own` policies already allow authenticated users to read/update their own row, including the new column.

### 11.3 Repo artifact
- Added SQL file: `sql/persist_student_breadth_package_id.sql`.
- Added frontend integration guide: `docs/planner_breadth_package_frontend_patch.md`.
