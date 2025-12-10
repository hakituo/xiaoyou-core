# 使用国内镜像源下载mirai-login-solver-sakura插件
Write-Host "正在从国内镜像源下载mirai-login-solver-sakura插件..."

# 使用镜像源（GitHub Release的镜像）
$mirrorUrls = @(
    "https://ghproxy.com/https://github.com/KasukuSakura/mirai-login-solver-sakura/releases/latest/download/mirai-login-solver-sakura.jar",
    "https://gh.api.99988866.xyz/https://github.com/KasukuSakura/mirai-login-solver-sakura/releases/latest/download/mirai-login-solver-sakura.jar",
    "https://hub.fgit.ml/KasukuSakura/mirai-login-solver-sakura/releases/latest/download/mirai-login-solver-sakura.jar"
)

$pluginsDir = "$PSScriptRoot\plugins"
$outputPath = "$pluginsDir\mirai-login-solver-sakura.jar"

# 确保plugins目录存在
if (-not (Test-Path $pluginsDir)) {
    New-Item -ItemType Directory -Path $pluginsDir -Force | Out-Null
}

# 尝试从多个镜像源下载
foreach ($mirrorUrl in $mirrorUrls) {
    Write-Host "正在尝试从镜像源下载: $mirrorUrl"
    try {
        Invoke-WebRequest -Uri $mirrorUrl -OutFile $outputPath -UseBasicParsing -TimeoutSec 30
        Write-Host "插件下载成功！"
        Write-Host "插件已保存到: $outputPath"
        
        # 显示安装说明
        Write-Host ""
        Write-Host "安装完成！请重启Mirai Console以加载新插件。"
        Write-Host "重启后，登录时将自动使用Sakura验证器处理验证码。"
        Exit 0
    } catch {
        Write-Host "从该镜像源下载失败: $($_.Exception.Message)"
        Write-Host "尝试下一个镜像源..."
    }
}

# 如果所有镜像源都失败，提示手动下载
Write-Host ""
Write-Host "所有镜像源下载失败！请手动访问以下链接下载："
Write-Host "1. GitHub: https://github.com/KasukuSakura/mirai-login-solver-sakura/releases/latest"
Write-Host "2. 或者搜索 'mirai-login-solver-sakura jar 下载' 使用其他镜像站点"
Write-Host ""
Write-Host "下载后请将jar文件放到: $pluginsDir 目录下"
Write-Host "然后重启Mirai Console"