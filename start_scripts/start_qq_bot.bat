@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

echo =======================================================
echo          Xiaoyou QQ Bot Integration
echo =======================================================
echo.

:: Get project root directory correctly
set "BASE_DIR=%~dp0.."
:: Remove trailing backslash if present
if "%BASE_DIR:~-1%"=="\" set "BASE_DIR=%BASE_DIR:~0,-1%"

echo Current Directory: %BASE_DIR%
cd /d "%BASE_DIR%"

:: Match start.bat: prefer the CPU environment, then fall back to venv_core.
set "VENV=venv_cpu"
if not exist "%BASE_DIR%\%VENV%\Scripts\python.exe" set "VENV=venv_core"
set "PYTHON_EXE=%BASE_DIR%\%VENV%\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    echo [ERROR] Neither venv_cpu nor venv_core was found under %BASE_DIR%
    exit /b 1
)
echo [INFO] QQ Adapter Python: %PYTHON_EXE%

:: Read QQ Number from .env using a safer method
set "QQ_NUMBER="
if exist ".env" (
    for /f "tokens=1* delims==" %%a in ('type ".env" ^| findstr "XIAOYOU_QQ_BOT_NUMBER"') do (
        set "KEY=%%a"
        set "VAL=%%b"
        :: Trim whitespace
        for /f "tokens=* delims= " %%k in ("!KEY!") do set "KEY=%%k"
        if "!KEY!"=="XIAOYOU_QQ_BOT_NUMBER" set "QQ_NUMBER=!VAL!"
    )
)

:: Clean up QQ Number (remove spaces)
if defined QQ_NUMBER (
    set "QQ_NUMBER=%QQ_NUMBER: =%"
)

:: 1. Check dependencies
echo [1/3] Checking dependencies...
"%PYTHON_EXE%" -c "import websockets" 2>nul
if %errorlevel% neq 0 (
    echo [INFO] Installing required websockets library...
    "%PYTHON_EXE%" -m pip install websockets
)

:: 2. Start NapCatQQ
echo [2/3] Starting NapCatQQ...
set "NAPCAT_PATH="
set "NAPCAT_WORK_DIR="

:: Check common NapCat locations
if exist "%BASE_DIR%\external\NapCatQQ-main\packages\napcat-shell\dist\launcher.bat" (
    set "NAPCAT_PATH=launcher.bat"
    set "NAPCAT_WORK_DIR=%BASE_DIR%\external\NapCatQQ-main\packages\napcat-shell\dist"
) else if exist "%BASE_DIR%\external\NapCatQQ-main\launcher.bat" (
    set "NAPCAT_PATH=launcher.bat"
    set "NAPCAT_WORK_DIR=%BASE_DIR%\external\NapCatQQ-main"
) else if exist "%BASE_DIR%\external\NapCatQQ\launcher.bat" (
    set "NAPCAT_PATH=launcher.bat"
    set "NAPCAT_WORK_DIR=%BASE_DIR%\external\NapCatQQ"
)

if not defined NAPCAT_PATH (
    echo.
    echo [ERROR] NapCatQQ not found!
    echo.
    echo Please ensure NapCatQQ is installed in 'external\NapCatQQ-main' or 'external\NapCatQQ'.
    echo NOTE: You may have downloaded the Source Code instead of the Release version.
    echo Please download the latest Release zip from https://github.com/NapNeko/NapCatQQ/releases
    echo and extract it to: %BASE_DIR%\external\NapCatQQ-main
    echo.
    pause
    exit /b 1
)

echo Found NapCat at: %NAPCAT_WORK_DIR%

if defined QQ_NUMBER (
    echo [INFO] Attempting login for QQ: %QQ_NUMBER%
    start "NapCatQQ" cmd /k "cd /d "%NAPCAT_WORK_DIR%" && %NAPCAT_PATH% %QQ_NUMBER%"
) else (
    start "NapCatQQ" cmd /k "cd /d "%NAPCAT_WORK_DIR%" && %NAPCAT_PATH%"
)

echo Waiting for NapCatQQ to initialize (5 seconds)...
timeout /t 5 /nobreak > nul

:: 3. Start QQ Adapter
echo [3/3] Starting QQ Adapter...
set "ADAPTER_SCRIPT=%BASE_DIR%\clients\bots\multi_qq_adapter.py"
if not exist "%ADAPTER_SCRIPT%" (
    echo [ERROR] Adapter script not found: %ADAPTER_SCRIPT%
    pause
    exit /b 1
)

start "Xiaoyou QQ Adapter" cmd /k "cd /d "%BASE_DIR%" && "%PYTHON_EXE%" "%ADAPTER_SCRIPT%""

echo.
echo =======================================================
echo QQ Bot Integration started.
echo 1. Check NapCatQQ window for login status.
echo 2. Check Adapter window for connection to Xiaoyou Core.
echo =======================================================
echo.
timeout /t 3
exit

