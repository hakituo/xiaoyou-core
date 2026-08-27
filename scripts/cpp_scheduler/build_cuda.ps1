# 编译 CUDA 版 cpp_scheduler（不影响现有 CPU 版 build/Release）
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts/cpp_scheduler/build_cuda.ps1
#
# 前置要求：
#   - Visual Studio 2022（含 C++ 桌面开发）
#   - CUDA Toolkit（nvcc 需在 PATH，或 CUDA_PATH 环境变量已设置）
#   - CMake
#
# 产物：
#   - CUDA 版:  cpp_modules/cpp_scheduler/build/cuda/Release/（scheduler_py.pyd + llama.dll + ggml-*.dll）
#   - CPU 版:  原有 build/Release/ 保持不动
#
# 运行时切换（二选一，通过环境变量）：
#   $env:XIAOYOU_CPP_BACKEND="cuda"   # 用 GPU 推理
#   $env:XIAOYOU_CPP_BACKEND="cpu"    # 用 CPU 推理（默认 auto：有 CUDA 版则优先 CUDA）
#
# 说明：项目路径 D:\AI\xiaoyou-core 含空格，nvcc 对含空格路径很脆弱，
# 脚本自动用 subst 映射到无空格盘符后编译，编译结束自动取消映射。

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$CppSchedulerDir = Join-Path $ProjectRoot "cpp_modules\cpp_scheduler"
$BuildDir = Join-Path $CppSchedulerDir "build\cuda"

Write-Host "项目根目录: $ProjectRoot"
Write-Host "构建目录:   $BuildDir"

# 复用本地源码，避免联网下载
if (Test-Path "$ProjectRoot\libuv-1.x\CMakeLists.txt") {
    Write-Host "libuv 源码:  本地 $ProjectRoot\libuv-1.x（复用，不联网）"
}
if (Test-Path "$ProjectRoot\external\llama.cpp-master\CMakeLists.txt") {
    Write-Host "llama.cpp:    本地 $ProjectRoot\external\llama.cpp-master（复用，不联网）"
}

# 1. 检查 CUDA
$nvcc = Get-Command nvcc -ErrorAction SilentlyContinue
if (-not $nvcc -and -not $env:CUDA_PATH) {
    Write-Error "未找到 nvcc，也未设置 CUDA_PATH。请先安装 CUDA Toolkit 并重启终端。"
}
if ($nvcc) {
    Write-Host "nvcc: $($nvcc.Source)"
} else {
    Write-Host "CUDA_PATH: $env:CUDA_PATH"
}

# 2. subst 映射到无空格盘符（规避 nvcc 路径空格兼容性问题）
$Drive = "Z:"
$existing = Get-PSDrive -Name $Drive -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "盘符 $Drive 已被映射到 $($existing.Root)，沿用现有映射。"
} else {
    subst $Drive $ProjectRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Error "subst 映射失败，请以管理员权限运行或改用其他盘符。"
    }
    Write-Host "已映射 $Drive -> $ProjectRoot"
}

try {
    Push-Location "${Drive}\cpp_modules\cpp_scheduler"
    try {
        # 3. 配置 CMake（CUDA 开启）
        Write-Host "`n[1/2] 配置 CMake（GGML_CUDA=ON）..."
        cmake -S . -B build/cuda -G "Visual Studio 17 2022" -A x64 `
            -DLLAMA_CUDA=ON -DGGML_CUDA=ON
        if ($LASTEXITCODE -ne 0) { throw "CMake 配置失败" }

        # 4. 编译
        Write-Host "`n[2/2] 编译 CUDA 版（首次编译 CUDA kernels 较慢，约 10~30 分钟）..."
        cmake --build build/cuda --config Release --parallel
        if ($LASTEXITCODE -ne 0) { throw "编译失败" }
    } finally {
        Pop-Location
    }
} finally {
    # 5. 取消 subst 映射（产物已实际落在 D:\AI\xiaoyou-core 下）
    if (-not $existing) {
        subst $Drive /D
        Write-Host "已取消 $Drive 映射。"
    }
}

Write-Host "`nCUDA 版编译完成！"
Write-Host "产物目录: $BuildDir\Release"
Write-Host ""
Write-Host "切换方式（二选一，新开终端或启动前设置）："
Write-Host "  GPU 模式:  `$env:XIAOYOU_CPP_BACKEND=`"cuda`""
Write-Host "  CPU 模式:  `$env:XIAOYOU_CPP_BACKEND=`"cpu`""
Write-Host "  不设置 = auto（存在 CUDA 版则优先 CUDA）"
