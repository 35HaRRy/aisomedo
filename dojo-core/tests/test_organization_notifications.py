from dataclasses import replace
from datetime import UTC, datetime

import pytest
from dojo.adapters.memory import InMemoryStore
from dojo.model import Client, Job
from dojo.organizations import DojoOrganizations

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


@pytest.fixture(params=["memory", "postgres"])
def notifications(request):
    root = InMemoryStore() if request.param == "memory" else request.getfixturevalue("pg_registry")
    organizations = DojoOrganizations(root)
    stores = []
    for name in ("A", "B"):
        organization = organizations.create(name=name, email=f"{name}@example.com")
        store = root.for_organization(organization.id)
        client = store.create_client(Client(0, name, "device", NOW, "cli"), name)
        store.register_token(client.id, f"token-{name}", NOW)
        stores.append(store)
    return root, organizations, stores[0], stores[1]


def test_job_failure_alert_only_reaches_its_organization(notifications):
    root, _, first, _ = notifications
    job = first.create(Job(0, "failed-job", None, "render", "queued", {}, NOW))
    first.update(replace(job, status="failed", finished_at=NOW))
    assert root.prepare_alert_deliveries(NOW) == 1
    delivery = root.claim_alert_delivery(NOW)
    assert delivery.token == "token-A"
    assert root.claim_alert_delivery(NOW) is None


def test_deactivation_prevents_retry_delivery(notifications):
    root, organizations, first, _ = notifications
    job = first.create(Job(0, "failed-job", None, "render", "queued", {}, NOW))
    first.update(replace(job, status="failed", finished_at=NOW))
    root.prepare_alert_deliveries(NOW)
    organizations.deactivate("A")
    assert root.claim_alert_delivery(NOW) is None


def test_deactivation_after_claim_prevents_the_external_send(notifications):
    from dojo.adapters.stubs import StubNotifier
    from dojo.monitoring import DojoMonitoring
    from dojo.testing import FakeClock

    root, organizations, first, _ = notifications
    job = first.create(Job(0, "failed-job", None, "render", "queued", {}, NOW))
    first.update(replace(job, status="failed", finished_at=NOW))
    root.prepare_alert_deliveries(NOW)
    lease = root.claim_alert_delivery(NOW)
    organizations.deactivate("A")
    notifier = StubNotifier()
    service = DojoMonitoring(root, notifier, FakeClock(NOW))
    assert service._deliver(lease) == 0
    assert notifier.sent == []
