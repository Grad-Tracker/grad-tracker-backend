#!/usr/bin/env python3
"""
Data quality validator for Grad Tracker.

Usage:
  python scripts/validate_data.py --max-empty-blocks 200 --max-missing-course-refs 0 --max-nof-missing-n 0

Requires:
  DATABASE_URL in environment (Postgres connection string).
"""

from __future__ import annotations

import argparse
import os
import sys

import psycopg2


def fetch_one(cur, query: str):
    cur.execute(query)
    row = cur.fetchone()
    return row[0] if row else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-empty-blocks", type=int, default=200)
    ap.add_argument("--max-missing-course-refs", type=int, default=0)
    ap.add_argument("--max-nof-missing-n", type=int, default=0)
    ap.add_argument("--max-orphans", type=int, default=0)
    args = ap.parse_args()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("ERROR: DATABASE_URL is not set.")
        return 2

    failures = []
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            empty_blocks = fetch_one(
                cur,
                """
                select count(*)
                from (
                  select b.id
                  from public.program_requirement_blocks b
                  left join public.program_requirement_courses prc on prc.block_id = b.id
                  group by b.id
                  having count(prc.course_id) = 0
                ) t
                """,
            )
            missing_course_refs = fetch_one(
                cur,
                """
                select count(*)
                from public.program_requirement_courses prc
                left join public.courses c on c.id = prc.course_id
                where c.id is null
                """,
            )
            n_of_missing_n = fetch_one(
                cur,
                """
                select count(*)
                from public.program_requirement_blocks
                where rule = 'N_OF' and n_required is null
                """,
            )
            orphan_block_courses = fetch_one(
                cur,
                """
                select count(*)
                from public.program_requirement_courses prc
                left join public.program_requirement_blocks b on b.id = prc.block_id
                where b.id is null
                """,
            )
            orphan_req_nodes = fetch_one(
                cur,
                """
                select count(*)
                from public.program_req_nodes n
                left join public.program_req_sets s on s.id = n.req_set_id
                where s.id is null
                """,
            )
            orphan_req_atoms = fetch_one(
                cur,
                """
                select count(*)
                from public.program_req_atoms a
                left join public.program_req_nodes n on n.id = a.node_id
                where n.id is null
                """,
            )

    total_orphans = orphan_block_courses + orphan_req_nodes + orphan_req_atoms

    if empty_blocks > args.max_empty_blocks:
        failures.append(
            f"empty_blocks={empty_blocks} exceeds max_empty_blocks={args.max_empty_blocks}"
        )
    if missing_course_refs > args.max_missing_course_refs:
        failures.append(
            "missing_course_refs="
            f"{missing_course_refs} exceeds max_missing_course_refs={args.max_missing_course_refs}"
        )
    if n_of_missing_n > args.max_nof_missing_n:
        failures.append(
            f"n_of_missing_n={n_of_missing_n} exceeds max_nof_missing_n={args.max_nof_missing_n}"
        )
    if total_orphans > args.max_orphans:
        failures.append(
            f"orphans={total_orphans} exceeds max_orphans={args.max_orphans}"
        )

    print("Validation metrics:")
    print(f"  empty_blocks={empty_blocks}")
    print(f"  missing_course_refs={missing_course_refs}")
    print(f"  n_of_missing_n={n_of_missing_n}")
    print(f"  orphans={total_orphans}")

    if failures:
        print("Validation failed:")
        for line in failures:
            print(f"  - {line}")
        return 1

    print("Validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
