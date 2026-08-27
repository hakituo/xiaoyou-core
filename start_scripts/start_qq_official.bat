@echo off
chcp 65001 >nul

cd /d "%~dp0\.."

REM Match start.bat: prefer the CPU environment, then fall back to venv_core.
set "VENV=venv_cpu"
if not exist "%CD%\%VENV%\Scripts\python.exe" set "VENV=venv_core"
set "PYTHON_EXE=%CD%\%VENV%\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    echo [ERROR] Neither venv_cpu nor venv_core was found under %CD%
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
    start "bot1" cmd /c "cd /d "%~dp0\.." && "%PYTHON_EXE%" -m clients.bots.qq_official.adapter --role_id bot1"
) else if "%choice%"=="2" (
    start "bot2" cmd /c "cd /d "%~dp0\.." && "%PYTHON_EXE%" -m clients.bots.qq_official.adapter --role_id bot2"
) else if "%choice%"=="3" (
    start "bot1" cmd /c "cd /d "%~dp0\.." && "%PYTHON_EXE%" -m clients.bots.qq_official.adapter --role_id bot1"
    start "bot2" cmd /c "cd /d "%~dp0\.." && "%PYTHON_EXE%" -m clients.bots.qq_official.adapter --role_id bot2"
)

exit
