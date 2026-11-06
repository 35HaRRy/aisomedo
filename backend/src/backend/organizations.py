"""Build and cache one immutable organization scope for each authenticated request."""

import os
from dataclasses import dataclass
from typing import Any

from dojo import DojoActivity, DojoMetaConnection, DojoPublishing, DojoSetup
from dojo.exceptions import OrganizationInactive, OrganizationNotFound
from dojo.organizations import DojoOrganizations
from fastapi import HTTPException, Request


@dataclass(frozen=True)
class OrganizationServices:
    organization_id: int
    publishing: DojoPublishing
    setup: DojoSetup
    activity: DojoActivity
    meta: DojoMetaConnection | None


def build_organization_services(organization_id: int, registry: Any) -> OrganizationServices:
    from backend.deps import build_activity, build_meta, build_publishing, build_setup

    store = registry.for_organization(organization_id)
    meta = build_meta(store) if os.environ.get("META_TOKEN_ENCRYPTION_KEY") else None
    setup = build_setup(meta, store)
    publishing = build_publishing(store)
    publishing._setup = setup
    return OrganizationServices(organization_id, publishing, setup, build_activity(store), meta)


def services_for_organization(request: Request, organization_id: int) -> OrganizationServices:
    factory = getattr(request.app.state, "services_factory", None)
    if factory is not None:
        return factory(organization_id)
    # Existing dependency-injected applications already provide one explicit scope.
    publishing = getattr(request.app.state, "publishing", None)
    if publishing is None or publishing._packages.organization_id != organization_id:
        raise HTTPException(status_code=403, detail="organization services are unavailable")
    return OrganizationServices(
        organization_id, publishing, getattr(request.app.state, "setup", None),
        getattr(request.app.state, "activity", None), getattr(request.app.state, "meta", None),
    )


def get_organization_services(request: Request) -> OrganizationServices:
    existing = getattr(request.state, "organization_services", None)
    if existing is not None:
        return existing
    client = getattr(request.state, "current_client", None)
    if client is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    registry = request.app.state.pairing._pairing
    try:
        DojoOrganizations(registry).require_active(client.organization_id)
    except (OrganizationInactive, OrganizationNotFound) as exc:
        raise HTTPException(status_code=401, detail="unauthorized") from exc
    services = services_for_organization(request, client.organization_id)
    if services.organization_id != client.organization_id:
        raise HTTPException(status_code=403, detail="organization scope mismatch")
    request.state.organization_services = services
    return services
