from __future__ import annotations

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
