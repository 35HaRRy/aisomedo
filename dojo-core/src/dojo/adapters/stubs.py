from __future__ import annotations

import shutil
from pathlib import Path


class StubReelRenderer:
    def __init__(self, *, fail_reason: str | None = None) -> None:
        self.calls: list[tuple[object, Path]] = []
        self.fail_reason = fail_reason

    def render(self, build: object, work_dir: Path, out_path: Path) -> Path:
        from dojo.exceptions import RenderFailed

        self.calls.append((build, out_path))
        if self.fail_reason is not None:
            raise RenderFailed(self.fail_reason)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"fake-reel")
        return out_path


class StubMetaPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.created: list[tuple[str, str, str]] = []
        self.status_queues: dict[str, list[str]] = {}
        self.statuses: dict[str, str] = {}
        self.publish_results: dict[str, str] = {}
        self.fail_create: Exception | None = None
        self.fail_publish: Exception | None = None
        self.publish_calls: list[str] = []
        self._next_container = 1

    def publish_reel(self, signed_url: str, caption: str) -> None:
        self.calls.append((signed_url, caption))

    def create_container(self, signed_url: str, caption: str) -> str:
        if self.fail_create is not None:
            exc = self.fail_create
            self.fail_create = None
            raise exc
        container_id = f"container_{self._next_container}"
        self._next_container += 1
        self.created.append((signed_url, caption, container_id))
        self.calls.append((signed_url, caption))
        return container_id

    def get_container_status(self, container_id: str) -> str:
        queue = self.status_queues.get(container_id)
        if queue:
            return queue.pop(0)
        return self.statuses.get(container_id, "FINISHED")

    def publish_container(self, container_id: str) -> str:
        self.publish_calls.append(container_id)
        if self.fail_publish is not None:
            exc = self.fail_publish
            self.fail_publish = None
            raise exc
        return self.publish_results.get(container_id, f"media_{container_id}")


class StubNotifier:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.sent: list[tuple[object, list[str]]] = []
        self.fail_next: Exception | None = None
        self.invalid_tokens: set[str] = set()
        self.transient_tokens: set[str] = set()

    def notify(self, title: str, body: str) -> None:
        self.messages.append((title, body))

    def send(self, notification: object, tokens: list[str]) -> object:
        from dojo.model import NotificationResult

        if self.fail_next is not None:
            exc = self.fail_next
            self.fail_next = None
            raise exc
        self.sent.append((notification, list(tokens)))
        delivered = [
            t for t in tokens if t not in self.invalid_tokens and t not in self.transient_tokens
        ]
        invalid = [t for t in tokens if t in self.invalid_tokens]
        transient = [t for t in tokens if t in self.transient_tokens]
        return NotificationResult(
            delivered=delivered, invalid_tokens=invalid, transient_failures=transient
        )


class StubSignedUrlStore:
    def __init__(self) -> None:
        self.active: list[str] = []
        self.paths: dict[str, Path] = {}
        self.created_paths: list[Path] = []
        self.revoked: list[str] = []
        self._next = 1

    def create(self, artifact_path: Path) -> str:
        url = f"https://signed.local/{self._next}/{artifact_path.name}"
        self._next += 1
        self.active.append(url)
        self.paths[url] = Path(artifact_path)
        self.created_paths.append(Path(artifact_path))
        return url

    def revoke(self, url: str) -> None:
        self.revoked.append(url)
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
