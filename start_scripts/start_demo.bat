@echo off
setlocal EnableExtensions EnableDelayedExpansion

chcp 65001 > nul 2>&1
title Xiaoyou Core - Demo Launcher

set "ROOT=%~dp0.."
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%" > nul 2>&1

set "BACKEND_HOST=127.0.0.1"
set "BACKEND_PORT=8000"
set "TTS_PORT=9880"
set "FORGE_PORT=7860"
set "WAIT_SECONDS=60"
set "WAIT_TTS_SECONDS=45"
set "WAIT_FORGE_SECONDS=90"

set "START_TTS=1"
set "START_FORGE=1"
set "OPEN_BROWSER=1"
set "DRY_RUN=0"

REM Set global demo mode and VRAM limit
set "XIAOYOU_DEMO_MODE=1"
set "XIAOYOU_VRAM_LIMIT=8192"
set "XIAOYOU_IMAGE_PROVIDER=forge"

REM Demo must enable the resource-isolation scheduler - in-process Python binding, not 8080 HTTP
set "XIAOYOU_SCHEDULER_USE_CPP=1"
set "XIAOYOU_SCHEDULER_USE_CPP_FOR_LLM=1"
set "XIAOYOU_SCHEDULER_LLM_BACKEND=python"
set "XIAOYOU_SCHEDULER_WORKER_COUNT=4"

REM Demo defaults tighten memory/context to reduce system memory pressure and OOM risk
set "XIAOYOU_MODEL_N_CTX=4096"
set "XIAOYOU_MODEL_N_GPU_LAYERS=-1"
set "XIAOYOU_MODEL_N_BATCH=256"
set "XIAOYOU_MODEL_MAX_NEW_TOKENS=1024"
set "XIAOYOU_MODEL_KV_SWAP_ENABLED=1"
set "XIAOYOU_MODEL_KV_SWAP_TRIGGER_TOKENS=2048"
set "XIAOYOU_DEMO_CPU_LLM_N_CTX=4096"
set "XIAOYOU_DEMO_CPU_LLM_N_BATCH=128"
set "XIAOYOU_MODEL_LLM_PRELOAD_ON_STARTUP=0"
set "XIAOYOU_MODEL_FORGE_KEEP_MODEL_LOADED_SECONDS=0"
set "XIAOYOU_SEND_IMAGE_BASE64=0"
set "XIAOYOU_IMAGE_BASE64_MAX_BYTES=2097152"

REM Allow overriding the llama.cpp unified memory policy via an environment variable
if not defined GGML_CUDA_ENABLE_UNIFIED_MEMORY set "GGML_CUDA_ENABLE_UNIFIED_MEMORY=0"

:parse_args
if "%~1"=="" goto after_parse
if /i "%~1"=="--help" goto show_help
if /i "%~1"=="-h" goto show_help

if /i "%~1"=="--no-tts" (
  set "START_TTS=0"
  shift
  goto parse_args
)
if /i "%~1"=="--no-forge" (
  set "START_FORGE=0"
  shift
  goto parse_args
)
if /i "%~1"=="--no-browser" (
  set "OPEN_BROWSER=0"
  shift
  goto parse_args
)
if /i "%~1"=="--dry-run" (
  set "DRY_RUN=1"
  shift
  goto parse_args
)

if /i "%~1"=="--backend-port" (
  if "%~2"=="" goto show_help
  set "BACKEND_PORT=%~2"
  shift
  shift
  goto parse_args
)
if /i "%~1"=="--tts-port" (
  if "%~2"=="" goto show_help
  set "TTS_PORT=%~2"
  shift
  shift
  goto parse_args
)
if /i "%~1"=="--forge-port" (
  if "%~2"=="" goto show_help
  set "FORGE_PORT=%~2"
  shift
  shift
  goto parse_args
)
if /i "%~1"=="--wait" (
  if "%~2"=="" goto show_help
  set "WAIT_SECONDS=%~2"
  shift
  shift
  goto parse_args
)

if /i "%~1"=="--wait-tts" (
  if "%~2"=="" goto show_help
  set "WAIT_TTS_SECONDS=%~2"
  shift
  shift
  goto parse_args
)
if /i "%~1"=="--wait-forge" (
  if "%~2"=="" goto show_help
  set "WAIT_FORGE_SECONDS=%~2"
  shift
  shift
  goto parse_args
)

echo [WARNING] Unknown argument: %~1
shift
goto parse_args

:after_parse

echo ====================================================
echo    Xiaoyou Core Multimodal Demo Launcher
echo ====================================================

set "PY_EXE="
if defined XIAOYOU_PYTHON if exist "%XIAOYOU_PYTHON%" set "PY_EXE=%XIAOYOU_PYTHON%"
if not defined PY_EXE if exist "%ROOT%\venv_core\Scripts\python.exe" set "PY_EXE=%ROOT%\venv_core\Scripts\python.exe"
if not defined PY_EXE if exist "%ROOT%\venv\Scripts\python.exe" set "PY_EXE=%ROOT%\venv\Scripts\python.exe"
if not defined PY_EXE (
  echo [ERROR] No usable Python found - prepare venv_core or set XIAOYOU_PYTHON
  goto fail
)

echo Using Python: %PY_EXE%
%PY_EXE% -c "import sys;print(sys.version.split()[0])" > nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python is not usable: %PY_EXE%
  goto fail
)

if not exist "%ROOT%\main.py" (
  echo [ERROR] main.py not found: %ROOT%\main.py
  goto fail
)

call :check_port %BACKEND_PORT% "Backend"
if "%START_TTS%"=="1" call :check_port %TTS_PORT% "TTS"
if "%START_FORGE%"=="1" call :check_port %FORGE_PORT% "Forge"

echo.
echo [Configuration Summary]
echo - Backend: http://%BACKEND_HOST%:%BACKEND_PORT%
echo - TTS: %START_TTS% (port %TTS_PORT%)
echo - Forge: %START_FORGE% (port %FORGE_PORT%)
echo - Options: OPEN_BROWSER=%OPEN_BROWSER%  DRY_RUN=%DRY_RUN%
echo - Demo: XIAOYOU_DEMO_MODE=%XIAOYOU_DEMO_MODE%  XIAOYOU_VRAM_LIMIT=%XIAOYOU_VRAM_LIMIT%  XIAOYOU_IMAGE_PROVIDER=%XIAOYOU_IMAGE_PROVIDER%

echo.
echo [1/4] Starting core components - new windows will open...

if "%START_TTS%"=="1" (
  if exist "%ROOT%\models\GPT-SoVITS-v2pro-20250604-nvidia50" (
    echo - Starting TTS - port %TTS_PORT%
    if "%DRY_RUN%"=="1" (
      echo   [DRY-RUN] start "Xiaoyou-TTS" /D "..." cmd /k "..."
    ) else (
      start "Xiaoyou-TTS" /D "%ROOT%\models\GPT-SoVITS-v2pro-20250604-nvidia50" cmd /k title Xiaoyou-TTS ^& "%PY_EXE%" api_v2.py -a %BACKEND_HOST% -p %TTS_PORT% -c GPT_SoVITS/configs/tts_infer.yaml
    )
  ) else (
    echo - Skipping TTS - not found: %ROOT%\models\GPT-SoVITS-v2pro-20250604-nvidia50
  )
) else (
  echo - Skipping TTS - disabled
)

if "%START_FORGE%"=="1" (
  if exist "%ROOT%\models\Image\stable-diffusion-webui-forge-main\webui-user.bat" (
    echo - Starting Forge - port %FORGE_PORT%
    if "%DRY_RUN%"=="1" (
      echo   [DRY-RUN] start "Xiaoyou-Forge" /D "..." cmd /k "..."
    ) else (
      start "Xiaoyou-Forge" /D "%ROOT%\models\Image\stable-diffusion-webui-forge-main" cmd /k title Xiaoyou-Forge ^& set "PYTHONPATH=" ^& set "PYTHONHOME=" ^& set "COMMANDLINE_ARGS=--api --nowebui --skip-prepare-environment --port %FORGE_PORT% --opt-sdp-attention --disable-xformers" ^& call webui-user.bat
    )
  ) else (
    echo - Skipping Forge - not found: %ROOT%\models\Image\stable-diffusion-webui-forge-main\webui-user.bat
  )
) else (
  echo - Skipping Forge - disabled
)

echo - Starting main backend (port %BACKEND_PORT%)
if "%DRY_RUN%"=="1" (
  echo   [DRY-RUN] start "Xiaoyou-Backend" /D "%ROOT%" cmd /k "..."
) else (
  start "Xiaoyou-Backend" /D "%ROOT%" cmd /k title Xiaoyou-Backend ^& "%PY_EXE%" main.py
)

echo.
echo [2/4] Waiting for services - backend/TTS/Forge...
if "%DRY_RUN%"=="1" (
  echo   [DRY-RUN] skipping wait
) else (
  if "%START_TTS%"=="1" (
    call :wait_http http://%BACKEND_HOST%:%TTS_PORT%/docs %WAIT_TTS_SECONDS%
    if errorlevel 1 echo [WARNING] TTS not ready in time - continuing.
  )
  if "%START_FORGE%"=="1" (
    call :wait_http http://%BACKEND_HOST%:%FORGE_PORT%/sdapi/v1/options %WAIT_FORGE_SECONDS%
    if errorlevel 1 echo [WARNING] Forge not ready in time - continuing.
  )
  call :wait_http http://%BACKEND_HOST%:%BACKEND_PORT%/docs %WAIT_SECONDS%
  if errorlevel 1 echo [WARNING] Backend not ready in time - continuing anyway.
)

echo.
echo [3/4] Starting demo environment...
echo [HINT] Autoplay script is disabled - interact with the AI directly in the browser.
if "%DRY_RUN%"=="1" (
  echo   [DRY-RUN] environment check skipped
) else (
  echo   Demo environment ready.
)

if "%OPEN_BROWSER%"=="1" (
  echo.
  echo [4/4] Opening Web dashboard: http://localhost:%BACKEND_PORT%/demo
  if "%DRY_RUN%"=="1" (
    echo   [DRY-RUN] start "" "http://localhost:%BACKEND_PORT%/demo"
  ) else (
    start "" "http://localhost:%BACKEND_PORT%/demo"
  )
) else (
  echo.
  echo [4/4] Skipping browser open - disabled
)

echo.
echo ====================================================
echo    Xiaoyou Core demo ready
echo ====================================================
echo.
echo [Demo Talk Track Highlights]
echo 1. Heterogeneous Computing: 
echo    - CPU (LLM/TTS) + GPU (SDXL) + NPU (Active Care) working together
echo    - Emphasize the "Resource Isolation" architecture
echo    - [NOTE] The NPU in this demo is a "virtual scheduling simulation", meant to show the
echo      forward-looking architecture support and task migration for Jetson/RK3588 class hardware.
echo.
echo 2. 8GB VRAM Extreme Optimization:
echo    - Show "Model Offloading"
echo    - Watch VRAM level changes on the Dashboard (red-line warning)
echo.
echo 3. Real-time Scheduling:
echo    - Demo "Priority Preemption" (voice interrupting image generation)
echo    - Watch "Lock Acquired/Released" events in the Log panel
echo.
echo 4. Architecture Visualization:
echo    - Switch to the Dashboard "Architecture" tab to show the Mermaid-generated topology.
echo.
echo [Operation Guide]
echo - Dashboard URL: http://localhost:%BACKEND_PORT%/demo
echo - Click the "Architecture" tab to show the topology diagram
echo - The Xiaoyou-Controller console window provides Web demo helpers
echo.
if "%DRY_RUN%"=="1" (
  exit /b 0
) else (
  echo [OK] All services started - the launcher will close automatically.
  timeout /t 3 > nul
  exit /b 0
)

:check_port
set "P=%~1"
set "NAME=%~2"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /r ":%P% .*LISTENING"') do (
  echo [WARNING] %NAME% port %P% may already be in use - PID=%%a
  goto :eof
)
goto :eof

:wait_http
set "URL=%~1"
set "MAX=%~2"
for /l %%i in (1,1,%MAX%) do (
  set /a "REMAIN=%%i"
  <nul set /p "=Waiting for %URL% ready (!REMAIN!/%MAX%)... "
  powershell -NoProfile -Command "$u='%URL%'; try { $r=Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 3; if(($r.StatusCode -ge 200) -and ($r.StatusCode -lt 400)){ exit 0 } else { exit 1 } } catch { exit 1 }" > nul 2>&1
  if not errorlevel 1 (
    echo [OK]
    exit /b 0
  )
  echo [RETRY]
  timeout /t 1 /nobreak > nul
)
exit /b 1

:show_help
echo Usage:
echo   start_demo.bat [--no-tts] [--no-forge] [--no-browser] [--dry-run]
echo                [--backend-port PORT] [--tts-port PORT] [--forge-port PORT]
echo                [--wait SECONDS] [--wait-tts SECONDS] [--wait-forge SECONDS]
echo.
echo Examples:
echo   start_demo.bat --dry-run
echo   start_demo.bat --no-tts --no-forge
echo   start_demo.bat --backend-port 8010 --wait 120
echo   start_demo.bat --wait-tts 60 --wait-forge 180
exit /b 0

:fail
echo.
echo Startup failed.
pause > nul
exit /b 1
