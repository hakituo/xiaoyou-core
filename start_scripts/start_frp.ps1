# Xiaoyou Core FRP Start Script
$ErrorActionPreference = "Continue"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Xiaoyou Core FRP Start Script" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

$FRP_EXE = ".\external\frpc.exe"
$FRP_CONFIG = ".\external\frpc.toml"

if (-not (Test-Path $FRP_EXE)) {
    Write-Host "[Error] frpc.exe not found in external directory." -ForegroundColor Red
    Write-Host "Please make sure frpc.exe is in the external folder."
    Read-Host "Press Enter to exit"
    exit
}

if (-not (Test-Path $FRP_CONFIG)) {
    Write-Host "[Error] frpc.toml not found in external directory." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit
}

Write-Host "[Status] Connecting to qishihao.icu:17000..." -ForegroundColor Green
Write-Host "[Status] Mapping Local Backend (API: 8000, WS: 8999) to Remote..." -ForegroundColor Gray
Write-Host "[Status] Remote API: 18000 | Remote WS: 18999"
Write-Host ""

& $FRP_EXE -c $FRP_CONFIG
exit $LASTEXITCODE
