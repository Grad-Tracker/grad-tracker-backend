# Scraping Notes

This document summarizes scraper behavior and expected outputs.

## Scripts
- `src/scrape_program_requirements.py` for undergraduate/major/minor/certificate pages.
- `src/scrape_masters_programs.py` for graduate masters pages.

## Output Artifacts
Both scripts produce:
- `--out-json`: parsed program + block + course payload.
- `--out-report`: summary report with counts and manual requirement entries.
- `--out-missing-courses`: CSV for course codes not found in `courses`.
- `--out-manual-blocks`: CSV for non-explicit/manual requirement notes.

## Parsing Rules
- Detect section headers and split requirement blocks accordingly.
- Detect `select/choose N` to set `rule = N_OF` and `n_required`.
- Capture subtotal/total credit rows into `credits_required`.
- Parse course links and regex course codes.
- Build OR/AND trees for grouped choices where possible.

## Manual Flagging
When requirement text is not explicit enough for structured parsing, the scraper records a manual flag in `program_requirement_block_flags`.

Examples:
- Advisor consent
- Placement/audition
- Special topics / variable topic
- Standing or level-only text

## Insert Path
When `--insert-db` is used:
- Programs are created/updated in `programs`.
- Blocks are inserted into `program_requirement_blocks`.
- Course links go to `program_requirement_courses`.
- Requirement tree data goes to `program_req_sets`, `program_req_nodes`, `program_req_atoms`.
- Manual flags go to `program_requirement_block_flags`.

## Known Limitations
- Some catalog rows describe requirements without explicit course codes.
- Some `courses.number` formats are non-standard and are intentionally left as manual review.
- Credits-based requirements are stored but not fully enforced as credit sums in all contexts.
