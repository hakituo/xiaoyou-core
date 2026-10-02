$initialDir = Get-Location
# 脚本位于 clients\bots\scripts\，向上三级才是仓库根目录
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$napcatDir = Join-Path $repoRoot "external\NapCatQQ-main"

Write-Host "Setting up NapCatQQ..."

# Check for pnpm, install if missing
if (!(Get-Command pnpm -ErrorAction SilentlyContinue)) {
    Write-Host "pnpm not found. Installing pnpm via npm..."
    npm install -g pnpm
    if (!(Get-Command pnpm -ErrorAction SilentlyContinue)) {
        Write-Host "Failed to install pnpm. Please install it manually: npm install -g pnpm"
        exit 1
    }
}

Set-Location $napcatDir

Write-Host "Installing dependencies using pnpm..."
# 源码更新后 lockfile 可能过期，需 --no-frozen-lockfile 更新 workspace 链接
pnpm install --no-frozen-lockfile

Write-Host "Building NapCat components..."
# NapCatQQ needs to build its components in order
pnpm run build:framework
pnpm run build:shell

if ($LASTEXITCODE -eq 0) {
    Write-Host "Build successful."
} else {
    Write-Host "Build failed. Please check errors."
}

Set-Location $initialDir
Write-Host "Setup complete."
