@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

echo =======================================================
echo       Xiaoyou Rushuang + Yeye NapCat (3003 / 3004)
echo =======================================================
echo.

set "BASE_DIR=%~dp0"
if "%BASE_DIR:~-1%"=="\" set "BASE_DIR=%BASE_DIR:~0,-1%"
cd /d "%BASE_DIR%"

set "QQ_NUMBER_RUSHUANG="
set "QQ_NUMBER_YEYE="

if exist ".env" (
    for /f "usebackq tokens=1* delims==" %%a in (".env") do (
        set "KEY=%%a"
        set "VAL=%%b"
        for /f "tokens=* delims= " %%k in ("!KEY!") do set "KEY=%%k"
        if "!KEY!"=="XIAOYOU_QQ_BOT_NUMBER_RUSHUANG" set "QQ_NUMBER_RUSHUANG=!VAL!"
        if "!KEY!"=="XIAOYOU_QQ_BOT_NUMBER_YEYE" set "QQ_NUMBER_YEYE=!VAL!"
    )
)

if defined QQ_NUMBER_RUSHUANG set "QQ_NUMBER_RUSHUANG=!QQ_NUMBER_RUSHUANG: =!"
if defined QQ_NUMBER_YEYE set "QQ_NUMBER_YEYE=!QQ_NUMBER_YEYE: =!"

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
    pause
    exit /b 1
)

echo Found NapCat at: %NAPCAT_WORK_DIR%
echo.

echo [1/2] Starting NapCatQQ - Rushuang (port 3003)...
if defined QQ_NUMBER_RUSHUANG (
    start "NapCat-Rushuang" cmd /k "cd /d !NAPCAT_WORK_DIR! && !NAPCAT_PATH! !QQ_NUMBER_RUSHUANG!"
    echo   QQ: !QQ_NUMBER_RUSHUANG!
) else (
    echo   [WARNING] XIAOYOU_QQ_BOT_NUMBER_RUSHUANG not set in .env
    start "NapCat-Rushuang" cmd /k "cd /d !NAPCAT_WORK_DIR! && !NAPCAT_PATH!"
)

echo.
echo [2/2] Starting NapCatQQ - Yeye (port 3004)...
if defined QQ_NUMBER_YEYE (
    start "NapCat-Yeye" cmd /k "cd /d !NAPCAT_WORK_DIR! && !NAPCAT_PATH! !QQ_NUMBER_YEYE!"
    echo   QQ: !QQ_NUMBER_YEYE!
) else (
    echo   [WARNING] XIAOYOU_QQ_BOT_NUMBER_YEYE not set in .env
    start "NapCat-Yeye" cmd /k "cd /d !NAPCAT_WORK_DIR! && !NAPCAT_PATH!"
)

echo.
echo =======================================================
echo Rushuang + Yeye NapCat started
echo   Rushuang: NapCat port 3003
echo   Yeye:     NapCat port 3004
echo =======================================================
exit
