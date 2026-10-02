# pybind11 3.x 自身要求 cmake >= 3.15，声明不要再低于这个值
cmake_minimum_required(VERSION 3.15)
project(cpp_memory_index VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Enable OpenMP for parallel computing
find_package(OpenMP REQUIRED)

# pybind11 统一由 cpp_modules/cmake/pybind11.cmake 提供（版本单一来源）
# 历史：本模块曾用 git 拉 v2.11.1（2023 年，不支持 Python 3.13/3.14），现统一到 3.0.3
include(${CMAKE_CURRENT_SOURCE_DIR}/../cmake/pybind11.cmake)

pybind11_add_module(memory_index_py bindings/python_bindings.cpp)

# Apply OpenMP flags
target_link_libraries(memory_index_py PRIVATE OpenMP::OpenMP_CXX)

# Apply Architecture-specific optimization flags (AVX2/AVX-512)
if(MSVC)
    target_compile_options(memory_index_py PRIVATE /arch:AVX2 /O2 /fp:fast /openmp:experimental)
else()
    target_compile_options(memory_index_py PRIVATE -mavx2 -mfma -O3 -ffast-math)
endif()

target_include_directories(memory_index_py PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
