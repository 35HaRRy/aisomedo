from concurrent.futures import ThreadPoolExecutor

import pytest
from dojo import DojoActivity, DojoMetaConnection, DojoPairing, DojoPublishing, DojoSetup
from dojo.adapters.memory import InMemoryStore
from dojo.adapters.meta import FernetCipher, StubMetaOAuthProvider
from dojo.organizations import DojoOrganizations, organization_media_root
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.organizations import OrganizationServices


@pytest.fixture
def workspaces(tmp_path):
    root = InMemoryStore()
    organizations = DojoOrganizations(root)
    a = organizations.create(name="A", email="a@example.com")
    b = organizations.create(name="B", email="b@example.com")
    pairing = DojoPairing(pairing=root, audit=root)
    cipher = FernetCipher(FernetCipher.generate_key())

    def factory(organization_id):
        store = root.for_organization(organization_id)
        return OrganizationServices(
            organization_id, DojoPublishing(packages=store, audit=store, settings=store,
                                            media_root=organization_media_root(
                                                tmp_path, organization_id)),
            DojoSetup(setup=store, audit=store, pairing=store),
            DojoActivity(audit=store, pairing=store),
            DojoMetaConnection(store=store, audit=store, provider=StubMetaOAuthProvider(),
                               cipher=cipher, app_id="test", app_secret="test",
                               redirect_uri="https://example.test/api/meta/oauth/callback"),
        )

    app = create_app(pairing=pairing, services_factory=factory, cookie_secure=False)
    clients = []
    for organization in (a, b):
        client = TestClient(app)
        code = pairing.create_pairing_code(requester="cli", organization_id=organization.id)
        result = pairing.validate_code(code=code.raw_code, kind="device", name=organization.name)
        client.headers.update({"Authorization": f"Bearer {result.raw_credential}",
                               "X-Android-Version-Code": "999999"})
        clients.append(client)
    return root, organizations, clients[0], clients[1]


def test_pairing_clients_and_codes_stay_in_their_workspace(workspaces):
    root, _, first, second = workspaces
    a = first.get("/api/pairing/me").json()
    b = second.get("/api/pairing/me").json()
    assert a["organization_id"] != b["organization_id"]
    assert [c["id"] for c in first.get("/api/pairing/clients").json()] == [a["id"]]
    assert first.post(f"/api/pairing/clients/{b['id']}/revoke").status_code == 404
    code = first.post("/api/pairing/codes").json()["code"]
    result = second.post("/api/pairing/validate", json={
        "code": code, "name": "New A device", "kind": "device",
    })
    assert result.status_code == 200
    assert len(root.for_organization(a["organization_id"]).list_clients()) == 2
    assert len(root.for_organization(b["organization_id"]).list_clients()) == 1


def test_parallel_settings_reads_do_not_share_scope(workspaces):
    _, _, first, second = workspaces
    for client, caption in ((first, "First caption"), (second, "Second caption")):
        response = client.patch("/api/settings/branding", json={"caption_template": caption})
        assert response.status_code == 200
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = list(pool.map(lambda c: c.get("/api/settings/branding").json(), [first, second]))
    assert a["caption_template"] == "First caption"
    assert b["caption_template"] == "Second caption"


def test_deactivation_rejects_existing_api_credentials_only_for_its_workspace(workspaces):
    _, organizations, first, second = workspaces
    organizations.deactivate("A")
    assert first.get("/api/pairing/me").status_code == 401
    assert first.post("/api/pairing/codes").status_code == 401
    assert second.get("/api/pairing/me").status_code == 200


def test_oauth_callback_uses_the_states_owner_not_an_organization_parameter(workspaces):
    from urllib.parse import parse_qs, urlsplit

    root, organizations, first, second = workspaces
    started = first.post("/api/meta/oauth/start", json={})
    assert started.status_code == 200
    attempt_id = started.json()["attempt_id"]
    state = parse_qs(urlsplit(started.json()["auth_url"]).query)["state"][0]
    assert second.get(f"/api/meta/oauth/attempts/{attempt_id}").status_code == 404
    other_id = organizations.require_name("B").id
    response = first.get("/api/meta/oauth/callback", params={
        "state": state, "code": "valid", "organization_id": other_id,
    })
    assert response.status_code == 200
    assert root.for_organization(other_id).get_meta_attempt(attempt_id) is None
    started = first.post("/api/meta/oauth/start", json={}).json()
    state = parse_qs(urlsplit(started["auth_url"]).query)["state"][0]
    organizations.deactivate("A")
    response = first.get("/api/meta/oauth/callback", params={"state": state, "code": "valid"})
    assert response.status_code == 400


@pytest.mark.parametrize("asset", ["organizations/2/branding/assets/private.png",
                                   "../private.png", "/media/organizations/2/private.png",
                                   "C:\\media\\private.png"])
def test_asset_input_cannot_reference_another_workspace(workspaces, asset):
    _, _, first, _ = workspaces
    before = first.get("/api/settings/branding").json()
    response = first.put("/api/settings/branding", json={"logo_asset": asset})
    assert response.status_code == 422
    assert first.get("/api/settings/branding").json() == before
