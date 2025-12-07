# QQ机器人登录卡住故障排查脚本
# 当登录过程卡在PoW计算后不动时使用此脚本

Write-Output "===== QQ机器人登录故障排查工具 ====="
Write-Output "当登录过程卡在PoW计算后不动时，请尝试以下解决方案："
Write-Output ""

# 问题分析
Write-Output "【问题分析】"
Write-Output "- PoW计算完成后，登录过程通常会进入验证码验证阶段"
Write-Output "- 卡住可能是因为需要手动验证码验证，但终端没有显示提示"
Write-Output "- 也可能是网络连接问题或账号安全验证"
Write-Output ""

# 解决方案1：检查验证码文件
Write-Output "【解决方案1：检查验证码文件】"
Write-Output "在Mirai Console目录下查找验证码图片文件，通常在以下位置："
Write-Output "- ./bots/3406280693/verify.png 或类似名称的图片文件"
Write-Output "- 如果找到验证码图片，请手动打开并输入验证码到控制台"
Write-Output ""

# 解决方案2：重启并使用二维码登录
Write-Output "【解决方案2：使用二维码登录】"
Write-Output "如果账号支持扫码登录，尝试以下命令："
Write-Output "1. 先停止当前登录进程（Ctrl+C）"
Write-Output "2. 使用以下命令进行二维码登录："
Write-Output "   login 3406280693 --protocol ANDROID_PHONE --qrcode"
Write-Output "3. 然后使用手机QQ扫描生成的二维码图片"
Write-Output ""

# 解决方案3：使用不同协议重试
Write-Output "【解决方案3：尝试不同的登录协议】"
Write-Output "尝试使用这些协议组合："
Write-Output "- login 3406280693 Leslie.1 ANDROID_PAD"
Write-Output "- login 3406280693 Leslie.1 ANDROID_WATCH"
Write-Output "- login 3406280693 Leslie.1 IPAD"
Write-Output ""

# 解决方案4：清理缓存后重试
Write-Output "【解决方案4：清理登录缓存】"
Write-Output "执行以下步骤清理缓存后重试："
Write-Output "1. 停止Mirai Console（Ctrl+C）"
Write-Output "2. 删除或重命名以下目录："
Write-Output "   - ./bots/3406280693/"
Write-Output "   - ./device.json（如果存在）"
Write-Output "3. 重启Mirai Console并使用原始命令登录"
Write-Output ""

# 解决方案5：检查网络连接
Write-Output "【解决方案5：检查网络连接】"
Write-Output "- 确保网络连接稳定，特别是对腾讯服务器的访问"
Write-Output "- 检查是否有防火墙或代理阻止了连接"
Write-Output "- 尝试重启网络设备后重试"
Write-Output ""

# 紧急方案：使用备用账号或等待
Write-Output "【紧急方案】"
Write-Output "如果以上方法都无效，可以考虑："
Write-Output "1. 使用备用QQ账号进行测试"
Write-Output "2. 等待一段时间（几小时或第二天）后再尝试，可能是腾讯的临时限制"
Write-Output "3. 检查账号是否被临时冻结，可尝试在手机QQ上登录确认"
Write-Output ""

Write-Output "===== 故障排查结束 ====="
Write-Output "如果问题仍然存在，请检查Mirai Console的完整日志以获取更多错误信息。"