# Database Hardening Implementation

Author: CJ Shane
Status: Historical reference; not the current source of truth.

This document records the hardening work implemented from `DATABASE_HARDENING_TODOS.md`, with a short explanation for each change.

## Applied Database Changes

### 1) Recreated `public.is_admin(uuid)` as safe `SECURITY DEFINER`
- Change:
  - Replaced function definition with `SECURITY DEFINER` + `search_path = public`.
  - Granted execute to `authenticated`.
- Why:
  - Prevents recursive RLS failures when policies call `is_admin()`.
  - Keeps admin checks centralized and consistent.

### 2) Hardened own-row RLS policies on `staff` and `students`
- Change:
  - Recreated `staff_*_own` and `students_*_own` policies.
  - Added explicit guards:
    - `auth.uid() is not null`
    - `auth_user_id is not null`
    - `(auth.uid() = auth_user_id OR public.is_admin(auth.uid()))`
- Why:
  - Enforces the rule that rows without `auth_user_id` are inaccessible.
  - Preserves admin override while keeping self-access strict.

### 3) Removed permissive `terms` insert policy
- Change:
  - Dropped `Authenticated users can insert terms` policy.
- Why:
  - Prevents non-admin term creation.
  - Aligns `terms` writes with admin-only control.

### 4) Added admin full-write policy to `program_requirement_block_flags`
- Change:
  - Added `program_requirement_block_flags_admin_all` for authenticated admins.
- Why:
  - Ensures admins can manage manual/non-explicit requirement flags.

### 5) Enforced view security model for progress views
- Change:
  - Set `security_invoker = true` and `security_barrier = true` on:
    - `student_block_completion`
    - `student_program_summary`
- Why:
  - Ensures underlying table RLS is applied for callers.

### 6) Added validation constraints
- Change:
  - Added checks:
    - `program_requirement_blocks.n_required > 0` (when not null)
    - `program_requirement_blocks.credits_required >= 0` (when not null)
    - `courses.credits >= 0`
    - `courses.subject` uppercase alpha pattern
- Why:
  - Prevents invalid requirement/cardinality and malformed course metadata.
  - Note: `credits_required` was set to non-negative (not strictly positive) due existing zero-credit rows.

### 7) Strengthened student history defaults
- Change:
  - Set `student_course_history.completed` default to `false`.
  - Updated null `completed` values to `false`.
- Why:
  - Ensures consistent completion semantics and avoids null-state ambiguity.

### 8) Added performance indexes
- Change:
  - Added indexes:
    - `program_requirement_courses(course_id)`
    - `student_course_history(student_id)`
    - `student_course_history(course_id)`
    - `course_crosslistings(course_id)`
- Why:
  - Improves joins for progress and course-equivalence queries.

### 9) Added canonical alias table for course codes
- Change:
  - Created `course_code_aliases`:
    - `subject`, `number`, `course_id`, `created_at`
    - unique `(subject, number)`
  - Enabled RLS + policies:
    - authenticated read
    - admin full write
- Why:
  - Supports normalized handling of alternate course code formats during scrape/import.

### 10) Added observability view: `public.data_quality`
- Change:
  - Created view with per-program rollups:
    - `empty_blocks`
    - `non_empty_blocks`
    - `manual_empty_blocks`
    - `missing_course_refs`
  - Granted `SELECT` to authenticated users.
- Why:
  - Gives a single quality dashboard for monitoring scrape completeness and requirement integrity.

## Applied Codebase Changes

### 11) Added migration artifact file
- Change:
  - Added SQL file: `sql/database_hardening_todos_phase1d.sql`.
- Why:
  - Keeps applied DB hardening migration reproducible in repo.

### 12) Added scraper output for manual blocks CSV
- Change:
  - `src/scrape_program_requirements.py`:
    - Added `--out-manual-blocks` (default `manual_blocks_undergrad.csv`)
    - Writes CSV from `manual_requirements` report section.
  - `src/scrape_masters_programs.py`:
    - Added `--out-manual-blocks` (default `manual_blocks_graduate.csv`)
    - Writes CSV from `manual_requirements` report section.
- Why:
  - Satisfies TODO requirement for a discrete manual/non-explicit requirements artifact.

### 13) Added CI validation script
- Change:
  - Added `scripts/validate_data.py` with threshold checks for:
    - empty requirement blocks
    - missing course references
    - `N_OF` blocks missing `n_required`
    - orphaned rows in requirement tree/link tables
- Why:
  - Enables automated quality gate in CI and scheduled checks.

### 14) Added documentation pages
- Change:
  - Added `docs/requirements.md`
  - Added `docs/scraping.md`
- Why:
  - Documents rule semantics, tree representation, scraper outputs, and known limitations.

### 15) Completed P2 observability/audit traceability
- Change:
  - Added table `public.scrape_runs` with RLS:
    - authenticated read
    - admin full write
  - Added `created_at`, `updated_at`, and `scrape_run_id` to:
    - `program_requirement_blocks`
    - `program_requirement_courses`
    - `program_requirement_block_flags`
    - `program_req_sets`
    - `program_req_nodes`
    - `program_req_atoms`
  - Added `set_updated_at()` trigger function and per-table update triggers.
- Why:
  - Provides row-level audit timestamps and per-run lineage for scraped requirement data.

### 16) Expanded `data_quality` observability view
- Change:
  - Updated `public.data_quality` to include `manual_blocks` total count while preserving prior columns.
- Why:
  - Fully covers requested quality metrics:
    - empty blocks by program
    - manual block counts
    - missing course references

### 17) Added heavy-query support for progress
- Change:
  - Added materialized view `public.student_block_completion_mv`.
  - Added index `idx_student_block_completion_mv_student_program` on `(student_id, program_id, block_id)`.
  - Added admin-gated refresh function:
    - `public.refresh_student_block_completion_mv()`
- Why:
  - Supports faster reads for high-volume progress queries with explicit refresh control.

### 18) Added crosslisting ID-based performance path
- Change:
  - Added nullable `course_crosslistings.crosslisted_course_id` FK to `courses(id)`.
  - Backfilled by matching `(cross_subject, cross_number)` to `courses(subject, number)`.
  - Added index `idx_course_crosslistings_course_id_crosslisted_course_id`.
- Why:
  - Satisfies the requested index shape for faster equivalency joins.
  - Keeps compatibility with existing `cross_subject/cross_number` columns.
- Note:
  - A small set of rows remains unresolved where crosslisted course code did not match a `courses` row; those keep `crosslisted_course_id = NULL`.

### 19) Scraper output and cleanup hardening
- Change:
  - Both scrapers now emit:
    - report JSON with `skipped_count`, `skipped_programs`, and `unparseable_elements_count`
    - missing courses CSV
    - manual blocks CSV
  - Added post-scrape normalization in both scrapers:
    - trim trailing whitespace
    - collapse multi-space
    - remove trailing periods conservatively (abbreviations preserved)
    - normalize punctuation spacing
    - standardize program/block/manual-note text before DB insert
- Why:
  - Makes scraped requirement text cleaner and more consistent without relying on later DB cleanup.

### 20) Added alias-map lookup in scrapers
- Change:
  - Updated course resolution flow in both scrapers:
    1. lookup in `courses(subject, number)`
    2. fallback to `course_code_aliases(subject, number)` and use mapped `course_id`
- Why:
  - Reduces false missing-course reports and supports alternate course code formats.

### 21) Manual requirement reason classification
- Change:
  - Added `manual_reason` column to `program_requirement_block_flags`.
  - Added allowed values check:
    - `credits_only`
    - `non_explicit`
    - `special_topics`
  - Scrapers now write `manual_reason` and explicitly flag credits-only blocks.
- Why:
  - Improves downstream reporting and manual triage quality.

### 22) Student history quality updates completed
- Change:
  - Added `student_course_history.credits_override numeric(6,2)`.
  - Backfilled null `term_id` rows to Spring/Fall 2026 and set `term_id` to `NOT NULL`.
  - Added grade validation check constraint for letter and pass/fail style values.
  - Replaced uniqueness model:
    - dropped strict `(student_id, course_id)` uniqueness
    - set PK to `(student_id, course_id, term_id)`
- Why:
  - Supports retakes across terms while still preventing duplicates per term.
  - Enables optional transfer/partial-credit modeling.

### 23) Nightly quality job scaffold
- Change:
  - Added `nightly_data_quality_runs` table.
  - Added `run_nightly_data_quality_job()` function that records:
    - empty blocks
    - `N_OF` blocks missing `n_required`
    - missing course references
  - Added RLS policies (authenticated read, admin write).
- Why:
  - Provides a repeatable nightly-quality checkpoint for operational monitoring.
- Note:
  - `pg_cron` is not enabled in this project, so scheduling must be done by external runner (e.g., GitHub Actions, server cron, or Supabase scheduled function) calling `select public.run_nightly_data_quality_job();`.

### 24) Completed remaining P0 policy and nullability enforcement
- Change:
  - Set `staff.auth_user_id` to `NOT NULL`.
  - Added missing admin policy coverage:
    - `plan_programs` now has admin `UPDATE`.
    - `program_req_sets`, `program_req_nodes`, `program_req_atoms` now have admin `SELECT`.
- Why:
  - Ensures full admin CRUD policy availability on all public tables.
  - Aligns staff auth linkage with schema-level integrity, not just policy behavior.

### 25) Strengthened P0 integrity checks
- Change:
  - Added `program_requirement_blocks_rule_chk`:
    - `rule IN ('ALL_OF','N_OF','CREDITS_OF')`
  - Normalized invalid `credits_required <= 0` values to `NULL`.
  - Added `program_requirement_blocks_credits_positive_chk`:
    - `credits_required IS NULL OR credits_required > 0`
  - Added `terms.code` generated column and format check:
    - `YYYYSP|YYYYSU|YYYYFA|YYYYWI`
- Why:
  - Hardens requirement-rule integrity and term-code consistency at schema level.

### 26) Added remaining duplicate-prevention constraints/indexes
- Change:
  - Added unique index:
    - `uq_course_crosslistings_course_crosslisted` on `(course_id, crosslisted_course_id)` where non-null.
  - Added unique index:
    - `uq_program_req_atoms_node_course` on `(node_id, required_course_id)`.
  - Added `course_offerings.term_id` FK compatibility path + unique index:
    - `uq_course_offerings_course_term_id` on `(course_id, term_id)` where non-null.
- Why:
  - Meets requested duplicate guards while preserving existing `term_code`-based offering model.

### 27) Backward-compatible strict course-number validation
- Change:
  - Added `courses_number_numeric_3_4_chk` as `NOT VALID`:
    - `number ~ '^[0-9]{3,4}$'`
- Why:
  - Enforces strict numeric format for new/updated compliant data.
  - Avoids immediate breakage from legacy rows that use non-numeric formats.
- Note:
  - Existing legacy rows are intentionally not auto-rewritten in this migration.

### 28) Completed remaining enforceable P0 checklist items
- Change:
  - Added missing admin policy coverage to guarantee admin CRUD on all public tables:
    - `plan_programs` admin `UPDATE`
    - `program_req_sets` admin `SELECT`
    - `program_req_nodes` admin `SELECT`
    - `program_req_atoms` admin `SELECT`
  - Set `staff.auth_user_id` to `NOT NULL`.
  - Added strict requirement checks:
    - `program_requirement_blocks.rule IN ('ALL_OF','N_OF','CREDITS_OF')`
    - `program_requirement_blocks.credits_required > 0` (nullable)
  - Added `terms.code` generated column (`YYYYSP/SU/FA/WI`) and format check.
  - Added unique guards:
    - `course_crosslistings(course_id, crosslisted_course_id)` (filtered non-null)
    - `course_offerings(course_id, term_id)` (filtered non-null)
    - `program_req_atoms(node_id, required_course_id)`
- Why:
  - Closes the remaining P0 security/integrity gaps while preserving compatibility with existing data shapes.

### 29) P0 audit artifact added
- Change:
  - Added reproducible audit report:
    - `docs/audits/P0_AUDIT_2026-03-11.md`
  - Includes:
    - pass/fail table for each P0 requirement
    - exact SQL used to run the audit
    - observability/testing verification SQL
- Why:
  - Makes validation repeatable and transparent for future schema changes.

## Additional Migration Artifacts Added
- `sql/p0_remaining_security_and_checks_cleanup.sql`
- `sql/p0_backcompat_constraints_course_number_and_course_offerings_term_id.sql`
- `sql/p1_followups_alias_manual_reason_nightly_and_student_history_v2.sql`
- `sql/p2_observability_scrape_run_and_materialized_progress_v2.sql`

## Additional Follow-up Applied

### A) Enforced `students.auth_user_id` as `NOT NULL`
- Change:
  - Deleted dependent `student_course_history` rows for any student rows with `auth_user_id IS NULL`.
  - Deleted the `students` rows with `auth_user_id IS NULL`.
  - Applied `ALTER TABLE public.students ALTER COLUMN auth_user_id SET NOT NULL`.
- Why:
  - Moves enforcement from policy-only to schema-level integrity.
  - Guarantees every student row is linked to an auth user.
- Verification:
  - `SELECT count(*) FROM public.students WHERE auth_user_id IS NULL` returns `0`.
  - `information_schema.columns.is_nullable` for `students.auth_user_id` is `NO`.

## Items Not Enforced Yet (Intentional)

### A) Strict course number format check
- Status:
  - Not applied.
- Reason:
  - Existing data contains non-standard course number formats.
  - Enforcing strict numeric pattern immediately would reject valid legacy rows.

## Verification Notes
- Supabase migration applied successfully under:
  - `database_hardening_todos_phase1d`
- RLS remained enabled on all existing public base tables.
- Existing admin recursion fix behavior was preserved (`is_admin` stays `SECURITY DEFINER`).
