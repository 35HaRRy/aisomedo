"""Execute workflow guards with controlled inputs; parse wiring as CI consumes it."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash") if os.name != "nt" else r"C:\Program Files\Git\bin\bash.exe"


def workflow(name):
    path = ROOT / ".github/workflows" / name
    assert path.is_file(), f"missing workflow {name}"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def run_step(step, tmp_path, env=None):
    script = tmp_path / "step.sh"
    script.write_text("set -euo pipefail\n" + step["run"], encoding="utf-8")
    environment = {**os.environ, "RUNNER_TEMP": tmp_path.as_posix(),
                   "GITHUB_ENV": (tmp_path / "github-env").as_posix(),
                   "MSYS2_ENV_CONV_EXCL": "*", **(env or {})}
    return subprocess.run([BASH, str(script)], env=environment, cwd=ROOT,
                          capture_output=True, text=True)


@pytest.mark.parametrize("missing", ["ANDROID_KEYSTORE_BASE64", "ANDROID_KEYSTORE_PASSWORD",
                                    "ANDROID_KEY_ALIAS", "ANDROID_KEY_PASSWORD"])
def test_signing_preparation_fails_closed_without_inputs(tmp_path, missing):
    wf = workflow("android-release.yml")
    step = next(s for s in wf["jobs"]["release"]["steps"] if s.get("id") == "signing")
    env = {key: "synthetic-secret" for key in (
        "ANDROID_KEYSTORE_BASE64", "ANDROID_KEYSTORE_PASSWORD",
        "ANDROID_KEY_ALIAS", "ANDROID_KEY_PASSWORD",
    )}
    env[missing] = ""
    result = run_step(step, tmp_path, env)
    assert result.returncode != 0
    assert "synthetic-secret" not in result.stdout + result.stderr
    assert not (tmp_path / "android-release.jks").exists()


def test_android_pipeline_verifies_before_publication():
    wf = workflow("android-release.yml")
    assert wf.get("on", wf.get(True))["push"]["tags"] == ["android-v*"]
    job = wf["jobs"]["release"]
    assert job["environment"] == "android-release"
    assert job["permissions"]["contents"] == "write"
    steps = job["steps"]
    verify = next(i for i, step in enumerate(steps) if step.get("id") == "verify")
    publish = next(i for i, step in enumerate(steps) if step.get("id") == "publish")
    assert verify < publish
    assert steps[-1]["if"] == "always()"


def test_production_passes_android_compatibility_settings(tmp_path):
    result = subprocess.run([
        "docker", "compose", "--env-file", str(ROOT / "ops/.env.example"),
        "-f", str(ROOT / "ops/docker-compose.prod.yml"),
        "-f", str(ROOT / "ops/docker-compose.existing-proxy.yml"), "config", "--format", "json",
    ], capture_output=True, text=True, env={**os.environ,
        "ANDROID_CURRENT_VERSION_CODE": "9", "ANDROID_MIN_VERSION_CODE": "8",
        "ANDROID_UPDATE_URL": "https://example.test/aisomedo.apk"})
    assert result.returncode == 0, result.stderr
    import json
    env = json.loads(result.stdout)["services"]["backend"]["environment"]
    assert env["ANDROID_CURRENT_VERSION_CODE"] == "9"
    assert env["ANDROID_MIN_VERSION_CODE"] == "8"
    assert env["ANDROID_UPDATE_URL"] == "https://example.test/aisomedo.apk"


def test_ci_gate_covers_all_checks_and_merge_queue():
    wf = workflow("ci.yml")
    assert "merge_group" in wf.get("on", wf.get(True))
    jobs = wf["jobs"]
    checks = set(jobs) - {"required", "publish", "deploy"}
    assert set(jobs["required"]["needs"]) == checks
    assert jobs["required"]["if"] == "always()"
    assert wf["permissions"] == {"contents": "read"}
    assert jobs["publish"]["needs"] == ["required"]
    assert jobs["deploy"]["needs"] == ["publish"]
    for job in (jobs["publish"], jobs["deploy"]):
        assert "github.event_name == 'push'" in job["if"]
        assert "github.ref == 'refs/heads/master'" in job["if"]
    assert jobs["deploy"]["environment"] == "production"
    assert jobs["deploy"]["concurrency"]["cancel-in-progress"] is False
    assert jobs["publish"]["permissions"] == {"contents": "read", "packages": "write"}
    for name in checks:
        assert "secrets." not in str(jobs[name])


@pytest.mark.parametrize("status,success", [("success", True), ("failure", False),
                                          ("cancelled", False), ("skipped", False)])
def test_aggregate_executes_exact_success_gate(tmp_path, status, success):
    import json
    job = workflow("ci.yml")["jobs"]["required"]
    step = job["steps"][0]
    results = {name: {"result": "success"} for name in job["needs"]}
    results[job["needs"][0]]["result"] = status
    result = run_step(step, tmp_path, {"NEEDS_JSON": json.dumps(results)})
    assert (result.returncode == 0) is success


@pytest.mark.parametrize("field,value", [("DEPLOY_HOST", "x;touch /tmp/pwned"),
                                       ("DEPLOY_ROOT", "/srv/x y"), ("DEPLOY_PORT", "0"),
                                       ("DEPLOY_USER", "-root"), ("DEPLOY_MODE", "oops"),
                                       ("DEPLOY_ORIGIN", "http://example.test"),
                                       ("DEPLOY_ORIGIN", "https://example.test:99999"),
                                       ("DEPLOY_ORIGIN", "https://example.test:0"),
                                       ("DEPLOY_MONITORING", "yes")])
def test_ssh_inputs_rejected_before_key_installation(tmp_path, field, value):
    step = next(s for s in workflow("ci.yml")["jobs"]["deploy"]["steps"]
                if s.get("id") == "inputs")
    env = {"DEPLOY_HOST": "example.test", "DEPLOY_ROOT": "/srv/aisomedo",
           "DEPLOY_PORT": "22", "DEPLOY_USER": "deploy", "DEPLOY_MODE": "dedicated",
           "DEPLOY_ORIGIN": "https://example.test", "DEPLOY_MONITORING": "false"}
    env[field] = value
    result = run_step(step, tmp_path, env)
    assert result.returncode != 0
    assert "Release validate failed" not in result.stdout, (
        "input guard did not reject malformed input"
    )
    assert "AssertionError" in result.stderr or "ValueError" in result.stderr


def test_valid_ssh_input_guard_succeeds(tmp_path):
    step = next(s for s in workflow("ci.yml")["jobs"]["deploy"]["steps"]
                if s.get("id") == "inputs")
    guard = {"run": step["run"].split("PY\n", 1)[0] + "PY\n"}
    env = {"DEPLOY_HOST": "example.test", "DEPLOY_ROOT": "/srv/aisomedo",
           "DEPLOY_PORT": "22", "DEPLOY_USER": "deploy", "DEPLOY_MODE": "dedicated",
           "DEPLOY_ORIGIN": "https://example.test", "DEPLOY_MONITORING": "false"}
    result = run_step(guard, tmp_path, env)
    assert result.returncode == 0, result.stderr


def test_ssh_transport_strict_host_keys_and_cleanup():
    job = workflow("ci.yml")["jobs"]["deploy"]
    steps = job["steps"]
    transport = next(s for s in steps if s.get("id") == "transport")["run"]
    assert "StrictHostKeyChecking=yes" in transport
    assert "ssh-keyscan" not in transport
    assert "StrictHostKeyChecking=no" not in transport
    assert steps[-1]["if"] == "always()"


def test_serialized_deploy_skips_superseded_main_commit():
    steps = workflow("ci.yml")["jobs"]["deploy"]["steps"]
    fresh = next(s for s in steps if s.get("id") == "freshness")
    assert "git/ref/heads/master" in fresh["run"]
    for step in steps:
        if step.get("id") == "transport" or "SSH_KEY" in step.get("env", {}):
            assert step["if"] == "steps.freshness.outputs.deploy == 'true'"


def test_development_render_uses_only_synthetic_env(tmp_path):
    shutil.copyfile(ROOT / "ops/docker-compose.yml", tmp_path / "compose.yml")
    shutil.copyfile(ROOT / "ops/.env.example", tmp_path / ".env")
    result = subprocess.run(["docker", "compose", "--env-file", str(tmp_path / ".env"),
                             "-f", str(tmp_path / "compose.yml"), "config", "--quiet"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("mode", [None, "dedicated", "existing-proxy"])
def test_postgres18_mounts_versioned_data_in_persistent_volume(tmp_path, mode):
    import json

    compose = "docker-compose.prod.yml" if mode else "docker-compose.yml"
    shutil.copyfile(ROOT / "ops/.env.example", tmp_path / ".env")
    shutil.copyfile(ROOT / "ops" / compose, tmp_path / compose)
    command = ["docker", "compose", "--env-file", str(tmp_path / ".env"),
               "-f", str(tmp_path / compose)]
    if mode:
        command.extend(["-f", str(ROOT / "ops" / f"docker-compose.{mode}.yml")])
    result = subprocess.run(command + ["config", "--format", "json"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)
    db = config["services"]["db"]
    assert db["image"] == "postgres:18"
    mount, = db["volumes"]
    assert mount["type"] == "volume"
    assert mount["target"] == "/var/lib/postgresql"
    if not mode:
        assert mount["source"] == "db-data"
    else:
        assert "driver_opts" not in config["volumes"][mount["source"]]
