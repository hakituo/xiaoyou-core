@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

echo =======================================================
echo       Xiaoyou Multi QQ Bot (Aveline + Ling)
echo =======================================================
echo.

set "BASE_DIR=%~dp0"
if "%BASE_DIR:~-1%"=="\" set "BASE_DIR=%BASE_DIR:~0,-1%"
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
echo [INFO] QQ Adapter Python: %PYTHON_EXE%

"%PYTHON_EXE%" -c "import websockets" 2>nul
if !errorlevel! neq 0 (
    echo [INFO] Installing websockets...
    "%PYTHON_EXE%" -m pip install websockets
)

set "QQ_NUMBER_AVELINE="
set "QQ_NUMBER_LING="

if exist ".env" (
    for /f "usebackq tokens=1* delims==" %%a in (".env") do (
        set "KEY=%%a"
        set "VAL=%%b"
        for /f "tokens=* delims= " %%k in ("!KEY!") do set "KEY=%%k"
        if "!KEY!"=="XIAOYOU_QQ_BOT_NUMBER" set "QQ_NUMBER_AVELINE=!VAL!"
        if "!KEY!"=="XIAOYOU_QQ_BOT_NUMBER_LING" set "QQ_NUMBER_LING=!VAL!"
    )
)

if defined QQ_NUMBER_AVELINE set "QQ_NUMBER_AVELINE=!QQ_NUMBER_AVELINE: =!"
if defined QQ_NUMBER_LING set "QQ_NUMBER_LING=!QQ_NUMBER_LING: =!"

echo [1/4] Checking NapCatQQ...

set "NAPCAT_PATH="
set "NAPCAT_WORK_DIR="

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
    echo Please download from https://github.com/NapNeko/NapCatQQ/releases
    echo.
    pause
    exit /b 1
)

echo Found NapCat at: %NAPCAT_WORK_DIR%

echo.
echo [2/4] Starting NapCatQQ - Aveline (port 3001)...
if defined QQ_NUMBER_AVELINE (
    start "NapCat-Aveline" cmd /k "cd /d !NAPCAT_WORK_DIR! && !NAPCAT_PATH! !QQ_NUMBER_AVELINE!"
    echo   QQ: !QQ_NUMBER_AVELINE!
) else (
    start "NapCat-Aveline" cmd /k "cd /d !NAPCAT_WORK_DIR! && !NAPCAT_PATH!"
    echo   No QQ number configured, manual login required
)

echo.
echo [3/4] Starting NapCatQQ - Ling (port 3002)...
echo   Note: Second NapCat needs different data dir and port 3002
if defined QQ_NUMBER_LING (
    start "NapCat-Ling" cmd /k "cd /d !NAPCAT_WORK_DIR! && !NAPCAT_PATH! !QQ_NUMBER_LING!"
    echo   QQ: !QQ_NUMBER_LING!
) else (
    echo   [WARNING] XIAOYOU_QQ_BOT_NUMBER_LING not set in .env
    start "NapCat-Ling" cmd /k "cd /d !NAPCAT_WORK_DIR! && !NAPCAT_PATH!"
)

echo.
echo [4/4] Starting Multi QQ Adapter...
set "MULTI_SCRIPT=%BASE_DIR%\clients\bots\multi_qq_adapter.py"
if not exist "%MULTI_SCRIPT%" (
    echo [ERROR] Script not found: %MULTI_SCRIPT%
    pause
    exit /b 1
)

start "Xiaoyou-MultiQQ" cmd /k "cd /d !BASE_DIR! && !PYTHON_EXE! !MULTI_SCRIPT!"

echo.
echo =======================================================
echo Multi QQ Bot started
echo   Aveline:  NapCat port 3001
echo   Ling:     NapCat port 3002
echo
echo Notes:
echo   1. Two NapCat instances need different WS ports (3001/3002)
echo   2. Two NapCat instances need different QQ accounts
echo   3. Complete login in each NapCat window
echo =======================================================
echo.
exit
