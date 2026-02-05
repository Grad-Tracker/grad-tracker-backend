import os
import pathlib
import sys

import pytest
from dotenv import load_dotenv

# Ensure project root and src are on the import path
ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from connection import get_connection  # noqa: E402


@pytest.mark.integration
def test_supabase_users_table_access():
    """Verify we can query the `users` table."""

    # Load env vars from .env (if present) before checking
    load_dotenv(ROOT / ".env")

    if not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_KEY"):
        pytest.skip("SUPABASE_URL/SUPABASE_KEY not set in environment")

    client = get_connection()
    response = client.table("users").select("*").limit(1).execute()

    # supabase-py v2+ returns APIResponse without an `error` attr on success
    assert isinstance(response.data, list)
