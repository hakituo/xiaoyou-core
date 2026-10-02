@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

REM Path resolution: works from repo root or start_scripts, anchored on main.py
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
if exist "%SCRIPT_DIR%\main.py" (
    set "BASE_DIR=%SCRIPT_DIR%"
) else if exist "%SCRIPT_DIR%\..\main.py" (
    set "BASE_DIR=%SCRIPT_DIR%\.."
) else (
    echo [ERROR] Cannot locate project root - main.py is not in the script dir or its parent
    pause
    exit /b 1
)
for %%I in ("%BASE_DIR%") do set "BASE_DIR=%%~fI"
cd /d "%BASE_DIR%"

REM Match start.bat: prefer the CPU environment, then fall back to venv_core.
set "VENV=venv_cpu"
if not exist "%BASE_DIR%\%VENV%\Scripts\python.exe" set "VENV=venv_core"
set "PYTHON_EXE=%BASE_DIR%\%VENV%\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    echo [ERROR] Neither venv_cpu nor venv_core was found under %BASE_DIR%
    pause
    exit /b 1
)
echo [INFO] QQ Official Adapter Python: %PYTHON_EXE%

echo.
echo Select bot to start:
echo   1. XiaoLu (bot1)
echo   2. YeYe (bot2)
echo   3. Both
echo.
set /p choice="Enter (1/2/3): "

if "%choice%"=="1" (
    start "bot1" cmd /c "cd /d "%BASE_DIR%" && "%PYTHON_EXE%" -m clients.bots.qq_official.adapter --role_id bot1"
) else if "%choice%"=="2" (
    start "bot2" cmd /c "cd /d "%BASE_DIR%" && "%PYTHON_EXE%" -m clients.bots.qq_official.adapter --role_id bot2"
) else if "%choice%"=="3" (
    start "bot1" cmd /c "cd /d "%BASE_DIR%" && "%PYTHON_EXE%" -m clients.bots.qq_official.adapter --role_id bot1"
    start "bot2" cmd /c "cd /d "%BASE_DIR%" && "%PYTHON_EXE%" -m clients.bots.qq_official.adapter --role_id bot2"
)

exit /b 0
