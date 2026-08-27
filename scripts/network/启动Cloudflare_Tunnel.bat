@echo off
chcp 65001 >nul
REM 双击启动 Cloudflare Tunnel (xiaoyou)
REM 关闭此窗口即停止 tunnel
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_cloudflared_tunnel.ps1"
pause
