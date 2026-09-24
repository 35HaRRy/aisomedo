import shutil
import subprocess
from pathlib import Path

import pytest

POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
SCRIPT = Path(__file__).resolve().parents[2] / "ops" / "connect-instagram.ps1"


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is not installed")
def test_powershell_sends_separate_credentials_and_outputs_only_status():
    assert POWERSHELL is not None
    assert SCRIPT.exists(), "PowerShell connector must exist"
    code = """
    $ErrorActionPreference = 'Stop'
    function Invoke-RestMethod {
        param($Uri, $Method, $Headers, $Body, $ContentType, $MaximumRedirection, $TimeoutSec)
        if ($Uri -ne 'http://localhost:8000/api/meta/instagram/token') { throw 'Wrong endpoint' }
        if ($Headers.Authorization -ne 'Bearer app-private') { throw 'Wrong app credential' }
        if (($Body | ConvertFrom-Json).access_token -ne 'ig-private') {
            throw 'Wrong IG credential'
        }
        if ($Method -ne 'Post') { throw 'Wrong method' }
        return [pscustomobject]@{
            health='healthy'; ig_user_id='178414000000001'; connection_type='instagram_login'
        }
    }
    $app = ConvertTo-SecureString 'app-private' -AsPlainText -Force
    $ig = ConvertTo-SecureString 'ig-private' -AsPlainText -Force
    & '__SCRIPT__' -AppToken $app -InstagramToken $ig | ConvertTo-Json -Compress
    """.replace("__SCRIPT__", str(SCRIPT).replace("'", "''"))
    result = subprocess.run([POWERSHELL, "-NoProfile", "-Command", code],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert '"ig_user_id":"178414000000001"' in result.stdout
    assert "ig-private" not in result.stdout + result.stderr
    assert "app-private" not in result.stdout + result.stderr
