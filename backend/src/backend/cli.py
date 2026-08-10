from __future__ import annotations

import argparse
import os

from dojo import DojoPairing
from dojo.adapters.db import PostgresStore
from dojo.model import PairingCodeIssued

DEFAULT_URL = "postgresql+psycopg://dojo:dojo@localhost:5433/dojo"


def mint_code(pairing: DojoPairing) -> PairingCodeIssued:
    return pairing.create_pairing_code(requester="cli")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dojo-create-pairing-code")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_URL),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("create-code")
    args = parser.parse_args(argv)

    store = PostgresStore(args.database_url)
    store.create_all()
    pairing = DojoPairing(pairing=store, audit=store)
    issued = mint_code(pairing)
    print(f"Pairing code: {issued.raw_code}")
    print(f"Expires at:   {issued.expires_at.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
