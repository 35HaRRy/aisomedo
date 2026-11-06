from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dojo import BrandingConfig, DojoPairing, DojoPublishing, DojoSetup
from dojo.adapters.db import PostgresStore
from dojo.exceptions import (
    OrganizationInactive,
    OrganizationInvalid,
    OrganizationNameTaken,
    OrganizationNotFound,
)
from dojo.model import ConsentPolicy, PairingCodeIssued
from dojo.organizations import DojoOrganizations

DEFAULT_URL = "postgresql+psycopg://dojo:dojo@localhost:5434/dojo"


def mint_code(pairing: DojoPairing, *, organization_id: int) -> PairingCodeIssued:
    return pairing.create_pairing_code(requester="cli", organization_id=organization_id)


def _organization_store(
    parser: argparse.ArgumentParser, store: PostgresStore, name: str,
) -> PostgresStore:
    try:
        organization = DojoOrganizations(store).require_name(name)
    except (OrganizationInvalid, OrganizationNotFound, OrganizationInactive) as exc:
        parser.error(str(exc))
    return store.for_organization(organization.id)


def organizations_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dojo-organizations")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_URL))
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--name", required=True)
    create.add_argument("--email", required=True)
    create.add_argument("--phone")
    subparsers.add_parser("list")
    deactivate = subparsers.add_parser("deactivate")
    deactivate.add_argument("--name", required=True)
    args = parser.parse_args(argv)
    store = PostgresStore(args.database_url)
    store.create_all()
    organizations = DojoOrganizations(store)
    try:
        if args.command == "create":
            organization = organizations.create(name=args.name, email=args.email, phone=args.phone)
            print(f"Organization created: {organization.name} (id={organization.id})")
        elif args.command == "deactivate":
            organizations.deactivate(args.name)
            print("Organization is inactive.")
        else:
            for organization in organizations.list():
                status = "active" if organization.active else "inactive"
                print(f"{organization.id}\t{organization.name}\t{organization.email}\t"
                      f"{organization.phone or '-'}\t{status}")
    except (OrganizationInvalid, OrganizationNameTaken, OrganizationNotFound) as exc:
        parser.error(str(exc))
    return 0


def render_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dojo-render")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_URL),
    )
    parser.add_argument(
        "--media-root",
        default=os.environ.get("MEDIA_ROOT", "media"),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    render = subparsers.add_parser("render-preview")
    render.add_argument("--organization", required=True)
    args = parser.parse_args(argv)

    store = PostgresStore(args.database_url)
    store.create_all()
    store = _organization_store(parser, store, args.organization)
    publishing = DojoPublishing(
        packages=store,
        audit=store,
        uploads=store,
        jobs=store,
        settings=store,
        media_root=Path(args.media_root),
    )
    result = publishing.render_preview()
    print(f"stale: {result['stale']}")
    print(f"render_revision: {result['render_revision']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dojo-create-pairing-code")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_URL),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create-code")
    create.add_argument("--organization", required=True)
    args = parser.parse_args(argv)

    store = PostgresStore(args.database_url)
    store.create_all()
    store = _organization_store(parser, store, args.organization)
    pairing = DojoPairing(pairing=store, audit=store)
    try:
        issued = mint_code(pairing, organization_id=store.organization_id)
    except OrganizationInactive as exc:
        parser.error(str(exc))
    print(f"Pairing code: {issued.raw_code}")
    print(f"Expires at:   {issued.expires_at.isoformat()}")
    return 0


def set_consent_policy(setup: DojoSetup, *, version: int, text: str) -> ConsentPolicy:
    return setup.set_policy(version=version, text=text, requester="cli")


def set_branding_defaults(
    publishing: DojoPublishing, *, config: BrandingConfig
) -> BrandingConfig:
    return publishing.set_branding_defaults(config, requester="cli")


def consent_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dojo-consent")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_URL),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    set_policy_parser = subparsers.add_parser("set-policy")
    set_policy_parser.add_argument("--version", type=int, required=True)
    set_policy_parser.add_argument("--text", required=True)
    args = parser.parse_args(argv)

    store = PostgresStore(args.database_url)
    store.create_all()
    organizations = DojoOrganizations(store).list()
    if not organizations:
        parser.error("initialize the database before setting the global consent policy")
    for organization in organizations:
        scoped = store.for_organization(organization.id)
        setup = DojoSetup(setup=scoped, audit=scoped, pairing=scoped)
        set_consent_policy(setup, version=args.version, text=args.text)
    print(f"Consent policy v{args.version} saved globally")
    return 0


def settings_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dojo-settings")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_URL),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    limits = subparsers.add_parser("set-upload-limits")
    limits.add_argument("--organization", required=True)
    limits.add_argument("--max-file-bytes", type=int)
    limits.add_argument("--max-package-bytes", type=int)
    branding = subparsers.add_parser("set-branding")
    branding.add_argument("--organization", required=True)
    branding.add_argument("--logo-asset")
    branding.add_argument("--intro-asset")
    branding.add_argument("--intro-duration", type=float)
    branding.add_argument("--outro-asset")
    branding.add_argument("--outro-duration", type=float)
    caption = subparsers.add_parser("set-caption-template")
    caption.add_argument("--organization", required=True)
    caption.add_argument("--text", required=True)
    args = parser.parse_args(argv)

    store = PostgresStore(args.database_url)
    store.create_all()
    store = _organization_store(parser, store, args.organization)
    now = datetime.now(ZoneInfo("Europe/Istanbul"))
    if args.command == "set-upload-limits":
        if args.max_file_bytes is not None:
            store.set("upload.max_file_bytes", args.max_file_bytes, updated_at=now)
        if args.max_package_bytes is not None:
            store.set("upload.max_package_bytes", args.max_package_bytes, updated_at=now)
        print("upload limits saved")
        return 0
    publishing = DojoPublishing(
        packages=store,
        audit=store,
        uploads=store,
        jobs=store,
        settings=store,
        media_root=Path(os.environ.get("MEDIA_ROOT", "media")),
    )
    if args.command == "set-branding":
        set_branding_defaults(
            publishing,
            config=BrandingConfig(
                logo_asset=args.logo_asset,
                intro_asset=args.intro_asset,
                intro_duration=args.intro_duration,
                outro_asset=args.outro_asset,
                outro_duration=args.outro_duration,
            ),
        )
        print("branding defaults saved")
        return 0
    if args.command == "set-caption-template":
        set_branding_defaults(
            publishing, config=BrandingConfig(caption_template=args.text)
        )
        print("caption template saved")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
