[CmdletBinding()]
param([switch]$PairingCode, [switch]$CheckOnly, [switch]$StartWorker)
$ErrorActionPreference = 'Stop'

function New-Secret([switch]$Base64) {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    if ($Base64) { return [Convert]::ToBase64String($bytes).Replace('+', '-').Replace('/', '_') }
    return (($bytes | ForEach-Object { $_.ToString('x2') }) -join '')
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Install Docker Desktop and start its Linux engine first.' }
docker info --format '{{.ServerVersion}}' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker is not ready. Start Docker Desktop with Linux containers.' }
if ($CheckOnly) { Write-Host 'Docker ready. No files or services changed.'; return }

$environment = Join-Path $PSScriptRoot '.env.local'
if (-not (Test-Path $environment)) {
    $values = @(
        "POSTGRES_PASSWORD=$(New-Secret)", "SIGNED_URL_SECRET=$(New-Secret)",
        'PUBLIC_BASE_URL=http://localhost:9081', 'PUBLIC_HTTPS_ORIGIN=http://localhost:9081',
        'COOKIE_SECURE=false', 'IMAGE_TAG=aisomedo-local', 'ANDROID_CURRENT_VERSION_CODE=4',
        'ANDROID_UPDATE_URL=https://github.com/35HaRRy/aisomedo/releases/download/android-v0.2.0/aisomedo.apk'
    )
    # CreateNew refuses to overwrite another process's environment file.
    $file = [IO.File]::Open($environment, [IO.FileMode]::CreateNew)
    $writer = New-Object IO.StreamWriter($file, (New-Object Text.UTF8Encoding($false)))
    try { $writer.WriteLine(($values -join "`n")) } finally { $writer.Dispose() }
}
if ([IO.File]::ReadAllText($environment) -notmatch '(?m)^META_TOKEN_ENCRYPTION_KEY=') {
    [IO.File]::AppendAllText($environment, "`nMETA_TOKEN_ENCRYPTION_KEY=$(New-Secret -Base64)`n", (New-Object Text.UTF8Encoding($false)))
}
$compose = @('compose', '--env-file', $environment, '-p', 'aisomedo-local',
    '-f', (Join-Path $PSScriptRoot 'docker-compose.prod.yml'),
    '-f', (Join-Path $PSScriptRoot 'docker-compose.local.yml'))
docker @compose up -d --build --wait db backend gateway
if ($LASTEXITCODE -ne 0) { throw 'Local startup failed. Check Docker logs and whether port 9081 is free.' }
if ($StartWorker) {
    Write-Warning 'The worker can publish if this local installation already has Instagram credentials and an enabled plan.'
    if ((Read-Host 'Type START to allow this local worker to run') -cne 'START') { throw 'Worker not started.' }
    docker @compose up -d --build --wait worker
    if ($LASTEXITCODE -ne 0) { throw 'Local worker failed to start.' }
}
Write-Host 'Open http://localhost:9081 . Worker is opt-in; use -StartWorker for rendering and scheduling.'
if ($PairingCode) {
    docker @compose exec backend .venv/bin/dojo-create-pairing-code create-code
    if ($LASTEXITCODE -ne 0) { throw 'Could not create a pairing code. Check local backend logs.' }
}
