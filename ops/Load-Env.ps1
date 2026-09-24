# Loads ops/.env into process env for local (terminal) runs.
# Dot-source from another script: . "$PSScriptRoot/Load-Env.ps1"
# Single source of truth stays ops/.env (same file compose uses).
param(
    [string]$EnvFile = (Join-Path $PSScriptRoot ".env")
)

if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "Env file not found: $EnvFile. Copy ops/.env.example to ops/.env first."
}

# Explicitly exported vars win over the file (12-factor precedence).
$preDatabaseUrl = $Env:DATABASE_URL
$preCookieSecure = $Env:COOKIE_SECURE

foreach ($line in (Get-Content -LiteralPath $EnvFile)) {
    $trimmed = $line.Trim()
    if ($trimmed -eq "" -or $trimmed.StartsWith("#")) { continue; }
    if ($trimmed.StartsWith("export ")) {
        $trimmed = $trimmed.Substring(7).Trim()
    }
    $eq = $trimmed.IndexOf("=")
    if ($eq -lt 1) { continue; }
    $name = $trimmed.Substring(0, $eq).Trim()
    $value = $trimmed.Substring($eq + 1).Trim()
    if ($value.Length -ge 2) {
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
    }
    if ($name -eq "DATABASE_URL" -and -not [string]::IsNullOrWhiteSpace($preDatabaseUrl) -and -not $preDatabaseUrl.Contains("@db:")) { continue; }
    if ($name -eq "COOKIE_SECURE" -and -not [string]::IsNullOrWhiteSpace($preCookieSecure)) { continue; }
    Set-Item -Path "Env:$name" -Value $value
}

if ([string]::IsNullOrWhiteSpace($Env:POSTGRES_PASSWORD)) {
    throw "POSTGRES_PASSWORD is empty after loading $EnvFile."
}

# DATABASE_URL cannot be shared verbatim: compose uses @db:5432, local uses @localhost:5434.
# Derive the local variant unless caller already set an explicit non-compose URL.
$currentDb = $Env:DATABASE_URL
if ([string]::IsNullOrWhiteSpace($currentDb) -or $currentDb.Contains("@db:")) {
    $Env:DATABASE_URL = "postgresql+psycopg://dojo:$($Env:POSTGRES_PASSWORD)@localhost:5434/dojo"
}

# Local dev runs over plain http, so secure cookies would never stick.
if ([string]::IsNullOrWhiteSpace($Env:COOKIE_SECURE)) {
    $Env:COOKIE_SECURE = "false"
}
