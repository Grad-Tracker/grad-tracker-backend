# Legacy Database Utilities

These scripts are archived for traceability and should not be used as the current database workflow.

Use the current scripts in `scripts/` for schema export, local rebuilds, reference seed export/restore, and handoff validation.

## Archived Scripts

- `run_sql_file.py`: depends on a Supabase SQL RPC such as `exec_sql`, which is not part of the current reliable workflow.
- `link_certificates_to_majors.py`: targets the older `program_major_links` shape; the current schema uses `major_certificate_mappings`.
- `load_program_requirements.py`: loads only the simple program/block/course model and does not populate the current requirement tree tables.

If one of these workflows becomes necessary again, update it against the current live schema before running it.
