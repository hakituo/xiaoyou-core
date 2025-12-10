@echo off

:: XiaoYou QQ机器人增强启动脚本
:: 处理签名服务器配置和登录问题

echo =============================
echo XiaoYou QQ机器人增强启动脚本
echo =============================

:: 切换到脚本所在目录
cd /d "%~dp0"

:: 显示当前配置
set /p dummy=按任意键显示当前配置信息...
echo 当前QQ账号: 3906331448
echo 使用协议: iOS (protocol: 2)
echo 注意: 需要签名服务器来解决登录45错误码

:: 提供签名服务器配置说明
echo.
echo =============================
echo 签名服务器配置说明:
echo 1. 如果你有签名服务器，请修改config.yml中的sign-server部分
echo 2. 或者可以尝试使用go-cqhttp的device.json修改设备信息
echo 3. 也可以尝试使用账号密码登录（非扫码方式）
echo =============================

:: 提供选择
set /p login_choice=请选择登录方式 [1:扫码登录 2:账号密码登录]: 

:: 根据选择进行相应操作
if /i "%login_choice%"=="1" (
    echo 正在以扫码方式启动go-cqhttp...
    go-cqhttp.exe
) else if /i "%login_choice%"=="2" (
    echo 请修改config.yml文件，在password字段填入您的QQ密码
    echo 按任意键继续...
    pause
    notepad config.yml
    echo 修改完成后，请重新运行此脚本
    pause
    exit /b
) else (
    echo 无效选择，默认使用扫码登录...
    go-cqhttp.exe
)

:: 处理退出
if errorlevel 1 (
    echo 登录失败，请检查以下几点：
    echo 1. 确保使用有效的签名服务器
    echo 2. 尝试更新go-cqhttp到最新版本
    echo 3. 或者尝试使用账号密码登录方式
    pause
) else (
    echo 登录成功！
    echo QQ机器人已启动
    pause
)