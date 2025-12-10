# 下载并安装mirai-login-solver-sakura插件
Write-Host "正在下载mirai-login-solver-sakura插件..."

# 插件下载链接（使用最新版本）
$pluginUrl = "https://github.com/KasukuSakura/mirai-login-solver-sakura/releases/latest/download/mirai-login-solver-sakura.jar"
$pluginsDir = "$PSScriptRoot\plugins"
$outputPath = "$pluginsDir\mirai-login-solver-sakura.jar"

# 确保plugins目录存在
if (-not (Test-Path $pluginsDir)) {
    New-Item -ItemType Directory -Path $pluginsDir -Force | Out-Null
}

# 下载插件
try {
    Invoke-WebRequest -Uri $pluginUrl -OutFile $outputPath -UseBasicParsing
    Write-Host "插件下载成功！"
    Write-Host "插件已保存到: $outputPath"
    
    # 显示安装说明
    Write-Host ""
    Write-Host "安装完成！请重启Mirai Console以加载新插件。"
    Write-Host "重启后，登录时将自动使用Sakura验证器处理验证码。"
    Write-Host ""
    Write-Host "如果需要验证码，可能会弹出窗口或显示链接，请按照提示操作。"
} catch {
    Write-Host "下载失败！错误信息：$($_.Exception.Message)"
    Write-Host "请手动访问以下链接下载："
    Write-Host "https://github.com/KasukuSakura/mirai-login-solver-sakura/releases/latest"
}