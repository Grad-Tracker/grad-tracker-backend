#!/usr/bin/env python3
"""
Scrape UW-Parkside program pages and extract Major Requirements.

Outputs:
  - JSON summary (programs + requirement blocks + courses)
  - Optional SQL inserts for:
      programs
      program_requirement_blocks
      program_requirement_courses

Notes:
  - This script focuses on pages that contain a "Major Requirements" section.
  - It uses heuristics to group courses into blocks using nearby headings.
  - Enum values for block.rule are configurable via CLI.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from dataclasses import dataclass, asdict
from typing import Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

from connection import get_connection

COURSE_RE = re.compile(r"\b([A-Z]{2,10})\s*([0-9]{1,4}[A-Z]?)\b")
CROSSLIST_RE = re.compile(r"\b([A-Z]{2,10}(?:/[A-Z]{2,10})+)\s*([0-9]{1,4}[A-Z]?)\b")
CATALOG_YEAR_RE = re.compile(r"\b(20\d{2}\s*-\s*20\d{2})\b")

STOP_HEADINGS = {
    "degree requirements",
    "general university degree requirements",
    "4-year academic plan",
    "four-year academic plan",
    "plan of study grid",
}

REQ_HEADINGS = {
    "major requirements",
    "minor requirements",
    "certificate requirements",
    "requirements for the",
    "program requirements",
}

SELECT_RE = re.compile(
    r"\b(select|choose)\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b",
    re.IGNORECASE,
)

NUM_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}

MANUAL_REQUIREMENT_RE = re.compile(
    r"\b("
    r"special topics|independent study|internship|placement|audition|"
    r"varies by topic|varies with topic|varies by subject|"
    r"approval|permission|consent|advisor|department chair|"
    r"thesis|project|portfolio|comprehensive exam|"
    r"one course in|two courses in|three courses in|"
    r"\d{3}\s*-\s*level|upper\s*-?\s*level|"
    r"elective(s)?|"
    r"practicum|clinical|field experience"
    r")\b",
    re.IGNORECASE,
)

SPECIAL_TOPICS_RE = re.compile(r"\bspecial topics?\b|\bvaries by topic\b", re.IGNORECASE)


@dataclass
class Block:
    name: str
    courses: List[Tuple[str, str]]
    rule: str
    n_required: Optional[int] = None
    credits_required: Optional[float] = None
    manual_notes: List[str] = None
    option_groups: List[List[Tuple[str, str]]] = None


@dataclass
class Program:
    name: str
    catalog_year: str
    url: str
    program_type: str
    blocks: List[Block]


def fetch_html(url: str, timeout: int = 30) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ProgramScraper/1.0; +https://example.com)"
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_text_value(text: str) -> str:
    t = normalize_ws(text)
    t = re.sub(r"\s+([,;:])", r"\1", t)
    t = re.sub(r"\(\s+", "(", t)
    t = re.sub(r"\s+\)", ")", t)
    # Keep short abbreviation endings (e.g., "U.S.") intact.
    if t.endswith(".") and not re.search(r"(?:\b[A-Z]{1,4}\.)$", t):
        t = t[:-1].rstrip()
    return t


def standardize_program_name(name: str) -> str:
    return normalize_text_value(name)


def classify_manual_reason(note: str, credits_required: Optional[float], has_courses: bool) -> str:
    if credits_required is not None and not has_courses:
        return "credits_only"
    if SPECIAL_TOPICS_RE.search(note or ""):
        return "special_topics"
    return "non_explicit"


def parse_catalog_year(soup: BeautifulSoup) -> Optional[str]:
    text = normalize_ws(soup.get_text(" ", strip=True))
    m = CATALOG_YEAR_RE.search(text)
    if m:
        return m.group(1).replace(" ", "")
    return None


def discover_program_links(base_url: str, html: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    base = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}"
    links: List[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href:
            continue
        if href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        full = urljoin(base, href)
        if not full.startswith(("http://", "https://")):
            continue
        if "/programs/" not in full:
            continue
        # Skip PDFs and other non-HTML assets
        if full.lower().endswith(".pdf"):
            continue
        # Only keep program detail pages: /programs/{area}/{program}/
        path_parts = [p for p in urlparse(full).path.split("/") if p]
        if "programs" not in path_parts:
            continue
        prog_idx = path_parts.index("programs")
        prog_parts = path_parts[prog_idx + 1 :]
        if len(prog_parts) < 2:
            continue
        # Skip the base programs index itself
        if full.rstrip("/").endswith("/programs"):
            continue
        links.append(full)

    seen: Set[str] = set()
    uniq: List[str] = []
    for link in links:
        link = link.split("#", 1)[0]
        if link in seen:
            continue
        seen.add(link)
        uniq.append(link)
    return uniq


def find_major_requirements_anchor(soup: BeautifulSoup) -> Optional[Tag]:
    # Prefer explicit requirement containers (Acalog tabs)
    for req_id in (
        "majorrequirementstextcontainer",
        "minorrequirementstextcontainer",
        "certificaterequirementstextcontainer",
        "programrequirementstextcontainer",
        "majorrequirementstext",
        "minorrequirementstext",
        "certificaterequirementstext",
        "programrequirementstext",
    ):
        anchor = soup.find(id=req_id)
        if anchor:
            return anchor
    # Fallback: any id that looks like a requirement container
    anchor = soup.find(id=re.compile(r"(major|minor|certificate|program)requirementstext(container)?$"))
    if anchor:
        return anchor

    # Fallback: find heading matching major requirements
    for tag in soup.find_all(["h2", "h3", "h4"]):
        text = normalize_ws(tag.get_text(" ", strip=True)).lower()
        if text in REQ_HEADINGS or any(text.startswith(x) for x in REQ_HEADINGS):
            return tag
        if text.startswith("requirements for the") and (
            "major" in text or "minor" in text or "certificate" in text
        ):
            return tag
        if text.startswith("requirements for the") and "program" in text:
            return tag
    return None


def is_stop_heading(tag: Tag) -> bool:
    if tag.name not in {"h2", "h3"}:
        return False
    text = normalize_ws(tag.get_text(" ", strip=True)).lower()
    return any(text.startswith(h) for h in STOP_HEADINGS)


def iter_section_nodes(start: Tag) -> Iterable[Tag]:
    """
    Iterate forward in document order after `start` until a stop heading.
    Uses next_elements (not just siblings) to handle nested layouts.
    """
    started = False
    for el in start.next_elements:
        if el is start:
            continue
        if isinstance(el, Tag):
            if not started:
                started = True
            # Skip nested container children; handle container as a whole
            if el.name != "table" and el.find_parent("table") is not None:
                continue
            if el.name != "dl" and el.find_parent("dl") is not None:
                continue
            if el.name not in {"ul", "ol"} and el.find_parent(["ul", "ol"]) is not None:
                continue
            if is_stop_heading(el):
                break
            # Stop if we hit another major requirement heading
            if el.name in {"h2", "h3"}:
                text = normalize_ws(el.get_text(" ", strip=True)).lower()
                if text.startswith("requirements for the") and "major" in text:
                    break
            yield el


def iter_container_nodes(container: Tag) -> Iterable[Tag]:
    """
    Iterate elements within a container only, skipping nested table/list children
    to avoid duplicate parsing.
    """
    for el in container.descendants:
        if not isinstance(el, Tag):
            continue
        if el is container:
            continue
        if el.name != "table" and el.find_parent("table") is not None:
            continue
        if el.name != "dl" and el.find_parent("dl") is not None:
            continue
        if el.name not in {"ul", "ol"} and el.find_parent(["ul", "ol"]) is not None:
            continue
        yield el


def extract_courses_from_tag(tag: Tag) -> List[Tuple[str, str]]:
    courses: List[Tuple[str, str]] = []
    def add_from_text(text: str) -> None:
        # Cross-listed patterns like CSCI/MATH 231
        for subjects, num in CROSSLIST_RE.findall(text):
            for subj in subjects.split("/"):
                courses.append((subj.upper(), num.upper()))
        for subj, num in COURSE_RE.findall(text):
            courses.append((subj.upper(), num.upper()))

    # Prefer linked course codes
    for a in tag.find_all("a"):
        text = normalize_ws(a.get_text(" ", strip=True))
        add_from_text(text)
    # Fallback: plain text scan
    if not courses:
        text = normalize_ws(tag.get_text(" ", strip=True))
        add_from_text(text)
    return courses


def extract_courses_from_footnotes(dl: Tag) -> List[Tuple[str, str]]:
    """
    Only extract courses from explicit list items in footnotes.
    This avoids pulling exclusions like "excluding CSCI 495".
    """
    courses: List[Tuple[str, str]] = []
    items = dl.find_all("li")
    if not items:
        return courses
    for li in items:
        courses.extend(extract_courses_from_tag(li))
    # De-dup preserving order
    seen = set()
    out: List[Tuple[str, str]] = []
    for c in courses:
        if c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


def extract_courses_from_row(tr: Tag) -> List[Tuple[str, str]]:
    courses: List[Tuple[str, str]] = []
    def add_from_text(text: str) -> None:
        for subjects, num in CROSSLIST_RE.findall(text):
            for subj in subjects.split("/"):
                courses.append((subj.upper(), num.upper()))
        for subj, num in COURSE_RE.findall(text):
            courses.append((subj.upper(), num.upper()))

    # Prefer linked course codes inside the row
    for a in tr.find_all("a"):
        text = normalize_ws(a.get_text(" ", strip=True))
        add_from_text(text)
    if not courses:
        text = normalize_ws(tr.get_text(" ", strip=True))
        add_from_text(text)
    return courses


def detect_select_count_from_row(tr: Tag) -> Optional[int]:
    text = normalize_ws(tr.get_text(" ", strip=True))
    return detect_select_count(text)


def is_section_header_row(tr: Tag) -> Optional[str]:
    """
    Detect rows that act as section headers inside a course list table,
    e.g., "Required Science Course", "Required Major Courses", etc.
    """
    # If it has a single header-like cell, treat as section header.
    cells = tr.find_all(["th", "td"])
    if len(cells) == 1:
        text = normalize_ws(cells[0].get_text(" ", strip=True))
    elif len(cells) == 2:
        left = normalize_ws(cells[0].get_text(" ", strip=True))
        right = normalize_ws(cells[1].get_text(" ", strip=True))
        # treat as header if right cell is empty or just credits, and left has no course codes
        if not left:
            return None
        if right and not re.fullmatch(r"\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?", right):
            return None
        if COURSE_RE.search(left):
            return None
        text = left
    else:
        return None

    if not text:
        return None
    # Filter out column header rows
    if text.lower() in {"code title credits", "code title"}:
        return None
    # Filter out subtotal/total rows
    if "subtotal" in text.lower() or text.lower().startswith("total "):
        return None
    # Don't treat select/choose rows as headers
    if SELECT_RE.search(text):
        return None
    # If it looks like a note (no course codes), still allow as header
    # Treat as section header
    return text


def parse_subtotal_credits(text: str) -> Optional[float]:
    """
    Parse subtotal credit numbers from a row like:
      "Required Science Course Subtotal 5"
      "Required Major Courses Subtotal 62-63"
    If a range is present, returns the lower bound.
    """
    if "subtotal" not in text.lower():
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:-\s*(\d+(?:\.\d+)?))?", text)
    if not m:
        return None
    return float(m.group(1))


def parse_subtotal_label(text: str) -> Optional[str]:
    m = re.search(r"^(.*?)\s+subtotal\b", text, re.IGNORECASE)
    if not m:
        return None
    label = normalize_ws(m.group(1))
    return label or None


def detect_select_count(text: str) -> Optional[int]:
    m = SELECT_RE.search(text or "")
    if not m:
        return None
    raw = m.group(2).lower()
    if raw.isdigit():
        return int(raw)
    return NUM_WORDS.get(raw)


def parse_major_requirements(
    soup: BeautifulSoup,
    rule_all: str,
    rule_any: str,
    rule_choose: str,
) -> Optional[List[Block]]:
    anchor = find_major_requirements_anchor(soup)
    if not anchor:
        return None

    blocks: Dict[str, Block] = {}
    anchor_id = (anchor.get("id") or "").lower()
    anchor_text = ""
    node_iter: Iterable[Tag]

    def requirement_label_from_id(req_id: str) -> str:
        if "minor" in req_id:
            return "Minor Requirements"
        if "certificate" in req_id:
            return "Certificate Requirements"
        if "program" in req_id:
            return "Program Requirements"
        if "major" in req_id:
            return "Major Requirements"
        return "Program Requirements"

    if anchor_id.endswith("requirementstextcontainer"):
        # Prefer an explicit heading inside the container
        heading = anchor.find(["h2", "h3", "h4", "h5"])
        if heading:
            anchor_text = normalize_ws(heading.get_text(" ", strip=True))
        else:
            anchor_text = requirement_label_from_id(anchor_id)
        node_iter = iter_container_nodes(anchor)
    else:
        anchor_text = normalize_ws(anchor.get_text(" ", strip=True))
        if not anchor_text:
            next_heading = anchor.find_next(["h2", "h3", "h4", "h5"])
            if next_heading:
                anchor_text = normalize_ws(next_heading.get_text(" ", strip=True))
        node_iter = iter_section_nodes(anchor)

    current_block_name = anchor_text or "Requirements"
    current_text_parts: List[str] = []

    def ensure_block(name: str) -> Block:
        name = normalize_text_value(name)
        if name not in blocks:
            blocks[name] = Block(
                name=name, courses=[], rule=rule_all, manual_notes=[], option_groups=[]
            )
        return blocks[name]

    ensure_block(current_block_name)
    last_select_block: Optional[str] = None

    def table_block_name(tbl: Tag) -> Optional[str]:
        # Prefer table caption
        caption = tbl.find("caption")
        if caption:
            text = normalize_ws(caption.get_text(" ", strip=True))
            if text and text.lower() not in {"course list"}:
                return text
        # Some tables have a first row like "Required Courses"
        first_row = tbl.find("tr")
        if first_row:
            text = normalize_ws(first_row.get_text(" ", strip=True))
            # Keep it only if it's short-ish and not the column header row
            if text and text.lower() not in {"code title credits", "code title"} and len(text) < 80:
                return text
        return None

    saw_table_courses = False

    for node in node_iter:
        if node.name in {"h3", "h4", "h5"}:
            current_block_name = normalize_ws(node.get_text(" ", strip=True))
            ensure_block(current_block_name)
            current_text_parts = []
            continue

        text = normalize_ws(node.get_text(" ", strip=True))
        if text:
            current_text_parts.append(text)

        # Course list tables often appear as <table class="sc_courselist">
        is_table = node.name == "table" or "courselist" in " ".join(node.get("class", [])).lower()
        courses = extract_courses_from_tag(node)

        if is_table:
            # Parse table row-by-row to preserve section buckets
            base_name = table_block_name(node) or current_block_name
            current_table_block = base_name
            ensure_block(current_table_block)
            saw_section_header = False
            last_area_header: Optional[str] = None

            for tr in node.find_all("tr"):
                # Section header rows inside table (using Acalog classes if present)
                tr_classes = " ".join(tr.get("class", [])).lower()
                row_text = normalize_ws(tr.get_text(" ", strip=True))

                if "areaheader" in tr_classes:
                    header_name = row_text
                    if header_name:
                        saw_section_header = True
                        last_area_header = header_name
                        current_table_block = header_name
                        ensure_block(current_table_block)
                        continue
                if "areasubheader" in tr_classes:
                    header_name = row_text
                    if header_name:
                        saw_section_header = True
                        if last_area_header and header_name != last_area_header:
                            current_table_block = f"{last_area_header} - {header_name}"
                        else:
                            current_table_block = header_name
                        ensure_block(current_table_block)
                        continue

                # Generic section header fallback
                header_name = is_section_header_row(tr)
                if header_name:
                    saw_section_header = True
                    last_area_header = header_name
                    current_table_block = header_name
                    ensure_block(current_table_block)
                    continue

                # Subtotal row -> assign credits_required to current block
                subtotal = parse_subtotal_credits(row_text)
                if subtotal is not None:
                    label = parse_subtotal_label(row_text)
                    if label:
                        block = ensure_block(label)
                    else:
                        block = ensure_block(current_table_block)
                    block.credits_required = subtotal
                    continue

                # Detect "select/choose" row scoped to current block
                select_n = detect_select_count_from_row(tr)
                if select_n:
                    block = ensure_block(current_table_block)
                    block.rule = rule_choose
                    block.n_required = select_n
                    last_select_block = current_table_block
                    # Capture grouped options if course rows appear below
                    continue

                # Recommended row
                row_text = normalize_ws(tr.get_text(" ", strip=True))
                if "recommended" in row_text.lower():
                    block = ensure_block(current_table_block)
                    block.rule = rule_any
                    continue

                # Extract courses from row
                row_courses = extract_courses_from_row(tr)
                if row_courses:
                    block = ensure_block(current_table_block)
                    for c in row_courses:
                        if c not in block.courses:
                            block.courses.append(c)
                    saw_table_courses = True
                    # If this is a select/choose block, capture row as an option group
                    if block.rule == rule_choose:
                        block.option_groups.append(row_courses)
                else:
                    if MANUAL_REQUIREMENT_RE.search(row_text):
                        block = ensure_block(current_table_block)
                        block.manual_notes.append(row_text)
            # If table had no section headers and base_name is generic, fall back to current block
            if not saw_section_header and base_name.lower() == "course list":
                current_table_block = current_block_name
        elif courses:
            # Non-table fallback behavior
            target_block = current_block_name
            is_footnotes = node.name == "dl" and "sc_footnotes" in " ".join(node.get("class", [])).lower()
            if is_footnotes:
                # Only pull courses from list items in footnotes
                courses = extract_courses_from_footnotes(node)
                if not courses:
                    continue
                if last_select_block:
                    target_block = last_select_block
            # If we already captured table courses, ignore non-table lists except footnotes
            if saw_table_courses and not is_footnotes:
                continue
            block = ensure_block(target_block)
            for c in courses:
                if c not in block.courses:
                    block.courses.append(c)

            scope_text = normalize_ws(node.get_text(" ", strip=True))
            if not scope_text:
                scope_text = " ".join(current_text_parts)
            select_n = detect_select_count(scope_text)
            if select_n:
                block.rule = rule_choose
                block.n_required = select_n
                last_select_block = target_block
            elif "recommended" in scope_text.lower():
                block.rule = rule_any
        else:
            if MANUAL_REQUIREMENT_RE.search(text):
                block = ensure_block(current_block_name)
                block.manual_notes.append(text)

    # Keep blocks that either have courses, credit requirements, or explicit counts
    out = [
        b
        for b in blocks.values()
        if b.courses or b.credits_required is not None or b.n_required is not None
    ]
    return out or None


def parse_program_title(soup: BeautifulSoup) -> Optional[str]:
    h1 = soup.find("h1")
    if h1:
        return normalize_ws(h1.get_text(" ", strip=True))
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    return normalize_ws(title) if title else None


def classify_program_type(program_title: Optional[str]) -> Optional[str]:
    if not program_title:
        return None
    t = program_title.lower()
    # Degree markers imply a major program
    if any(marker in t for marker in ("(bs)", "(ba)", "(aas)", "(as)", "(aa)")):
        return "MAJOR"
    if "major" in t:
        return "MAJOR"
    if "minor" in t:
        return "MINOR"
    if "certificate" in t:
        return "CERTIFICATE"
    return None


def is_major_page(program_title: Optional[str], blocks: Optional[List[Block]]) -> bool:
    if not blocks:
        return False
    if not program_title:
        return True
    return "major" in program_title.lower()


def sql_escape_literal(s: str) -> str:
    return s.replace("'", "''")


def write_sql(programs: List[Program], out_path: str) -> None:
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("-- Generated by scrape_program_requirements.py\n")
        f.write("BEGIN;\n\n")

        for p in programs:
            f.write(
                "INSERT INTO public.programs (name, catalog_year, program_type)\n"
                "SELECT '{name}', '{year}', '{ptype}'\n"
                "WHERE NOT EXISTS (\n"
                "  SELECT 1 FROM public.programs WHERE name = '{name}' AND catalog_year = '{year}'\n"
                ");\n\n".format(
                    name=sql_escape_literal(p.name),
                    year=sql_escape_literal(p.catalog_year),
                    ptype=sql_escape_literal(p.program_type),
                )
            )

            for b in p.blocks:
                n_required_sql = "NULL" if b.n_required is None else str(b.n_required)
                credits_sql = "NULL" if b.credits_required is None else str(b.credits_required)
                f.write(
                    "INSERT INTO public.program_requirement_blocks (program_id, name, rule, n_required, credits_required)\n"
                    "SELECT p.id, '{block}', '{rule}', {n_required}, {credits}\n"
                    "FROM public.programs p\n"
                    "WHERE p.name = '{name}' AND p.catalog_year = '{year}';\n\n".format(
                        block=sql_escape_literal(b.name),
                        rule=sql_escape_literal(b.rule),
                        n_required=n_required_sql,
                        credits=credits_sql,
                        name=sql_escape_literal(p.name),
                        year=sql_escape_literal(p.catalog_year),
                    )
                )

                for subj, num in b.courses:
                    f.write(
                        "INSERT INTO public.program_requirement_courses (block_id, course_id)\n"
                        "SELECT b.id, c.id\n"
                        "FROM public.program_requirement_blocks b\n"
                        "JOIN public.programs p ON p.id = b.program_id\n"
                        "JOIN public.courses c ON c.subject = '{subj}' AND c.number = '{num}'\n"
                        "WHERE p.name = '{name}' AND p.catalog_year = '{year}' AND b.name = '{block}'\n"
                        "ON CONFLICT DO NOTHING;\n\n".format(
                            subj=sql_escape_literal(subj),
                            num=sql_escape_literal(num),
                            name=sql_escape_literal(p.name),
                            year=sql_escape_literal(p.catalog_year),
                            block=sql_escape_literal(b.name),
                        )
                    )

        f.write("COMMIT;\n")


def sb_one(resp, context: str):
    if getattr(resp, "error", None):
        raise RuntimeError(f"{context}: {resp.error}")
    data = resp.data
    if not data:
        return None
    return data[0]

def execute_with_retry(fn, context: str, retries: int = 3, delay: float = 1.0):
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except Exception as exc:
            last_err = exc
            msg = str(exc)
            if "WinError 10054" in msg or "ReadError" in msg or "Connection" in msg:
                time.sleep(delay * attempt)
                continue
            raise
    raise RuntimeError(f"{context} failed after {retries} retries: {last_err}")

def get_or_create_program(sb, name: str, catalog_year: str, program_type: str) -> int:
    resp = execute_with_retry(
        lambda: sb.table("programs")
        .select("id")
        .eq("name", name)
        .eq("catalog_year", catalog_year)
        .limit(1)
        .execute(),
        f"select program {name} {catalog_year}",
    )
    row = sb_one(resp, f"select program {name} {catalog_year}")
    if row:
        # Ensure program_type is set
        if row.get("program_type") != program_type:
            upd = execute_with_retry(
                lambda: sb.table("programs")
                .update({"program_type": program_type})
                .eq("id", row["id"])
                .execute(),
                f"update program_type {name} {catalog_year}",
            )
            if getattr(upd, "error", None):
                raise RuntimeError(f"update program_type {name} {catalog_year}: {upd.error}")
        return int(row["id"])

    resp2 = execute_with_retry(
        lambda: sb.table("programs")
        .insert({"name": name, "catalog_year": catalog_year, "program_type": program_type})
        .execute(),
        f"insert program {name} {catalog_year}",
    )
    row2 = sb_one(resp2, f"insert program {name} {catalog_year}")
    return int(row2["id"])


def get_or_create_block(
    sb,
    program_id: int,
    name: str,
    rule: str,
    n_required: Optional[int],
    credits_required: Optional[float],
) -> int:
    resp = execute_with_retry(
        lambda: sb.table("program_requirement_blocks")
        .select("id")
        .eq("program_id", program_id)
        .eq("name", name)
        .limit(1)
        .execute(),
        f"select block {program_id} {name}",
    )
    row = sb_one(resp, f"select block {program_id} {name}")
    if row:
        return int(row["id"])

    payload = {
        "program_id": program_id,
        "name": name,
        "rule": rule,
    }
    if n_required is not None:
        payload["n_required"] = n_required
    if credits_required is not None:
        payload["credits_required"] = credits_required

    resp2 = execute_with_retry(
        lambda: sb.table("program_requirement_blocks").insert(payload).execute(),
        f"insert block {program_id} {name}",
    )
    row2 = sb_one(resp2, f"insert block {program_id} {name}")
    return int(row2["id"])


def get_course_id(sb, subject: str, number: str, cache: Dict[Tuple[str, str], Optional[int]]) -> Optional[int]:
    key = (subject, number)
    if key in cache:
        return cache[key]
    resp = execute_with_retry(
        lambda: sb.table("courses")
        .select("id")
        .eq("subject", subject)
        .eq("number", number)
        .limit(1)
        .execute(),
        f"select course {subject} {number}",
    )
    row = sb_one(resp, f"select course {subject} {number}")
    if row:
        cid = int(row["id"])
        cache[key] = cid
        return cid

    # Fallback via canonical alias map
    resp_alias = execute_with_retry(
        lambda: sb.table("course_code_aliases")
        .select("course_id")
        .eq("subject", subject)
        .eq("number", number)
        .limit(1)
        .execute(),
        f"select alias course {subject} {number}",
    )
    row_alias = sb_one(resp_alias, f"select alias course {subject} {number}")
    if not row_alias:
        cache[key] = None
        return None
    cid = int(row_alias["course_id"])
    cache[key] = cid
    return cid


def insert_block_course(sb, block_id: int, course_id: int) -> None:
    payload = {"block_id": block_id, "course_id": course_id}
    resp = execute_with_retry(
        lambda: sb.table("program_requirement_courses")
        .upsert(payload, on_conflict="block_id,course_id")
        .execute(),
        f"insert block_course {block_id} {course_id}",
    )
    if getattr(resp, "error", None):
        raise RuntimeError(f"insert block_course {block_id} {course_id}: {resp.error}")


def insert_programs(sb, programs: List[Program], out_missing_courses: Optional[str]) -> None:
    course_cache: Dict[Tuple[str, str], Optional[int]] = {}
    missing_courses: List[Tuple[str, str]] = []
    blocks_processed = 0
    courses_inserted = 0

    for p in programs:
        program_name = standardize_program_name(p.name)
        program_id = get_or_create_program(sb, program_name, p.catalog_year, p.program_type)
        for b in p.blocks:
            b.name = normalize_text_value(b.name)
            b.manual_notes = [normalize_text_value(n) for n in (b.manual_notes or [])]
            block_id = get_or_create_block(
                sb, program_id, b.name, b.rule, b.n_required, b.credits_required
            )
            blocks_processed += 1

            # Build requirement tree for the block
            use_count = bool(b.n_required and b.n_required > 1)
            # Clear existing tree
            execute_with_retry(
                lambda: sb.table("program_req_sets").delete().eq("block_id", block_id).execute(),
                f"delete program_req_set {block_id}",
            )
            resp_set = execute_with_retry(
                lambda: sb.table("program_req_sets")
                .insert({"block_id": block_id, "use_count": use_count})
                .execute(),
                f"insert program_req_set {block_id}",
            )
            set_row = sb_one(resp_set, f"insert program_req_set {block_id}")
            req_set_id = int(set_row["id"])

            def insert_node(node_type: str, parent_id: Optional[int], sort_order: int) -> int:
                resp = execute_with_retry(
                    lambda: sb.table("program_req_nodes")
                    .insert(
                        {
                            "req_set_id": req_set_id,
                            "node_type": node_type,
                            "parent_id": parent_id,
                            "sort_order": sort_order,
                        }
                    )
                    .execute(),
                    f"insert program_req_node {block_id}",
                )
                row = sb_one(resp, f"insert program_req_node {block_id}")
                return int(row["id"])

            def insert_atom(node_id: int, course_id: int) -> None:
                resp = execute_with_retry(
                    lambda: sb.table("program_req_atoms")
                    .insert(
                        {
                            "node_id": node_id,
                            "atom_type": "COURSE",
                            "required_course_id": course_id,
                        }
                    )
                    .execute(),
                    f"insert program_req_atom {block_id}",
                )
                if getattr(resp, "error", None):
                    raise RuntimeError(f"insert program_req_atom {block_id}: {resp.error}")

            # Tree shape
            if b.rule == "N_OF" and b.n_required == 1 and b.option_groups:
                root_id = insert_node("OR", None, 0)
                for idx, group in enumerate(b.option_groups):
                    if len(group) == 1:
                        node_id = insert_node("ATOM", root_id, idx)
                        course_id = get_course_id(sb, group[0][0], group[0][1], course_cache)
                        if course_id:
                            insert_atom(node_id, course_id)
                    else:
                        and_id = insert_node("AND", root_id, idx)
                        for j, (subj, num) in enumerate(group):
                            node_id = insert_node("ATOM", and_id, j)
                            course_id = get_course_id(sb, subj, num, course_cache)
                            if course_id:
                                insert_atom(node_id, course_id)
            else:
                root_id = insert_node("AND", None, 0)
                for idx, (subj, num) in enumerate(b.courses):
                    node_id = insert_node("ATOM", root_id, idx)
                    course_id = get_course_id(sb, subj, num, course_cache)
                    if course_id:
                        insert_atom(node_id, course_id)
            payloads = []
            for subj, num in b.courses:
                course_id = get_course_id(sb, subj, num, course_cache)
                if course_id is None:
                    missing_courses.append((subj, num))
                    continue
                payloads.append({"block_id": block_id, "course_id": course_id})
            if payloads:
                resp = execute_with_retry(
                    lambda: sb.table("program_requirement_courses")
                    .upsert(payloads, on_conflict="block_id,course_id")
                    .execute(),
                    f"insert block_courses {block_id}",
                )
                if getattr(resp, "error", None):
                    raise RuntimeError(f"insert block_courses {block_id}: {resp.error}")
                courses_inserted += len(payloads)
            if b.manual_notes:
                seen_notes = set()
                flag_payloads = []
                for note in b.manual_notes:
                    note_trim = note[:1000]
                    if note_trim in seen_notes:
                        continue
                    seen_notes.add(note_trim)
                    flag_payloads.append(
                        {
                            "block_id": block_id,
                            "flag_type": "MANUAL_REQUIREMENT",
                            "manual_reason": classify_manual_reason(
                                note_trim, b.credits_required, bool(b.courses)
                            ),
                            "note": note_trim,
                        }
                    )
                resp = execute_with_retry(
                    lambda: sb.table("program_requirement_block_flags")
                    .upsert(flag_payloads, on_conflict="block_id,flag_type,note")
                    .execute(),
                    f"insert block flags {block_id}",
                )
                if getattr(resp, "error", None):
                    raise RuntimeError(f"insert block flags {block_id}: {resp.error}")
            elif b.credits_required is not None and not b.courses:
                # Explicitly track credits-only blocks as manual requirements.
                payload = {
                    "block_id": block_id,
                    "flag_type": "MANUAL_REQUIREMENT",
                    "manual_reason": "credits_only",
                    "note": "Credits-only requirement",
                }
                resp = execute_with_retry(
                    lambda: sb.table("program_requirement_block_flags")
                    .upsert(payload, on_conflict="block_id,flag_type,note")
                    .execute(),
                    f"insert credits-only block flag {block_id}",
                )
                if getattr(resp, "error", None):
                    raise RuntimeError(f"insert credits-only block flag {block_id}: {resp.error}")

    if missing_courses:
        uniq = sorted(set(missing_courses))
        print(f"Missing {len(uniq)} courses not found in courses table.")
        for subj, num in uniq[:50]:
            print(f"  - {subj} {num}")
        if len(uniq) > 50:
            print(f"  ... and {len(uniq) - 50} more")
        if out_missing_courses:
            with open(out_missing_courses, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["subject", "number"])
                writer.writerows(uniq)
            print(f"Wrote missing courses -> {out_missing_courses}")

    print(f"Blocks processed: {blocks_processed}")
    print(f"Block courses inserted: {courses_inserted}")


def reset_program_tables(sb) -> None:
    # Delete in dependency order (keep programs to preserve student_programs references)
    resp = sb.table("program_requirement_block_flags").delete().gt("id", 0).execute()
    if getattr(resp, "error", None):
        raise RuntimeError(f"clear program_requirement_block_flags: {resp.error}")

    resp = sb.table("program_requirement_courses").delete().gt("block_id", 0).execute()
    if getattr(resp, "error", None):
        raise RuntimeError(f"clear program_requirement_courses: {resp.error}")

    resp = sb.table("program_requirement_blocks").delete().gt("id", 0).execute()
    if getattr(resp, "error", None):
        raise RuntimeError(f"clear program_requirement_blocks: {resp.error}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--base-url",
        default="https://catalog.uwp.edu/programs/",
        help="Base programs index URL.",
    )
    ap.add_argument(
        "--program-url",
        default=None,
        help="Scrape a single program URL (skips index discovery).",
    )
    ap.add_argument(
        "--catalog-year",
        default=None,
        help="Catalog year to use (e.g., 2025-2026). If omitted, attempts to parse from page.",
    )
    ap.add_argument("--sleep", type=float, default=0.0, help="Delay between requests (seconds).")
    ap.add_argument("--limit", type=int, default=0, help="Limit number of programs for testing.")
    ap.add_argument("--offset", type=int, default=0, help="Skip the first N programs (for batching).")
    ap.add_argument("--only-majors", action="store_true", help="Only include pages that look like majors.")
    ap.add_argument("--out-json", default="program_requirements.json", help="Output JSON file.")
    ap.add_argument("--out-sql", default=None, help="Optional output SQL file.")
    ap.add_argument("--out-report", default="program_requirements_report.json", help="Report JSON file.")
    ap.add_argument("--out-missing-courses", default="missing_courses_undergrad.csv", help="CSV for missing course codes.")
    ap.add_argument("--out-manual-blocks", default="manual_blocks_undergrad.csv", help="CSV for manual/non-explicit blocks.")
    ap.add_argument("--insert-db", action="store_true", help="Insert results into the database.")
    ap.add_argument("--skip-reset", action="store_true", help="Skip resetting program tables before insert.")
    ap.add_argument("--reset-only", action="store_true", help="Reset program tables and exit.")
    ap.add_argument("--rule-all", default="ALL_OF", help="Enum value for an ALL/required block.")
    ap.add_argument("--rule-any", default="ANY_OF", help="Enum value for a recommended/any block.")
    ap.add_argument("--rule-choose", default="N_OF", help="Enum value for a choose-N block.")
    args = ap.parse_args()

    if args.program_url:
        program_links = [args.program_url]
    else:
        index_html = fetch_html(args.base_url)
        program_links = discover_program_links(args.base_url, index_html)

    if args.offset and args.offset > 0:
        program_links = program_links[args.offset :]
    if args.limit and args.limit > 0:
        program_links = program_links[: args.limit]

    programs: List[Program] = []
    skipped: List[str] = []

    for url in program_links:
        try:
            html = fetch_html(url)
        except requests.HTTPError as exc:
            # Skip broken program links (some are outdated in the index)
            if exc.response is not None and exc.response.status_code == 404:
                continue
            raise
        if args.sleep > 0:
            time.sleep(args.sleep)

        soup = BeautifulSoup(html, "html.parser")
        program_name = parse_program_title(soup) or url.rstrip("/").split("/")[-1]
        program_type = classify_program_type(program_name)
        catalog_year = args.catalog_year or parse_catalog_year(soup)
        if not catalog_year:
            # Skip if we can't determine year; user can re-run with --catalog-year
            skipped.append(f"{program_name} | missing catalog year")
            continue

        blocks = parse_major_requirements(
            soup, rule_all=args.rule_all, rule_any=args.rule_any, rule_choose=args.rule_choose
        )
        # Always ignore pages we can't classify as major/minor/certificate
        if not program_type:
            skipped.append(f"{program_name} | unclassified program type")
            continue
        if args.only_majors and not is_major_page(program_name, blocks):
            skipped.append(f"{program_name} | filtered by only-majors")
            continue
        if not blocks:
            skipped.append(f"{program_name} | no requirements blocks found")
            continue

        programs.append(
            Program(
                name=program_name,
                catalog_year=catalog_year,
                url=url,
                program_type=program_type,
                blocks=blocks,
            )
        )

    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump([asdict(p) for p in programs], f, indent=2)

    print(f"Wrote {len(programs)} programs -> {args.out_json}")
    if skipped:
        with open("programs_skipped.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(skipped))
        print(f"Wrote {len(skipped)} skipped program titles -> programs_skipped.txt")

    if args.out_sql:
        write_sql(programs, args.out_sql)
        print(f"Wrote SQL -> {args.out_sql}")

    # Report
    report = {
        "programs": len(programs),
        "skipped_count": len(skipped),
        "skipped_programs": skipped,
        "blocks_total": sum(len(p.blocks) for p in programs),
        "blocks_empty_courses": [
            {
                "program": p.name,
                "catalog_year": p.catalog_year,
                "block": b.name,
            }
            for p in programs
            for b in p.blocks
            if not b.courses
        ],
        "manual_requirements": [
            {
                "program": p.name,
                "catalog_year": p.catalog_year,
                "block": b.name,
                "note": n,
            }
            for p in programs
            for b in p.blocks
            for n in (b.manual_notes or [])
        ],
        "unparseable_elements_count": sum(len(b.manual_notes or []) for p in programs for b in p.blocks),
        "rules": {
            "ALL_OF": sum(1 for p in programs for b in p.blocks if b.rule == "ALL_OF"),
            "ANY_OF": sum(1 for p in programs for b in p.blocks if b.rule == "ANY_OF"),
            "N_OF": sum(1 for p in programs for b in p.blocks if b.rule == "N_OF"),
            "CREDITS_OF": sum(1 for p in programs for b in p.blocks if b.rule == "CREDITS_OF"),
        },
    }
    with open(args.out_report, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"Wrote report -> {args.out_report}")
    with open(args.out_manual_blocks, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["program", "catalog_year", "block", "note"])
        for row in report["manual_requirements"]:
            writer.writerow([row["program"], row["catalog_year"], row["block"], row["note"]])
    print(f"Wrote manual blocks -> {args.out_manual_blocks}")

    if args.insert_db or args.reset_only:
        sb = get_connection()
        if not args.skip_reset:
            reset_program_tables(sb)
        if args.reset_only:
            print("Reset complete.")
            return
        insert_programs(sb, programs, args.out_missing_courses)


if __name__ == "__main__":
    main()
