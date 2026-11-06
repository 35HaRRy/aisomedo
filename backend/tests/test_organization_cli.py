import pytest
from dojo.adapters.memory import InMemoryStore
from dojo.organizations import DojoOrganizations

from backend import cli


@pytest.fixture
def registry(monkeypatch):
    store = InMemoryStore()
    monkeypatch.setattr(store, "create_all", lambda: None, raising=False)
    monkeypatch.setattr(cli, "PostgresStore", lambda _url: store)
    return store


def test_create_list_and_deactivate(registry, capsys):
    assert cli.organizations_main(["create", "--name", "Kaizen Aikido Akademi", "--email",
                                   "kaizenaikidoakademi@gmail.com"]) == 0
    capsys.readouterr()
    assert cli.organizations_main(["list"]) == 0
    output = capsys.readouterr().out
    assert "Kaizen Aikido Akademi" in output
    assert "kaizenaikidoakademi@gmail.com" in output
    assert "active" in output
    assert "token" not in output and "hash" not in output
    assert cli.organizations_main(["deactivate", "--name", "kaizen aikido akademi"]) == 0
    assert cli.organizations_main(["deactivate", "--name", "Kaizen Aikido Akademi"]) == 0
    assert DojoOrganizations(registry).list()[0].active is False


@pytest.mark.parametrize("argv", [
    ["create", "--name", "A"], ["create", "--email", "a@example.com"],
    ["create", "--name", " ", "--email", "a@example.com"],
    ["create", "--name", "A", "--email", "invalid"],
    ["deactivate", "--name", "missing"],
])
def test_invalid_organization_command_is_rejected(registry, argv):
    with pytest.raises(SystemExit) as exc:
        cli.organizations_main(argv)
    assert exc.value.code == 2
    assert DojoOrganizations(registry).list() == []


def test_pairing_command_requires_active_organization(registry, capsys):
    organizations = DojoOrganizations(registry)
    a = organizations.create(name="A", email="a@example.com")
    for argv in (["create-code"], ["create-code", "--organization", " "],
                 ["create-code", "--organization", "missing"]):
        with pytest.raises(SystemExit) as exc:
            cli.main(argv)
        assert exc.value.code == 2
        assert "Pairing code:" not in capsys.readouterr().out
    assert cli.main(["create-code", "--organization", "A"]) == 0
    output = capsys.readouterr().out
    assert "Pairing code:" in output
    assert len(registry.for_organization(a.id)._codes) == 1
    organizations.deactivate("A")
    with pytest.raises(SystemExit) as exc:
        cli.main(["create-code", "--organization", "A"])
    assert exc.value.code == 2
    assert len(registry.for_organization(a.id)._codes) == 1
