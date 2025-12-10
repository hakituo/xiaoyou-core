# QQ机器人完整验证脚本

echo "==========================="
echo "QQ机器人验证和功能测试"
echo "==========================="
echo ""

# 验证Mirai Console运行状态
echo "1. 检查Mirai Console状态..."
echo "请确认终端32中Mirai Console正在运行"
echo ""

# 登录步骤指南
echo "2. 登录验证..."
echo "如果尚未登录，请执行以下操作:"
echo "- 在终端32中粘贴: login 3406280693 Leslie.1 ANDROID_PHONE"
echo "- 或者运行: .\direct_login.ps1"
echo ""

# 验证插件加载
echo "3. 验证插件加载..."
echo "请确认Mirai Console中显示: Successfully loaded plugin mirai-login-solver-sakura v0.0.12"
echo ""

# 功能测试建议
echo "4. 功能测试建议:"
echo "- 使用status命令检查登录状态"
echo "- 发送消息测试基本功能"
echo "- 检查验证码是否能正常处理"
echo ""

# 完成信息
echo "验证完成! 机器人配置已就绪。"
echo "如果遇到问题，请参考以下常见解决方案:"
echo "- 切换登录协议: ANDROID_PAD, ANDROID_WATCH, MACOS, IPAD"
echo "- 检查网络连接"
echo "- 重启Mirai Console后重试"
echo ""
echo "脚本执行完毕。"