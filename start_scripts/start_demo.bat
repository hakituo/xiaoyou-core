@echo off
setlocal EnableExtensions EnableDelayedExpansion

chcp 65001 > nul 2>&1
title Xiaoyou Core - 演示启动器

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

REM 设置全局演示模式与显存限制
set "XIAOYOU_DEMO_MODE=1"
set "XIAOYOU_VRAM_LIMIT=8192"
set "XIAOYOU_IMAGE_PROVIDER=forge"

REM 演示必须启用资源隔离调度器（进程内 Python 绑定，不走 8080 HTTP）
set "XIAOYOU_SCHEDULER_USE_CPP=1"
set "XIAOYOU_SCHEDULER_USE_CPP_FOR_LLM=1"
set "XIAOYOU_SCHEDULER_LLM_BACKEND=python"
set "XIAOYOU_SCHEDULER_WORKER_COUNT=4"

REM 演示默认内存/上下文收敛（降低系统内存压力与 OOM 风险）
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

REM 允许通过环境变量覆盖 llama.cpp 统一内存策略
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

echo [警告] 未识别参数: %~1
shift
goto parse_args

:after_parse

echo ====================================================
echo    Xiaoyou Core (小友核心) 多模态演示启动器
echo ====================================================

set "PY_EXE="
if defined XIAOYOU_PYTHON if exist "%XIAOYOU_PYTHON%" set "PY_EXE=%XIAOYOU_PYTHON%"
if not defined PY_EXE if exist "%ROOT%\venv_core\Scripts\python.exe" set "PY_EXE=%ROOT%\venv_core\Scripts\python.exe"
if not defined PY_EXE if exist "%ROOT%\venv\Scripts\python.exe" set "PY_EXE=%ROOT%\venv\Scripts\python.exe"
if not defined PY_EXE (
  echo [错误] 未找到可用 Python，请先准备 venv_core 或设置 XIAOYOU_PYTHON
  goto fail
)

echo 使用 Python: %PY_EXE%
%PY_EXE% -c "import sys;print(sys.version.split()[0])" > nul 2>&1
if errorlevel 1 (
  echo [错误] Python 不可用：%PY_EXE%
  goto fail
)

if not exist "%ROOT%\main.py" (
  echo [错误] 未找到 main.py：%ROOT%\main.py
  goto fail
)

call :check_port %BACKEND_PORT% "Backend"
if "%START_TTS%"=="1" call :check_port %TTS_PORT% "TTS"
if "%START_FORGE%"=="1" call :check_port %FORGE_PORT% "Forge"

echo.
echo [配置摘要]
echo - 后端: http://%BACKEND_HOST%:%BACKEND_PORT%
echo - TTS: %START_TTS% (端口 %TTS_PORT%)
echo - Forge: %START_FORGE% (端口 %FORGE_PORT%)
echo - 选项: OPEN_BROWSER=%OPEN_BROWSER%  DRY_RUN=%DRY_RUN%
echo - 演示: XIAOYOU_DEMO_MODE=%XIAOYOU_DEMO_MODE%  XIAOYOU_VRAM_LIMIT=%XIAOYOU_VRAM_LIMIT%  XIAOYOU_IMAGE_PROVIDER=%XIAOYOU_IMAGE_PROVIDER%

echo.
echo [1/4] 启动核心组件（将弹出新窗口）...

if "%START_TTS%"=="1" (
  if exist "%ROOT%\models\GPT-SoVITS-v2pro-20250604-nvidia50" (
    echo - 启动 TTS（端口 %TTS_PORT%）
    if "%DRY_RUN%"=="1" (
      echo   [DRY-RUN] start "Xiaoyou-TTS" /D "..." cmd /k "..."
    ) else (
      start "Xiaoyou-TTS" /D "%ROOT%\models\GPT-SoVITS-v2pro-20250604-nvidia50" cmd /k title Xiaoyou-TTS ^& "%PY_EXE%" api_v2.py -a %BACKEND_HOST% -p %TTS_PORT% -c GPT_SoVITS/configs/tts_infer.yaml
    )
  ) else (
    echo - 跳过 TTS：未找到 %ROOT%\models\GPT-SoVITS-v2pro-20250604-nvidia50
  )
) else (
  echo - 跳过 TTS：已禁用
)

if "%START_FORGE%"=="1" (
  if exist "%ROOT%\models\Image\stable-diffusion-webui-forge-main\webui-user.bat" (
    echo - 启动 Forge（端口 %FORGE_PORT%）
    if "%DRY_RUN%"=="1" (
      echo   [DRY-RUN] start "Xiaoyou-Forge" /D "..." cmd /k "..."
    ) else (
      start "Xiaoyou-Forge" /D "%ROOT%\models\Image\stable-diffusion-webui-forge-main" cmd /k title Xiaoyou-Forge ^& set "PYTHONPATH=" ^& set "PYTHONHOME=" ^& set "COMMANDLINE_ARGS=--api --nowebui --skip-prepare-environment --port %FORGE_PORT% --opt-sdp-attention --disable-xformers" ^& call webui-user.bat
    )
  ) else (
    echo - 跳过 Forge：未找到 %ROOT%\models\Image\stable-diffusion-webui-forge-main\webui-user.bat
  )
) else (
  echo - 跳过 Forge：已禁用
)

echo - 启动主后端（端口 %BACKEND_PORT%）
if "%DRY_RUN%"=="1" (
  echo   [DRY-RUN] start "Xiaoyou-Backend" /D "%ROOT%" cmd /k "..."
) else (
  start "Xiaoyou-Backend" /D "%ROOT%" cmd /k title Xiaoyou-Backend ^& "%PY_EXE%" main.py
)

echo.
echo [2/4] 等待服务就绪（后端/TTS/Forge）...
if "%DRY_RUN%"=="1" (
  echo   [DRY-RUN] 跳过等待
) else (
  if "%START_TTS%"=="1" (
    call :wait_http http://%BACKEND_HOST%:%TTS_PORT%/docs %WAIT_TTS_SECONDS%
    if errorlevel 1 echo [警告] TTS 未在限定时间内就绪（将继续）。
  )
  if "%START_FORGE%"=="1" (
    call :wait_http http://%BACKEND_HOST%:%FORGE_PORT%/sdapi/v1/options %WAIT_FORGE_SECONDS%
    if errorlevel 1 echo [警告] Forge 未在限定时间内就绪（将继续）。
  )
  call :wait_http http://%BACKEND_HOST%:%BACKEND_PORT%/docs %WAIT_SECONDS%
  if errorlevel 1 echo [警告] 后端未在限定时间内就绪（仍会继续）。
)

echo.
echo [3/4] 启动演示环境...
echo [提示] 自动播放脚本已禁用，请直接在浏览器中与 AI 交互。
if "%DRY_RUN%"=="1" (
  echo   [DRY-RUN] ^(已跳过环境检查^)
) else (
  echo   演示环境准备就绪。
)

if "%OPEN_BROWSER%"=="1" (
  echo.
  echo [4/4] 打开 Web 仪表盘: http://localhost:%BACKEND_PORT%/demo
  if "%DRY_RUN%"=="1" (
    echo   [DRY-RUN] start "" "http://localhost:%BACKEND_PORT%/demo"
  ) else (
    start "" "http://localhost:%BACKEND_PORT%/demo"
  )
) else (
  echo.
  echo [4/4] 跳过打开浏览器：已禁用
)

echo.
echo ====================================================
echo    Xiaoyou Core 演示就绪
echo ====================================================
echo.
echo [演示演讲重点提示]
echo 1. 异构计算 (Heterogeneous Computing): 
echo    - CPU (LLM/TTS) + GPU (SDXL) + NPU (Active Care) 协同工作
echo    - 强调 "Resource Isolation" (资源隔离) 架构
echo    - [注] 演示中的 NPU 为 "虚拟调度模拟"，旨在展示系统对 Jetson/RK3588 等异构硬件的
echo      前瞻性架构支撑与任务迁移能力。
echo.
echo 2. 8GB 显存极限优化:
echo    - 展示 "Model Offloading" (动态卸载)
echo    - 观察 Dashboard 上的显存水位变化 (红线预警)
echo.
echo 3. 实时并发调度 (Real-time Scheduling):
echo    - 演示 "Priority Preemption" (语音打断生图)
echo    - 观察 Log 面板中的 "Lock Acquired/Released" 事件
echo.
echo 4. 架构可视化:
echo    - 切换 Dashboard 的 "Architecture" 标签页，向教授展示 Mermaid 生成的系统拓扑。
echo.
echo [操作指南]
echo - 仪表盘地址: http://localhost:%BACKEND_PORT%/demo
echo - 点击“系统架构”标签页可展示拓扑图
echo - 控制台窗口 Xiaoyou-Controller 提供 Web 演示相关辅助
echo.
if "%DRY_RUN%"=="1" (
  exit /b 0
) else (
  echo [成功] 所有服务已启动，启动器即将自动关闭。
  timeout /t 3 > nul
  exit /b 0
)

:check_port
set "P=%~1"
set "NAME=%~2"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /r ":%P% .*LISTENING"') do (
  echo [警告] %NAME% 端口 %P% 可能已被占用（PID=%%a）
  goto :eof
)
goto :eof

:wait_http
set "URL=%~1"
set "MAX=%~2"
for /l %%i in (1,1,%MAX%) do (
  set /a "REMAIN=%%i"
  <nul set /p "=等待 %URL% 就绪 (!REMAIN!/%MAX%)... "
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
echo 用法:
echo   start_demo.bat [--no-tts] [--no-forge] [--no-browser] [--dry-run]
echo                [--backend-port PORT] [--tts-port PORT] [--forge-port PORT]
echo                [--wait SECONDS] [--wait-tts SECONDS] [--wait-forge SECONDS]
echo.
echo 示例:
echo   start_demo.bat --dry-run
echo   start_demo.bat --no-tts --no-forge
echo   start_demo.bat --backend-port 8010 --wait 120
echo   start_demo.bat --wait-tts 60 --wait-forge 180
exit /b 0

:fail
echo.
echo 启动失败。
pause > nul
exit /b 1
