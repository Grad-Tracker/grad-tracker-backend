# Scraping Notes

Author: CJ Shane

This document summarizes current scraper behavior and expected outputs.

## Current Scripts

- `src/class_scrapper.py`: course catalog data.
- `src/build_crosslistings.py`: course cross-listing relationships.
- `src/build_prereqs.py`: structured prerequisite trees from `courses.prereq_text`.
- `src/scrape_program_requirements.py`: undergraduate majors, minors, and certificates.
- `src/scrape_masters_programs.py`: graduate programs.

## Program Scraper Outputs

Undergraduate and graduate program scrapers can generate:

- `--out-json`: parsed program, block, course, and tree payload.
- `--out-report`: summary counts and manual requirement entries.
- `--out-missing-courses`: CSV for course codes not found in `courses`.
- `--out-manual-blocks`: CSV for non-explicit/manual requirement notes.
- `--out-sql`: optional SQL output.

Generated reports are ignored by git unless a sanitized sample is intentionally placed under `docs/samples/`.

## Insert Path

When `--insert-db` is used:

- programs are created or updated in `programs`
- blocks are inserted into `program_requirement_blocks`
- flat course links go to `program_requirement_courses`
- tree data goes to `program_req_sets`, `program_req_nodes`, and `program_req_atoms`
- manual flags go to `program_requirement_block_flags`

## Parsing Rules

- Detect section headers and split requirement blocks.
- Detect `select` or `choose N` language to set `rule = N_OF` and `n_required`.
- Capture subtotal and total credit rows into `credits_required` where possible.
- Parse explicit course links and regex course-code references.
- Build `AND`/`OR` trees for grouped choices where possible.
- Flag non-explicit requirements for manual review instead of inventing logic.

## Known Limitations

- Some catalog rows describe requirements without explicit course codes.
- Some requirements depend on standing, placement, audition, advisor approval, or variable topics.
- Credits-based requirements are tracked but not fully enforced as credit sums in every progress surface.
