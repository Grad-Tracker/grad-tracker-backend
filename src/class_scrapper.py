#!/usr/bin/env python3
"""
Scrape UW-Parkside catalog course descriptions and generate SQL inserts.

Default target table:
  public.courses(subject, number, title, credits, description, prereq_text)

Optional prereq output (if you create):
  public.course_prereqs(course_id, prereq_text)

Usage:
  python scrape_uwp_catalog.py \
    --url "https://catalog.uwp.edu/course-descriptions/csci/" \
    --out courses.sql

Optional prereq output:
  python scrape_uwp_catalog.py --out courses.sql --out-prereqs prereqs.sql

Notes:
- Uses requests + BeautifulSoup4.
- Tries to parse:
    "CSCI 241 | Computer Science I | 5 cr"
    description paragraph
    "Prerequisites: ..."
"""

from __future__ import annotations

import argparse
import re
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag


@dataclass
class Course:
    subject: str
    number: str
    title: str
    credits: float
    description: str
    prereq_text: Optional[str] = None


HEADER_RE = re.compile(
    r"^\s*([A-Z]{2,10})\s+([0-9]{1,4}[A-Z]?)\s*\|\s*(.*?)\s*\|\s*([0-9]+(?:\.[0-9])?)\s*cr\s*$",
    re.IGNORECASE,
)

PREREQ_RE = re.compile(
    r"^\s*(Prerequisites?|Prereqs?)\s*:?\s*(.*)\s*$", re.IGNORECASE
)


def sql_escape_literal(s: str) -> str:
    """Escape a string for a SQL single-quoted literal."""
    return s.replace("'", "''")


def fetch_html(url: str, timeout: int = 30) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; CourseScraper/1.0; +https://example.com)"
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _clean_prereq_text(text: str) -> Optional[str]:
    cleaned = normalize_ws(text)
    if not cleaned:
        return None
    if cleaned.lower() in {"none", "no", "n/a", "na"}:
        return None
    return cleaned


def parse_courseblock(block: Tag) -> Optional[Course]:
    # Many Acalog-style pages use .courseblocktitle and .courseblockdesc
    title_el = block.select_one(".courseblocktitle")
    desc_el = block.select_one(".courseblockdesc")

    subject = number = title = None
    credits: Optional[float] = None

    if title_el:
        header = normalize_ws(title_el.get_text(" ", strip=True))
        m = HEADER_RE.match(header)
        if not m:
            # Sometimes the separator differs; try a fallback parse
            # Example: "CSCI 241  Computer Science I  5 cr"
            fallback = normalize_ws(header)
            fallback = re.sub(r"\s*\|\s*", " | ", fallback)
            m = HEADER_RE.match(fallback)
        if m:
            subject, number, title, credits_s = m.group(1).upper(), m.group(2), m.group(3), m.group(4)
            credits = float(credits_s)

    # Newer UW-Parkside layout uses detail-* spans instead of courseblocktitle
    if subject is None:
        code_el = block.select_one(".detail-code")
        title_el2 = block.select_one(".detail-title")
        credits_el = block.select_one(".detail-hours_html")
        if code_el and title_el2 and credits_el:
            code_text = normalize_ws(code_el.get_text(" ", strip=True))
            parts = code_text.split()
            if len(parts) >= 2:
                subject, number = parts[0].upper(), parts[1]
                title = normalize_ws(title_el2.get_text(" ", strip=True))
                credits_text = normalize_ws(credits_el.get_text(" ", strip=True))
                m = re.match(r"^([0-9]+(?:\.[0-9])?)", credits_text)
                if m:
                    credits = float(m.group(1))

    if subject is None or number is None or title is None or credits is None:
        return None

    description = ""
    prereq_text: Optional[str] = None

    desc_parts: List[str] = []

    if desc_el:
        # Get text with line breaks preserved-ish
        raw = desc_el.get_text("\n", strip=True)
        lines = [normalize_ws(x) for x in raw.split("\n") if normalize_ws(x)]
        # Heuristic: description is usually first paragraph(s) until a line that starts with "Prerequisites:"
        pending_prereq = False
        for line in lines:
            pm = PREREQ_RE.match(line)
            if pm:
                content = pm.group(2).strip()
                if content:
                    prereq_text = _clean_prereq_text(content)
                else:
                    pending_prereq = True
                continue
            if pending_prereq:
                prereq_text = _clean_prereq_text(line)
                pending_prereq = False
                continue
            # ignore other catalog metadata if you want (e.g., "Offered: Fall")
            desc_parts.append(line)

    # Newer layout: description/prereqs are in .courseblockextra paragraphs
    if not desc_parts:
        extras = block.select("p.courseblockextra")
        for p in extras:
            text = normalize_ws(p.get_text(" ", strip=True))
            if not text:
                continue
            pm = PREREQ_RE.match(text)
            if pm:
                prereq_text = _clean_prereq_text(pm.group(2))
                continue
            # ignore other labeled metadata
            if text.lower().startswith(("offered:", "meets:", "equiv:", "equivalent:")):
                continue
            desc_parts.append(text)

    description = normalize_ws(" ".join(desc_parts))

    # Some pages put prereqs in their own <p><strong>Prerequisites:</strong> ...</p>
    if prereq_text is None and desc_el:
        # Search for explicit strong label
        strongs = desc_el.find_all("strong")
        for st in strongs:
            if "Prereq" in st.get_text():
                # Grab full parent text
                parent_text = normalize_ws(st.parent.get_text(" ", strip=True))
                pm = PREREQ_RE.match(parent_text)
                if pm:
                    prereq_text = _clean_prereq_text(pm.group(2))
                break

    # Last resort: scan any paragraph/div in the block for a prereq label
    if prereq_text is None:
        for el in block.find_all(["p", "div"]):
            text = normalize_ws(el.get_text(" ", strip=True))
            if "Prereq" not in text:
                continue
            pm = PREREQ_RE.match(text)
            if pm:
                prereq_text = _clean_prereq_text(pm.group(2))
                if prereq_text:
                    break

    return Course(
        subject=subject,
        number=number,
        title=normalize_ws(title),
        credits=credits,
        description=description,
        prereq_text=prereq_text,
    )


def parse_courses(html: str) -> List[Course]:
    soup = BeautifulSoup(html, "html.parser")

    # Acalog-ish pages usually have div.courseblock
    blocks = soup.select(".courseblock")
    courses: List[Course] = []
    for b in blocks:
        c = parse_courseblock(b)
        if c:
            courses.append(c)

    # Fallback: try another common structure if none found
    if not courses:
        # Sometimes it is <div class="courseblock"> but different container.
        # As a last resort, search for elements that look like course headers.
        headers = soup.find_all(string=lambda t: isinstance(t, str) and " cr" in t and "|" in t)
        for h in headers:
            text = normalize_ws(h)
            m = HEADER_RE.match(text)
            if m:
                subject, number, title, credits_s = m.group(1).upper(), m.group(2), m.group(3), m.group(4)
                courses.append(
                    Course(subject, number, normalize_ws(title), float(credits_s), description="", prereq_text=None)
                )

    # Deduplicate by (subject, number)
    seen = set()
    uniq: List[Course] = []
    for c in courses:
        key = (c.subject, c.number)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)

    return uniq


def discover_course_links(index_url: str, html: str) -> List[str]:
    """
    Discover course description page links from the course-descriptions index page.
    Keeps only links under the same /course-descriptions/ path.
    """
    soup = BeautifulSoup(html, "html.parser")
    base = f"{urlparse(index_url).scheme}://{urlparse(index_url).netloc}"
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href:
            continue
        if href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        full = urljoin(base, href)
        if not full.startswith(("http://", "https://")):
            continue
        if "/course-descriptions/" not in full:
            continue
        links.append(full)

    # Deduplicate while preserving order
    seen = set()
    uniq = []
    for link in links:
        if link in seen:
            continue
        seen.add(link)
        uniq.append(link)
    return uniq


def write_courses_sql(courses: List[Course], out_path: str) -> None:
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("-- Generated by scrape_uwp_catalog.py\n")
        f.write("BEGIN;\n\n")
        f.write(
            "INSERT INTO public.courses "
            "(subject, number, title, credits, description, prereq_text)\nVALUES\n"
        )

        values_lines = []
        for c in courses:
            prereq_sql = "NULL"
            if c.prereq_text:
                prereq_sql = f"'{sql_escape_literal(c.prereq_text)}'"
            values_lines.append(
                f"('{sql_escape_literal(c.subject)}',"
                f"'{sql_escape_literal(c.number)}',"
                f"'{sql_escape_literal(c.title)}',"
                f"{c.credits},"
                f"'{sql_escape_literal(c.description)}',"
                f"{prereq_sql})"
            )

        f.write(",\n".join(values_lines))
        f.write("\n;\n\nCOMMIT;\n")


def write_prereqs_sql(courses: List[Course], out_path: str) -> None:
    """
    Writes prereqs using a lookup on courses.id (requires that courses have been inserted already).
    Table recommended:

      CREATE TABLE public.course_prereqs (
        course_id bigint PRIMARY KEY REFERENCES public.courses(id) ON DELETE CASCADE,
        prereq_text text NOT NULL
      );
    """
    rows = [c for c in courses if c.prereq_text and c.prereq_text.strip()]
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("-- Generated by scrape_uwp_catalog.py\n")
        f.write("-- Requires public.course_prereqs(course_id, prereq_text)\n")
        f.write("BEGIN;\n\n")
        for c in rows:
            f.write(
                "INSERT INTO public.course_prereqs (course_id, prereq_text)\n"
                "SELECT id, '{pr}'\n"
                "FROM public.courses\n"
                "WHERE subject = '{sub}' AND number = '{num}'\n"
                "ON CONFLICT (course_id) DO UPDATE SET prereq_text = EXCLUDED.prereq_text;\n\n"
                .format(
                    pr=sql_escape_literal(c.prereq_text),
                    sub=sql_escape_literal(c.subject),
                    num=sql_escape_literal(c.number),
                )
            )
        f.write("COMMIT;\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--url",
        default="https://catalog.uwp.edu/course-descriptions/csci/",
        help="Catalog page URL to scrape.",
    )
    ap.add_argument("--out", default="courses.sql", help="Output SQL file for public.courses inserts.")
    ap.add_argument(
        "--out-prereqs",
        default=None,
        help="Optional output SQL file for prereqs (requires separate table).",
    )
    ap.add_argument("--sleep", type=float, default=0.0, help="Optional delay after fetch (seconds).")
    ap.add_argument(
        "--recursive",
        action="store_true",
        help="If set, treats --url as the course-descriptions index page and scrapes all linked subjects.",
    )
    args = ap.parse_args()

    courses: List[Course] = []
    if args.recursive:
        index_html = fetch_html(args.url)
        links = discover_course_links(args.url, index_html)
        if not links:
            raise SystemExit("No course description links found on index page.")
        for link in links:
            html = fetch_html(link)
            if args.sleep > 0:
                time.sleep(args.sleep)
            courses.extend(parse_courses(html))
    else:
        html = fetch_html(args.url)
        if args.sleep > 0:
            time.sleep(args.sleep)
        courses = parse_courses(html)

    if not courses:
        raise SystemExit("No courses parsed. Page structure may have changed.")

    # Sort nicely by number (best effort)
    def sort_key(c: Course) -> Tuple[str, int, str]:
        m = re.match(r"^(\d+)([A-Z]?)$", c.number)
        num = int(m.group(1)) if m else 0
        suffix = m.group(2) if m else c.number
        return (c.subject, num, suffix)

    courses.sort(key=sort_key)

    write_courses_sql(courses, args.out)
    print(f"Wrote {len(courses)} course inserts -> {args.out}")

    if args.out_prereqs:
        write_prereqs_sql(courses, args.out_prereqs)
        print(f"Wrote prereq inserts -> {args.out_prereqs}")


if __name__ == "__main__":
    main()
