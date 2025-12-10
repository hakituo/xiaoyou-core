@echo off
title Xiaoyou Web Frontend
echo ==========================================
echo Starting Xiaoyou Web Frontend...
echo ==========================================

:: Set path to current script directory
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%clients\frontend\Aveline_UI"

if %errorlevel% neq 0 (
    echo [ERROR] Could not find frontend directory: %SCRIPT_DIR%clients\frontend\Aveline_UI
    pause
    exit /b
)

echo Working Directory: %CD%
echo Executing: npm run dev
echo.

if exist "node_modules" (
    echo [INFO] node_modules found, skipping npm install.
) else (
    echo [INFO] node_modules not found, running npm install...
    call npm install
)

call npm run dev

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] npm run dev failed with error code %errorlevel%.
    echo Please check if Node.js is installed and 'npm install' has been run.
    pause
)
pause
