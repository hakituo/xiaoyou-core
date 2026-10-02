# cpp_modules 共享：pybind11 的唯一版本源（五个 C++ 子项目统一从这里取）
#
# 用法（每个子项目的顶层 CMakeLists.txt）：
#   include(${CMAKE_CURRENT_SOURCE_DIR}/../cmake/pybind11.cmake)
#
# 历史包袱：过去分裂成两拨——cpp_memory_index / cpp_scheduler 用 git 拉 v2.11.1（2023 年发布，
# 不支持 Python 3.13 / 3.14），cpp_bert_engine / cpp_fast_tokenizer / cpp_audio_processor 用本地
# zip 3.0.3。现在统一到同一个版本，改版本只需要动 PYBIND11_VERSION 一处。
#
# 取值优先级：
#   1) 本地 zip（third_party/ 被 .gitignore 排除，存在时离线也能编，且省一次下载）
#   2) GitHub 同名源码包（自带 SHA256 校验）——新机器 clone 下来没 zip 也能一次编出来
#
# 需要临时用别的版本做对照时：-DPYBIND11_VERSION=3.0.4

include_guard(GLOBAL)

set(PYBIND11_VERSION "3.0.3" CACHE STRING "cpp_modules 统一使用的 pybind11 版本")

# 兼容两种 include 场景：子项目顶层（推荐）与其子目录。
set(_pybind11_zip "")
foreach(_dir
        "${CMAKE_CURRENT_SOURCE_DIR}/third_party"
        "${CMAKE_SOURCE_DIR}/third_party"
        "${CMAKE_CURRENT_SOURCE_DIR}/../cpp_bert_engine/third_party"
        "${CMAKE_CURRENT_SOURCE_DIR}/../third_party")
  if(EXISTS "${_dir}/pybind11-${PYBIND11_VERSION}.zip")
    set(_pybind11_zip "${_dir}/pybind11-${PYBIND11_VERSION}.zip")
    break()
  endif()
endforeach()

include(FetchContent)

if(_pybind11_zip)
  message(STATUS "[pybind11 ${PYBIND11_VERSION}] 复用本地包: ${_pybind11_zip}")
  FetchContent_Declare(pybind11 URL "${_pybind11_zip}")
else()
  message(STATUS "[pybind11 ${PYBIND11_VERSION}] 本地包不存在，从 GitHub 下载 v${PYBIND11_VERSION}")
  FetchContent_Declare(
    pybind11
    URL "https://github.com/pybind/pybind11/archive/refs/tags/v${PYBIND11_VERSION}.tar.gz"
    URL_HASH SHA256=787459E1E186EE82001759508FEFA408373EAE8A076FFE0078B126C6F8F0EC5E
  )
endif()

FetchContent_MakeAvailable(pybind11)
