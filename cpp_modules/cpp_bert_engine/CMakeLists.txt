# pybind11 3.x 自身要求 3.15 起；本机/Ubuntu 24.04 的 cmake 都够，
# 但声明不要再写成 3.14，否则遇到真 3.14 会在 pybind11 子项目里直接 configure 失败。
cmake_minimum_required(VERSION 3.15)
project(cpp_bert_engine VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Enable OpenMP for parallel computing if available
find_package(OpenMP)

# pybind11 统一由 cpp_modules/cmake/pybind11.cmake 提供（版本单一来源）
include(${CMAKE_CURRENT_SOURCE_DIR}/../cmake/pybind11.cmake)

# Fetch ONNX Runtime precompiled binaries
# 官方 release 里 Windows 是 .zip，Linux/macOS 是 .tgz，分支按平台选，不要写死 Windows 包名。
set(ORT_VERSION "1.24.4")
if(WIN32)
  set(ORT_ARCHIVE "onnxruntime-win-x64-${ORT_VERSION}.zip")
elseif(APPLE AND CMAKE_SYSTEM_PROCESSOR MATCHES "arm64")
  set(ORT_ARCHIVE "onnxruntime-osx-arm64-${ORT_VERSION}.tgz")
elseif(CMAKE_SYSTEM_PROCESSOR MATCHES "^(aarch64|arm64)$")
  set(ORT_ARCHIVE "onnxruntime-linux-aarch64-${ORT_VERSION}.tgz")
else()
  set(ORT_ARCHIVE "onnxruntime-linux-x64-${ORT_VERSION}.tgz")
endif()

# 本地 third_party/ 有就用本地（离线也能编），没有再从官方 release 拉同名包。
set(ORT_LOCAL_ARCHIVE "${CMAKE_CURRENT_SOURCE_DIR}/third_party/${ORT_ARCHIVE}")
if(EXISTS "${ORT_LOCAL_ARCHIVE}")
  message(STATUS "[onnxruntime ${ORT_VERSION}] 复用本地包: ${ORT_LOCAL_ARCHIVE}")
  FetchContent_Declare(onnxruntime URL "${ORT_LOCAL_ARCHIVE}")
else()
  set(ORT_RELEASE_URL
      "https://github.com/microsoft/onnxruntime/releases/download/v${ORT_VERSION}/${ORT_ARCHIVE}")
  message(STATUS "[onnxruntime ${ORT_VERSION}] 本地包不存在，从官方 release 下载: ${ORT_RELEASE_URL}")
  FetchContent_Declare(onnxruntime URL "${ORT_RELEASE_URL}")
endif()
FetchContent_MakeAvailable(onnxruntime)

# Pybind module
pybind11_add_module(bert_engine_py bindings/python_bindings.cpp src/bert_engine.cpp)

# Target include directories
target_include_directories(bert_engine_py PRIVATE 
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${onnxruntime_SOURCE_DIR}/include
)

if(OpenMP_CXX_FOUND)
    target_link_libraries(bert_engine_py PRIVATE OpenMP::OpenMP_CXX)
endif()

# Link ONNX Runtime：Windows 链导入库 + 拷 DLL；Linux/macOS 链带 SONAME 的 .so 并配 $ORIGIN rpath
if(WIN32)
    target_link_libraries(bert_engine_py PRIVATE ${onnxruntime_SOURCE_DIR}/lib/onnxruntime.lib)
    add_custom_command(TARGET bert_engine_py POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${onnxruntime_SOURCE_DIR}/lib/onnxruntime.dll"
        $<TARGET_FILE_DIR:bert_engine_py>
    )
else()
    # 官方 Linux 包里只有 libonnxruntime.so.1（带 SONAME），没有裸 .so，故按通配符取，不写死文件名
    file(GLOB ORT_LINK_LIB "${onnxruntime_SOURCE_DIR}/lib/libonnxruntime.so*")
    if(NOT ORT_LINK_LIB)
        message(FATAL_ERROR
            "未在 ${onnxruntime_SOURCE_DIR}/lib 下找到 libonnxruntime.so*，请检查 ORT 包是否完整")
    endif()
    list(GET ORT_LINK_LIB 0 ORT_LINK_LIB)
    target_link_libraries(bert_engine_py PRIVATE "${ORT_LINK_LIB}")
    # 运行时加载器按 DT_NEEDED 的 SONAME 找库：$ORIGIN 指模块所在目录，下面把所有 .so 拷过去
    set_target_properties(bert_engine_py PROPERTIES
        BUILD_RPATH "\$ORIGIN"
        INSTALL_RPATH "\$ORIGIN"
    )
    file(GLOB ORT_SO_FILES "${onnxruntime_SOURCE_DIR}/lib/*.so*")
    foreach(_ort_so IN LISTS ORT_SO_FILES)
        add_custom_command(TARGET bert_engine_py POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${_ort_so}"
            $<TARGET_FILE_DIR:bert_engine_py>
        )
    endforeach()
endif()

# Apply Architecture-specific optimization flags
# 注意：AVX2/FMA 是 x86-64 专有指令；ARM Linux(aarch64) 上不适用，故单独按架构判断。
if(CMAKE_SYSTEM_PROCESSOR MATCHES "^(x86_64|AMD64|amd64)$")
    if(MSVC)
        target_compile_options(bert_engine_py PRIVATE /arch:AVX2 /O2 /fp:fast)
    else()
        target_compile_options(bert_engine_py PRIVATE -mavx2 -mfma -O3 -ffast-math)
    endif()
else()
    target_compile_options(bert_engine_py PRIVATE -O3)
endif()
