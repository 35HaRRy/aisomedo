"""Render real Compose configuration without starting production containers."""
import json
import os
import subprocess
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]


def render(mode):
    result = subprocess.run(
        ["docker", "compose", "-f", str(OPS / "docker-compose.prod.yml"),
         "-f", str(OPS / f"docker-compose.{mode}.yml"), "config", "--format", "json"],
        env={**os.environ, "POSTGRES_PASSWORD": "fixture", "SIGNED_URL_SECRET": "fixture",
             "PUBLIC_BASE_URL": "https://example.test", "DOMAIN": "example.test"},
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def test_shared_gateway_isolates_database_and_does_not_publish_ingress():
    assert (OPS / "docker-compose.shared-gateway.yml").is_file(), "shared gateway mode missing"
    config = render("shared-gateway")
    gateway = config["services"]["gateway"]
    assert not gateway.get("ports")
    assert gateway["environment"]["SITE_ADDRESS"] == ":80"
    assert gateway["networks"]["proxy"]["aliases"] == ["aisomedo-gateway"]
    assert config["networks"]["proxy"]["external"] is True
    assert config["networks"]["proxy"]["name"] == "gateway-aisomedo"
    for service in ("db", "backend", "worker", "init"):
        assert set(config["services"][service]["networks"]) == {"default"}
        assert not config["services"][service].get("ports")
    for name in ("db-data", "media-data", "caddy-data"):
        assert config["volumes"][name]["name"] == f"dojo-prod_{name}"


def test_existing_deployment_modes_keep_their_ports():
    dedicated = render("dedicated")["services"]["gateway"]
    assert {str(p["published"]) for p in dedicated["ports"]} == {"80", "443"}
    existing = render("existing-proxy")["services"]["gateway"]
    assert existing["ports"][0]["host_ip"] == "127.0.0.1"
