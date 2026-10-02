@echo off
pushd "%~dp0.."
powershell -ExecutionPolicy Bypass -File .\start_scripts\start_frp.ps1
if %ERRORLEVEL% neq 0 (
    echo.
    echo [FRP Exit] Please check config or network.
    pause
)
popd
