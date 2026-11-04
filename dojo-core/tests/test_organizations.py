from __future__ import annotations

import pytest
from dojo.adapters.memory import InMemoryStore
from dojo.organizations import (
    DojoOrganizations,
    OrganizationInactive,
    OrganizationInvalid,
    OrganizationNameTaken,
    OrganizationNotFound,
)


@pytest.fixture
def organizations() -> DojoOrganizations:
    return DojoOrganizations(InMemoryStore())


def test_create_preserves_contact_details_and_optional_phone(organizations):
    organization = organizations.create(
        name=" Kaizen Aikido Akademi ", email=" kaizenaikidoakademi@gmail.com ",
    )
    assert organization.id > 0
    assert organization.name == "Kaizen Aikido Akademi"
    assert organization.email == "kaizenaikidoakademi@gmail.com"
    assert organization.phone is None
    assert organization.active is True
    assert organizations.require_name("KAIZEN AIKIDO AKADEMI") == organization
    assert organizations.list() == [organization]


@pytest.mark.parametrize("name", ["", " ", "\t"])
def test_empty_name_is_rejected(organizations, name):
    with pytest.raises(OrganizationInvalid):
        organizations.create(name=name, email="dojo@example.com")
    assert organizations.list() == []


@pytest.mark.parametrize("email", ["", " ", "dojo", "@example.com", "a@", "a b@example.com",
                                   "a@example.com\nBcc: other@example.com"])
def test_invalid_email_is_rejected(organizations, email):
    with pytest.raises(OrganizationInvalid):
        organizations.create(name="Dojo", email=email)
    assert organizations.list() == []


def test_name_selection_is_unambiguous_after_normalization(organizations):
    organizations.create(name="Kaizen", email="first@example.com")
    for name in ("kaizen", " KAIZEN ", "Ｋａｉｚｅｎ"):
        with pytest.raises(OrganizationNameTaken):
            organizations.create(name=name, email="other@example.com")
    assert len(organizations.list()) == 1


def test_deactivation_is_idempotent_and_preserves_other_organizations(organizations):
    first = organizations.create(name="First", email="shared@example.com", phone=" +90 123 ")
    second = organizations.create(name="Second", email="shared@example.com", phone=" ")
    organizations.deactivate("first")
    organizations.deactivate("FIRST")
    with pytest.raises(OrganizationInactive):
        organizations.require_active(first.id)
    with pytest.raises(OrganizationInactive):
        organizations.require_name("First")
    assert organizations.require_name("First", active=False).phone == "+90 123"
    assert organizations.require_active(second.id) == second
    assert organizations.list(active_only=True) == [second]
    assert len(organizations.list()) == 2


def test_missing_organization_does_not_fall_back(organizations):
    with pytest.raises(OrganizationNotFound):
        organizations.require_name("missing")
    with pytest.raises(OrganizationNotFound):
        organizations.require_active(999)


def test_postgres_organization_registry(pg_registry):
    organizations = DojoOrganizations(pg_registry)
    first = organizations.create(name="First", email="shared@example.com")
    second = organizations.create(name="Second", email="shared@example.com")
    with pytest.raises(OrganizationNameTaken):
        organizations.create(name=" FIRST ", email="other@example.com")
    organizations.deactivate("First")
    assert organizations.list(active_only=True) == [second]
    assert organizations.require_name("First", active=False).id == first.id
