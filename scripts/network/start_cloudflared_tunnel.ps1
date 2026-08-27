# 启动 Cloudflare Tunnel (xiaoyou)
# 用途: 让外网通过 https://api.qishihao.icu 访问本机后端 (http://localhost:8000)
# 用法:
#   直接双击运行, 或在 PowerShell 里:
#     cd D:\AI\xiaoyou-core\scripts\network
#     .\start_cloudflared_tunnel.ps1
# 停止: Ctrl+C 关闭窗口即可 (cloudflared 会主动断开 tunnel 连接)
#
# 前置条件:
#   1. cloudflared 已通过 winget 安装
#   2. 已完成 `cloudflared tunnel login` (~/.cloudflared/cert.pem)
#   3. 已创建 tunnel 'xiaoyou' 并配置好 config.yml
#   4. 后端 FastAPI 服务在 http://localhost:8000 运行中

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Cloudflare Tunnel 启动器 (xiaoyou)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. 检查 cloudflared 是否在 PATH
$cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cloudflared) {
    Write-Host "[X] 未找到 cloudflared, 请先安装:" -ForegroundColor Red
    Write-Host "    winget install Cloudflare.cloudflared"
    exit 1
}
Write-Host "[OK] cloudflared: $($cloudflared.Source)" -ForegroundColor Green

# 2. 检查配置目录
$configDir = Join-Path $env:USERPROFILE ".cloudflared"
$configFile = Join-Path $configDir "config.yml"
if (-not (Test-Path $configFile)) {
    Write-Host "[X] 缺少 config.yml, 路径: $configFile" -ForegroundColor Red
    Write-Host "    请先执行:" -ForegroundColor Yellow
    Write-Host "      cloudflared tunnel login"
    Write-Host "      cloudflared tunnel create xiaoyou"
    exit 1
}
Write-Host "[OK] 配置文件: $configFile" -ForegroundColor Green

# 3. 显示 tunnel 域名映射
Write-Host ""
Write-Host "Tunnel 域名映射:" -ForegroundColor Cyan
Get-Content $configFile | Select-String "hostname|service" | ForEach-Object {
    Write-Host "  $_" -ForegroundColor Gray
}
Write-Host ""

# 4. 提示后端检查
$backendAlive = Test-NetConnection -ComputerName 127.0.0.1 -Port 8000 -WarningAction SilentlyContinue
if (-not $backendAlive.TcpTestSucceeded) {
    Write-Host "[!] 警告: localhost:8000 看起来没在监听, 后端服务可能未启动" -ForegroundColor Yellow
    Write-Host "    请先在另一个终端启动后端: python main.py" -ForegroundColor Yellow
    Write-Host ""
    $continue = Read-Host "仍然启动 tunnel? (y/N)"
    if ($continue -ne "y" -and $continue -ne "Y") { exit 0 }
} else {
    Write-Host "[OK] 后端服务在 localhost:8000 监听中" -ForegroundColor Green
}

# 5. 启动 tunnel
Write-Host ""
Write-Host "启动 tunnel (Ctrl+C 停止)..." -ForegroundColor Cyan
Write-Host "手机端请访问: https://api.qishihao.icu" -ForegroundColor Green
Write-Host "----------------------------------------" -ForegroundColor DarkGray

try {
    & cloudflared tunnel run xiaoyou
} catch {
    Write-Host ""
    Write-Host "[X] tunnel 异常退出: $_" -ForegroundColor Red
    exit 1
} finally {
    Write-Host ""
    Write-Host "tunnel 已停止" -ForegroundColor Yellow
}
