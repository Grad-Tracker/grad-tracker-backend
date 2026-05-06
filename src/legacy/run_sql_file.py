#!/usr/bin/env python3
"""
LEGACY: Run a SQL file through a Supabase RPC function.

This is archived because the current database handoff workflow uses direct
Postgres tools instead of relying on an exposed SQL RPC.

Uses one of these env vars for the connection string:
  - DATABASE_URL
  - SUPABASE_DB_URL
  - POSTGRES_URL

Example:
  python src/run_sql_file.py --file program_requirements.sql
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from connection import get_connection


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="Path to SQL file to execute.")
    ap.add_argument(
        "--rpc-fn",
        default="exec_sql",
        help="RPC function name for SQL execution.",
    )
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        raise SystemExit(f"SQL file not found: {path}")

    sql = path.read_text(encoding="utf-8")
    if not sql.strip():
        raise SystemExit("SQL file is empty.")

    sb = get_connection()
    resp = sb.rpc(args.rpc_fn, {"sql": sql}).execute()
    if getattr(resp, "error", None):
        raise RuntimeError(f"RPC {args.rpc_fn} failed: {resp.error}")

    print(f"Executed SQL file: {path}")


if __name__ == "__main__":
    main()
