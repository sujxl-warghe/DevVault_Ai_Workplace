"""Optional file upload to the "hackathon-templates" Supabase Storage
bucket (see supabase/migrations/0013_hackathon_template_storage.sql).

Entirely optional: the hackathon form's Template/Photo field always
accepts a plain URL. If the bucket doesn't exist (migration not run) or
the upload fails for any reason, this fails soft — callers catch the
exception and fall back to URL-only entry rather than blocking the form.
"""
from __future__ import annotations

import time
import uuid

from supabase import Client

BUCKET_NAME = "hackathon-templates"


def upload_template_photo(client: Client, file_bytes: bytes, filename: str) -> str:
    """Uploads bytes to the bucket and returns a public URL. Raises on any
    failure (missing bucket, RLS denial, network error) — callers must
    catch and fall back to URL entry."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    safe_ext = ext if ext.isalnum() and len(ext) <= 5 else "jpg"
    object_path = f"{int(time.time())}-{uuid.uuid4().hex[:8]}.{safe_ext}"

    client.storage.from_(BUCKET_NAME).upload(object_path, file_bytes)
    return client.storage.from_(BUCKET_NAME).get_public_url(object_path)


def storage_available(client: Client) -> bool:
    try:
        client.storage.from_(BUCKET_NAME).list(path="", options={"limit": 1})
        return True
    except Exception:
        return False
