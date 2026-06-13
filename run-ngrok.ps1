param(
    [int]$Port = 8000,
    [string]$Domain = "startup-oversweet-eggshell.ngrok-free.dev",
    [string]$AuthToken = "3F56oDnNvRZeBAWXp4sdivLLhLf_7sGELHNj1HRuTLFNbpKqx"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command ngrok -ErrorAction SilentlyContinue)) {
    Write-Error "ngrok was not found on PATH. Install ngrok or add ngrok.exe to PATH, then run this script again."
}

Write-Host "Configuring ngrok auth token..."
ngrok config add-authtoken $AuthToken

Write-Host "Starting ngrok tunnel:"
Write-Host "  Domain: https://$Domain"
Write-Host "  Target: http://localhost:$Port"

ngrok http --domain=$Domain "http://localhost:$Port"
