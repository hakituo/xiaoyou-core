@echo off
title Xiaoyou Web Frontend
echo ==========================================
echo Starting Xiaoyou Web Frontend...
echo ==========================================
echo.
echo Please choose mode:
echo   1. Development (npm run dev)
echo   2. Preview (npm run preview - requires build)
echo.
set /p MODE="Enter mode (1 or 2, default=1): "

:: Set path to project root directory
set "PROJECT_ROOT=%~dp0.."
set "FRONTEND_DIR=%PROJECT_ROOT%\clients\frontend\aveline-web"
cd /d "%FRONTEND_DIR%"

if %errorlevel% neq 0 (
    echo [ERROR] Could not find frontend directory: %FRONTEND_DIR%
    pause
    exit /b
)

echo Working Directory: %CD%

if "%MODE%"=="2" (
    echo Executing: npm run preview
    echo.
    call npm run preview
) else (
    echo Executing: npm run dev
    echo.
    if exist "node_modules" (
        echo [INFO] node_modules found, skipping npm install.
    ) else (
        echo [INFO] node_modules not found, running npm install...
        call npm install
    )
    call npm run dev
)

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Command failed with error code %errorlevel%.
    echo Please check if Node.js is installed and 'npm install' has been run.
    pause
)
pause
