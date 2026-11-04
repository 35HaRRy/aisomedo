from dojo import DojoPublishing
from dojo.adapters.memory import InMemoryStore
from dojo.organizations import DojoOrganizations

from worker import main


def test_worker_dispatches_only_active_organizations(monkeypatch, tmp_path):
    registry = InMemoryStore()
    organizations = DojoOrganizations(registry)
    a = organizations.create(name="A", email="a@example.com")
    b = organizations.create(name="B", email="b@example.com")
    organizations.deactivate("A")
    observed = []

    def build(*, organization_id, registry):
        observed.append(organization_id)
        scoped = registry.for_organization(organization_id)
        publishing = DojoPublishing(packages=scoped, audit=scoped, media_root=tmp_path)
        return publishing

    monkeypatch.setattr(main, "build_publishing", build)
    publishing = DojoPublishing(packages=registry, audit=registry, media_root=tmp_path)
    main.run_tick(publishing)
    assert observed == [b.id]
    assert a.id not in observed


def test_deactivation_prevents_all_operations_in_an_already_bound_tick(monkeypatch, tmp_path):
    registry = InMemoryStore()
    organizations = DojoOrganizations(registry)
    organization = organizations.create(name="A", email="a@example.com")
    scoped = registry.for_organization(organization.id)
    publishing = DojoPublishing(packages=scoped, audit=scoped, media_root=tmp_path)
    organizations.deactivate("A")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("inactive organization must not enter a worker turn")

    monkeypatch.setattr(main, "_run_emission_turn", forbidden)
    monkeypatch.setattr(main, "_run_singleton_turn", forbidden)
    monkeypatch.setattr(main, "_run_job_turn", forbidden)
    main.run_tick(publishing)
