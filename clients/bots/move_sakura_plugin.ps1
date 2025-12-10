# 移动sakura插件到正确目录的脚本
Write-Host "===== Mirai Login Solver Sakura 插件移动脚本 ====="
Write-Host "请确保你已从GitHub下载了mirai-login-solver-sakura-0.0.12.mirai2.jar文件"
Write-Host "并将其保存在当前目录(D:\AI\xiaoyou-core\bots)中"

# 定义变量
$pluginName = "mirai-login-solver-sakura-0.0.12.mirai2.jar"
$pluginPath = Join-Path -Path $PWD -ChildPath $pluginName
$targetDir = Join-Path -Path $PWD -ChildPath "plugins"
$targetPath = Join-Path -Path $targetDir -ChildPath $pluginName

# 检查插件文件是否存在
if (Test-Path $pluginPath) {
    # 检查plugins目录是否存在
    if (-not (Test-Path $targetDir)) {
        Write-Host "创建plugins目录..."
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    }
    
    # 移动文件
    Write-Host "正在将插件文件移动到plugins目录..."
    Copy-Item -Path $pluginPath -Destination $targetPath -Force
    
    # 检查是否成功
    if (Test-Path $targetPath) {
        Write-Host "✅ 插件文件已成功移动到: $targetPath"
        Write-Host "请重启Mirai Console以加载新插件"
        Write-Host "重启命令: cd d:\AI\xiaoyou-core\bots && .\start_mirai.bat"
    } else {
        Write-Host "❌ 插件文件移动失败，请检查权限"
    }
} else {
    Write-Host "❌ 未找到插件文件: $pluginPath"
    Write-Host "请从GitHub下载mirai-login-solver-sakura-0.0.12.mirai2.jar文件"
    Write-Host "下载链接: https://github.com/KasukuSakura/mirai-login-solver-sakura/releases/download/v0.0.12/mirai-login-solver-sakura-0.0.12.mirai2.jar"
    Write-Host "下载后请将文件放入D:\AI\xiaoyou-core\bots目录"
}

Write-Host ""
Write-Host "按任意键退出..."
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')