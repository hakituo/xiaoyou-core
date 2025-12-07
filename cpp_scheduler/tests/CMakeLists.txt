# 集成测试的CMakeLists.txt配置

# 定义测试项目名称
project(ai_scheduler_tests)

# 设置C++标准
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# 查找依赖包
find_package(Threads REQUIRED)

# 设置包含目录
include_directories(
    ${CMAKE_CURRENT_SOURCE_DIR}/../core
    ${CMAKE_CURRENT_SOURCE_DIR}/../api
    ${CMAKE_CURRENT_SOURCE_DIR}/../workers
    ${CMAKE_CURRENT_SOURCE_DIR}/../utils
    ${CMAKE_CURRENT_SOURCE_DIR}
)

# 列出测试源文件
file(GLOB TEST_SOURCES
    "*.cpp"
    "integration/*.cpp"
    "integration/*.h"
)

# 添加集成测试可执行文件
add_executable(integration_tests
    integration_test.cpp
    integration_test.h
)

# 链接必要的库
target_link_libraries(integration_tests
    PRIVATE
    Threads::Threads
    # 如果有其他库需要链接，在这里添加
)

# 启用测试
if(BUILD_TESTING)
    # 添加测试
    add_test(NAME integration_tests COMMAND integration_tests all)
    
    # 添加特定测试用例
    add_test(NAME scheduler_tests COMMAND integration_tests scheduler)
    add_test(NAME api_tests COMMAND integration_tests api)
    add_test(NAME isolation_tests COMMAND integration_tests isolation)
    add_test(NAME queue_tests COMMAND integration_tests queue)
    add_test(NAME blackbox_tests COMMAND integration_tests blackbox)
endif()

# 设置输出目录
set_target_properties(integration_tests
    PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/tests
)

# 编译选项
if(MSVC)
    # Windows平台编译选项
    target_compile_options(integration_tests PRIVATE /W4 /WX)
else()
    # Linux/Mac平台编译选项
    target_compile_options(integration_tests PRIVATE -Wall -Wextra -Werror)
endif()