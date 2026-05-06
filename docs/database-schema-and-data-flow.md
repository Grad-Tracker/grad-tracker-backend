# Database Schema And Data Flow

Author: CJ Shane

Last rescanned: 2026-05-06

This document describes the current Supabase `public` schema, where the database data comes from, and where that data lands.

## Rescan Method

- Used Supabase MCP schema inspection for current public tables, columns, primary keys, foreign keys, enums, and RLS status.
- Used direct SQL `count(*)` checks through Supabase MCP for exact row counts across public tables, views, and the materialized view.
- Confirmed local script paths from the repo after moving legacy scripts under `src/legacy/`.
- `sql/schema.sql` is not generated in this environment because direct Postgres URLs and local PostgreSQL CLI tools are not currently available here. Generate it with `scripts/export_live_schema.ps1` when `SOURCE_DATABASE_URL` and `pg_dump` are available.

## Current Inventory

The live database currently exposes 53 public definitions: base tables, views, and one materialized view.

| Definition | Rows | Type | Role |
| --- | ---: | --- | --- |
| `ai_conversations` | 30 | table | AI chat conversation headers |
| `ai_messages` | 198 | table | AI chat messages |
| `course_code_aliases` | 0 | table | Alternate or historical course codes |
| `course_crosslistings` | 149 | table | Course cross-listing links |
| `course_equivalents` | 2,442 | view | Derived course equivalency pairs |
| `course_offerings` | 3,113 | table | Course offering seasons/terms |
| `course_req_atoms` | 3,503 | table | Course prerequisite leaf atoms |
| `course_req_nodes` | 4,694 | table | Course prerequisite logic nodes |
| `course_req_sets` | 1,737 | table | Course prerequisite rule roots |
| `courses` | 2,298 | table | Canonical course catalog |
| `data_quality` | 159 | view | Program-level quality metrics |
| `gen_ed_bucket_courses` | 185 | table | Course-to-gen-ed bucket links |
| `gen_ed_buckets` | 3 | table | General education buckets |
| `major_certificate_mappings` | 0 | table | Major/certificate mapping table |
| `nightly_data_quality_runs` | 0 | table | Nightly quality job snapshots |
| `notification_preferences` | 0 | table | Student notification settings |
| `plan_programs` | 46 | table | Programs attached to plans |
| `plans` | 38 | table | Student plan headers |
| `program_advisors` | 5 | table | Program-to-staff advisor assignments |
| `program_req_atoms` | 3,721 | table | Program requirement tree leaf atoms |
| `program_req_nodes` | 4,646 | table | Program requirement tree logic nodes |
| `program_req_sets` | 834 | table | Program requirement tree roots |
| `program_requirement_block_flags` | 603 | table | Manual/special requirement flags |
| `program_requirement_blocks` | 834 | table | Program requirement sections |
| `program_requirement_courses` | 3,870 | table | Flat block-to-course requirements |
| `programs` | 159 | table | Majors, minors, certificates, graduate programs |
| `scrape_runs` | 0 | table | Scraper run tracking |
| `staff` | 5 | table | Staff/advisor/admin profiles |
| `student_activity_log` | 147 | table | Student activity feed |
| `student_block_completion` | 14,178 | view | Requirement block completion calculation |
| `student_block_completion_mv` | 5,004 | materialized view | Completion snapshot |
| `student_course_history` | 155 | table | Completed or attempted student courses |
| `student_planned_courses` | 431 | table | Planned future courses |
| `student_program_summary` | 2,703 | view | Student/program progress summary |
| `student_programs` | 29 | table | Student declared programs |
| `student_term_plan` | 104 | table | Plan terms per student |
| `students` | 34 | table | Student profiles |
| `terms` | 14 | table | Academic terms |
| `v_course_catalog` | 2,298 | view | Course catalog API view |
| `v_gened_bucket_courses` | 3 | view | Gen-ed bucket aggregation |
| `v_plan_courses` | 431 | view | Planned courses with course details |
| `v_plan_meta` | 38 | view | Plan summary metadata |
| `v_plan_terms` | 104 | view | Plan terms with term details |
| `v_program_block_courses` | 834 | view | Planner-ready block/course aggregation |
| `v_program_block_courses_base` | 834 | view | Base block/course aggregation |
| `v_program_catalog` | 159 | view | Program catalog API view |
| `v_program_requirement_detail` | 834 | view | Requirement detail with courses/tree JSON |
| `v_student_course_history_detail` | 155 | view | Student history with course details |
| `v_student_course_progress` | 586 | view | Completed/planned course status |
| `v_student_major_program` | 20 | view | Student major program selection |
| `v_student_primary_major_program` | 20 | view | Student primary major selection |
| `v_student_profile` | 34 | view | Student profile API view |
| `v_terms_chronological` | 14 | view | Terms ordered for planning |

## Source To Database Map

| Source | Current entry point | Data produced | Destination |
| --- | --- | --- | --- |
| UW-Parkside course catalog pages | `src/class_scrapper.py` | Course subject, number, title, credits, description, raw prerequisite text, offered terms | `courses`, `course_offerings` |
| Parsed course prerequisite text | `src/build_prereqs.py` | Structured prerequisite/corequisite/restriction trees | `course_req_sets`, `course_req_nodes`, `course_req_atoms` |
| Parsed cross-listing text | `src/build_crosslistings.py` | Equivalent catalog listings | `course_crosslistings`, surfaced through `course_equivalents` |
| UW-Parkside undergraduate catalog programs | `src/scrape_program_requirements.py` | Majors, minors, certificates, blocks, flat courses, nested choices, manual flags | `programs`, `program_requirement_*`, `program_req_*` |
| UW-Parkside graduate program pages | `src/scrape_masters_programs.py` | Graduate programs and requirement structures | same program requirement tables with `program_type = 'GRADUATE'` |
| Application workflows | frontend/backend app writes | Student profiles, staff, plans, course history, AI chat, preferences, activity | `students`, `staff`, `plans`, `student_*`, `ai_*`, `notification_preferences` |
| Operational jobs and migrations | SQL scripts and scheduled jobs | Scrape run metadata and quality snapshots | `scrape_runs`, `nightly_data_quality_runs`, `data_quality` |

Legacy or archived paths:

- `src/legacy/load_program_requirements.py` loads only simple program/block/course data and does not populate the current tree tables.
- `src/legacy/run_sql_file.py` depends on a Supabase SQL RPC and is not the current reliable SQL execution path.
- `src/legacy/link_certificates_to_majors.py` targets an older mapping shape and must be updated before use with `major_certificate_mappings`.

## Core Schema Areas

### Course Catalog

- `courses` is the source of truth for catalog courses.
- `course_offerings` links courses to academic term codes and optional `terms.id`.
- `course_crosslistings` stores catalog cross-listings and optional resolved `crosslisted_course_id`.
- `course_code_aliases` exists for obsolete or alternate course codes but currently has no rows.
- `course_equivalents` exposes derived equivalency pairs used by progress logic.

Key course columns:

- `courses.id`: primary key.
- `courses.subject` and `courses.number`: catalog code.
- `courses.title`, `courses.credits`, `courses.description`: display/catalog fields.
- `courses.prereq_text`: raw prerequisite text used by `src/build_prereqs.py`.
- `courses.is_active`: active catalog flag.

### Course Prerequisites

Course prerequisites are represented as rule trees.

- `course_req_sets`: one root set per course requirement group; `set_type` is `PREREQ`, `COREQ`, or `RESTRICTION`.
- `course_req_nodes`: nested `AND`, `OR`, and `ATOM` nodes.
- `course_req_atoms`: leaf requirements such as required courses, course groups, consent, tests, and GPA rules.

Enums used here:

- `req_set_type`: `PREREQ`, `COREQ`, `RESTRICTION`
- `req_eval_policy`: `BEFORE_ONLY`, `BEFORE_OR_CONCURRENT`
- `req_node_type`: `AND`, `OR`, `ATOM`
- `req_atom_type`: `COURSE`, `COURSE_GROUP`, `CONSENT`, `TEST_SCORE`, `MIN_GPA`

### Programs And Requirements

- `programs` is the source of truth for academic programs.
- `programs.program_type` is `MAJOR`, `MINOR`, `CERTIFICATE`, or `GRADUATE`.
- `program_requirement_blocks` stores human-readable requirement sections.
- `program_requirement_courses` stores flat course links for block-level requirements.
- `program_requirement_block_flags` stores manual review and special handling metadata.
- `program_req_sets`, `program_req_nodes`, and `program_req_atoms` store nested requirement logic.

Requirement rules:

- `ALL_OF`: all listed requirements must be completed.
- `N_OF`: at least `n_required` listed requirements must be completed.
- `ANY_OF`: flexible choice-like bucket from scraped data.
- `CREDITS_OF`: credits-based requirement tracked through `credits_required`.

### General Education

- `gen_ed_buckets` defines gen-ed buckets and required credits.
- `gen_ed_bucket_courses` maps courses to those buckets.
- `v_gened_bucket_courses` aggregates bucket/course data for API reads.

### Students, Staff, Plans, And AI

These tables contain user or operational application data and are intentionally excluded from reference seeds:

- `students`, `staff`
- `student_programs`, `student_course_history`, `student_planned_courses`, `student_term_plan`
- `plans`, `plan_programs`
- `ai_conversations`, `ai_messages`
- `notification_preferences`, `student_activity_log`

### Operational Tables

- `scrape_runs` is connected to requirement rows through `scrape_run_id`, but currently has zero rows.
- `nightly_data_quality_runs` exists for scheduled quality snapshots, but currently has zero rows.
- `data_quality` exposes current quality metrics by program.

## Local Rebuild Data Policy

`scripts/rebuild_local_db.ps1` and `scripts/export_reference_seed.ps1` include only safe reference data:

- course catalog tables
- course prerequisite trees
- program catalog tables
- program requirement blocks, courses, flags, and trees
- gen-ed tables
- terms
- non-user mapping/reference tables

They intentionally exclude:

- students and staff
- plans and student history
- AI conversations and messages
- notification preferences
- student activity logs
- operational run logs

This keeps local rebuilds useful for development while avoiding private student/user data.

## Progress Calculation

Progress is driven by:

- `student_course_history.completed = true`
- canonical `courses.id`
- equivalency data from `course_equivalents`
- flat and tree-based program requirement data
- manual flags from `program_requirement_block_flags`

Main output surfaces:

- `student_block_completion`
- `student_block_completion_mv`
- `student_program_summary`
- `v_student_course_progress`

## Current Gaps To Track

- `sql/schema.sql` still needs to be generated with direct Postgres access and `pg_dump`.
- `scrape_runs` and `nightly_data_quality_runs` exist but have no rows yet.
- `course_code_aliases` exists but has no live alias rows.
- `major_certificate_mappings` exists but is empty; the archived certificate-linking script must be updated before that area is relied on.
