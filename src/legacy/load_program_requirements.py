#!/usr/bin/env python3
"""
LEGACY: Load program_requirements.json into Supabase tables:
  - programs
  - program_requirement_blocks
  - program_requirement_courses

This is archived because it does not populate the current program requirement
tree tables or manual flag metadata used by the current scrapers.

Usage:
  python src/load_program_requirements.py --file program_requirements.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from connection import get_connection


def sb_one(resp, context: str):
    if getattr(resp, "error", None):
        raise RuntimeError(f"{context}: {resp.error}")
    data = resp.data
    if not data:
        return None
    return data[0]


def get_or_create_program(sb, name: str, catalog_year: str) -> int:
    resp = (
        sb.table("programs")
        .select("id")
        .eq("name", name)
        .eq("catalog_year", catalog_year)
        .limit(1)
        .execute()
    )
    row = sb_one(resp, f"select program {name} {catalog_year}")
    if row:
        return int(row["id"])

    resp2 = (
        sb.table("programs")
        .insert({"name": name, "catalog_year": catalog_year})
        .execute()
    )
    row2 = sb_one(resp2, f"insert program {name} {catalog_year}")
    return int(row2["id"])


def get_or_create_block(
    sb, program_id: int, name: str, rule: str, n_required: Optional[int], credits_required: Optional[float], note: Optional[str]
) -> int:
    resp = (
        sb.table("program_requirement_blocks")
        .select("id")
        .eq("program_id", program_id)
        .eq("name", name)
        .limit(1)
        .execute()
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
    # Avoid sending note unless you confirm the column exists in Supabase schema cache
    if note:
        payload["note"] = note
    resp2 = sb.table("program_requirement_blocks").insert(payload).execute()
    row2 = sb_one(resp2, f"insert block {program_id} {name}")
    return int(row2["id"])


def get_course_id(sb, subject: str, number: str, cache: Dict[Tuple[str, str], int]) -> Optional[int]:
    key = (subject, number)
    if key in cache:
        return cache[key]
    resp = (
        sb.table("courses")
        .select("id")
        .eq("subject", subject)
        .eq("number", number)
        .limit(1)
        .execute()
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
    resp = (
        sb.table("program_requirement_courses")
        .upsert(payload, on_conflict="block_id,course_id")
        .execute()
    )
    if getattr(resp, "error", None):
        raise RuntimeError(f"insert block_course {block_id} {course_id}: {resp.error}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="Path to program_requirements.json")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        raise SystemExit(f"JSON file not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit("Expected a JSON list at top level.")

    sb = get_connection()

    course_cache: Dict[Tuple[str, str], Optional[int]] = {}
    inserted_blocks = 0
    inserted_courses = 0
    missing_courses: List[Tuple[str, str]] = []

    for prog in data:
        name = (prog.get("name") or "").strip()
        catalog_year = (prog.get("catalog_year") or "").strip()
        blocks = prog.get("blocks") or []
        if not name or not catalog_year:
            continue

        program_id = get_or_create_program(sb, name, catalog_year)

        for block in blocks:
            bname = (block.get("name") or "Requirements").strip()
            rule = (block.get("rule") or "ALL").strip()
            n_required = block.get("n_required")
            credits_required = block.get("credits_required")
            note = block.get("note")

            block_id = get_or_create_block(
                sb, program_id, bname, rule, n_required, credits_required, note
            )
            inserted_blocks += 1

            courses = block.get("courses") or []
            for subj, num in courses:
                subj = (subj or "").strip().upper()
                num = (num or "").strip().upper()
                if not subj or not num:
                    continue
                course_id = get_course_id(sb, subj, num, course_cache)
                if course_id is None:
                    missing_courses.append((subj, num))
                    continue
                insert_block_course(sb, block_id, course_id)
                inserted_courses += 1

    if missing_courses:
        uniq = sorted(set(missing_courses))
        print(f"Missing {len(uniq)} courses not found in courses table.")
        for subj, num in uniq[:50]:
            print(f"  - {subj} {num}")
        if len(uniq) > 50:
            print(f"  ... and {len(uniq) - 50} more")

    print(f"Blocks processed: {inserted_blocks}")
    print(f"Block courses inserted: {inserted_courses}")


if __name__ == "__main__":
    main()
