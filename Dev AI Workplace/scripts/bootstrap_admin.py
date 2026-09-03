"""One-time bootstrap: create the initial DevVault admin account.

Run this ONCE, locally, after running the database migrations, before
anyone signs into the app. It creates the Supabase Auth user + matching
`profiles` row for the first administrator (username "sujal", role
"admin"), using the same secure Auth Admin API path the in-app "Create
User" feature uses later — nothing here bypasses password hashing or
inserts a plaintext password anywhere.

No password is ever hardcoded in this file or committed to source control:
the password is entered interactively via getpass() (hidden input, not
echoed to the terminal, not saved to shell history).

Usage:
    cd streamlit_app
    SUPABASE_URL=https://your-project.supabase.co \
    SUPABASE_SERVICE_ROLE_KEY=your-service-role-key \
    python scripts/bootstrap_admin.py

You will be prompted for the admin's username (default: sujal) and
password. The service-role key is only used for this one script run and is
read from the environment, exactly like the app itself expects at deploy
time — never pasted into this file.
"""
from __future__ import annotations

import getpass
import os
import sys

# Allow running this script directly from the streamlit_app/ directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.admin_service import UsernameTakenError, create_user  # noqa: E402
from services.auth_service import InvalidUsernameError  # noqa: E402
from services.config import Settings  # noqa: E402


def main() -> None:
    supabase_url = os.environ.get("SUPABASE_URL")
    service_role_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

    if not supabase_url or not service_role_key:
        print(
            "ERROR: set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY as environment "
            "variables before running this script (see the docstring at the top of "
            "this file for an example)."
        )
        sys.exit(1)

    settings = Settings(
        supabase_url=supabase_url,
        supabase_anon_key="",  # not needed for this script
        supabase_service_role_key=service_role_key,
        gemini_api_key=None,
        gemini_model="",
    )

    print("DevVault — initial admin bootstrap")
    print("-----------------------------------")
    username = input("Admin username [sujal]: ").strip() or "sujal"
    password = getpass.getpass("Admin password: ")
    confirm = getpass.getpass("Confirm password: ")

    if password != confirm:
        print("ERROR: passwords do not match.")
        sys.exit(1)
    if len(password) < 8:
        print("ERROR: password must be at least 8 characters.")
        sys.exit(1)

    try:
        result = create_user(settings, username, password, role="admin")
    except InvalidUsernameError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)
    except UsernameTakenError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    print()
    print(f"✓ Admin account '{result.username}' created successfully.")
    print("You can now sign in to the DevVault app with this username and password.")


if __name__ == "__main__":
    main()
