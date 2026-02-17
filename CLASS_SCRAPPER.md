# Class Scrapper Usage

This script scrapes UW‑Parkside course descriptions and generates SQL inserts.

## Requirements
- Python 3.10+
- Dependencies from `requirements.txt`:
  - `requests`
  - `beautifulsoup4`

Install:
```bash
python -m pip install -r requirements.txt
```

## Basic Usage
```bash
python src/class_scrapper.py --url "https://catalog.uwp.edu/azindex/" --recursive --out courses.sql
```

This produces a SQL file with inserts into:
```
public.courses(subject, number, title, credits, description, prereq_text, offered_terms)
```
The `offered_terms` value is taken from the catalog line after `Offered:` and stored as-is (normalized whitespace).

## Prerequisites Output (Optional)
```bash
python src/class_scrapper.py --out courses.sql --out-prereqs prereqs.sql
```

This creates a second SQL file that expects a table like:
```
public.course_prereqs(course_id, prereq_text)
```

## Offered Column (Optional)
If your `courses` table uses a different column name for offered seasons, pass it explicitly:
```bash
python src/class_scrapper.py --url "https://catalog.uwp.edu/azindex/" --recursive --out courses.sql --offered-column offered
```

## Options
- `--url`  
  Catalog page to scrape (default: CSCI page).
- `--out`  
  Output SQL file for courses (default: `courses.sql`).
- `--out-prereqs`  
  Optional output SQL file for prereq text.
- `--offered-column`  
  Column name on `public.courses` to store offered seasons (default: `offered_terms`). Use empty string to omit.
- `--sleep`  
  Optional delay after fetching (seconds).

## Notes
- The scraper is HTML‑structure dependent. If the catalog layout changes, parsing may fail.
- The script does not modify your database. It only writes SQL files.
