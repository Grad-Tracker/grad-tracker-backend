#!/usr/bin/env python3
"""
Scrape UW-Parkside graduate (masters) program requirements from the catalog.

Workflow:
  1) Start from https://www.uwp.edu/learn/programs/ (Graduate Programs list)
  2) Follow each program page
  3) From program page, follow "Program Overview" (catalog.uwp.edu)
  4) Scrape Program Requirements course lists

Outputs:
  - JSON summary (programs + requirement blocks + courses)
  - Optional SQL inserts for:
      programs
      program_requirement_blocks
      program_requirement_courses
"""

from __future__ import annotations

import argparse
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
GRAD_DEGREE_RE = re.compile(r"\((MBA|MS|MA)\)", re.IGNORECASE)

REQ_HEADINGS = {
    "program requirements",
    "requirements for the",
}

STOP_HEADINGS = {
    "university requirements",
    "admission requirements",
    "courses",
    "overview",
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
        "User-Agent": "Mozilla/5.0 (compatible; MastersProgramScraper/1.0; +https://example.com)"
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def parse_catalog_year(soup: BeautifulSoup) -> Optional[str]:
    text = normalize_ws(soup.get_text(" ", strip=True))
    m = CATALOG_YEAR_RE.search(text)
    if m:
        return m.group(1).replace(" ", "")
    return None


def discover_graduate_program_links(programs_url: str, html: str) -> List[Tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    base = f"{urlparse(programs_url).scheme}://{urlparse(programs_url).netloc}"

    # Find the "Graduate Programs" heading and collect links until the next heading
    grad_heading = None
    for h in soup.find_all(["h2", "h3"]):
        if normalize_ws(h.get_text(" ", strip=True)).lower() == "graduate programs":
            grad_heading = h
            break

    links: List[Tuple[str, str]] = []
    if grad_heading:
        for el in grad_heading.next_elements:
            if el is grad_heading:
                continue
            if isinstance(el, Tag):
                if el.name in {"h2", "h3"}:
                    break
                if el.name == "a" and el.get("href"):
                    title = normalize_ws(el.get_text(" ", strip=True))
                    href = el["href"].strip()
                    if not href:
                        continue
                    full = urljoin(base, href)
                    links.append((title, full))

    # Fallback: scan entire page for links under /learn/programs/
    if not links:
        for a in soup.find_all("a", href=True):
            title = normalize_ws(a.get_text(" ", strip=True))
            href = a["href"].strip()
            if not href:
                continue
            if "/learn/programs/" not in href and "/learn/programs/" not in urljoin(base, href):
                continue
            links.append((title, urljoin(base, href)))

    # Filter to masters programs by label
    out: List[Tuple[str, str]] = []
    seen: Set[str] = set()
    for title, link in links:
        if not GRAD_DEGREE_RE.search(title):
            continue
        link = link.split("#", 1)[0]
        if link in seen:
            continue
        seen.add(link)
        out.append((title, link))
    return out


def find_program_overview_link(html: str, base_url: str) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        text = normalize_ws(a.get_text(" ", strip=True)).lower()
        href = a["href"].strip()
        if not href:
            continue
        if "program overview" in text and "catalog." in href:
            return href
        if "program overview" in text:
            return urljoin(base_url, href)
    # Fallback: first catalog.uwp.edu link
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if "catalog.uwp.edu" in href:
            return href
    return None


def parse_program_title(soup: BeautifulSoup) -> Optional[str]:
    h1 = soup.find("h1")
    if h1:
        return normalize_ws(h1.get_text(" ", strip=True))
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    return normalize_ws(title) if title else None


def is_stop_heading(tag: Tag) -> bool:
    if tag.name not in {"h2", "h3"}:
        return False
    text = normalize_ws(tag.get_text(" ", strip=True)).lower()
    return any(text.startswith(h) for h in STOP_HEADINGS)


def iter_section_nodes(start: Tag) -> Iterable[Tag]:
    started = False
    for el in start.next_elements:
        if el is start:
            continue
        if isinstance(el, Tag):
            if not started:
                started = True
            if el.name != "table" and el.find_parent("table") is not None:
                continue
            if el.name != "dl" and el.find_parent("dl") is not None:
                continue
            if el.name not in {"ul", "ol"} and el.find_parent(["ul", "ol"]) is not None:
                continue
            if is_stop_heading(el):
                break
            yield el


def extract_courses_from_tag(tag: Tag) -> List[Tuple[str, str]]:
    courses: List[Tuple[str, str]] = []

    def add_from_text(text: str) -> None:
        for subjects, num in CROSSLIST_RE.findall(text):
            for subj in subjects.split("/"):
                courses.append((subj.upper(), num.upper()))
        for subj, num in COURSE_RE.findall(text):
            courses.append((subj.upper(), num.upper()))

    for a in tag.find_all("a"):
        text = normalize_ws(a.get_text(" ", strip=True))
        add_from_text(text)
    if not courses:
        text = normalize_ws(tag.get_text(" ", strip=True))
        add_from_text(text)
    return courses


def extract_courses_from_row(tr: Tag) -> List[Tuple[str, str]]:
    courses: List[Tuple[str, str]] = []

    def add_from_text(text: str) -> None:
        for subjects, num in CROSSLIST_RE.findall(text):
            for subj in subjects.split("/"):
                courses.append((subj.upper(), num.upper()))
        for subj, num in COURSE_RE.findall(text):
            courses.append((subj.upper(), num.upper()))

    for a in tr.find_all("a"):
        text = normalize_ws(a.get_text(" ", strip=True))
        add_from_text(text)
    if not courses:
        text = normalize_ws(tr.get_text(" ", strip=True))
        add_from_text(text)
    return courses


def detect_select_count(text: str) -> Optional[int]:
    m = SELECT_RE.search(text or "")
    if not m:
        return None
    raw = m.group(2).lower()
    if raw.isdigit():
        return int(raw)
    return NUM_WORDS.get(raw)


def parse_program_requirements(
    soup: BeautifulSoup,
    rule_all: str,
    rule_any: str,
    rule_choose: str,
) -> Optional[List[Block]]:
    anchor = None
    for tag in soup.find_all(["h2", "h3", "h4"]):
        text = normalize_ws(tag.get_text(" ", strip=True)).lower()
        if text in REQ_HEADINGS or any(text.startswith(x) for x in REQ_HEADINGS):
            anchor = tag
            break
        if text.startswith("requirements for the") and "program" in text:
            anchor = tag
            break
    if not anchor:
        return None

    blocks: Dict[str, Block] = {}
    current_block_name = normalize_ws(anchor.get_text(" ", strip=True)) or "Program Requirements"
    current_text_parts: List[str] = []

    def ensure_block(name: str) -> Block:
        if name not in blocks:
            blocks[name] = Block(
                name=name, courses=[], rule=rule_all, manual_notes=[], option_groups=[]
            )
        return blocks[name]

    ensure_block(current_block_name)
    last_select_block: Optional[str] = None

    def is_section_header_row(tr: Tag) -> Optional[str]:
        cells = tr.find_all(["th", "td"])
        if len(cells) == 1:
            text = normalize_ws(cells[0].get_text(" ", strip=True))
        elif len(cells) == 2:
            left = normalize_ws(cells[0].get_text(" ", strip=True))
            right = normalize_ws(cells[1].get_text(" ", strip=True))
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
        if text.lower() in {"code title credits", "code title"}:
            return None
        if "subtotal" in text.lower() or text.lower().startswith("total "):
            return None
        if SELECT_RE.search(text):
            return None
        return text

    def parse_subtotal_credits(text: str) -> Optional[float]:
        if "subtotal" not in text.lower() and not text.lower().startswith("total "):
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

    for node in iter_section_nodes(anchor):
        if node.name in {"h3", "h4", "h5"}:
            current_block_name = normalize_ws(node.get_text(" ", strip=True))
            ensure_block(current_block_name)
            current_text_parts = []
            continue

        text = normalize_ws(node.get_text(" ", strip=True))
        if text:
            current_text_parts.append(text)

        is_table = node.name == "table" or "courselist" in " ".join(node.get("class", [])).lower()
        courses = extract_courses_from_tag(node)

        if is_table:
            current_table_block = current_block_name
            for tr in node.find_all("tr"):
                tr_classes = " ".join(tr.get("class", [])).lower()
                row_text = normalize_ws(tr.get_text(" ", strip=True))

                if "areaheader" in tr_classes or "areasubheader" in tr_classes:
                    header_name = row_text
                    if header_name:
                        current_table_block = header_name
                        ensure_block(current_table_block)
                        continue

                header_name = is_section_header_row(tr)
                if header_name:
                    current_table_block = header_name
                    ensure_block(current_table_block)
                    continue

                subtotal = parse_subtotal_credits(row_text)
                if subtotal is not None:
                    label = parse_subtotal_label(row_text)
                    block = ensure_block(label or current_table_block)
                    block.credits_required = subtotal
                    continue

                row_text = normalize_ws(tr.get_text(" ", strip=True))
                select_n = detect_select_count(row_text)
                if select_n:
                    block = ensure_block(current_table_block)
                    block.rule = rule_choose
                    block.n_required = select_n
                    last_select_block = current_table_block
                    continue

                row_courses = extract_courses_from_row(tr)
                if row_courses:
                    block = ensure_block(current_table_block)
                    for c in row_courses:
                        if c not in block.courses:
                            block.courses.append(c)
                    if block.rule == rule_choose:
                        block.option_groups.append(row_courses)
                else:
                    if MANUAL_REQUIREMENT_RE.search(row_text):
                        block = ensure_block(current_table_block)
                        block.manual_notes.append(row_text)
        elif courses:
            block = ensure_block(current_block_name)
            for c in courses:
                if c not in block.courses:
                    block.courses.append(c)

            scope_text = " ".join(current_text_parts)
            select_n = detect_select_count(scope_text)
            if select_n:
                block.rule = rule_choose
                block.n_required = select_n
                last_select_block = current_block_name
            elif "recommended" in scope_text.lower():
                block.rule = rule_any
        else:
            if MANUAL_REQUIREMENT_RE.search(text):
                block = ensure_block(current_block_name)
                block.manual_notes.append(text)

    out = [
        b
        for b in blocks.values()
        if b.courses or b.credits_required is not None or b.n_required is not None
    ]
    return out or None


def sql_escape_literal(s: str) -> str:
    return s.replace("'", "''")


def write_sql(programs: List[Program], out_path: str) -> None:
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("-- Generated by scrape_masters_programs.py\n")
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

    payload = {"program_id": program_id, "name": name, "rule": rule}
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
    if not row:
        cache[key] = None
        return None
    cid = int(row["id"])
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


def insert_programs(sb, programs: List[Program]) -> None:
    course_cache: Dict[Tuple[str, str], Optional[int]] = {}
    missing_courses: List[Tuple[str, str]] = []
    blocks_processed = 0
    courses_inserted = 0

    for p in programs:
        program_id = get_or_create_program(sb, p.name, p.catalog_year, p.program_type)
        for b in p.blocks:
            block_id = get_or_create_block(
                sb, program_id, b.name, b.rule, b.n_required, b.credits_required
            )
            blocks_processed += 1

            use_count = bool(b.n_required and b.n_required > 1)
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

    if missing_courses:
        uniq = sorted(set(missing_courses))
        print(f"Missing {len(uniq)} courses not found in courses table.")
        for subj, num in uniq[:50]:
            print(f"  - {subj} {num}")
        if len(uniq) > 50:
            print(f"  ... and {len(uniq) - 50} more")

    print(f"Blocks processed: {blocks_processed}")
    print(f"Block courses inserted: {courses_inserted}")


def reset_graduate_programs(sb, program_type: str) -> None:
    resp = (
        sb.table("programs")
        .select("id")
        .eq("program_type", program_type)
        .execute()
    )
    if getattr(resp, "error", None):
        raise RuntimeError(f"fetch graduate programs: {resp.error}")
    program_ids = [row["id"] for row in (resp.data or [])]
    if not program_ids:
        return

    # Delete in dependency order
    resp = (
        sb.table("program_requirement_blocks")
        .select("id")
        .in_("program_id", program_ids)
        .execute()
    )
    if getattr(resp, "error", None):
        raise RuntimeError(f"fetch graduate blocks: {resp.error}")
    block_ids = [row["id"] for row in (resp.data or [])]

    if block_ids:
        del_courses = sb.table("program_requirement_courses").delete().in_("block_id", block_ids).execute()
        if getattr(del_courses, "error", None):
            raise RuntimeError(f"delete graduate program_requirement_courses: {del_courses.error}")

        del_blocks = sb.table("program_requirement_blocks").delete().in_("id", block_ids).execute()
        if getattr(del_blocks, "error", None):
            raise RuntimeError(f"delete graduate program_requirement_blocks: {del_blocks.error}")

    del_programs = sb.table("programs").delete().in_("id", program_ids).execute()
    if getattr(del_programs, "error", None):
        raise RuntimeError(f"delete graduate programs: {del_programs.error}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--programs-url",
        default="https://www.uwp.edu/learn/programs/",
        help="Programs index URL.",
    )
    ap.add_argument(
        "--catalog-year",
        default=None,
        help="Catalog year to use (e.g., 2025-2026). If omitted, attempts to parse from page.",
    )
    ap.add_argument("--sleep", type=float, default=0.0, help="Delay between requests (seconds).")
    ap.add_argument("--limit", type=int, default=0, help="Limit number of programs for testing.")
    ap.add_argument("--out-json", default="masters_program_requirements.json", help="Output JSON file.")
    ap.add_argument("--out-sql", default=None, help="Optional output SQL file.")
    ap.add_argument("--out-report", default="masters_program_requirements_report.json", help="Report JSON file.")
    ap.add_argument("--insert-db", action="store_true", help="Insert results into the database.")
    ap.add_argument(
        "--reset-graduate",
        action="store_true",
        help="If set, deletes existing programs with program_type=GRADUATE before insert.",
    )
    ap.add_argument("--rule-all", default="ALL_OF", help="Enum value for an ALL/required block.")
    ap.add_argument("--rule-any", default="ANY_OF", help="Enum value for a recommended/any block.")
    ap.add_argument("--rule-choose", default="N_OF", help="Enum value for a choose-N block.")
    ap.add_argument("--program-type", default="GRADUATE", help="programs.program_type value to use.")
    args = ap.parse_args()

    index_html = fetch_html(args.programs_url)
    program_links = discover_graduate_program_links(args.programs_url, index_html)

    if args.limit and args.limit > 0:
        program_links = program_links[: args.limit]

    programs: List[Program] = []
    skipped: List[str] = []

    for title, program_url in program_links:
        try:
            html = fetch_html(program_url)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                continue
            raise
        if args.sleep > 0:
            time.sleep(args.sleep)

        catalog_url = find_program_overview_link(html, program_url)
        if not catalog_url:
            skipped.append(f"{title} | missing program overview link")
            continue

        catalog_html = fetch_html(catalog_url)
        if args.sleep > 0:
            time.sleep(args.sleep)

        soup = BeautifulSoup(catalog_html, "html.parser")
        program_name = parse_program_title(soup) or title
        catalog_year = args.catalog_year or parse_catalog_year(soup)
        if not catalog_year:
            skipped.append(f"{program_name} | missing catalog year")
            continue

        blocks = parse_program_requirements(
            soup, rule_all=args.rule_all, rule_any=args.rule_any, rule_choose=args.rule_choose
        )
        if not blocks:
            skipped.append(f"{program_name} | no requirements blocks found")
            continue

        programs.append(
            Program(
                name=program_name,
                catalog_year=catalog_year,
                url=catalog_url,
                program_type=args.program_type,
                blocks=blocks,
            )
        )

    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump([asdict(p) for p in programs], f, indent=2)

    print(f"Wrote {len(programs)} programs -> {args.out_json}")
    if skipped:
        with open("masters_programs_skipped.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(skipped))
        print(f"Wrote {len(skipped)} skipped programs -> masters_programs_skipped.txt")

    if args.out_sql:
        write_sql(programs, args.out_sql)
        print(f"Wrote SQL -> {args.out_sql}")

    report = {
        "programs": len(programs),
        "blocks_total": sum(len(p.blocks) for p in programs),
        "blocks_empty_courses": [
            {"program": p.name, "catalog_year": p.catalog_year, "block": b.name}
            for p in programs
            for b in p.blocks
            if not b.courses
        ],
        "manual_requirements": [
            {"program": p.name, "catalog_year": p.catalog_year, "block": b.name, "note": n}
            for p in programs
            for b in p.blocks
            for n in (b.manual_notes or [])
        ],
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

    if args.insert_db:
        sb = get_connection()
        if args.reset_graduate:
            reset_graduate_programs(sb, args.program_type)
        insert_programs(sb, programs)


if __name__ == "__main__":
    main()
