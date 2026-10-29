"""Add one clearly labelled local archive; never publish or modify the active package.

From the repo root (with the local environment loaded):
    uv run --project backend python backend/scripts/seed_completed_package.py

Requires local PostgreSQL, an initialized schema, and ffmpeg on PATH. Re-runs
leave an existing demo untouched. DATABASE_URL must point to loopback, not db/prod.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from dojo.adapters.db import PostgresStore
from dojo.model import Package
from sqlalchemy.engine import make_url

FOLDER = "29-10-2026 00-00-demo-completed"


def require_local_database(value: str) -> str:
    url = make_url(value)
    if (url.get_backend_name() != "postgresql"
            or url.host not in ("localhost", "127.0.0.1", "::1") or url.query
            or any(os.environ.get(name) for name in ("PGHOSTADDR", "PGSERVICE"))):
        raise ValueError("Test data requires loopback PostgreSQL; remote databases are refused.")
    return value


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", *args],
                   check=True, timeout=120)


def seed_completed_package(store, media_root: Path) -> tuple[Package, bool]:
    media_root = media_root.resolve()
    media_root.mkdir(parents=True, exist_ok=True)
    with store.package_lock() as acquired:
        if not acquired:
            raise RuntimeError("Another package operation is running; try again later.")
        existing = store.get_by_folder(FOLDER)
        if existing:
            return existing, False
        destination = media_root / FOLDER
        if destination.exists():
            raise FileExistsError(f"Refusing to overwrite existing directory: {destination}")
        now = datetime.now(UTC)
        with TemporaryDirectory(prefix="completed-demo-", dir=media_root) as temporary:
            root = Path(temporary)
            photo, video = root / "media/demo-photo", root / "media/demo-video"
            photo.mkdir(parents=True)
            video.mkdir(parents=True)
            ffmpeg("-f", "lavfi", "-i", "testsrc2=size=360x640:rate=25", "-frames:v", "1",
                   str(photo / "original.jpg"))
            shutil.copyfile(photo / "original.jpg", photo / "processed.jpg")
            ffmpeg("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25", "-t", "3",
                   "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video / "original.mp4"))
            ffmpeg("-i", str(video / "original.mp4"), "-vf",
                   "scale=360:640:force_original_aspect_ratio=decrease,pad=360:640:(ow-iw)/2:(oh-ih)/2",
                   "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                   str(video / "processed.mp4"))
            generation = "d" * 32
            thumbnail_ref = f"media/demo-video/previews/{generation}.jpg"
            (video / "previews").mkdir()
            ffmpeg("-i", str(video / "processed.mp4"), "-frames:v", "1",
                   str(root / thumbnail_ref))
            (root / "render").mkdir()
            ffmpeg("-loop", "1", "-t", "2.95", "-i", str(photo / "processed.jpg"),
                   "-i", str(video / "processed.mp4"), "-filter_complex",
                   "[0:v]fps=25,setsar=1[a];[1:v]setsar=1[b];[a][b]concat=n=2:v=1:a=0[out]",
                   "-map", "[out]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                   "-movflags", "+faststart", str(root / "render/reel.mp4"))
            media = []
            for mid, filename, mime, suffix, duration in (
                ("demo-photo", "profile.jpg", "image/jpeg", ".jpg", None),
                ("demo-video", "training.mp4", "video/mp4", ".mp4", 3.0),
            ):
                processed = root / f"media/{mid}/processed{suffix}"
                media.append({
                    "media_id": mid, "filename": filename, "content_type": mime,
                    "size_bytes": (root / f"media/{mid}/original{suffix}").stat().st_size,
                    "uploaded_at": now.isoformat(), "status": "finalized",
                    **({"photo_duration_seconds": 2.95} if duration is None else {}),
                    "processed": {"path": f"media/{mid}/processed{suffix}", "content_type": mime,
                                  "size_bytes": processed.stat().st_size,
                                  "dimensions": [360, 640], "duration": duration},
                })
            manifest = {
                "demo_fixture": True, "media": media, "order": [m["media_id"] for m in media],
                "selections": {}, "caption": "TEST VERİSİ — Instagram'da yayınlanmadı.",
                "render_revision": "local-demo", "render_duration": 5.96,
                "thumbnails": {"demo-video": {"status": "ready", "generation": generation,
                                             "artifact_ref": thumbnail_ref}},
            }
            (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                                 encoding="utf-8")
            with store.command_transaction():
                package = store.create(Package(0, FOLDER, now, status="completed"))
                store.write_package_state(package.id, manifest, content_changed=True)
                root.rename(destination)
                store.queue_change(["completed"])
    return package, True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"),
                        required=not os.environ.get("DATABASE_URL"))
    parser.add_argument("--media-root", type=Path,
                        default=Path(os.environ.get("MEDIA_ROOT", "media")))
    args = parser.parse_args()
    database = require_local_database(args.database_url)
    result, created = seed_completed_package(PostgresStore(database), args.media_root)
    print(f"{'Created' if created else 'Already exists, unchanged'}: {result.folder_name}")
    print(f"Media root: {args.media_root.resolve()}")
