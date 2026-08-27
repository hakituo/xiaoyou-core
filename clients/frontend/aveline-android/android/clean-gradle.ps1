# 清理Gradle缓存脚本 - 直接删除不经过回收站
# 使用方法: .\clean-gradle.ps1

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Gradle 缓存清理工具" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. 清理项目的 build 目录
$projectBuild = Join-Path $PSScriptRoot "build"
$appBuild = Join-Path $PSScriptRoot "app\build"

Write-Host "正在清理项目 build 目录..." -ForegroundColor Yellow
if (Test-Path $projectBuild) {
    Remove-Item -Path $projectBuild -Recurse -Force
    Write-Host "  ✓ $projectBuild 已删除" -ForegroundColor Green
} else {
    Write-Host "  ✗ $projectBuild 不存在" -ForegroundColor Gray
}

Write-Host "正在清理 app build 目录..." -ForegroundColor Yellow
if (Test-Path $appBuild) {
    Remove-Item -Path $appBuild -Recurse -Force
    Write-Host "  ✓ $appBuild 已删除" -ForegroundColor Green
} else {
    Write-Host "  ✗ $appBuild 不存在" -ForegroundColor Gray
}

# 2. 清理用户目录下的 Gradle 缓存
$gradleCache = Join-Path $env:USERPROFILE ".gradle\caches"
$gradleDaemon = Join-Path $env:USERPROFILE ".gradle\daemon"

Write-Host ""
Write-Host "正在清理 Gradle 缓存..." -ForegroundColor Yellow
if (Test-Path $gradleCache) {
    Remove-Item -Path $gradleCache -Recurse -Force
    Write-Host "  ✓ $gradleCache 已删除" -ForegroundColor Green
} else {
    Write-Host "  ✗ $gradleCache 不存在" -ForegroundColor Gray
}

Write-Host "正在清理 Gradle 守护进程..." -ForegroundColor Yellow
if (Test-Path $gradleDaemon) {
    Remove-Item -Path $gradleDaemon -Recurse -Force
    Write-Host "  ✓ $gradleDaemon 已删除" -ForegroundColor Green
} else {
    Write-Host "  ✗ $gradleDaemon 不存在" -ForegroundColor Gray
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  清理完成！" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "提示: 下次编译会重新下载依赖，可能需要一些时间" -ForegroundColor Yellow
