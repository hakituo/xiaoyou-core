@echo off
chcp 65001 >nul
title XiaoYou AI Core
cd /d "%~dp0"

echo ==========================================
echo    XiaoYou AI Core Launcher
echo ==========================================
echo.

REM Default: venv_cpu (CPU-only torch, saves ~3GB RAM). Change to venv_core for GPU.
set VENV=venv_cpu

REM Check if virtual environment exists
if not exist "%VENV%\Scripts\python.exe" (
    echo [WARN] %VENV% not found, falling back to venv_core...
    set VENV=venv_core
)
if not exist "%VENV%\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found, please install dependencies first
    pause
    exit /b 1
)

REM Bypass venv launcher to avoid orphan child process on Ctrl+C.
REM venv\Scripts\python.exe is a 268KB launcher that spawns home Python as a
REM child process. On Windows, Ctrl+C only reaches the launcher (parent),
REM leaving the child orphaned and holding the port. We call home Python
REM directly with PYTHONPATH pointing to the venv's site-packages instead.
set HOME_PYTHON=
for /f "tokens=2 delims==" %%a in ('findstr "^home" "%VENV%\pyvenv.cfg"') do set HOME_PYTHON=%%a
set HOME_PYTHON=%HOME_PYTHON: =%

if not exist "%HOME_PYTHON%\python.exe" (
    echo [WARN] Home Python not found at %HOME_PYTHON%, using venv launcher
    echo [INFO] Starting XiaoYou AI Core with %VENV% launcher...
    echo.
    "%VENV%\Scripts\python.exe" main.py
) else (
    set PYTHONPATH=%CD%\%VENV%\Lib\site-packages
    echo [INFO] Starting XiaoYou AI Core ^(no venv launcher, Ctrl+C safe^):
    echo        Python: %HOME_PYTHON%\python.exe
    echo        Packages: %VENV%\Lib\site-packages
    echo.
    "%HOME_PYTHON%\python.exe" main.py
)

REM If program exits abnormally, pause to show error message
if errorlevel 1 (
    echo.
    echo [ERROR] Program exited abnormally
    pause
)
