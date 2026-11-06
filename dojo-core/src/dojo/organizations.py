"""Organization management shared by CLI, authentication, and background work."""

from __future__ import annotations

import unicodedata
from email.errors import HeaderParseError
from email.headerregistry import Address
from pathlib import Path

from dojo.exceptions import (
    OrganizationInactive,
    OrganizationInvalid,
    OrganizationNameTaken,
    OrganizationNotFound,
)
from dojo.model import Organization
from dojo.ports import OrganizationStore

__all__ = [
    "DojoOrganizations", "OrganizationInactive", "OrganizationInvalid",
    "OrganizationNameTaken", "OrganizationNotFound", "organization_name_key",
]

INITIAL_ORGANIZATION_NAME = "Kaizen Aikido Akademi"
INITIAL_ORGANIZATION_EMAIL = "kaizenaikidoakademi@gmail.com"


def organization_media_root(root: Path, organization_id: int) -> Path:
    # Organization 1 retains the existing installation's paths after the migration.
    if organization_id == 1:
        return Path(root)
    return Path(root) / "organizations" / str(organization_id)


def organization_name_key(name: str) -> str:
    key = unicodedata.normalize("NFKC", name.strip()).casefold()
    if not key or len(name.strip()) > 128 or any(ord(c) < 32 for c in name.strip()):
        raise OrganizationInvalid("organization name is required (maximum 128 characters)")
    return key


class DojoOrganizations:
    def __init__(self, store: OrganizationStore) -> None:
        self._store = store

    def create(self, *, name: str, email: str, phone: str | None = None) -> Organization:
        key = organization_name_key(name)
        email = email.strip()
        try:
            address = Address(addr_spec=email)
        except (ValueError, IndexError, HeaderParseError) as exc:
            raise OrganizationInvalid("a valid email address is required") from exc
        if (not address.username or not address.domain or len(email) > 254
                or any(c.isspace() for c in email)):
            raise OrganizationInvalid("a valid email address is required")
        phone = (phone.strip() or None) if phone is not None else None
        if phone is not None and (len(phone) > 64 or any(ord(c) < 32 for c in phone)):
            raise OrganizationInvalid("invalid phone number (maximum 64 characters)")
        return self._store.create_organization(name.strip(), key, email, phone)

    def require_name(self, name: str, *, active: bool = True) -> Organization:
        organization = self._store.find_organization_by_name_key(organization_name_key(name))
        if organization is None:
            raise OrganizationNotFound("organization not found")
        if active and not organization.active:
            raise OrganizationInactive("organization is inactive")
        return organization

    def require_active(self, organization_id: int) -> Organization:
        organization = self._store.find_organization(organization_id)
        if organization is None:
            raise OrganizationNotFound("organization not found")
        if not organization.active:
            raise OrganizationInactive("organization is inactive")
        return organization

    def list(self, *, active_only: bool = False) -> list[Organization]:
        return self._store.list_organizations(active_only=active_only)

    def deactivate(self, name: str) -> None:
        organization = self.require_name(name, active=False)
        self._store.deactivate_organization(organization.id)
