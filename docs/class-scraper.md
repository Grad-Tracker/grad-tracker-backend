# Course Catalog Scraper

Author: CJ Shane

This document explains `src/class_scrapper.py`. The filename uses the original project spelling, but the script is the current course catalog scraper.

## Purpose

The scraper reads UW-Parkside catalog course description pages and writes SQL insert files for catalog/reference data.

Primary destinations:

- `courses`
- `course_offerings`, when `--out-offerings` is used

`courses.prereq_text` stores raw prerequisite text. Structured prerequisite trees are built later by `src/build_prereqs.py`.

## Requirements

- Python 3.10+
- dependencies from `requirements.txt`

```powershell
python -m pip install -r requirements.txt
```

## Basic Usage

```powershell
python src/class_scrapper.py --url "https://catalog.uwp.edu/azindex/" --recursive --out courses.sql --prereq-column prereq_text --out-offerings course_offerings.sql
```

Generated files are intentionally ignored by git. Move only sanitized samples under `docs/samples/` if a sample needs to be kept.

## Important Options

- `--url`: catalog page to scrape.
- `--recursive`: follow discovered catalog links.
- `--out`: output SQL file for `courses`.
- `--out-offerings`: output SQL file for `course_offerings`.
- `--prereq-column`: column on `courses` for raw prerequisite text; use `prereq_text`.
- `--offered-column`: optional legacy column for offered seasons; current workflow prefers `course_offerings`.
- `--sleep`: optional delay after fetching pages.

## Current Workflow

1. Run `src/class_scrapper.py` to refresh course catalog SQL.
2. Load generated SQL through an approved direct Postgres path.
3. Run `src/build_crosslistings.py` to rebuild cross-listing rows.
4. Run `src/build_prereqs.py` to rebuild structured course prerequisite trees.
5. Run `scripts/validate_data.py` if program requirement data was also changed.

## Notes

- The scraper depends on the current catalog HTML structure.
- The scraper writes SQL files; it does not directly mutate the database.
- The older optional `course_prereqs` table path is not part of the current schema.
