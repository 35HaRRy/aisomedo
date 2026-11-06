import asyncio
from datetime import UTC, datetime

import pytest
from dojo.adapters.memory import InMemoryStore
from dojo.model import Client
from dojo.organizations import DojoOrganizations

from backend.live import LiveHub


@pytest.mark.asyncio
async def test_changes_and_deactivation_only_reach_their_organization():
    root = InMemoryStore()
    organizations = DojoOrganizations(root)
    a = organizations.create(name="A", email="a@example.com")
    b = organizations.create(name="B", email="b@example.com")
    first = root.for_organization(a.id)
    second = root.for_organization(b.id)
    client_a = first.create_client(Client(0, "A", "browser", datetime.now(UTC), "cli"), "a")
    client_b = second.create_client(Client(0, "B", "browser", datetime.now(UTC), "cli"), "b")
    hub = LiveHub(root, connect=lambda: None, heartbeat_seconds=0.01)
    hub._listener_ready()
    stream_a = hub.subscribe(client_a.id, organization_id=a.id, expires_at=None)
    stream_b = hub.subscribe(client_b.id, organization_id=b.id, expires_at=None)
    try:
        assert (await anext(stream_a)).event == "ready"
        assert (await anext(stream_b)).event == "ready"
        with first.command_transaction():
            event = first.record_change(["dashboard"])
        hub._committed_change(event)
        assert (await anext(stream_a)).event == "change"
        assert (await asyncio.wait_for(anext(stream_b), 1)).event == "heartbeat"
        organizations.deactivate("A")
        hub._committed_change(next(reversed(first._live_events.values())))
        message = await anext(stream_a)
        assert message.event == "resync"
        assert message.data["reason"] == "unauthorized"
        assert (await asyncio.wait_for(anext(stream_b), 1)).event == "heartbeat"
        late = hub.subscribe(client_a.id, organization_id=a.id, expires_at=None)
        assert (await anext(late)).data["reason"] == "unauthorized"
        await late.aclose()
    finally:
        await stream_a.aclose()
        await stream_b.aclose()
