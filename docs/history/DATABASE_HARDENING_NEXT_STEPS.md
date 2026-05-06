# Database Hardening Next Steps

Author: CJ Shane
Status: Historical reference; not the current source of truth.

This document captures the immediate follow-up work after the latest hardening pass.

## 1) Integrate `course_code_aliases` Into Scrapers
- Update `src/scrape_program_requirements.py` and `src/scrape_masters_programs.py` lookup flow:
  - Try direct match in `courses(subject, number)`.
  - If not found, fallback to `course_code_aliases(subject, number)`.
- Keep unresolved codes in `missing_courses_*.csv`.
- Add a report counter: `resolved_via_aliases`.

## 2) Seed Initial Alias Data
- Use existing missing-course CSVs to create an initial alias mapping backlog.
- Add only verified aliases to `course_code_aliases`.
- Re-run requirement insertion after alias seeding to reduce manual gaps.

## 3) Add CI Data Validation
- Wire `scripts/validate_data.py` into CI (or nightly job).
- Start with practical thresholds, then tighten over time:
  - `--max-empty-blocks`
  - `--max-missing-course-refs`
  - `--max-nof-missing-n`
  - `--max-orphans`

## 4) Clean Up Remaining Policy Duplication
- Review `terms` policies and keep one clear admin insert policy.
- Normalize policy naming across tables (`admin_*`, `*_own`, `*_readonly`) for consistency.

## 5) Backfill and Govern `course_code_aliases`
- Add an admin-only workflow/process for alias additions.
- Optionally add columns for provenance:
  - `source` (manual/scrape/review)
  - `approved_by`
  - `approved_at`

## 6) Expand Quality Monitoring
- Query and track `public.data_quality` regularly.
- Add dashboard/report for:
  - programs with highest empty blocks
  - manual-only blocks
  - missing course references

## 7) Decide on Strict Course Number Validation
- Current strict number-format check is intentionally not enforced.
- Decide whether to:
  - normalize legacy course numbers first, then enforce strict check, or
  - keep relaxed format permanently.

## 8) Optional Hardening Enhancements
- Add `NOT NULL` to `staff.auth_user_id` after confirming no operational edge cases.
- Consider replacing duplicated unique indexes (`courses(subject, number)`) if still duplicated.
- Evaluate adding `UNIQUE(student_id, course_id, term_id)` once repeat-course-per-term behavior is finalized.

## 9) Documentation and Runbook
- Keep these files updated after each migration:
  - `DATABASE_HARDENING_IMPLEMENTATION.md`
  - `DATABASE_CHANGES.md`
  - `DATABASE_CHANGES_BY_JIRA.md`
- Add a short runbook for:
  - applying migrations
  - running validation
  - triaging missing courses and manual blocks
