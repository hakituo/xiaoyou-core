@echo off
setlocal
chcp 65001 > nul

echo =======================================================
echo          Xiaoyou Core - 启动所有服务
echo =======================================================
echo.

:: Get project root directory
set "BASE_DIR=%~dp0.."
:: Remove trailing backslash if present
if "%BASE_DIR:~-1%"=="\" set "BASE_DIR=%BASE_DIR:~0,-1%"

echo Current Directory: %BASE_DIR%
cd /d "%BASE_DIR%"

:: Check Python Environment
set "PYTHON_EXE=%BASE_DIR%\venv_core\Scripts\python.exe"
if not exist "%PYTHON_EXE%" goto PYTHON_MISSING

echo Using Python: %PYTHON_EXE%
echo.

echo [INFO] 正在启动所有服务...
echo.

:: 1. 启动 TTS (调用 start_tts.bat)
echo [1/4] 启动 TTS 服务...
if exist "%BASE_DIR%\start_scripts\start_tts.bat" (
    call "%BASE_DIR%\start_scripts\start_tts.bat"
) else (
    echo [WARNING] start_tts.bat 不存在，跳过 TTS 启动.
)

:: 等待 2 秒
timeout /t 2 /nobreak > nul

:: 2. 启动 Forge (调用 start_forge.bat)
echo [2/4] 启动 Forge 画图服务...
if exist "%BASE_DIR%\start_scripts\start_forge.bat" (
    call "%BASE_DIR%\start_scripts\start_forge.bat"
) else (
    echo [WARNING] start_forge.bat 不存在，跳过 Forge 启动.
)

:: 等待 2 秒
timeout /t 2 /nobreak > nul

:: 3. 启动主程序 (直接启动)
echo [3/4] 正在启动 Xiaoyou 主程序...
start "Xiaoyou Core Main" /D "%BASE_DIR%" cmd /k ""%PYTHON_EXE%" main.py"

:: 等待 2 秒
timeout /t 2 /nobreak > nul

:: 4. 启动前端 (调用 start_web.bat)
echo [4/4] 正在启动前端页面...
set "FRONTEND_DIR=%BASE_DIR%\clients\frontend\aveline-web"

if exist "%FRONTEND_DIR%" (
    if exist "%BASE_DIR%\start_scripts\start_web.bat" (
        echo [INFO] 正在启动前端开发服务器...
        start "Xiaoyou Web" "%BASE_DIR%\start_scripts\start_web.bat"
        goto FINISH
    ) else (
        echo [WARNING] start_web.bat 不存在，跳过前端启动.
        goto FINISH
    )
) else (
    echo [WARNING] 未找到前端目录: %FRONTEND_DIR%
    echo 跳过前端启动.
    goto FINISH
)

:PYTHON_MISSING
echo [ERROR] 未找到 Python 环境: %PYTHON_EXE%
echo 请确保 venv_core 已正确安装.
pause
exit /b 1

:FINISH
echo.
echo =======================================================
echo 所有启动命令已发送.
echo 启动脚本将在 3 秒后自动关闭...
echo =======================================================
timeout /t 3 /nobreak > nul
exit
