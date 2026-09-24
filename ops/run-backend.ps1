# Local backend run sharing the same ops/.env as compose.
# Usage: powershell -File ops/run-backend.ps1 [-- extra uvicorn args]
# Requires: DB up via `docker compose --env-file ops/.env -f ops/docker-compose.yml up db`
. "$PSScriptRoot/Load-Env.ps1"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $RepoRoot

$UvicornArgs = @("--host", "127.0.0.1", "--port", "8000", "--reload")
if ($args.Count -gt 0) {
    $UvicornArgs += $args
}

& uv run --project backend python -m uvicorn backend.main:app @UvicornArgs
