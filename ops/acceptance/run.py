"""Run only disposable acceptance resources; never load an installation env."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[2]
CASES = {
    "scheduled publication preserves reviewed artifact", "manual publication preserves cadence",
}


def validate_config(config: dict[str, Any], project: str) -> None:
    services = config.get("services", {})
    required = {"db", "init", "backend", "worker", "gateway", "fixtures", "tls"}
    if (config.get("name") != project or not required.issubset(services)
            or not config.get("networks", {}).get("default", {}).get("internal")
            or any(s.get("ports") for s in services.values())):
        raise ValueError("acceptance stack must be complete and network-isolated")
    for volume in config.get("volumes", {}).values():
        if (volume.get("external") or volume.get("driver_opts")
                or not volume.get("name", "").startswith(project + "_")):
            raise ValueError("acceptance volumes must be project-owned")


def validate_report(path: Path) -> None:
    report = json.loads(path.read_text(encoding="utf-8"))
    specs: list[dict[str, Any]] = []

    def walk(suite: dict[str, Any]) -> None:
        specs.extend(suite.get("specs", []))
        for child in suite.get("suites", []):
            walk(child)

    for suite in report.get("suites", []):
        walk(suite)
    if len(specs) != 2 or {s.get("title") for s in specs} != CASES or report.get("errors"):
        raise ValueError("acceptance must execute both named cases without errors")
    for spec in specs:
        tests = spec.get("tests", [])
        if len(tests) != 1 or tests[0].get("expectedStatus") != "passed":
            raise ValueError("acceptance test missing or skipped")
        results = tests[0].get("results", [])
        if (len(results) != 1 or results[0].get("status") != "passed"
                or results[0].get("retry") != 0):
            raise ValueError("acceptance must pass without retries or skips")


def certificates(directory: Path) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Dojo acceptance CA")])
    now = datetime.now(UTC)
    ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
          .public_key(key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=2))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .sign(key, hashes.SHA256()))
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server = (x509.CertificateBuilder().subject_name(x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "dojo.acceptance.test"),
    ])).issuer_name(name).public_key(server_key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("dojo.acceptance.test")]), False)
        .sign(key, hashes.SHA256()))
    (directory / "ca.crt").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (directory / "server.crt").write_bytes(server.public_bytes(serialization.Encoding.PEM))
    (directory / "server.key").write_bytes(server_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    (directory / "server.key").chmod(0o600)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-tag", required=True)
    parser.add_argument("--output", type=Path, default=Path("artifacts/acceptance"))
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,100}", args.image_tag):
        parser.error("invalid verification image tag")
    project = "dojo-acceptance-" + uuid.uuid4().hex[:12]
    output = args.output.resolve() / project
    output.mkdir(parents=True, mode=0o700)
    print(f"Acceptance evidence: {output}", flush=True)
    # Only PATH/system/Docker connectivity are inherited, never Compose/app credentials.
    env = {k: v for k, v in os.environ.items() if k.upper() in {
        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE",
        "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH",
        "PROGRAMDATA", "APPDATA", "LOCALAPPDATA",
        "PROGRAMFILES", "PROGRAMFILES(X86)",
    }}

    def command(parts: list[str], timeout: int = 300) -> str:
        result = subprocess.run(parts, cwd=ROOT, env=env, check=True, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return result.stdout

    code = 0
    # User-approved tool temp root when available; otherwise platform-native temp.
    preferred = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "Temp/opencode"
    scratch_root = preferred if preferred.is_dir() else None
    with tempfile.TemporaryDirectory(prefix="dojo-acceptance-", dir=scratch_root) as tmp:
        scratch = Path(tmp)
        scratch.chmod(0o700)
        certs = scratch / "certs"
        certs.mkdir()
        certificates(certs)
        compose: list[str] = []
        try:
            images = {}
            for service, dockerfile in (("backend", "backend/Dockerfile"),
                                        ("worker", "worker/Dockerfile"),
                                        ("gateway", "ops/gateway/Dockerfile")):
                tag = f"dojo-{service}-verify:{args.image_tag}"
                if args.build:
                    command(["docker", "build", "-t", tag, "-f", dockerfile, "."], 1200)
                images[service] = command([
                    "docker", "image", "inspect", tag, "--format", "{{.Id}}",
                ]).strip()
            from cryptography.fernet import Fernet

            settings = {
                "POSTGRES_PASSWORD": uuid.uuid4().hex,
                "SIGNED_URL_SECRET": uuid.uuid4().hex,
                "META_TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
                "PUBLIC_BASE_URL": "https://dojo.acceptance.test", "COOKIE_SECURE": "true",
                "SITE_ADDRESS": ":80", "ACCEPTANCE_CERTS": certs.as_posix(),
                "ACCEPTANCE_OUTPUT": output.as_posix(),
                **{f"{key.upper()}_IMAGE": value for key, value in images.items()},
            }
            env_file = scratch / "acceptance.env"
            env_file.write_text("".join(f"{key}={value}\n" for key, value in settings.items()))
            env_file.chmod(0o600)
            compose = ["docker", "compose", "--env-file", str(env_file), "-p", project,
                       "-f", str(ROOT / "ops/docker-compose.prod.yml"),
                       "-f", str(ROOT / "ops/docker-compose.acceptance.yml")]
            validate_config(json.loads(command(compose + ["config", "--format", "json"])), project)
            command(compose + ["build", "browser"], 1200)
            command(compose + ["up", "-d", "--no-build", "--wait", "--wait-timeout", "180",
                               "db", "init", "fixtures", "backend", "worker", "gateway", "tls"])
            seed = command(compose + ["exec", "-T", "backend", ".venv/bin/python", "-m",
                                      "acceptance.bootstrap", "seed"])
            # Codes are private setup material, never part of uploaded diagnostics.
            seed_path = output / "seed.json"
            seed_path.write_text(json.dumps(json.loads(seed.strip().splitlines()[-1])))
            seed_path.chmod(0o600)
            command(compose + ["run", "--rm", "--no-deps", "browser"], 600)
            validate_report(output / "report.json")
            completed = json.loads(command(compose + [
                "exec", "-T", "backend", ".venv/bin/python", "-m",
                "acceptance.bootstrap", "inspect",
            ]))
            if len(completed["completed"]) != 2:
                raise ValueError("expected two real completed package folders")
            (output / "filesystem.json").write_text(json.dumps(completed))
        except (subprocess.SubprocessError, OSError, ValueError, KeyError) as exc:
            # Command output can contain synthetic secrets; retain only safe command identity.
            print(f"Acceptance failed: {type(exc).__name__}: "
                  f"{getattr(exc, 'cmd', 'invalid acceptance evidence')}")
            if isinstance(exc, subprocess.CalledProcessError):
                (output / "command-failure.log").write_text(
                    ((exc.stdout or "") + (exc.stderr or ""))[-100000:], encoding="utf-8",
                )
            code = 1
        finally:
            if compose:
                for filename, parts in (("compose.log", ["logs", "--no-color", "--tail", "200"]),
                                        ("status.json", ["ps", "--all", "--format", "json"]),
                                        ("evidence.json", ["exec", "-T", "backend",
                                         ".venv/bin/python", "-c", "import urllib.request; "
                                         "print(urllib.request.urlopen('http://fixtures:8000/evidence',"
                                         "timeout=5).read().decode())"])):
                    try:
                        (output / filename).write_text(command(compose + parts), encoding="utf-8")
                    except (subprocess.SubprocessError, OSError):
                        print(f"Could not collect {filename}")
                try:
                    command(compose + ["down", "--volumes", "--remove-orphans"], 180)
                except (subprocess.SubprocessError, OSError):
                    print(f"Cleanup failed for owned project {project}")
                    code = 1
            (output / "seed.json").unlink(missing_ok=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
