# pybind11 3.x 自身要求 cmake >= 3.15，声明不要再低于这个值
cmake_minimum_required(VERSION 3.15)
project(cpp_fast_tokenizer VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# pybind11 统一由 cpp_modules/cmake/pybind11.cmake 提供（版本单一来源）
# 仍会优先复用 cpp_bert_engine/third_party 下已下载的 zip
include(${CMAKE_CURRENT_SOURCE_DIR}/../cmake/pybind11.cmake)

# Pybind module
pybind11_add_module(fast_tokenizer_py bindings/python_bindings.cpp src/bpe_tokenizer.cpp)

# Target include directories
target_include_directories(fast_tokenizer_py PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)

# Apply Architecture-specific optimization flags (AVX2)
if(MSVC)
    target_compile_options(fast_tokenizer_py PRIVATE /arch:AVX2 /O2 /fp:fast)
else()
    target_compile_options(fast_tokenizer_py PRIVATE -mavx2 -mfma -O3 -ffast-math)
endif()
