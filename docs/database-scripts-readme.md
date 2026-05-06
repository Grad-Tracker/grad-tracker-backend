# Database Scripts README

Author: CJ Shane

This is the canonical guide for database scripts in this repo. It explains what each script does, what it generates, and when it should be used.

For the current schema and data flow, see `docs/database-schema-and-data-flow.md`.

## Requirements

Supabase REST scripts use:

- `SUPABASE_URL`
- `SUPABASE_KEY`

Direct Postgres scripts use:

- `SOURCE_DATABASE_URL`: direct Postgres URL for the live Supabase/Postgres source database.
- `LOCAL_ADMIN_DATABASE_URL`: local Postgres admin/maintenance URL, usually ending in `/postgres`.
- `LOCAL_TARGET_DATABASE_URL`: local Postgres URL for the database being rebuilt or restored.
- `DATABASE_URL`: direct Postgres URL used by validation scripts.

PostgreSQL CLI tools required for schema/rebuild workflows:

- `pg_dump`
- `psql`
- `createdb`
- `dropdb`, only for forced local rebuilds

## Current Scripts

| Script | Purpose | Generates |
| --- | --- | --- |
| `scripts/export_live_schema.ps1` | Exports the live `public` schema only. | `sql/schema.sql` |
| `scripts/export_reference_seed.ps1` | Exports whitelisted safe reference data only. | `.db_dumps/latest/reference_seed.sql` by default |
| `scripts/rebuild_local_db.ps1` | Creates/recreates a local DB, restores schema, then restores safe reference data. | `.db_dumps/latest/schema.sql`, `.db_dumps/latest/reference_seed.sql` |
| `scripts/restore_schema_only.ps1` | Restores an existing schema file into an existing local DB. | no new files |
| `scripts/restore_reference_seed.ps1` | Restores a generated reference seed into an existing local DB. | no new files |
| `scripts/validate_data.py` | Checks requirement-data quality through direct Postgres. | no new files |
| `scripts/check_handoff.ps1` | Checks handoff docs, required scripts, root clutter, source caches, tools, and tests. | no new files |
| `scripts/generate_sprint_report.py` | Generates a sprint/project report from GitHub data. | markdown report |

## Recommended Workflows

### Export The Exact Live Schema

Use this after intentional database schema changes.

```powershell
$env:SOURCE_DATABASE_URL = "postgresql://..."
.\scripts\export_live_schema.ps1
```

Generates:

- `sql/schema.sql`

Includes:

- `public` schema only
- tables, columns, enums, constraints, indexes, views, materialized views, functions, triggers, and RLS policies included by `pg_dump`
- no table data

### Export Safe Reference Data

Use this when seed data needs to be refreshed without rebuilding a local database.

```powershell
$env:SOURCE_DATABASE_URL = "postgresql://..."
.\scripts\export_reference_seed.ps1
```

Generates:

- `.db_dumps/latest/reference_seed.sql`

Includes:

- `terms`
- `courses`, `course_offerings`, `course_crosslistings`, `course_code_aliases`
- `course_req_sets`, `course_req_nodes`, `course_req_atoms`
- `programs`, `program_requirement_blocks`, `program_requirement_courses`, `program_requirement_block_flags`
- `program_req_sets`, `program_req_nodes`, `program_req_atoms`
- `gen_ed_buckets`, `gen_ed_bucket_courses`
- `major_certificate_mappings`

Excludes:

- `students`, `staff`
- plans, student history, planned courses, and selected programs
- AI conversations and messages
- notifications and activity logs
- operational run logs

### Rebuild A Local Database

Use this for a clean local database with the live schema and safe reference data.

```powershell
$env:SOURCE_DATABASE_URL = "postgresql://..."
$env:LOCAL_ADMIN_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/postgres"
$env:LOCAL_TARGET_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/grad_tracker_rebuild"
.\scripts\rebuild_local_db.ps1 -ForceDrop
```

Generates:

- `.db_dumps/latest/schema.sql`
- `.db_dumps/latest/reference_seed.sql`

Behavior:

- requires all env vars before creating anything
- checks required PostgreSQL tools before destructive work
- refuses to overwrite an existing local DB unless `-ForceDrop` is passed
- drops and recreates only the named local database when `-ForceDrop` is passed
- installs local Supabase compatibility roles and `auth.*` stubs
- restores schema first with `psql -v ON_ERROR_STOP=1`
- restores reference seed second
- validates included reference tables have rows
- validates excluded user/application tables are empty

Use schema-only mode when tests need an empty database:

```powershell
.\scripts\rebuild_local_db.ps1 -ForceDrop -SchemaOnly
```

### Restore Schema Without Live Access

Use this when `sql/schema.sql` already exists and a teammate does not have live Supabase access.

```powershell
$env:LOCAL_TARGET_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/grad_tracker_rebuild"
.\scripts\restore_schema_only.ps1
```

Requires:

- `sql/schema.sql`
- `psql`
- an existing local database

### Restore Reference Seed Into An Existing DB

Use this after schema restore when a generated seed file is already available.

```powershell
$env:LOCAL_TARGET_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/grad_tracker_rebuild"
.\scripts\restore_reference_seed.ps1
```

Default input:

- `.db_dumps/latest/reference_seed.sql`

Use `-SkipValidation` only when intentionally restoring a partial seed.

### Run Handoff Checks

Use this before transferring the repo.

```powershell
.\scripts\check_handoff.ps1
```

Use stricter tool validation when preparing a real handoff machine:

```powershell
.\scripts\check_handoff.ps1 -RequirePostgresTools
```

Checks:

- required docs and scripts exist
- historical database docs are under `docs/`
- generated root artifacts are not present
- repo source tree has no `__pycache__` directories outside `.venv`
- PostgreSQL CLI tools are available, as warnings by default
- Python tests pass unless `-SkipTests` is used

## Scraper And Loader Scripts

| Script | Current status | Destination |
| --- | --- | --- |
| `src/class_scrapper.py` | Current | `courses`, `course_offerings` |
| `src/build_prereqs.py` | Current | `course_req_sets`, `course_req_nodes`, `course_req_atoms` |
| `src/build_crosslistings.py` | Current | `course_crosslistings` |
| `src/scrape_program_requirements.py` | Current | `programs`, `program_requirement_*`, `program_req_*` |
| `src/scrape_masters_programs.py` | Current | same program tables with `program_type = 'GRADUATE'` |
| `src/legacy/load_program_requirements.py` | Legacy | simple `programs`, `program_requirement_blocks`, `program_requirement_courses` only |
| `src/legacy/run_sql_file.py` | Legacy | depends on an exposed SQL RPC |
| `src/legacy/link_certificates_to_majors.py` | Legacy | older certificate-major mapping shape |

## Generated Files And Git Tracking

Tracked intentionally:

- `sql/schema.sql`, after it is generated by `scripts/export_live_schema.ps1`
- sanitized sample JSON under `docs/samples/`

Ignored intentionally:

- `.db_dumps/`
- ad hoc generated `.sql` dumps
- generated JSON reports
- generated CSV reports
- skipped-line `.txt` files
- Python caches and test caches

## Full Reference Refresh Order

Use this order when intentionally refreshing catalog/program reference data:

1. Apply any approved SQL migration manually or through the database admin process.
2. Export the current schema with `scripts/export_live_schema.ps1`.
3. Refresh course catalog SQL with `src/class_scrapper.py`.
4. Load course data through the chosen direct Postgres restore path.
5. Rebuild cross-listings with `src/build_crosslistings.py`.
6. Rebuild course prerequisites with `src/build_prereqs.py`.
7. Scrape undergraduate programs with `src/scrape_program_requirements.py`.
8. Scrape graduate programs with `src/scrape_masters_programs.py`.
9. Validate with `scripts/validate_data.py`.
10. Rebuild a local development copy with `scripts/rebuild_local_db.ps1` if needed.

Any future live DB change should have a matching SQL file before it is applied. Do not use production as the only record of schema changes.
