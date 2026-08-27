cmake_minimum_required(VERSION 3.14)
project(cpp_bert_engine VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Enable OpenMP for parallel computing if available
find_package(OpenMP)

include(FetchContent)
FetchContent_Declare(
  pybind11
  URL "${CMAKE_CURRENT_SOURCE_DIR}/third_party/pybind11-3.0.3.zip"
)
FetchContent_MakeAvailable(pybind11)

# Fetch ONNX Runtime precompiled binaries
# Since building from source is slow, we use the precompiled zip for Windows x64.
set(ORT_VERSION "1.24.4")
set(ORT_URL "${CMAKE_CURRENT_SOURCE_DIR}/third_party/onnxruntime-win-x64-${ORT_VERSION}.zip")

FetchContent_Declare(
  onnxruntime
  URL ${ORT_URL}
)
FetchContent_MakeAvailable(onnxruntime)

# Pybind module
pybind11_add_module(bert_engine_py bindings/python_bindings.cpp src/bert_engine.cpp)

# Target include directories
target_include_directories(bert_engine_py PRIVATE 
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${onnxruntime_SOURCE_DIR}/include
)

# Link ONNX Runtime
target_link_libraries(bert_engine_py PRIVATE ${onnxruntime_SOURCE_DIR}/lib/onnxruntime.lib)

if(OpenMP_CXX_FOUND)
    target_link_libraries(bert_engine_py PRIVATE OpenMP::OpenMP_CXX)
endif()

# Apply Architecture-specific optimization flags (AVX2)
if(MSVC)
    target_compile_options(bert_engine_py PRIVATE /arch:AVX2 /O2 /fp:fast)
    # Ensure the DLL is copied to the build output directory for runtime
    add_custom_command(TARGET bert_engine_py POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${onnxruntime_SOURCE_DIR}/lib/onnxruntime.dll"
        $<TARGET_FILE_DIR:bert_engine_py>
    )
else()
    target_compile_options(bert_engine_py PRIVATE -mavx2 -mfma -O3 -ffast-math)
endif()
