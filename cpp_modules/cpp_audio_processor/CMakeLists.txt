cmake_minimum_required(VERSION 3.14)
project(cpp_audio_processor VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include(FetchContent)
# We reuse the pybind11 zip file we downloaded for cpp_bert_engine to save time
FetchContent_Declare(
  pybind11
  URL "${CMAKE_CURRENT_SOURCE_DIR}/../cpp_bert_engine/third_party/pybind11-3.0.3.zip"
)
FetchContent_MakeAvailable(pybind11)

# Pybind module
pybind11_add_module(audio_processor_py bindings/python_bindings.cpp src/audio_vad.cpp)

# Target include directories
target_include_directories(audio_processor_py PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)

# Apply Architecture-specific optimization flags (AVX2)
if(MSVC)
    target_compile_options(audio_processor_py PRIVATE /arch:AVX2 /O2 /fp:fast)
else()
    target_compile_options(audio_processor_py PRIVATE -mavx2 -mfma -O3 -ffast-math)
endif()
