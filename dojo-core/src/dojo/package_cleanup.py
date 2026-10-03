"""Identify package-owned audit records without touching installation settings."""
from __future__ import annotations


def owns_record(
    details: dict, folder: str, upload_ids: set[str], job_ids: set[str],
    media_ids: set[str], review_ids: set[int],
) -> bool:
    return (
        any(details.get(key) == folder for key in ("package", "package_folder", "folder_name"))
        or details.get("upload_id") in upload_ids
        or details.get("job_id") in job_ids
        or details.get("media_id") in media_ids
        or details.get("review_id") in review_ids
    )
