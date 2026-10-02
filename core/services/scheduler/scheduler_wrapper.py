from core.utils.logger import get_logger
import sys
import os

import importlib
import importlib.machinery

logger = get_logger(__name__)

_DLL_DIR_HANDLES = []


# Find and import the C++ scheduler extension
def _import_scheduler_py():
    # Helper to find the build directory
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # Add current directory to DLL search path for Windows
    if os.name == "nt":
        try:
            if os.path.isdir(current_dir):
                _DLL_DIR_HANDLES.append(os.add_dll_directory(current_dir))
            # Add lib directory for DLL files
            lib_dir = os.path.join(current_dir, "lib")
            if os.path.isdir(lib_dir):
                _DLL_DIR_HANDLES.append(os.add_dll_directory(lib_dir))
        except (Exception, AttributeError):
            pass

        project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
        cpp_scheduler_build = os.path.join(project_root, "cpp_modules", "cpp_scheduler", "build")
        libuv_candidates = [
            os.path.join(cpp_scheduler_build, "cuda", "_deps", "libuv-build", "Release"),
            os.path.join(cpp_scheduler_build, "cuda", "_deps", "libuv-build", "Debug"),
            os.path.join(cpp_scheduler_build, "cuda", "_deps", "libuv-build"),
            os.path.join(
                cpp_scheduler_build,
                "_deps",
                "libuv-build",
                "Release",
            ),
            os.path.join(
                cpp_scheduler_build, "_deps", "libuv-build", "Debug"
            ),
            os.path.join(
                cpp_scheduler_build, "_deps", "libuv-build"
            ),
        ]
        for libuv_dir in libuv_candidates:
            try:
                if os.path.isdir(libuv_dir):
                    _DLL_DIR_HANDLES.append(os.add_dll_directory(libuv_dir))
            except (Exception, AttributeError):
                pass

        try:
            import llama_cpp  # type: ignore

            llama_dir = os.path.dirname(getattr(llama_cpp, "__file__", "") or "")
            llama_lib_dir = os.path.join(llama_dir, "lib")
            if os.path.isdir(llama_lib_dir):
                _DLL_DIR_HANDLES.append(os.add_dll_directory(llama_lib_dir))
        except (Exception, AttributeError):
            pass

        # 添加 CUDA Toolkit bin 目录（ggml-cuda.dll 依赖 cudart/cublas）
        try:
            cuda_path = os.environ.get("CUDA_PATH")
            if cuda_path:
                cuda_bin = os.path.join(cuda_path, "bin")
                if os.path.isdir(cuda_bin):
                    _DLL_DIR_HANDLES.append(os.add_dll_directory(cuda_bin))
        except (Exception, AttributeError):
            pass

        # 添加 site-packages 目录（llama.dll / ggml*.dll 可能安装在这里，兜底）
        try:
            import site
            for sp in site.getsitepackages():
                if os.path.isdir(sp):
                    _DLL_DIR_HANDLES.append(os.add_dll_directory(sp))
        except (Exception, AttributeError):
            pass
    elif os.name == "posix":
        # On Linux, shared libraries are typically found via LD_LIBRARY_PATH or standard paths.
        # We can add paths to sys.path, but for shared libraries (.so),
        # the OS loader needs to know where they are if they are not in standard paths.
        pass

    # core/services/scheduler -> services -> core -> root
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
    cpp_scheduler_build = os.path.join(project_root, "cpp_modules", "cpp_scheduler", "build")

    # CUDA/CPU 双版本共存：XIAOYOU_CPP_BACKEND=cpu|cuda|auto
    # - cuda: 优先加载 build-cuda/Release（CUDA 版，需已用 build_cuda.ps1 编译）
    # - cpu:  强制使用 build/Release（纯 CPU 版）
    # - auto: 存在 CUDA 版产物时优先 CUDA，否则 CPU
    backend = os.environ.get("XIAOYOU_CPP_BACKEND", "auto").strip().lower()
    cuda_dir = os.path.join(cpp_scheduler_build, "cuda", "Release")
    cpu_dir = os.path.join(cpp_scheduler_build, "Release")

    search_paths = []
    if backend == "cuda":
        if not os.path.isdir(cuda_dir):
            logger.warning(
                "XIAOYOU_CPP_BACKEND=cuda 但未找到 %s，回退 CPU 版。"
                "请先运行 scripts/cpp_scheduler/build_cuda.ps1 编译 CUDA 版。",
                cuda_dir,
            )
        else:
            search_paths.append(cuda_dir)
    elif backend == "cpu":
        pass
    else:  # auto
        if os.path.isdir(cuda_dir):
            logger.info("XIAOYOU_CPP_BACKEND=auto：检测到 CUDA 版产物，优先加载 %s", cuda_dir)
            search_paths.append(cuda_dir)

    # Possible locations for the compiled extension
    search_paths += [
        cpu_dir,
        os.path.join(cpp_scheduler_build, "Debug"),
        cpp_scheduler_build,
        os.path.join(project_root, "build", "Release"),
        current_dir,
    ]

    scheduler_module = None

    extension_suffixes = tuple(importlib.machinery.EXTENSION_SUFFIXES or [])
    py_tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
    incompatible_candidates = []

    for path in search_paths:
        if os.path.exists(path):
            candidates = [
                f
                for f in os.listdir(path)
                if f.startswith("scheduler_py")
                and (f.endswith(".pyd") or f.endswith(".so"))
            ]
            if candidates:
                logger.info(f"Found scheduler_py extension in: {path}")
                if path not in sys.path:
                    sys.path.insert(0, path)

                # Add DLL directory for Windows
                if os.name == "nt":
                    try:
                        _DLL_DIR_HANDLES.append(os.add_dll_directory(path))
                    except Exception:
                        pass
                    # MSVC 多配置生成器把配套 DLL（llama.dll / ggml-*.dll）输出到
                    # build/<variant>/bin/Release，而 pyd 在 build/<variant>/Release。
                    # AddDllDirectory 按"后添加先搜索"（LIFO）解析，此处最后注册使其
                    # 优先级最高，确保加载与所选 pyd 配套的新编译 DLL，而不是
                    # site-packages 里安装的旧版。
                    for extra in (
                        os.path.join(os.path.dirname(path), "bin", "Release"),
                        os.path.join(os.path.dirname(path), "bin"),
                    ):
                        try:
                            if os.path.isdir(extra):
                                _DLL_DIR_HANDLES.append(os.add_dll_directory(extra))
                        except Exception:
                            pass

                has_compatible = any(
                    name == f"scheduler_py{suffix}" for name in candidates for suffix in extension_suffixes
                )
                if not has_compatible:
                    incompatible_candidates.append((path, list(candidates)))
                    logger.error(
                        "Found scheduler_py binaries but none match current Python ABI (%s). "
                        "Current suffixes: %s, candidates: %s",
                        py_tag,
                        list(extension_suffixes),
                        candidates,
                    )
                    continue

                try:
                    importlib.invalidate_caches()
                    if "scheduler_py" in sys.modules:
                        del sys.modules["scheduler_py"]
                    scheduler_py = importlib.import_module("scheduler_py")

                    scheduler_module = scheduler_py
                    break
                except Exception as e:
                    logger.error(f"Failed to import scheduler_py from {path}: {e}")

    if scheduler_module is None:
        if incompatible_candidates:
            logger.error(
                "scheduler_py ABI mismatch detected. Please rebuild cpp_scheduler for current Python: %s",
                py_tag,
            )
        logger.warning(
            "Could not find scheduler_py extension. C++ Scheduler features will be unavailable."
        )

    return scheduler_module


_scheduler_py_cache = None
_scheduler_py_loaded = False


def _get_scheduler_py():
    """延迟加载 scheduler_py C++ 扩展"""
    global _scheduler_py_cache, _scheduler_py_loaded
    if not _scheduler_py_loaded:
        _scheduler_py_loaded = True
        _scheduler_py_cache = _import_scheduler_py()
    return _scheduler_py_cache


def _get_scheduler_class(class_name: str):
    """延迟获取 scheduler_py 中的类"""
    mod = _get_scheduler_py()
    if mod is not None:
        return getattr(mod, class_name, None)
    return None


def is_cpp_scheduler_available():
    return _get_scheduler_py() is not None
