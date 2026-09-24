# Connect a Meta dashboard Instagram Login token to an authenticated Dojo backend.
# Secrets are prompted without echo; parameters accept SecureString for automation.
[CmdletBinding()]
param(
    [string]$BaseUrl = 'http://localhost:8000',
    [Security.SecureString]$AppToken,
    [Security.SecureString]$InstagramToken,
    [string]$PairingCode
)

$ErrorActionPreference = 'Stop'
$base = [Uri]$BaseUrl
if (-not $base.IsAbsoluteUri -or $base.UserInfo -or $base.Query -or $base.Fragment -or
    ($base.Scheme -ne 'https' -and -not ($base.Scheme -eq 'http' -and $base.IsLoopback))) {
    throw 'BaseUrl must use HTTPS (HTTP is allowed only for localhost).'
}
if ($PairingCode -and $AppToken) {
    throw 'Use either PairingCode or AppToken.'
}

function ConvertFrom-Secret([Security.SecureString]$Secret) {
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secret)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}

$headers = @{}
$body = $null
$appPlain = $null
$igPlain = $null
$paired = $null
# try {
    if ($PairingCode) {
        $pairBody = @{code=$PairingCode; kind='device'; name='PowerShell'} | ConvertTo-Json -Compress
        $validateUrl = "$($BaseUrl.TrimEnd('/'))/api/pairing/validate"
        $paired = Invoke-RestMethod -Uri $validateUrl `
            -Method Post -ContentType 'application/json' -Body $pairBody `
            -MaximumRedirection 0 -TimeoutSec 30
        $appPlain = $paired.token
        if (-not $appPlain) { throw 'Pairing failed.' }
    } else {
        if (-not $AppToken) {
            $AppToken = Read-Host 'Dojo application Bearer token' -AsSecureString
        }
        $appPlain = ConvertFrom-Secret $AppToken
    }
    if (-not $InstagramToken) {
        $InstagramToken = Read-Host 'Meta dashboard Instagram Login access token' -AsSecureString
    }
    $igPlain = ConvertFrom-Secret $InstagramToken

    $headers = @{Authorization="Bearer $appPlain"}
    $body = @{access_token=$igPlain} | ConvertTo-Json -Compress
    $status = Invoke-RestMethod -Uri "$($BaseUrl.TrimEnd('/'))/api/meta/instagram/token" `
        -Method Post -Headers $headers -ContentType 'application/json' -Body $body `
        -MaximumRedirection 0 -TimeoutSec 60
    # Explicit allowlist: never print any token returned by an unexpected server.
    $status | Select-Object health, connection_type, ig_user_id, ig_username, expires_at
# } catch {
#     # Avoid reflecting HTTP request/response bodies or credential-bearing exceptions.
#     throw 'Instagram connection failed. Check backend URL, Dojo authentication and Instagram permissions.'
# } finally {
#     $headers.Clear()
#     $body = $null
#     $pairBody = $null
#     $appPlain = $null
#     $igPlain = $null
#     $paired = $null
# }
