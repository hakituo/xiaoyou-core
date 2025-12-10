@echo off
title Xiaoyou Desktop Pet
echo ==========================================
echo Starting Xiaoyou Desktop Pet (Electron)...
echo ==========================================

:: Set path to current script directory
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%clients\frontend\Aveline_UI"

if %errorlevel% neq 0 (
    echo [ERROR] Could not find frontend directory: %SCRIPT_DIR%clients\frontend\Aveline_UI
    pause
    exit /b
)

:: Check if port 3001 is open
echo Checking if Frontend Server is running on port 3001...
powershell -Command "$tcp = New-Object System.Net.Sockets.TcpClient; try { $tcp.Connect('127.0.0.1', 3001); $tcp.Close(); exit 0 } catch { exit 1 }"

if %errorlevel% neq 0 (
    echo [INFO] Frontend Server not detected on port 3001.
    echo [INFO] Starting Frontend Server...
    
    if exist "%SCRIPT_DIR%start_web.bat" (
        start "Xiaoyou Web" "%SCRIPT_DIR%start_web.bat"
    ) else (
        echo [ERROR] start_web.bat not found at %SCRIPT_DIR%start_web.bat
        echo Please manually start the frontend server.
    )
    
    echo [INFO] Waiting for Frontend Server to be ready...
    set "MAX_RETRIES=30"
    set "RETRY_COUNT=0"
    
    :CHECK_PORT
    timeout /t 2 /nobreak > nul
    powershell -Command "$tcp = New-Object System.Net.Sockets.TcpClient; try { $tcp.Connect('127.0.0.1', 3001); $tcp.Close(); exit 0 } catch { exit 1 }"
    if %errorlevel% equ 0 goto PORT_READY
    
    set /a RETRY_COUNT+=1
    echo Waiting for port 3001... (%RETRY_COUNT%/%MAX_RETRIES%)
    
    if %RETRY_COUNT% lss %MAX_RETRIES% goto CHECK_PORT
    
    echo [WARNING] Timeout waiting for Frontend Server.
    echo [WARNING] Launching Electron anyway...
) else (
    echo [INFO] Frontend Server is already running.
)

:PORT_READY
echo [INFO] Frontend Server is ready!

echo.
echo Working Directory: %CD%
echo Executing: npm run electron:dev
echo.

call npm run electron:dev

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] npm run electron:dev failed with error code %errorlevel%.
    echo Please check if Node.js is installed and 'npm install' has been run.
    pause
)
pause
