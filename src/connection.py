import os
from dotenv import load_dotenv
from supabase import Client, create_client


def get_connection() -> Client:
    """Create and return a Supabase client using env vars.

    Expects SUPABASE_URL and SUPABASE_KEY to be set (e.g., via .env).
    """

    load_dotenv()  # pulls values from .env into the environment

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")

    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in the environment")

    return create_client(url, key)


def test_connection() -> dict:
    """Simple connectivity check against the `users` table.

    Returns the first row (if any) from `users`. Raises RuntimeError on failure.
    """

    client = get_connection()

    response = client.table("users").select("*").limit(1).execute()

    # supabase-py returns a PostgrestResponse with `error` and `data` attributes
    if getattr(response, "error", None):
        raise RuntimeError(f"Supabase query failed: {response.error}")

    return getattr(response, "data", {})
