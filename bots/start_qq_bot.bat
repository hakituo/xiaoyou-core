@echo off

:: XiaoYou QQ机器人启动脚本
:: 此脚本用于快速启动QQ机器人服务

echo =============================
echo XiaoYou QQ机器人启动脚本
set script_version=1.0
echo 版本: %script_version%
echo =============================

:: 设置颜色
echo.
set /p enable_color=是否启用彩色输出? (Y/N): 
if /i "%enable_color%"=="Y" (
    color 0A
    echo 已启用彩色输出
) else (
    color 07
    echo 使用默认颜色
)

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
:: 显示启动选项
echo 启动选项:
echo 1. 正常启动机器人
echo 2. 启动并显示详细日志
echo 3. 仅生成配置模板
echo 4. 检查依赖安装

set /p option=请选择操作 (1-4, 默认 1): 
if not defined option set option=1

echo.
:: 根据选项执行操作
if "%option%"=="1" (
    echo 正在启动QQ机器人...
    echo 如需停止，请按 Ctrl+C
    echo.
    python -m bots.qq_bot
    
) else if "%option%"=="2" (
    echo 正在启动QQ机器人（详细日志模式）...
    echo 如需停止，请按 Ctrl+C
    echo.
    set XIAOYOU_QQ_LOGGING_LEVEL=DEBUG
    python -m bots.qq_bot
    
) else if "%option%"=="3" (
    echo 正在生成配置模板...
    python -m bots.config_loader
    echo 配置模板已生成: bots\qq_bot_config.example.json
    echo 请复制为 bots\qq_bot_config.json 并进行配置
    
) else if "%option%"=="4" (
    echo 正在检查依赖...
    echo 请确保已安装所有必要的Python依赖
    echo 推荐使用以下命令安装依赖:
    echo pip install -r requirements.txt
    
    :: 检查关键依赖
    echo.
    echo 检查关键依赖:
    pip show aiohttp >nul 2>&1
    if errorlevel 1 (
        echo - aiohttp: 未安装
    ) else (
        echo - aiohttp: 已安装
    )
    
    pip show websockets >nul 2>&1
    if errorlevel 1 (
        echo - websockets: 未安装
    ) else (
        echo - websockets: 已安装
    )
    
    pip show requests >nul 2>&1
    if errorlevel 1 (
        echo - requests: 未安装
    ) else (
        echo - requests: 已安装
    )
    
    pip show python-dotenv >nul 2>&1
    if errorlevel 1 (
        echo - python-dotenv: 未安装
    ) else (
        echo - python-dotenv: 已安装
    )
    
    echo.
    echo 可选依赖:
    pip show transformers >nul 2>&1
    if errorlevel 1 (
        echo - transformers: 未安装 如需使用transformers模型框架，请安装
    ) else (
        echo - transformers: 已安装
    )
    
) else (
    echo 无效的选项
    pause
    exit /b 1
)

echo.
echo 操作完成!
pause