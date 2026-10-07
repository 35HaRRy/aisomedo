"""Run real Gradle signing guards; opt in on hosts with Android tooling."""
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.environ.get("RUN_ANDROID_SIGNING_TESTS") != "1",
                                reason="requires Java 25 and Android SDK 35")


def gradle(env, *tasks):
    wrapper = ROOT / "android" / ("gradlew.bat" if os.name == "nt" else "gradlew")
    return subprocess.run([str(wrapper), "-p", str(ROOT / "android"), *tasks, "--console=plain"],
                          capture_output=True, text=True, env=env, timeout=300)


def test_release_guard_and_real_signature(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("ANDROID_KEY")}
    env.pop("ANDROID_RELEASE_VERSION", None)
    missing = gradle(env, ":app:assembleRelease")
    assert missing.returncode != 0
    assert "Missing release signing inputs" in missing.stdout + missing.stderr
    java_bin = Path(env["JAVA_HOME"]) / "bin"
    key = tmp_path / "synthetic.jks"
    subprocess.run([str(java_bin / ("keytool.exe" if os.name == "nt" else "keytool")),
                    "-genkeypair", "-keystore", str(key), "-storepass", "fixture-pass",
                    "-keypass", "fixture-pass", "-alias", "release", "-keyalg", "RSA",
                    "-validity", "1", "-dname", "CN=Issue39 Test"],
                   check=True, capture_output=True)
    env.update(ANDROID_KEYSTORE_PATH=str(key), ANDROID_KEYSTORE_PASSWORD="fixture-pass",
               ANDROID_KEY_ALIAS="release", ANDROID_KEY_PASSWORD="fixture-pass",
               ANDROID_RELEASE_VERSION="wrong-version")
    mismatch = gradle(env, ":app:validateReleaseInputs")
    assert mismatch.returncode != 0
    assert "Release tag must match versionName" in mismatch.stdout + mismatch.stderr
    env.pop("ANDROID_RELEASE_VERSION")
    signed = gradle(env, ":app:assembleRelease")
    assert signed.returncode == 0, signed.stdout + signed.stderr
    signer = Path(env["ANDROID_HOME"]) / "build-tools/35.0.0" / (
        "apksigner.bat" if os.name == "nt" else "apksigner")
    result = subprocess.run([str(signer), "verify", "--print-certs",
                             str(ROOT / "android/app/build/outputs/apk/release/app-release.apk")],
                            capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert "CN=Issue39 Test" in result.stdout
    assert "CN=Android Debug" not in result.stdout


def test_debug_tasks_need_no_release_secrets():
    env = {k: v for k, v in os.environ.items() if not k.startswith("ANDROID_KEY")}
    env.pop("ANDROID_RELEASE_VERSION", None)
    result = gradle(env, ":app:testDebugUnitTest", ":app:assembleDebug")
    assert result.returncode == 0, result.stdout + result.stderr
