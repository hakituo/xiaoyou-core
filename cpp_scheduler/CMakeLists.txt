cmake_minimum_required(VERSION 3.14)
project(cpp_scheduler VERSION 1.0.0 LANGUAGES CXX)

# 设置C++标准
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# 编译选项
if(MSVC)
    add_compile_options(/W4 /WX /permissive- /O2 /Oi /Ot /Oy /GL)
else()
    add_compile_options(-Wall -Wextra -Werror -O3 -march=native -ffast-math)
endif()

# 查找依赖
find_package(Threads REQUIRED)
find_package(libuv QUIET)

# 如果没找到libuv，设置为需要下载
if(NOT libuv_FOUND)
    message(STATUS "libuv not found, will download during build")
    include(FetchContent)
    FetchContent_Declare(
        libuv
        GIT_REPOSITORY https://github.com/libuv/libuv.git
        GIT_TAG v1.48.0
    )
    FetchContent_MakeAvailable(libuv)
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

# 创建主程序
add_executable(ai_scheduler
    ${API_SOURCES}
    main.cpp
)

# 链接依赖
target_link_libraries(async_scheduler PRIVATE
    Threads::Threads
    uv_a
)

target_link_libraries(ai_scheduler PRIVATE
    async_scheduler
)

# 包含目录
target_include_directories(async_scheduler PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${libuv_SOURCE_DIR}/include
)

target_include_directories(ai_scheduler PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
)

# 启用测试选项
option(BUILD_TESTING "Build tests" ON)

# 如果启用测试，添加测试子目录
if(BUILD_TESTING)
    message(STATUS "Building tests enabled")
    enable_testing()
    add_subdirectory(tests)
endif()

# 安装配置
install(TARGETS ai_scheduler
    RUNTIME DESTINATION bin
)

install(TARGETS async_scheduler
    ARCHIVE DESTINATION lib
)