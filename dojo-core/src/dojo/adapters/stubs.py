from __future__ import annotations

import shutil
from pathlib import Path


class StubMetaPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def publish_reel(self, signed_url: str, caption: str) -> None:
        self.calls.append((signed_url, caption))


class StubNotifier:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def notify(self, title: str, body: str) -> None:
        self.messages.append((title, body))


class StubSignedUrlStore:
    def __init__(self) -> None:
        self.active: list[str] = []

    def create(self, artifact_path: Path) -> str:
        url = f"https://signed.local/{artifact_path.name}"
        self.active.append(url)
        return url

    def revoke(self, url: str) -> None:
        if url in self.active:
            self.active.remove(url)


class StubMediaProcessor:
    def __init__(
        self,
        *,
        content_type: str = "image/jpeg",
        fail_reason: str | None = None,
        duration: float | None = None,
    ) -> None:
        self.calls: list[tuple[object, Path]] = []
        self.content_type = content_type
        self.fail_reason = fail_reason
        self.duration = duration

    def process(self, upload: object, original_path: Path, work_dir: Path) -> object:
        from dojo.model import ProcessedMedia

        self.calls.append((upload, original_path))
        if self.fail_reason is not None:
            from dojo.exceptions import MediaValidationError

            raise MediaValidationError(self.fail_reason)
        processed = work_dir / "processed.jpg"
        shutil.copyfile(original_path, processed)
        return ProcessedMedia(
            original_path=original_path,
            processed_path=processed,
            content_type=self.content_type,
            size_bytes=processed.stat().st_size,
            dimensions=(100, 100),
            duration=self.duration,
        )
