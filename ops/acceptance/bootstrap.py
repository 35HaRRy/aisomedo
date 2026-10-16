"""Acceptance-only composition. Production images never import this module."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from dojo import DojoActivity, DojoMetaConnection, DojoPairing, DojoPublishing, DojoSetup
from dojo.adapters.db import PostgresStore
from dojo.adapters.meta import FernetCipher, HttpMetaPublisher, StubMetaOAuthProvider
from dojo.adapters.signed_urls import HmacSignedUrlStore
from dojo.model import MetaCandidate, Notification, NotificationResult

if TYPE_CHECKING:
    from fastapi import FastAPI

ORIGIN = "https://dojo.acceptance.test"


def fixture_http() -> httpx.Client:
    return httpx.Client(base_url="http://fixtures:8000", timeout=10, trust_env=False)


class RemoteClock:
    def __init__(self, http: httpx.Client | None = None) -> None:
        self.http = http if http is not None else fixture_http()

    def now(self) -> datetime:
        response = self.http.get("/clock")
        response.raise_for_status()
        now = datetime.fromisoformat(response.json()["now"])
        if now.tzinfo is None:
            raise ValueError("fixture clock requires timezone")
        return now


class CollectorNotifier:
    def __init__(self, http: httpx.Client | None = None) -> None:
        self.http = http if http is not None else fixture_http()

    def send(self, notification: Notification, tokens: list[str]) -> NotificationResult:
        try:
            response = self.http.post("/notifications", json={
                "notification": asdict(notification), "tokens": tokens,
            })
            response.raise_for_status()
            if response.json() != {"accepted": True}:
                raise ValueError("collector did not accept notification")
        except (httpx.HTTPError, ValueError):
            return NotificationResult([], [], tokens)
        return NotificationResult(tokens, [], [])

    def notify(self, title: str, body: str) -> None:
        raise RuntimeError("acceptance requires recipient-aware send(), not legacy notify()")


class AccountProvider:
    def get_account(self, token: str) -> MetaCandidate:
        if token != "acceptance-token":
            raise ValueError("only synthetic acceptance credentials allowed")
        return MetaCandidate(ig_user_id="ig_123", ig_username="acceptance_dojo",
                             page_id=None, page_name=None)

    def refresh_token(self, token: str) -> tuple[str, datetime]:
        self.get_account(token)
        return token, RemoteClock().now() + timedelta(days=60)


def store() -> PostgresStore:
    return PostgresStore(os.environ.get("DATABASE_URL", ""))


def build_meta() -> DojoMetaConnection:
    db = store()
    return DojoMetaConnection(
        store=db, audit=db, clock=RemoteClock(), provider=StubMetaOAuthProvider(),
        instagram_provider=AccountProvider(),
        cipher=FernetCipher(os.environ["META_TOKEN_ENCRYPTION_KEY"]),
        app_id="acceptance", app_secret="acceptance", redirect_uri=f"{ORIGIN}/callback",
    )


def build_setup() -> DojoSetup:
    db = store()
    return DojoSetup(setup=db, audit=db, pairing=db, clock=RemoteClock(), meta=build_meta())


def build_publishing() -> DojoPublishing:
    db = store()
    clock = RemoteClock()
    return DojoPublishing(
        packages=db, audit=db, uploads=db, jobs=db, settings=db,
        media_root=Path(os.environ["MEDIA_ROOT"]), clock=clock, setup=build_setup(),
        notifier=CollectorNotifier(),
        meta=HttpMetaPublisher(connection_store=db,
                               cipher=FernetCipher(os.environ["META_TOKEN_ENCRYPTION_KEY"]),
                               host="http://fixtures:8000"),
        signed_urls=HmacSignedUrlStore(base_url=ORIGIN,
                                       secret=os.environ["SIGNED_URL_SECRET"], clock=clock),
    )


def build_pairing() -> DojoPairing:
    db = store()
    return DojoPairing(pairing=db, audit=db, clock=RemoteClock())


def create_backend_app() -> FastAPI:
    from backend.main import create_app

    db = store()
    return create_app(publishing=build_publishing(), pairing=build_pairing(),
                      activity=DojoActivity(audit=db, pairing=db), setup=build_setup(),
                      meta=build_meta(), cookie_secure=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["backend", "worker", "seed", "inspect"])
    args = parser.parse_args(argv)
    if args.mode == "backend":
        import uvicorn
        from dojo.observability import configure_logging

        configure_logging("backend")
        uvicorn.run(create_backend_app(), host="0.0.0.0", port=8000,
                    log_config=None, access_log=False)
    elif args.mode == "worker":
        import worker.main as worker

        worker.build_publishing = build_publishing
        worker.build_meta = build_meta
        worker.main()
    elif args.mode == "seed":
        from backend.cli import mint_code, set_consent_policy

        set_consent_policy(build_setup(), version=1, text="Acceptance media consent policy")
        pairing = build_pairing()
        print(json.dumps({"browser_code": mint_code(pairing).raw_code,
                          "device_code": mint_code(pairing).raw_code}))
    else:
        root = Path(os.environ["MEDIA_ROOT"])
        print(json.dumps({"completed": [p.name for p in root.glob("*-completed")
                                        if (p / "manifest.json").is_file()]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
