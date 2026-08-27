#!/bin/bash
set -euo pipefail

# 激活虚拟环境
source /home/leslie/.venvs/mvp_core-cu128/bin/activate

export PATH="/usr/local/cuda/bin:${PATH}"
export LD_LIBRARY_PATH="/usr/local/cuda/lib64:${LD_LIBRARY_PATH:-}"

SCRIPT_DIR="/home/leslie/xiaoyou-core/cpp_modules/cpp_scheduler"
BUILD_DIR="${SCRIPT_DIR}/build"
PYTHON_EXE="$(which python)"

echo "=== 主程序 C++ Scheduler Build ==="
echo "Python: $(python --version) at ${PYTHON_EXE}"
echo "CUDA: $(nvcc --version 2>/dev/null | grep release || echo 'not found')"
echo "cmake: $(cmake --version | head -1)"
echo ""

# 清理旧 build
rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"
cd "${BUILD_DIR}"

echo "=== Running CMake ==="
cmake .. \
    -DCMAKE_BUILD_TYPE=Release \
    -DPython_EXECUTABLE="${PYTHON_EXE}" \
    -DPYTHON_EXECUTABLE="${PYTHON_EXE}"

echo ""
echo "=== Building ==="
cmake --build . -j$(nproc)

echo ""
echo "=== Build Complete ==="
ls -la scheduler_py*.so 2>/dev/null || echo "WARNING: scheduler_py not found"
