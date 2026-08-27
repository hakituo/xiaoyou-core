cmake_minimum_required(VERSION 3.14)
project(cpp_memory_index VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Enable OpenMP for parallel computing
find_package(OpenMP REQUIRED)

include(FetchContent)
FetchContent_Declare(
  pybind11
  GIT_REPOSITORY https://github.com/pybind/pybind11.git
  GIT_TAG v2.11.1
  GIT_SHALLOW TRUE
)
FetchContent_MakeAvailable(pybind11)

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
