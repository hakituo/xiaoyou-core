# QQ机器人状态验证脚本
Write-Host "===== QQ机器人状态验证脚本 ====="
Write-Host "请确保你已经在Mirai Console中成功登录了QQ账号"
Write-Host ""

# 定义变量
$botDir = $PWD
$configFile = Join-Path -Path $botDir -ChildPath "qq_bot_config.json"

# 检查配置文件是否存在
if (Test-Path $configFile) {
    Write-Host "✅ 找到QQ机器人配置文件: $configFile"
    Write-Host ""
    Write-Host "验证步骤："
    Write-Host "1. 确保Mirai Console中QQ账号已成功登录"
    Write-Host "2. 在Mirai Console中输入 'status' 命令检查登录状态"
    Write-Host "3. 登录成功后，可以运行以下命令启动QQ机器人:"
    Write-Host "   cd d:\AI\xiaoyou-core\bots && .\start_qq_bot.bat"
    Write-Host ""
    Write-Host "常见问题排查："
    Write-Host "- 如果遇到验证码问题，确保mirai-login-solver-sakura插件已正确加载"
    Write-Host "- 如果登录失败，可以尝试其他协议：ANDROID_WATCH、IPAD、ANDROID_PAD"
    Write-Host "- 确保网络连接正常，并且没有防火墙阻止Mirai的网络请求"
} else {
    Write-Host "❌ 未找到QQ机器人配置文件: $configFile"
    Write-Host "请确保配置文件已正确创建"
}

Write-Host ""
Write-Host "按任意键退出..."
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')