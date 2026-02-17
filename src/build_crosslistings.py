#!/usr/bin/env python3
from __future__ import annotations

import re
from typing import Iterable, List, Optional, Set, Tuple

from connection import get_connection


COURSE_REF_RE = re.compile(r"\b([A-Z]{2,10})\s*([0-9]{1,4}[A-Z]?)\b")
CROSSLIST_RE = re.compile(r"cross-listed\s+with\s*:\s*", re.IGNORECASE)


def normalize_text(s: str) -> str:
    s = (s or "").replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def extract_crosslisted_refs(description: str) -> List[Tuple[str, str]]:
    """
    Returns list of (SUBJECT, NUMBER) parsed from the first "Cross-listed with:"
    segment in the description. If none, returns [].
    """
    text = normalize_text(description)
    m = CROSSLIST_RE.search(text)
    if not m:
        return []

    segment = text[m.end():]
    # Trim to end of sentence when possible
    dot = segment.find(".")
    if dot != -1:
        segment = segment[:dot]

    refs: List[Tuple[str, str]] = []
    for subj, num in COURSE_REF_RE.findall(segment):
        refs.append((subj.upper(), num.upper()))

    # De-dup while preserving order
    seen: Set[Tuple[str, str]] = set()
    out: List[Tuple[str, str]] = []
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            out.append(ref)
    return out


def sb_one(resp, context: str):
    if getattr(resp, "error", None):
        raise RuntimeError(f"{context}: {resp.error}")
    data = resp.data
    if not data:
        return None
    return data[0]


def ensure_course_id(sb, subject: str, number: str) -> int:
    resp = (
        sb.table("courses")
        .select("id")
        .eq("subject", subject)
        .eq("number", number)
        .limit(1)
        .execute()
    )
    row = sb_one(resp, f"select course {subject} {number}")
    if row:
        return int(row["id"])

    stub = {
        "subject": subject,
        "number": number,
        "title": f"{subject} {number} (stub)",
        "credits": 0,
        "description": "Placeholder created from cross-listed reference.",
        "prereq_text": None,
    }
    resp2 = (
        sb.table("courses")
        .upsert(stub, on_conflict="subject,number")
        .execute()
    )
    row2 = sb_one(resp2, f"upsert stub course {subject} {number}")
    return int(row2["id"])


def insert_crosslisting(
    sb,
    course_id: int,
    cross_subject: str,
    cross_number: str,
    note: Optional[str] = None,
) -> None:
    payload = {
        "course_id": course_id,
        "cross_subject": cross_subject,
        "cross_number": cross_number,
        "note": (note[:500] if note else None),
    }
    resp = (
        sb.table("course_crosslistings")
        .upsert(payload, on_conflict="course_id,cross_subject,cross_number")
        .execute()
    )
    if getattr(resp, "error", None):
        raise RuntimeError(
            f"insert crosslisting {course_id}->{cross_subject} {cross_number}: {resp.error}"
        )


def iter_crosslisting_pairs(
    sb,
    rows: Iterable[dict],
) -> Iterable[Tuple[int, int]]:
    for r in rows:
        course_id = int(r["id"])
        subject = (r.get("subject") or "").strip().upper()
        number = (r.get("number") or "").strip().upper()
        description = r.get("description") or ""

        refs = extract_crosslisted_refs(description)
        if not refs:
            continue

        for subj, num in refs:
            if subj == subject and num == number:
                continue
            yield (course_id, subj, num)


def main() -> None:
    sb = get_connection()

    resp = (
        sb.table("courses")
        .select("id, subject, number, description")
        .ilike("description", "%cross-listed with:%")
        .execute()
    )
    if getattr(resp, "error", None):
        raise RuntimeError(f"fetch courses: {resp.error}")

    rows = resp.data or []
    inserted = 0

    for course_id, subj, num in iter_crosslisting_pairs(sb, rows):
        insert_crosslisting(sb, course_id, subj, num)
        inserted += 1

    print(f"Inserted/updated {inserted} cross-listing rows.")


if __name__ == "__main__":
    main()
