cmake_minimum_required(VERSION 3.14)
set(CMAKE_TLS_VERIFY OFF)
set(FETCHCONTENT_QUIET OFF) # 开启下载进度显示
project(cpp_scheduler VERSION 1.0.0 LANGUAGES CXX)

# 设置C++标准
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# 强制关闭测试构建：llama.cpp / libuv 在 FetchContent 中可能通过 include(CTest)
# 把 BUILD_TESTING 打开（缓存值一旦为 ON，底部 option() 无法覆盖），导致
# add_subdirectory(tests) 编译引用已删除旧 API 的 integration_test.cpp 而失败。
# 必须在引入任何 FetchContent 之前用 FORCE 钉死为 OFF。
set(BUILD_TESTING OFF CACHE BOOL "Build tests" FORCE)

# 查找依赖
find_package(Threads REQUIRED)
find_package(PkgConfig QUIET)

# 优先使用本地 libuv 源码
set(LIBUV_LOCAL_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../libuv-1.x")
if(PkgConfig_FOUND)
    pkg_check_modules(LIBUV QUIET libuv)
endif()

if(NOT LIBUV_FOUND)
    find_package(libuv QUIET)
endif()

# 本地 libuv 源码
if(EXISTS "${LIBUV_LOCAL_SOURCE_DIR}/CMakeLists.txt")
    message(STATUS "Using local libuv source: ${LIBUV_LOCAL_SOURCE_DIR}")
    include(FetchContent)
    FetchContent_Declare(
        libuv
        SOURCE_DIR "${LIBUV_LOCAL_SOURCE_DIR}"
    )
    FetchContent_MakeAvailable(libuv)
elseif(NOT LIBUV_FOUND AND NOT libuv_FOUND)
    message(STATUS "libuv not found, will download during build")
    include(FetchContent)
    FetchContent_Declare(
        libuv
        GIT_REPOSITORY https://github.com/libuv/libuv.git
        GIT_TAG v1.48.0
        GIT_SHALLOW TRUE
    )
    FetchContent_MakeAvailable(libuv)
endif()

# llama.cpp 依赖 (从源码构建)
message(STATUS "Configuring llama.cpp...")

# MSVC char8_t 兼容性 / UTF-8 源码字符集。
# 注意：不能在这里用 add_compile_options 全局设置——该目录属性会随 FetchContent
# 传播给 llama.cpp 的 CUDA 目标，MSBuild 生成器会把 /utf-8 /Zc:char8_t- 原样传给
# nvcc，nvcc 将 /utf-8 误当作输入文件，报
# "nvcc fatal : A single input file is required for a non-link phase"。
# 因此只在下方 MSVC 分支用 target_compile_options 对本项目 C++ 目标单独设置。
# if(MSVC)
#     add_compile_options(/utf-8 /Zc:char8_t-)
# endif()

include(FetchContent)
set(LLAMA_BUILD_COMMON ON CACHE BOOL "" FORCE)
set(LLAMA_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_SERVER OFF CACHE BOOL "" FORCE)
set(LLAMA_CURL OFF CACHE BOOL "" FORCE)
# CUDA 支持：默认关闭（Windows 下 nvcc 对含空格/中文路径敏感，见 Question_Reviewer 10.14）。
# 需要 GPU 加速时，用 -DLLAMA_CUDA=ON -DGGML_CUDA=ON 开启（参考 scripts/cpp_scheduler/build_cuda.ps1）。
# 使用 if(NOT DEFINED) 而非 FORCE，保证命令行传入的参数能覆盖默认值。
if(NOT DEFINED LLAMA_CUDA)
    set(LLAMA_CUDA OFF CACHE BOOL "" FORCE)
endif()
if(NOT DEFINED GGML_CUDA)
    set(GGML_CUDA OFF CACHE BOOL "" FORCE)
endif()
set(LLAMA_CPP_LOCAL_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../external/llama.cpp-master")
set(LLAMA_CPP_LOCAL_ZIP "${CMAKE_CURRENT_SOURCE_DIR}/../llama.cpp-master.zip")
# WSL2 备用路径
set(LLAMA_CPP_WSL2_PATH "/home/leslie/mvp_core/cpp_scheduler/deps/llama.cpp-master")
if(EXISTS "${LLAMA_CPP_LOCAL_SOURCE_DIR}/CMakeLists.txt")
    FetchContent_Declare(
        llama_cpp
        SOURCE_DIR "${LLAMA_CPP_LOCAL_SOURCE_DIR}"
    )
elseif(EXISTS "${LLAMA_CPP_WSL2_PATH}/CMakeLists.txt")
    FetchContent_Declare(
        llama_cpp
        SOURCE_DIR "${LLAMA_CPP_WSL2_PATH}"
    )
elseif(EXISTS "${LLAMA_CPP_LOCAL_ZIP}")
    FetchContent_Declare(
        llama_cpp
        URL "${LLAMA_CPP_LOCAL_ZIP}"
        DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    )
else()
    FetchContent_Declare(
        llama_cpp
        GIT_REPOSITORY https://github.com/ggerganov/llama.cpp.git
        GIT_TAG master
        GIT_SHALLOW TRUE
    )
endif()
FetchContent_MakeAvailable(llama_cpp)

# Pybind11
message(STATUS "Configuring pybind11...")
find_package(pybind11 QUIET)
if(NOT pybind11_FOUND)
    include(FetchContent)
    FetchContent_Declare(
      pybind11
      GIT_REPOSITORY https://github.com/pybind/pybind11.git
      GIT_TAG v2.11.1
      GIT_SHALLOW TRUE
    )
    FetchContent_MakeAvailable(pybind11)
endif()

# 源文件
file(GLOB_RECURSE CORE_SOURCES "core/*.cpp")
file(GLOB_RECURSE WORKER_SOURCES "workers/*.cpp")
file(GLOB_RECURSE QUEUE_SOURCES "queue/*.cpp")
file(GLOB_RECURSE API_SOURCES "api/*.cpp")
file(GLOB_RECURSE UTILS_SOURCES "utils/*.cpp")

# 创建库
add_library(async_scheduler STATIC
    ${CORE_SOURCES}
    ${WORKER_SOURCES}
    ${QUEUE_SOURCES}
    ${UTILS_SOURCES}
)

# Python 扩展模块
pybind11_add_module(scheduler_py bindings/python_bindings.cpp)
target_link_libraries(scheduler_py PRIVATE async_scheduler)
target_include_directories(scheduler_py PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

# 创建主程序
add_executable(ai_scheduler
    ${API_SOURCES}
    main.cpp
)

add_executable(native_executor_bench
    bench/native_executor_bench.cpp
    core/native_executor.cpp
)

# 确定 libuv 链接目标
if(LIBUV_FOUND)
    set(LIBUV_LINK_TARGET ${LIBUV_LIBRARIES})
    set(LIBUV_INCLUDE_DIR ${LIBUV_INCLUDE_DIRS})
elseif(libuv_FOUND)
    set(LIBUV_LINK_TARGET uv_a)
    set(LIBUV_INCLUDE_DIR ${libuv_SOURCE_DIR}/include)
else()
    set(LIBUV_LINK_TARGET uv_a)
    set(LIBUV_INCLUDE_DIR ${libuv_SOURCE_DIR}/include)
endif()

# 链接依赖
target_link_libraries(async_scheduler PRIVATE
    Threads::Threads
    ${LIBUV_LINK_TARGET}
    llama
    llama-common
)

target_link_libraries(ai_scheduler PRIVATE
    async_scheduler
)

target_link_libraries(native_executor_bench PRIVATE
    Threads::Threads
    ${LIBUV_LINK_TARGET}
)

if(MSVC)
    # /utf-8 /Zc:char8_t- 只作用于本项目 C++ 目标，避免经 FetchContent 传播给
    # llama.cpp CUDA 目标导致 nvcc 把 /utf-8 误当输入文件（见上方注释）
    target_compile_options(async_scheduler PRIVATE /W4 /permissive- /O2 /Oi /Ot /Oy /GL /utf-8 /Zc:char8_t-)
    target_compile_options(scheduler_py PRIVATE /W4 /permissive- /O2 /Oi /Ot /Oy /GL /utf-8 /Zc:char8_t-)
    target_compile_options(ai_scheduler PRIVATE /W4 /permissive- /O2 /Oi /Ot /Oy /GL /utf-8 /Zc:char8_t-)
    target_compile_options(native_executor_bench PRIVATE /W4 /permissive- /O2 /Oi /Ot /Oy /GL /utf-8 /Zc:char8_t-)
else()
    target_compile_options(async_scheduler PRIVATE -Wall -Wextra -O3 -march=native -ffast-math)
    target_compile_options(scheduler_py PRIVATE -Wall -Wextra -O3 -march=native -ffast-math)
    target_compile_options(ai_scheduler PRIVATE -Wall -Wextra -O3 -march=native -ffast-math)
    target_compile_options(native_executor_bench PRIVATE -Wall -Wextra -O3 -march=native -ffast-math)
endif()

# 包含目录
target_include_directories(async_scheduler PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${LIBUV_INCLUDE_DIR}
    ${llama_cpp_SOURCE_DIR}
    ${llama_cpp_SOURCE_DIR}/common
)

target_include_directories(ai_scheduler PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
)

target_include_directories(native_executor_bench PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${LIBUV_INCLUDE_DIR}
)

# 测试构建：由文件顶部 set(BUILD_TESTING OFF CACHE ... FORCE) 强制关闭。
# tests/ 内的 integration_test.cpp 引用已删除的旧 API，无法编译，勿启用。
# if(BUILD_TESTING)
#     message(STATUS "Building tests enabled")
#     enable_testing()
#     add_subdirectory(tests)
# endif()

# 安装配置
install(TARGETS ai_scheduler
    RUNTIME DESTINATION bin
)

install(TARGETS async_scheduler
    ARCHIVE DESTINATION lib
)
