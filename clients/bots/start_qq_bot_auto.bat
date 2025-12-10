@echo off

:: XiaoYou QQ机器人自动启动脚本（无需交互）
echo =============================
echo XiaoYou QQ机器人自动启动脚本
echo 自动选择模式1：正常启动机器人
echo =============================

:: 设置颜色
echo.
color 0A
echo 已启用彩色输出
echo.

:: 检查Python环境
echo 正在检查Python环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo 错误: 未找到Python，请先安装Python 3.7或更高版本
    echo 建议访问 https://www.python.org/downloads/ 下载安装
    pause
    exit /b 1
)

:: 显示Python版本
for /f "tokens=2*" %%i in ('python --version') do set python_version=%%i
echo 找到Python版本: %python_version%

:: 切换到正确的目录
set "script_dir=%~dp0"
set "project_root=%script_dir%.."
echo 项目根目录: %project_root%
cd /d "%project_root%" || (
    echo 错误: 无法切换到项目目录
    pause
    exit /b 1
)

:: 创建必要的目录
echo 正在创建必要的目录...
mkdir logs 2>nul
echo 日志目录: logs/
mkdir models 2>nul
echo 模型目录: models/

:: 检查配置文件
if not exist "bots\qq_bot_config.json" (
    echo 警告: 未找到配置文件 bots\qq_bot_config.json
    echo 正在生成配置模板...
    python -m bots.config_loader
    if not exist "bots\qq_bot_config.json" (
        echo 正在复制配置模板...
        copy "bots\qq_bot_config.example.json" "bots\qq_bot_config.json" 2>nul
        if errorlevel 1 (
            echo 错误: 无法创建配置文件
            pause
            exit /b 1
        ) else (
            echo 配置文件已创建，请根据需要修改 bots\qq_bot_config.json
        )
    )
)

echo.
echo 正在启动QQ机器人...
echo 如需停止，请按 Ctrl+C
echo.
python -m bots.qq_bot

echo.
echo 操作完成!