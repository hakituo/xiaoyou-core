@echo off
setlocal enabledelayedexpansion

echo =====================================================
echo          TESTING GPU AVAILABILITY IN ALL ENVIRONMENTS
 echo =====================================================

REM Test venv_llm environment
call :test_environment "venv_llm"

REM Test venv_voice environment
call :test_environment "venv_voice"

REM Test venv_img environment
call :test_environment "venv_img"

echo =====================================================
echo                ALL ENVIRONMENTS TESTED
 echo =====================================================
pause
goto :eof

:test_environment
set "ENV_NAME=%~1"
set "ENV_PATH=d:\AI\xiaoyou-core\%ENV_NAME%\Scripts\python.exe"
set "TEST_SCRIPT=d:\AI\xiaoyou-core\paper\experiment\scripts\test_gpu_availability.py"

echo.
echo --------------- %ENV_NAME% ENVIRONMENT TEST ---------------
if exist "!ENV_PATH!" (
    echo Testing GPU availability in !ENV_NAME! environment...
    "!ENV_PATH!" "!TEST_SCRIPT!"
) else (
    echo Warning: !ENV_NAME! environment not found or Python path incorrect
)
echo --------------------------------------------------
goto :eof