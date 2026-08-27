import sys
import os
import time

_DLL_DIR_HANDLES = []

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
build_dir_candidates = [
    os.path.join(project_root, "cpp_modules", "cpp_scheduler", "build", "Release"),
    os.path.join(project_root, "cpp_modules", "cpp_scheduler", "build"),
]

build_dir = None
for candidate in build_dir_candidates:
    if os.path.exists(candidate):
        build_dir = candidate
        sys.path.insert(0, candidate)
        break

if os.name == "nt":
    try:
        if build_dir and os.path.isdir(build_dir):
            _DLL_DIR_HANDLES.append(os.add_dll_directory(build_dir))
    except Exception:
        pass

    try:
        if build_dir and os.path.isdir(build_dir):
            build_root = build_dir
            tail = os.path.basename(build_dir).lower()
            if tail in {"release", "debug"}:
                build_root = os.path.dirname(build_dir)

            libuv_candidates = [
                os.path.join(build_root, "_deps", "libuv-build", "Release"),
                os.path.join(build_root, "_deps", "libuv-build", "Debug"),
            ]
            for libuv_dir in libuv_candidates:
                if os.path.isdir(libuv_dir):
                    _DLL_DIR_HANDLES.append(os.add_dll_directory(libuv_dir))
    except Exception:
        pass

    try:
        import llama_cpp  # type: ignore

        llama_dir = os.path.dirname(getattr(llama_cpp, "__file__", "") or "")
        llama_lib_dir = os.path.join(llama_dir, "lib")
        if os.path.isdir(llama_lib_dir):
            _DLL_DIR_HANDLES.append(os.add_dll_directory(llama_lib_dir))
    except Exception:
        pass

try:
    import importlib

    sys.modules.pop("scheduler_py", None)
    scheduler_py = importlib.import_module("scheduler_py")  # type: ignore
except Exception:
    scheduler_py = None


def _set_cfg_attr(cfg, value, *names: str):
    for name in names:
        if hasattr(cfg, name):
            setattr(cfg, name, value)
            return True
    return False


def _set_gpu_device_id(cfg, value: int):
    _set_cfg_attr(cfg, value, "gpu_device_id", "gpuDeviceId")


def _set_max_context_size(cfg, value: int):
    _set_cfg_attr(cfg, value, "max_context_size", "maxContextSize")

def test_basic_lifecycle():
    print("\n--- Testing Basic Lifecycle ---")
    if scheduler_py is None:
        try:
            import pytest
            pytest.skip("scheduler_py 未构建或不可导入", allow_module_level=False)
        except Exception:
            return
    try:
        scheduler = scheduler_py.ResourceIsolationScheduler()
        print("Created ResourceIsolationScheduler instance")
        
        scheduler.initialize(4) # Pass worker count
        print("Initialized scheduler")
        
        # Check biological system
        # Note: getBiologicalSystem might return None if not initialized or not exposed correctly
        try:
            bio = scheduler.getBiologicalSystem()
            if bio:
                print("Got BiologicalSystem instance")
                nt = bio.getNeurotransmitters()
                print(f"Neurotransmitters: Dopamine={nt.dopamine:.4f}, Serotonin={nt.serotonin:.4f}")
                
                energy = bio.getEnergy()
                print(f"Energy: {energy:.4f}")
                
                # Test update
                bio.update(1.0) # 1 second
                print("Updated biological system (1s)")
                
                nt_after = bio.getNeurotransmitters()
                print(f"Neurotransmitters after update: Dopamine={nt_after.dopamine:.4f}")
            else:
                print("WARNING: getBiologicalSystem returned None")
        except AttributeError as e:
            print(f"WARNING: getBiologicalSystem not found on scheduler object or method missing: {e}")
            print(dir(bio)) # Print available methods
        except Exception as e:
            print(f"Error accessing BiologicalSystem: {e}")

        scheduler.shutdown()
        print("Shutdown scheduler")
    except Exception as e:
        print(f"Lifecycle test failed: {e}")
        raise

def test_llm_config_structs():
    print("\n--- Testing LLM Config Structures ---")
    if scheduler_py is None:
        try:
            import pytest
            pytest.skip("scheduler_py 未构建或不可导入", allow_module_level=False)
        except Exception:
            return
    try:
        # Create LLM config
        config = scheduler_py.LLMModelConfig()
        config.modelPath = "models/llama-2-7b.gguf"
        config.modelType = "llama"
        _set_gpu_device_id(config, 0)
        _set_max_context_size(config, 4096)
        config.temperature = 0.7
        
        print(f"Created config: path={config.modelPath}, type={config.modelType}, temp={config.temperature}")
        
        # Create Inference Response
        resp = scheduler_py.LLMInferenceResponse()
        resp.success = True
        resp.generatedText = "Hello world"
        
        print(f"Created response: success={resp.success}, text={resp.generatedText}")
    except Exception as e:
        print(f"Config struct test failed: {e}")
        raise

def test_llm_mock_stream_callback():
    if scheduler_py is None:
        try:
            import pytest
            pytest.skip("scheduler_py 未构建或不可导入", allow_module_level=False)
        except Exception:
            return

    scheduler = scheduler_py.ResourceIsolationScheduler()
    scheduler.initialize(1)
    try:
        worker = scheduler_py.GPULLMWorker("gpu-worker-0")
        cfg = scheduler_py.LLMModelConfig()
        cfg.modelPath = "models/mock-llm"
        cfg.modelType = "mock"
        _set_gpu_device_id(cfg, 0)
        _set_max_context_size(cfg, 256)
        cfg.maxBatchSize = 64
        cfg.temperature = 0.7
        cfg.topK = 40
        cfg.topP = 0.95
        cfg.repetitionPenalty = 1.1
        worker.setModelConfig(cfg)
        worker.initialize()
        scheduler.addWorker(worker)

        tokens = []

        def on_token(t: str):
            tokens.append(t)

        req = scheduler_py.LLMInferenceRequest()
        req.prompt = "你好"
        req.maxTokens = 8
        req.temperature = 0.7
        req.topK = 40
        req.topP = 0.95
        req.repetitionPenalty = 1.1
        req.streamOutput = True
        req.onTokenGenerated = on_token

        task = scheduler_py.LLMTask(req)
        scheduler.submitTask(task)

        deadline = time.time() + 10.0
        while time.time() < deadline:
            status = task.getStatus()
            if status == scheduler_py.TaskStatus.COMPLETED:
                break
            if status == scheduler_py.TaskStatus.FAILED:
                resp = task.getResponse()
                raise RuntimeError(resp.errorMessage or "LLMTask failed")
            time.sleep(0.01)

        assert tokens
    finally:
        scheduler.shutdown()


def test_cancel_running_llm_task():
    if scheduler_py is None:
        try:
            import pytest

            pytest.skip("scheduler_py 未构建或不可导入", allow_module_level=False)
        except Exception:
            return

    scheduler = scheduler_py.ResourceIsolationScheduler()
    scheduler.initialize(1)
    try:
        worker = scheduler_py.GPULLMWorker("gpu-worker-0")
        cfg = scheduler_py.LLMModelConfig()
        cfg.modelPath = "models/mock-llm"
        cfg.modelType = "mock"
        _set_gpu_device_id(cfg, 0)
        _set_max_context_size(cfg, 256)
        cfg.maxBatchSize = 64
        cfg.temperature = 0.7
        cfg.topK = 40
        cfg.topP = 0.95
        cfg.repetitionPenalty = 1.1
        worker.setModelConfig(cfg)
        worker.initialize()
        scheduler.addWorker(worker)

        req = scheduler_py.LLMInferenceRequest()
        req.prompt = "取消测试"
        req.maxTokens = 200
        req.temperature = 0.7
        req.topK = 40
        req.topP = 0.95
        req.repetitionPenalty = 1.1
        req.streamOutput = True

        task = scheduler_py.LLMTask(req)
        scheduler.submitTask(task)

        deadline = time.time() + 10.0
        while time.time() < deadline:
            status = task.getStatus()
            if status == scheduler_py.TaskStatus.RUNNING:
                break
            if status == scheduler_py.TaskStatus.COMPLETED:
                raise AssertionError("任务过快完成，取消测试无效")
            if status == scheduler_py.TaskStatus.FAILED:
                resp = task.getResponse()
                raise RuntimeError(resp.errorMessage or "LLMTask failed")
            time.sleep(0.01)

        ok = scheduler.cancelTask(task.getTaskId())
        assert ok is True

        deadline = time.time() + 5.0
        while time.time() < deadline:
            status = task.getStatus()
            if status == scheduler_py.TaskStatus.CANCELLED:
                break
            if status == scheduler_py.TaskStatus.COMPLETED:
                raise AssertionError("取消后仍完成，取消未生效")
            if status == scheduler_py.TaskStatus.FAILED:
                resp = task.getResponse()
                raise RuntimeError(resp.errorMessage or "LLMTask failed")
            time.sleep(0.01)

        assert task.getStatus() == scheduler_py.TaskStatus.CANCELLED
    finally:
        scheduler.shutdown()

if __name__ == "__main__":
    try:
        test_basic_lifecycle()
        test_llm_config_structs()
        print("\nAll tests passed!")
    except Exception as e:
        print(f"\nTests failed: {e}")
        sys.exit(1)
