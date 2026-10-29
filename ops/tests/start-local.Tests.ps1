$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot '../start-local.ps1'
if (-not (Test-Path $source)) { throw 'Missing local startup script' }
$sandbox = Join-Path ([IO.Path]::GetTempPath()) ('aisomedo-check-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $sandbox | Out-Null
try {
    Copy-Item $source (Join-Path $sandbox 'start-local.ps1')
    function global:docker { $global:LASTEXITCODE = 0 }
    & (Join-Path $sandbox 'start-local.ps1') -CheckOnly
    if (Test-Path (Join-Path $sandbox '.env.local')) { throw 'CheckOnly created environment' }
    $sentinel = 'POSTGRES_PASSWORD=existing-secret'
    [IO.File]::WriteAllText((Join-Path $sandbox '.env.local'), $sentinel)
    & (Join-Path $sandbox 'start-local.ps1') -CheckOnly
    if ([IO.File]::ReadAllText((Join-Path $sandbox '.env.local')) -cne $sentinel) { throw 'Existing secret overwritten' }
    $global:commands = @()
    function global:docker { $global:commands += ($args -join ' '); $global:LASTEXITCODE = 1 }
    $failed = $false
    try { & (Join-Path $sandbox 'start-local.ps1') -PairingCode } catch { $failed = $true }
    if (-not $failed) { throw 'Docker failure was ignored' }
    if ($global:commands -match 'create-code') { throw 'Pairing ran after Docker failed' }
    if ($global:commands -match '(--env-file\s+\S*[\\/]\.env\s|down|--volumes)') { throw 'Unsafe Docker command' }
    $global:commands = @()
    function global:docker {
        $global:commands += ($args -join ' ')
        $global:LASTEXITCODE = 0
        if ($args -contains 'up') { $global:LASTEXITCODE = 1 }
    }
    $failed = $false
    try { & (Join-Path $sandbox 'start-local.ps1') -PairingCode } catch { $failed = $true }
    if (-not $failed -or -not ($global:commands -match '\sup\s')) { throw 'Compose failure was not exercised' }
    if ($global:commands -match 'create-code') { throw 'Pairing ran after Compose failed' }
    function global:docker { $global:LASTEXITCODE = 0 }
    & (Join-Path $sandbox 'start-local.ps1')
    $updated = [IO.File]::ReadAllText((Join-Path $sandbox '.env.local'))
    if (-not $updated.StartsWith($sentinel)) { throw 'Existing secret was replaced' }
    if ($updated -notmatch '(?m)^META_TOKEN_ENCRYPTION_KEY=([A-Za-z0-9_-]+=*)\r?$') { throw 'Missing token encryption key' }
    if ([Convert]::FromBase64String($Matches[1].Replace('-', '+').Replace('_', '/')).Length -ne 32) { throw 'Invalid encryption key length' }
    & (Join-Path $sandbox 'start-local.ps1')
    if ([IO.File]::ReadAllText((Join-Path $sandbox '.env.local')) -cne $updated) { throw 'Repeat startup changed secrets' }
    Write-Host 'PASS: read-only validation, preserved secrets, failed Docker blocks startup/pairing'
} finally {
    Remove-Item Function:\docker -ErrorAction SilentlyContinue
    Remove-Item $sandbox -Recurse -Force
}
