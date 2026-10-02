# Telegram 独立调试启动脚本。
# 正常运行时由 main.py 根据 config/yaml/app.yaml 的 telegram.enabled 直接托管，
# 不需要另开终端，也不要与本脚本同时运行，否则 Telegram getUpdates 会互相抢占。

$ErrorActionPreference = "Stop"
$PROJECT_ROOT = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\.."))
$APP_CONFIG = Join-Path $PROJECT_ROOT "config\yaml\app.yaml"
$PYTHON = Join-Path $PROJECT_ROOT "venv_core\Scripts\python.exe"

Write-Host "小优 Telegram 独立调试启动器" -ForegroundColor Cyan
Write-Host "提示：主程序已启用 Telegram 时，请先关闭主程序中的 Telegram 托管。" -ForegroundColor Yellow

if (-not (Test-Path -LiteralPath $APP_CONFIG)) {
    Write-Error "未找到统一配置文件：$APP_CONFIG"
}
if (-not (Test-Path -LiteralPath $PYTHON)) {
    Write-Error "未找到 venv_core：$PYTHON。请先按项目说明准备虚拟环境。"
}

$envFile = Join-Path $PROJECT_ROOT ".env"
if (-not (Test-Path -LiteralPath $envFile)) {
    Write-Warning "未找到 .env；请确认 TELEGRAM_BOT_TOKEN 已通过环境变量提供。"
} else {
    Write-Host "已找到 .env（不会显示任何敏感值）。" -ForegroundColor Green
}

Set-Location -LiteralPath $PROJECT_ROOT
& $PYTHON -m clients.bots.telegram.adapter
exit $LASTEXITCODE
