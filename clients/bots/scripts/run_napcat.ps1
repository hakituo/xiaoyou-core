# 脚本位于 clients\bots\scripts\，向上三级才是仓库根目录
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$napcatDir = Join-Path $repoRoot "external\NapCatQQ-main\packages\napcat-shell\dist"
Set-Location $napcatDir

Write-Host "Starting NapCatQQ Launcher..."
Write-Host "Note: You may need to login to QQ in the opened window."
# Run the launcher. This will likely open a new window or run in the current one.
# If it needs admin, it handles it internally.
.\launcher.bat
