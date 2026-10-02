@echo off
setlocal
chcp 65001 > nul

echo =======================================================
echo          Xiaoyou Core - Starting all services
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

echo [INFO] Starting all services...
echo.

:: 1. Start TTS (via start_tts.bat)
echo [1/4] Starting TTS service...
if exist "%BASE_DIR%\start_scripts\start_tts.bat" (
    call "%BASE_DIR%\start_scripts\start_tts.bat"
) else (
    echo [WARNING] start_tts.bat not found - skipping TTS startup.
)

:: Wait 2 seconds
timeout /t 2 /nobreak > nul

:: 2. Start Forge (via start_forge.bat)
echo [2/4] Starting Forge image service...
if exist "%BASE_DIR%\start_scripts\start_forge.bat" (
    call "%BASE_DIR%\start_scripts\start_forge.bat"
) else (
    echo [WARNING] start_forge.bat not found - skipping Forge startup.
)

:: Wait 2 seconds
timeout /t 2 /nobreak > nul

:: 3. Start the main program (direct launch)
echo [3/4] Starting Xiaoyou main program...
start "Xiaoyou Core Main" /D "%BASE_DIR%" cmd /k ""%PYTHON_EXE%" main.py"

:: Wait 2 seconds
timeout /t 2 /nobreak > nul

:: 4. Start the frontend (via start_web.bat)
echo [4/4] Starting frontend page...
set "FRONTEND_DIR=%BASE_DIR%\clients\frontend\aveline-web"

if exist "%FRONTEND_DIR%" (
    if exist "%BASE_DIR%\start_scripts\start_web.bat" (
        echo [INFO] Starting frontend dev server...
        start "Xiaoyou Web" "%BASE_DIR%\start_scripts\start_web.bat"
        goto FINISH
    ) else (
        echo [WARNING] start_web.bat not found - skipping frontend startup.
        goto FINISH
    )
) else (
    echo [WARNING] Frontend directory not found: %FRONTEND_DIR%
    echo Skipping frontend startup.
    goto FINISH
)

:PYTHON_MISSING
echo [ERROR] Python environment not found: %PYTHON_EXE%
echo Please make sure venv_core is installed correctly.
pause
exit /b 1

:FINISH
echo.
echo =======================================================
echo All startup commands have been sent.
echo The launcher will close automatically in 3 seconds...
echo =======================================================
timeout /t 3 /nobreak > nul
exit
