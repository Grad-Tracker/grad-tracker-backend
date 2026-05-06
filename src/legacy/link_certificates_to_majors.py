#!/usr/bin/env python3
"""
LEGACY: Link certificates to majors based on course overlap.

This is archived because it writes to the older `program_major_links` table.
The current schema uses `major_certificate_mappings`.

Rule:
  - Compute overlap count between each certificate and major by course_id.
  - Choose the major with the highest overlap count.
  - Require overlap_ratio > 0.50 (overlap_count / certificate_course_count).
  - If tie on overlap_count, leave unmatched.

Writes to public.program_major_links.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from connection import get_connection


def collect_program_courses(sb, program_type: str) -> Dict[int, Set[int]]:
    """
    Return {program_id: set(course_id)} for the given program_type.
    """
    resp = (
        sb.table("programs")
        .select(
            "id,program_requirement_blocks("
            "program_requirement_courses(course_id)"
            ")"
        )
        .eq("program_type", program_type)
        .execute()
    )
    if getattr(resp, "error", None):
        raise RuntimeError(resp.error)

    out: Dict[int, Set[int]] = {}
    for p in resp.data:
        course_ids: Set[int] = set()
        for b in p.get("program_requirement_blocks", []):
            for r in b.get("program_requirement_courses") or []:
                cid = r.get("course_id")
                if cid is not None:
                    course_ids.add(cid)
        out[p["id"]] = course_ids
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.50, help="Minimum overlap ratio (> threshold).")
    ap.add_argument("--dry-run", action="store_true", help="Compute links but do not write.")
    args = ap.parse_args()

    sb = get_connection()

    majors = collect_program_courses(sb, "MAJOR")
    certs = collect_program_courses(sb, "CERTIFICATE")

    # Precompute major list for overlap checks
    major_items = list(majors.items())

    rows = []
    for cert_id, cert_courses in certs.items():
        cert_total = len(cert_courses)
        if cert_total == 0:
            continue

        # Find best major by overlap count
        best_major_id = None
        best_overlap = 0
        tied = False

        for major_id, major_courses in major_items:
            overlap = len(cert_courses & major_courses)
            if overlap > best_overlap:
                best_overlap = overlap
                best_major_id = major_id
                tied = False
            elif overlap == best_overlap and overlap > 0:
                # tie on overlap count
                tied = True

        overlap_ratio = (best_overlap / cert_total) if cert_total else 0.0

        if best_major_id is None or tied:
            # leave unmatched
            rows.append(
                {
                    "certificate_program_id": cert_id,
                    "major_program_id": None,
                    "overlap_count": best_overlap,
                    "cert_course_count": cert_total,
                    "overlap_ratio": overlap_ratio,
                    "method": "OVERLAP_RATIO",
                    "tied": True if tied else False,
                }
            )
            continue

        if overlap_ratio <= args.threshold:
            # threshold not met; leave unmatched
            rows.append(
                {
                    "certificate_program_id": cert_id,
                    "major_program_id": None,
                    "overlap_count": best_overlap,
                    "cert_course_count": cert_total,
                    "overlap_ratio": overlap_ratio,
                    "method": "OVERLAP_RATIO",
                    "tied": False,
                }
            )
            continue

        rows.append(
            {
                "certificate_program_id": cert_id,
                "major_program_id": best_major_id,
                "overlap_count": best_overlap,
                "cert_course_count": cert_total,
                "overlap_ratio": overlap_ratio,
                "method": "OVERLAP_RATIO",
                "tied": False,
            }
        )

    if args.dry_run:
        print(f"Computed {len(rows)} link rows (dry run).")
        return

    # Clear existing links
    resp = sb.table("program_major_links").delete().gt("certificate_program_id", 0).execute()
    if getattr(resp, "error", None):
        raise RuntimeError(resp.error)

    # Insert in batches
    batch_size = 500
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        resp = sb.table("program_major_links").insert(batch).execute()
        if getattr(resp, "error", None):
            raise RuntimeError(resp.error)

    print(f"Inserted {len(rows)} program_major_links rows.")


if __name__ == "__main__":
    main()

