"""Acceptance controls must fail closed; real workflows live in Playwright."""

import hashlib
import sys
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from acceptance.fixtures import create_app  # noqa: E402

START = datetime.fromisoformat("2026-10-19T06:59:00+03:00")


@pytest.fixture
def fixture_client(monkeypatch):
    # Only the external video fetch is replaced; Graph behavior stays real.
    def download(url, **kwargs):
        assert url == "https://dojo.acceptance.test/pub/render?secret=hidden"
        assert kwargs["verify"] is not False
        return httpx.Response(200, content=b"rendered-video", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", download)
    return TestClient(create_app(initial_time=START, ca_file=Path("fixture-ca.pem")))


def container(client):
    return client.post("/v26.0/ig_123/media", data={
        "media_type": "REELS", "video_url": "https://dojo.acceptance.test/pub/render?secret=hidden",
        "caption": "Dojo caption", "access_token": "acceptance-token",
    })


def test_graph_ingests_before_finished(fixture_client):
    client = fixture_client
    response = container(client)
    assert response.status_code == 200
    cid = response.json()["id"]
    assert client.get(f"/v26.0/{cid}", params={
        "fields": "status_code", "access_token": "acceptance-token",
    }).json() == {"status_code": "FINISHED"}
    for _ in range(2):
        assert client.post("/v26.0/ig_123/media_publish", data={
            "creation_id": cid, "access_token": "acceptance-token",
        }).status_code == 200
    evidence = client.get("/evidence").json()
    assert evidence["containers"][0]["sha256"] == hashlib.sha256(b"rendered-video").hexdigest()
    assert evidence["containers"][0]["caption"] == "Dojo caption"
    assert evidence["containers"][0]["bytes"] == 14
    assert len(evidence["publications"]) == 2
    assert "hidden" not in str(evidence)
    assert "acceptance-token" not in str(evidence)


def test_graph_rejects_unfetchable_video(fixture_client, monkeypatch):
    def fail(*args, **kwargs):
        raise httpx.ConnectError("unreachable signed URL")
    monkeypatch.setattr(httpx, "get", fail)
    assert container(fixture_client).status_code == 502
    assert fixture_client.get("/evidence").json()["containers"] == []


def test_ingestion_allows_clock_reads_during_video_fetch(fixture_client, monkeypatch):
    # Backend serving the signed video also reads RemoteClock. Blocking fixture's
    # event loop here would deadlock the fetch against its own /clock request.
    def download(url, **kwargs):
        assert fixture_client.get("/clock").status_code == 200
        return httpx.Response(200, content=b"video", request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx, "get", download)
    with fixture_client:
        assert container(fixture_client).status_code == 200


def test_publish_requires_ingested_container(fixture_client):
    assert fixture_client.post("/v26.0/ig_123/media_publish", data={
        "creation_id": "missing", "access_token": "acceptance-token",
    }).status_code == 404
    assert fixture_client.get("/evidence").json()["publications"] == []


def test_unknown_graph_request_fails(fixture_client):
    assert fixture_client.get("/v26.0/unexpected").status_code >= 400
    assert fixture_client.post("/v26.0/wrong-account/media", data={}).status_code >= 400


@pytest.mark.parametrize("now", ["broken", "2026-10-19T07:00:00", "2026-10-18T00:00:00Z"])
def test_clock_requires_aware_monotonic_time(fixture_client, now):
    assert fixture_client.post("/clock", json={"now": now}).status_code == 422
    assert fixture_client.get("/clock").json()["now"] == START.isoformat()


def test_collector_preserves_recipients_and_review_data(fixture_client):
    notification = {"title": "Review", "body": "Ready", "data": {"review_id": "4"}}
    response = fixture_client.post("/notifications", json={
        "notification": notification, "tokens": ["fixture-device"],
    })
    assert response.status_code == 200
    assert fixture_client.get("/evidence").json()["notifications"] == [
        {"notification": notification, "tokens": ["fixture-device"]},
    ]


def test_remote_clock_is_shared_and_fails_closed(fixture_client):
    from acceptance.bootstrap import RemoteClock
    first, second = RemoteClock(fixture_client), RemoteClock(fixture_client)
    assert first.now() == second.now() == START
    fixture_client.post("/clock", json={"now": "2026-10-19T07:00:01+03:00"})
    assert first.now() == second.now() == datetime.fromisoformat("2026-10-19T07:00:01+03:00")
    bad = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(
        200, json={"now": "2026-10-19T07:00:00"},
    )), base_url="http://fixture")
    with pytest.raises(ValueError):
        RemoteClock(bad).now()


def test_collector_failure_is_not_delivery(fixture_client):
    from acceptance.bootstrap import CollectorNotifier
    from dojo.model import Notification
    notification = Notification("Review", "Ready", {"review_id": "4"})
    assert CollectorNotifier(fixture_client).send(notification, ["recipient"]).delivered == [
        "recipient",
    ]
    bad = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503)),
                      base_url="http://fixture")
    result = CollectorNotifier(bad).send(notification, ["recipient"])
    assert result.delivered == []
    assert result.transient_failures == ["recipient"]
    with pytest.raises(RuntimeError):
        CollectorNotifier(bad).notify("Legacy", "Ready")


def test_bootstrap_uses_real_http_publisher_and_signed_urls(monkeypatch, tmp_path):
    from acceptance import bootstrap
    from cryptography.fernet import Fernet
    from dojo.adapters.memory import InMemoryStore
    from dojo.adapters.meta import HttpMetaPublisher
    from dojo.adapters.signed_urls import HmacSignedUrlStore
    monkeypatch.setenv("META_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path))
    monkeypatch.setenv("SIGNED_URL_SECRET", "acceptance-only")
    monkeypatch.setattr(bootstrap, "PostgresStore", lambda _: InMemoryStore())
    publishing = bootstrap.build_publishing()
    assert isinstance(publishing._meta, HttpMetaPublisher)
    assert isinstance(publishing._signed_urls, HmacSignedUrlStore)
    assert isinstance(publishing._clock, bootstrap.RemoteClock)
    assert isinstance(publishing._notifier, bootstrap.CollectorNotifier)


def test_worker_bootstrap_preserves_normal_main_loop(monkeypatch):
    import worker.main as worker
    monkeypatch.setattr(worker, "build_publishing", worker.build_publishing)
    monkeypatch.setattr(worker, "build_meta", worker.build_meta)
    from acceptance import bootstrap
    sentinel = object()
    monkeypatch.setattr(bootstrap, "build_publishing", lambda: sentinel)
    monkeypatch.setattr(bootstrap, "build_meta", lambda: sentinel)
    visited = []
    monkeypatch.setattr(worker, "main", lambda: visited.append(worker.build_publishing()))
    assert bootstrap.main(["worker"]) == 0
    assert visited == [sentinel]


@pytest.mark.parametrize("failure", ["startup", "browser", "cleanup", "image", None])
def test_runner_isolation_and_cleanup(tmp_path, monkeypatch, failure):
    import subprocess

    from acceptance import run

    calls = []
    def command(args, **kwargs):
        calls.append(args)
        assert kwargs["env"].get("POSTGRES_PASSWORD") is None
        assert kwargs["env"].get("COMPOSE_PROJECT_NAME") is None
        assert {k.upper(): v for k, v in kwargs["env"].items()}["PROGRAMFILES"] == (
            "Docker plugin lookup"
        )
        if ((failure == "startup" and "up" in args)
                or (failure == "browser" and "browser" in args)
                or (failure == "cleanup" and "down" in args)
                or (failure == "image" and "inspect" in args)):
            raise subprocess.CalledProcessError(1, args)
        output = "sha256:" + "a" * 64
        if "seed" in args:
            output = '{"browser_code":"synthetic", "device_code":"synthetic"}'
        elif "inspect" in args and "exec" in args:
            output = '{"completed":["one-completed","two-completed"]}'
        elif "config" in args:
            import json
            project = args[args.index("-p") + 1]
            output = json.dumps({"name": project,
                                 "services": {s: {} for s in ("db", "init", "backend", "worker",
                                                             "gateway", "fixtures", "tls")},
                                 "volumes": {"db-data": {"name": project + "_db-data"}},
                                 "networks": {"default": {"internal": True}}})
        return subprocess.CompletedProcess(args, 0, stdout=output)

    monkeypatch.setattr(run.subprocess, "run", command)
    reports = []
    monkeypatch.setattr(run, "validate_report", reports.append)
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "dojo-prod")
    monkeypatch.setenv("POSTGRES_PASSWORD", "never-read-this")
    monkeypatch.setenv("ProgramFiles", "Docker plugin lookup")
    output = tmp_path / "artifacts"
    result = run.main(["--image-tag", "fixture", "--output", str(output)])
    assert result == (0 if failure is None else 1)
    compose_calls = [c for c in calls if c[:2] == ["docker", "compose"]]
    if failure == "image":
        assert not compose_calls
        return
    assert compose_calls
    assert all("--env-file" in c and "-p" in c for c in compose_calls)
    projects = {c[c.index("-p") + 1] for c in compose_calls}
    assert len(projects) == 1
    assert next(iter(projects)).startswith("dojo-acceptance-")
    assert "dojo-prod" not in projects
    assert any("down" in c and "--volumes" in c for c in compose_calls)
    assert next(i for i, c in enumerate(calls) if "logs" in c) < next(
        i for i, c in enumerate(calls) if "down" in c)
    assert list(output.rglob("compose.log"))
    if failure is None:
        assert reports[0].parent != output  # Reused output roots cannot reuse stale reports.


@pytest.mark.parametrize("report", [None, {}, {"suites": [], "stats": {"expected": 0}}])
def test_acceptance_requires_two_passed_cases(tmp_path, report):
    import json

    from acceptance.run import validate_report
    path = tmp_path / "report.json"
    if report is not None:
        path.write_text(json.dumps(report))
    with pytest.raises((ValueError, FileNotFoundError)):
        validate_report(path)


def test_fixture_exposes_read_only_worker_progress(tmp_path, monkeypatch):
    path = tmp_path / "health.json"
    monkeypatch.setenv("WORKER_HEALTH_PATH", str(path))
    path.write_text('{"phase":"idle","monotonic":12.5}')
    client = TestClient(create_app(initial_time=START, ca_file=tmp_path / "ca.crt"))
    assert client.get("/worker-health").json() == {"phase": "idle", "monotonic": 12.5}


@pytest.mark.parametrize("change", ["skipped", "retry", "one", "error", None])
def test_acceptance_report_rejects_partial_or_flaky_success(tmp_path, change):
    import json

    from acceptance.run import CASES, validate_report
    specs = [{"title": name, "tests": [{"expectedStatus": "passed", "results": [
        {"status": "passed", "retry": 0},
    ]}]} for name in sorted(CASES)]
    report = {"suites": [{"suites": [{"specs": specs}]}], "errors": []}
    if change == "skipped":
        specs[0]["tests"][0]["results"][0]["status"] = "skipped"
    elif change == "retry":
        specs[0]["tests"][0]["results"].append({"status": "passed", "retry": 1})
    elif change == "one":
        specs.pop()
    elif change == "error":
        report["errors"] = ["worker failed"]
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))
    if change is None:
        validate_report(path)
    else:
        with pytest.raises(ValueError):
            validate_report(path)


@pytest.mark.parametrize("unsafe", ["volume", "port", "network"])
def test_runner_rejects_nonisolated_compose(unsafe):
    from acceptance.run import validate_config
    config = {"name": "dojo-acceptance-test",
              "services": {s: {} for s in ("db", "init", "backend", "worker",
                                          "gateway", "fixtures", "tls")},
              "volumes": {"db-data": {"name": "dojo-acceptance-test_db-data"}},
              "networks": {"default": {"internal": True}}}
    if unsafe == "volume":
        config["volumes"]["db-data"]["name"] = "dojo-prod_db-data"
    elif unsafe == "port":
        config["services"]["gateway"]["ports"] = [{"published": "443"}]
    else:
        config["networks"]["default"]["internal"] = False
    with pytest.raises(ValueError):
        validate_config(config, "dojo-acceptance-test")
