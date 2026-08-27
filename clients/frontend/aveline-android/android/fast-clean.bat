@echo off
chcp 65001 >nul
echo ========================================
echo   快速清理 Gradle 缓存 (极速版)
echo ========================================
echo.

echo [1/3] 正在清理项目 build 目录...
if exist "build" (
    rd /s /q "build" >nul 2>&1
    echo   ✓ build 目录已删除
) else (
    echo   ✗ build 目录不存在
)

echo [2/3] 正在清理 app build 目录...
if exist "app\build" (
    rd /s /q "app\build" >nul 2>&1
    echo   ✓ app\build 目录已删除
) else (
    echo   ✗ app\build 目录不存在
)

echo [3/3] 正在清理临时文件...
del /q /f "%TEMP%\gradle*" 2>nul
del /q /f "%LOCALAPPDATA%\Temp\gradle*" 2>nul
echo   ✓ 临时文件已清理

echo.
echo ========================================
echo   清理完成！
echo ========================================
echo.
echo 提示: 下次编译会重新构建，速度会快很多
echo.
pause
