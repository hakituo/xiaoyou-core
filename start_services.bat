@echo off
setlocal

echo =======================================================
echo          Xiaoyou Core Startup Script
echo =======================================================
echo.

:: Get current directory
set "BASE_DIR=%~dp0"
:: Remove trailing backslash if present
if "%BASE_DIR:~-1%"=="\" set "BASE_DIR=%BASE_DIR:~0,-1%"

echo Current Directory: %BASE_DIR%
cd /d "%BASE_DIR%"

:: Check Python Environment
set "PYTHON_EXE=%BASE_DIR%\venv_core\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python environment not found: %PYTHON_EXE%
    echo Please ensure venv_core is correctly installed.
    pause
    exit /b 1
)

echo Using Python: %PYTHON_EXE%
echo.

:: 1. Start GPT-SoVITS Service
echo [1/3] Starting GPT-SoVITS Service...
set "TTS_DIR=%BASE_DIR%\models\GPT-SoVITS-v2pro-20250604-nvidia50"

if not exist "%TTS_DIR%" (
    echo [ERROR] GPT-SoVITS directory not found: %TTS_DIR%
    pause
    exit /b 1
)

start "GPT-SoVITS Server" cmd /k "cd /d "%TTS_DIR%" && "%PYTHON_EXE%" api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml"

echo Waiting for TTS service initialization (5 seconds)...
timeout /t 5 /nobreak > nul

:: 2. Start Main Application
echo.
echo [2/3] Starting Xiaoyou Main Application...
start "Xiaoyou Core Main" cmd /k "cd /d "%BASE_DIR%" && "%PYTHON_EXE%" main.py"

:: 3. Start Frontend
echo.
echo [3/3] Starting Frontend UI...
set "FRONTEND_DIR=%BASE_DIR%\clients\frontend\Aveline_UI"

if not exist "%FRONTEND_DIR%" (
    echo [WARNING] Frontend directory not found: %FRONTEND_DIR%
    echo Skipping frontend startup.
) else (
    echo.
    echo [INFO] Starting Frontend Dev Server...
    start "Xiaoyou Web" "%BASE_DIR%\start_web.bat"
    
    echo.
    echo [INFO] Waiting for Frontend Server (port 3001)...
    
    set "MAX_RETRIES=60"
    set "RETRY_COUNT=0"
    
    :CHECK_PORT
    powershell -Command "try { $client = New-Object System.Net.Sockets.TcpClient; $client.Connect('127.0.0.1', 3001); $client.Close(); exit 0 } catch { exit 1 }"
    if %errorlevel% equ 0 (
        echo [INFO] Frontend Server is ready!
        goto START_PET
    )
    
    timeout /t 1 /nobreak > nul
    set /a RETRY_COUNT+=1
    if %RETRY_COUNT% lss %MAX_RETRIES% (
        echo [INFO] Waiting for port 3001... (%RETRY_COUNT%/%MAX_RETRIES%)
        goto CHECK_PORT
    )
    
    echo [WARNING] Frontend Server did not respond on port 3001 after 60 seconds.
    echo [WARNING] Attempting to start Desktop Pet anyway...

    :START_PET
    echo.
    echo [INFO] Launching Desktop Pet (Electron)...
    start "Xiaoyou Pet" "%BASE_DIR%\start_pet.bat"
)

echo.
echo =======================================================
echo All start commands issued.
echo Please check the three new windows for any error messages.
echo =======================================================
echo.
pause
