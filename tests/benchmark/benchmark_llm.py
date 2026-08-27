import time
import statistics
import sys
import os
import argparse
from pathlib import Path
from typing import List, Optional, Deque, Dict, Any

try:
    import yaml
except Exception:
    yaml = None

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _env_flag_enabled(name: str) -> bool:
    value = str(os.getenv(name, "") or "").strip().lower()
    return value in {"1", "true", "yes", "y", "on"}

def _get_int_env(name: str, default: int) -> int:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _get_float_env(name: str, default: float) -> float:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except Exception:
        return default


def _percentile(values, p: float) -> float:
    if not values:
        return 0.0
    if p <= 0:
        return float(min(values))
    if p >= 100:
        return float(max(values))
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return float(sorted_vals[f])
    d0 = sorted_vals[f] * (c - k)
    d1 = sorted_vals[c] * (k - f)
    return float(d0 + d1)


async def benchmark_tts_inprocess(text: str, rounds: int = 5, warmup: int = 1, ref_wav: str = ""):
    from routers.v1.media import _generate_tts_with_async

    params = {}
    if ref_wav:
        params["speaker_wav"] = ref_wav

    print("\n" + "=" * 50)
    print("开始测试: TTS (in-process, 复刻 /api/v1/tts 的核心路径)")
    print("=" * 50)
    print(f"rounds={rounds}, warmup={warmup}")
    print(f"text_len={len(text)}")
    if ref_wav:
        print(f"ref_wav={ref_wav}")

    for i in range(max(0, int(warmup))):
        try:
            await _generate_tts_with_async(text=text, params=params)
        except Exception as e:
            print(f"Warmup 失败: {e}")
            return

    costs = []
    audio_sizes = []
    for i in range(max(1, int(rounds))):
        t0 = time.perf_counter()
        try:
            result = await _generate_tts_with_async(text=text, params=params)
        except Exception as e:
            print(f"第 {i + 1} 次失败: {e}")
            return
        t1 = time.perf_counter()
        costs.append(t1 - t0)
        audio_base64 = str((result or {}).get("audio_base64") or "")
        audio_sizes.append(len(audio_base64))
        print(f"[{i + 1}/{rounds}] cost={costs[-1]:.3f}s, audio_base64_len={audio_sizes[-1]}")

    avg = statistics.mean(costs) if costs else 0.0
    p50 = _percentile(costs, 50)
    p95 = _percentile(costs, 95)

    print("\n" + "=" * 40)
    print(f"avg={avg:.3f}s, p50={p50:.3f}s, p95={p95:.3f}s")
    if audio_sizes:
        print(f"audio_base64_len(avg)={statistics.mean(audio_sizes):.0f}")
    print("=" * 40)


async def benchmark_tts_concurrent(
    text: str,
    rounds: int = 5,
    warmup: int = 1,
    concurrency: int = 4,
    ref_wav: str = "",
):
    import asyncio
    from routers.v1.media import _generate_tts_with_async

    params = {}
    if ref_wav:
        params["speaker_wav"] = ref_wav

    concurrency = max(1, int(concurrency))
    rounds = max(1, int(rounds))
    warmup = max(0, int(warmup))

    print("\n" + "=" * 50)
    print("开始测试: TTS (concurrent, in-process)")
    print("=" * 50)
    print(f"rounds={rounds}, warmup={warmup}, concurrency={concurrency}")
    print(f"text_len={len(text)}")
    if ref_wav:
        print(f"ref_wav={ref_wav}")

    async def _one_call() -> float:
        t0 = time.perf_counter()
        await _generate_tts_with_async(text=text, params=params)
        t1 = time.perf_counter()
        return t1 - t0

    for _ in range(warmup):
        try:
            await asyncio.gather(*[_one_call() for _ in range(concurrency)])
        except Exception as e:
            print(f"Warmup 失败: {e}")
            return

    per_req_costs: List[float] = []
    batch_costs: List[float] = []
    for i in range(rounds):
        t_batch0 = time.perf_counter()
        try:
            costs = await asyncio.gather(*[_one_call() for _ in range(concurrency)])
        except Exception as e:
            print(f"第 {i + 1} 轮失败: {e}")
            return
        t_batch1 = time.perf_counter()
        batch_cost = t_batch1 - t_batch0
        batch_costs.append(batch_cost)
        per_req_costs.extend([float(x) for x in costs])
        print(
            f"[{i + 1}/{rounds}] batch_cost={batch_cost:.3f}s, per_req_p50={_percentile(costs, 50):.3f}s, per_req_p95={_percentile(costs, 95):.3f}s"
        )

    per_avg = statistics.mean(per_req_costs) if per_req_costs else 0.0
    per_p50 = _percentile(per_req_costs, 50)
    per_p95 = _percentile(per_req_costs, 95)
    batch_avg = statistics.mean(batch_costs) if batch_costs else 0.0
    rps = (concurrency / batch_avg) if batch_avg > 0 else 0.0

    print("\n" + "=" * 40)
    print(f"per_req: avg={per_avg:.3f}s, p50={per_p50:.3f}s, p95={per_p95:.3f}s")
    print(f"batch:   avg={batch_avg:.3f}s, rps~={rps:.2f}")
    print("=" * 40)


def benchmark_raw_llama_cpp(model_path: Optional[str] = None, draft_model_path: Optional[str] = None):
    try:
        from llama_cpp import Llama
    except ImportError:
        print("错误: 无法导入 llama_cpp，请检查是否在正确的环境中运行 (venv_core)")
        sys.exit(1)

    allow_full_gpu = str(os.getenv("XIAOYOU_RUN_BENCHMARK", "") or "").strip() == "1"

    project_root = PROJECT_ROOT
    default_model_path = os.path.join(
        project_root,
        "models",
        "llm",
        "L3-8B-Stheno-v3.2-Q5_K_M.gguf",
    )
    model_path = str(model_path or os.getenv("XIAOYOU_BENCHMARK_MODEL_PATH", default_model_path) or default_model_path)
    
    enable_draft = str(os.getenv("XIAOYOU_BENCHMARK_ENABLE_DRAFT", "") or "").strip() == "1"
    if enable_draft:
        draft_model_path = draft_model_path or os.getenv("XIAOYOU_BENCHMARK_DRAFT_MODEL_PATH")
    else:
        draft_model_path = None
    
    if not os.path.exists(model_path):
        print(f"错误: 找不到主模型文件: {model_path}")
        return

    n_ctx = _get_int_env("XIAOYOU_BENCHMARK_N_CTX", 2048)
    max_tokens = _get_int_env("XIAOYOU_BENCHMARK_MAX_TOKENS", 128)
    n_gpu_layers_default = -1 if allow_full_gpu else 0
    n_gpu_layers = _get_int_env("XIAOYOU_BENCHMARK_N_GPU_LAYERS", n_gpu_layers_default)

    if not allow_full_gpu and n_gpu_layers != 0:
        n_gpu_layers = 0

    print(f"正在加载主模型: {os.path.basename(model_path)}")
    if draft_model_path:
        print(f"正在加载草稿模型: {os.path.basename(draft_model_path)} (Speculative Decoding)")
    
    print(f"配置: n_gpu_layers={n_gpu_layers}, n_ctx={n_ctx}, max_tokens={max_tokens}")
    
    # 自动识别模型类型并设置 Prompt
    model_name_lower = os.path.basename(model_path).lower()
    if "qwen" in model_name_lower:
        prompt = "<|im_start|>system\nYou are a helpful assistant.<|im_end|>\n<|im_start|>user\nHello, tell me a short joke.<|im_end|>\n<|im_start|>assistant\n"
        print("检测到 Qwen 模型，使用 Qwen Prompt 格式")
        stop_tokens = ["<|im_end|>", "<|endoftext|>"]
    elif "llama" in model_name_lower:
        prompt = "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\nYou are a helpful assistant.<|eot_id|><|start_header_id|>user<|end_header_id|>\n\nHello, tell me a short joke.<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
        print("检测到 Llama 模型，使用 Llama-3 Prompt 格式")
        stop_tokens = ["<|eot_id|>", "<|end_of_text|>"]
    else:
        prompt = "Hello, tell me a short joke."
        print("未识别模型类型，使用纯文本 Prompt")
        stop_tokens = []

    start_load = time.time()
    try:
        # 初始化主模型
        draft_gpu_layers = -1 if os.getenv("XIAOYOU_BENCHMARK_DRAFT_GPU") == "1" else 0
        llm = Llama(
            model_path=model_path,
            n_gpu_layers=n_gpu_layers,
            n_ctx=n_ctx,
            verbose=False,
            draft_model=Llama(
                model_path=draft_model_path,
                n_gpu_layers=draft_gpu_layers,
                n_ctx=n_ctx,
                verbose=False
            ) if draft_model_path else None
        )
    except Exception as e:
        print(f"模型加载失败: {e}")
        return
    
    end_load = time.time()
    print(f"模型加载耗时: {end_load - start_load:.2f} 秒")

    print("\n开始生成测试...")
    start_gen = time.time()
    
    output = llm(
        prompt,
        max_tokens=max_tokens,
        stop=stop_tokens,
        echo=False
    )
    
    end_gen = time.time()
    
    # 统计结果
    usage = output['usage']
    completion_tokens = usage['completion_tokens']
    total_time = end_gen - start_gen
    tps = completion_tokens / total_time
    
    print("\n" + "="*40)
    print(f"生成内容: {output['choices'][0]['text'].strip()}")
    print("="*40)
    print(f"生成 tokens: {completion_tokens}")
    print(f"总耗时: {total_time:.2f} 秒")
    print(f"速度: {tps:.2f} tokens/s")
    print("="*40)

async def benchmark_cpp_scheduler(model_path: Optional[str] = None, draft_model_path: Optional[str] = None):
    """
    使用项目正式的 C++ 调度器进行基准测试
    这是最准确的测试方式，因为它完全复刻了对话时的真实逻辑
    """
    from core.services.scheduler.cpp_scheduler_engine import cpp_scheduler_engine
    from config.integrated_config import get_settings

    print("\n" + "="*50)
    print("开始测试: C++ Scheduler (Speculative Decoding)")
    print("="*50)

    settings = get_settings()

    if model_path:
        settings.model_adapter.text_model.text_model_path = model_path
    elif not settings.model_adapter.text_model.text_model_path:
        fallback_path = None
        try:
            fallback_path = getattr(settings.model, "path", None) or getattr(settings.model, "text_model_path", None)
        except Exception:
            fallback_path = None
        if fallback_path:
            settings.model_adapter.text_model.text_model_path = str(fallback_path)
        elif yaml is not None:
            cfg = None
            try:
                from config.yaml_loader import load_resolved_yaml_config_from_disk

                cfg, _, _ = load_resolved_yaml_config_from_disk(
                    Path("config/yaml/app.yaml")
                )
            except Exception:
                cfg = None
            if isinstance(cfg, dict):
                try:
                    raw_path = str(((cfg.get("model") or {}).get("path") or "")).strip()
                except Exception:
                    raw_path = ""
                if raw_path:
                    if not os.path.isabs(raw_path):
                        raw_path = os.path.join(PROJECT_ROOT, raw_path)
                    settings.model_adapter.text_model.text_model_path = raw_path
    enable_draft = str(os.getenv("XIAOYOU_BENCHMARK_ENABLE_DRAFT", "") or "").strip() == "1"
    if enable_draft and draft_model_path:
        settings.model_adapter.text_model.draft_model_path = draft_model_path
        try:
            settings.model_adapter.text_model.draft_gpu_device_id = int(
                os.getenv("XIAOYOU_BENCHMARK_DRAFT_GPU_DEVICE_ID", "0")
            )
        except Exception:
            settings.model_adapter.text_model.draft_gpu_device_id = 0
    else:
        settings.model_adapter.text_model.draft_model_path = None
        settings.model_adapter.text_model.draft_gpu_device_id = -1

    print(f"主模型: {settings.model_adapter.text_model.text_model_path}")
    print(f"草稿模型: {settings.model_adapter.text_model.draft_model_path}")

    if not settings.model_adapter.text_model.text_model_path:
        print("主模型路径为空，无法进行测试")
        return

    # 1. 获取 C++ 调度器引擎
    engine = cpp_scheduler_engine
    
    start_load = time.time()
    # 构造 GPU 配置
    gpu_config = {
        "model_path": settings.model_adapter.text_model.text_model_path,
        "draft_model_path": settings.model_adapter.text_model.draft_model_path or "",
        "draft_gpu_device_id": settings.model_adapter.text_model.draft_gpu_device_id,
        "max_context_size": getattr(settings.model_adapter.text_model, "max_context_size", 2048),
        "gpu_device_id": getattr(settings.model_adapter.text_model, "gpu_device_id", 0),
        "backend": "cpp" # 强制使用 C++ 后端
    }
    
    # 设置环境变量以允许 C++ LLM Worker
    os.environ["XIAOYOU_ALLOW_CPP_LLM_WORKER"] = "true"
    
    # 使用 start 方法初始化
    engine.start(gpu_config=gpu_config, preload_llm=True)
    
    if not engine._gpu_worker_ready:
        print("C++ 引擎初始化失败 (GPU Worker 未就绪)")
        return
    print(f"C++ 引擎加载耗时: {time.time() - start_load:.2f} 秒")

    # 2. 准备测试 Prompt
    model_name_lower = os.path.basename(settings.model_adapter.text_model.text_model_path).lower()
    if "qwen" in model_name_lower:
        prompt = "<|im_start|>system\nYou are a helpful assistant.<|im_end|>\n<|im_start|>user\nHello, tell me a short joke.<|im_end|>\n<|im_start|>assistant\n"
    else:
        prompt = "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\nYou are a helpful assistant.<|eot_id|><|start_header_id|>user<|end_header_id|>\n\nHello, tell me a short joke.<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"

    max_tokens = _get_int_env("XIAOYOU_BENCHMARK_MAX_TOKENS", 50)
    
    print(f"\n开始推理测试 (max_tokens={max_tokens})...")
    
    # 3. 执行推理
    start_gen = time.time()
    first_token_time = None
    tokens_count = 0
    full_text = ""

    async for chunk in engine.submit_llm_task(
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=0.1, # 投机采样在低温下效果最好
        conversation_id="benchmark_test"
    ):
        if first_token_time is None:
            first_token_time = time.time() - start_gen
            print(f"首字延迟 (TTFT): {first_token_time:.3f} 秒")
        
        if isinstance(chunk, dict) and "error" in chunk:
            print(f"推理错误: {chunk['error']}")
            break

        content = ""
        if isinstance(chunk, str):
            content = chunk
        elif isinstance(chunk, dict):
            content = chunk.get("content", "")
        
        if content:
            full_text += content
            # 简单估算 token 数
            tokens_count += 1 

    end_gen = time.time()
    total_time = end_gen - start_gen
    tps = tokens_count / total_time if total_time > 0 else 0

    print("\n" + "="*40)
    print(f"生成内容: {full_text.strip()}")
    print("="*40)
    print(f"预估生成 tokens: {tokens_count}")
    print(f"总推理耗时: {total_time:.2f} 秒")
    print(f"平均速度: {tps:.2f} tokens/s")
    print("="*40)

    await engine.stop()

async def benchmark_module(model_path: Optional[str] = None):
    from config.integrated_config import get_settings
    from core.llm import get_llm_module

    settings = get_settings()

    default_model_path = (
        model_path
        or str(os.getenv("XIAOYOU_BENCHMARK_MODEL_PATH", "") or "").strip()
        or getattr(settings.model, "text_path", None)
        or None
    )
    model_path = default_model_path

    max_tokens = _get_int_env("XIAOYOU_BENCHMARK_MAX_TOKENS", int(getattr(settings.model, "max_new_tokens", 128) or 128))
    first_token_timeout = _get_float_env(
        "XIAOYOU_FIRST_TOKEN_TIMEOUT",
        float(getattr(settings.model, "first_token_timeout", 10) or 10),
    )
    temperature = _get_float_env("XIAOYOU_BENCHMARK_TEMPERATURE", float(getattr(settings.model, "temperature", 0.7) or 0.7))

    llm = get_llm_module()

    t0 = time.time()
    await llm.initialize()
    t_init = time.time() - t0

    prompts = [
        "你好，请用一句话介绍你自己。",
        "请用三点列出：1) 你能做什么 2) 你不能做什么 3) 你需要我提供什么信息。",
    ]

    for idx, prompt in enumerate(prompts, start=1):
        messages = [{"role": "user", "content": prompt}]
        llm_kwargs = {
            "max_tokens": max_tokens,
            "temperature": temperature,
            "first_token_timeout": first_token_timeout,
        }
        if model_path:
            llm_kwargs["model_path"] = model_path

        print(f"\n[MODULE] Round {idx}: prompt_len={len(prompt)}")
        print(f"[MODULE] init_cost={t_init:.3f}s, first_token_timeout={first_token_timeout}, max_tokens={max_tokens}")
        if model_path:
            print(f"[MODULE] model_path={model_path}")

        t_start = time.time()
        t_first = None
        parts: List[str] = []

        async for chunk in llm.stream_chat(messages, **llm_kwargs):
            if isinstance(chunk, dict) and chunk.get("error"):
                print(f"[MODULE] ERROR: {chunk.get('error')}")
                break
            content = ""
            if isinstance(chunk, dict):
                content = str(chunk.get("content") or "")
            else:
                content = str(getattr(chunk, "content", "") or "")

            if content:
                if t_first is None:
                    t_first = time.time() - t_start
                    print(f"[MODULE] first_token_cost={t_first:.3f}s")
                parts.append(content)

        t_total = time.time() - t_start
        text = "".join(parts).strip()
        print(f"[MODULE] total_cost={t_total:.3f}s, output_chars={len(text)}")
        if text:
            print("=" * 40)
            print(text)
            print("=" * 40)


async def benchmark_main(prompt: str, host: str = "127.0.0.1"):
    import asyncio
    import json
    import subprocess
    import threading
    from collections import deque

    try:
        import psutil
    except Exception:
        psutil = None

    import httpx
    import websockets

    project_root = PROJECT_ROOT
    python_exe = sys.executable

    env = dict(os.environ)
    env["XIAOYOU_DISABLE_TTS"] = "1"
    env["XIAOYOU_DISABLE_IMAGE"] = "1"
    env.setdefault("XIAOYOU_SFW_ONLY", "1")
    env.setdefault("XIAOYOU_MODEL_LLM_PRELOAD_ON_STARTUP", "0")
    env.setdefault("XIAOYOU_MODEL_N_CTX", "1536")
    env.setdefault("XIAOYOU_MODEL_N_GPU_LAYERS", "12")
    env.setdefault("XIAOYOU_MODEL_N_BATCH", "64")
    env.setdefault("XIAOYOU_MODEL_MAX_NEW_TOKENS", "128")
    env.setdefault("XIAOYOU_MODEL_KV_SWAP_ENABLED", "1")
    env.setdefault("XIAOYOU_MODEL_KV_SWAP_TRIGGER_TOKENS", "1024")
    env.setdefault("XIAOYOU_SEND_IMAGE_BASE64", "0")
    env.setdefault("XIAOYOU_IMAGE_BASE64_MAX_BYTES", "1048576")
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    health_timeout = _get_float_env("XIAOYOU_BENCHMARK_HEALTH_TIMEOUT", 3.0)

    async def _try_health(port: int) -> bool:
        urls = [
            f"http://{host}:{port}/health",
            f"http://{host}:{port}/health/",
        ]
        try:
            async with httpx.AsyncClient(timeout=health_timeout) as client:
                for url in urls:
                    r = await client.get(url)
                    if r.status_code == 200:
                        return True
                return False
        except Exception:
            return False

    preferred_port = _get_int_env("XIAOYOU_BENCHMARK_FALLBACK_PORT", 8000)
    if yaml is not None:
        try:
            from config.yaml_loader import load_resolved_yaml_config_from_disk

            cfg, _, _ = load_resolved_yaml_config_from_disk(
                Path("config/yaml/app.yaml")
            )
            if isinstance(cfg, dict):
                preferred_port = int(((cfg.get("server") or {}).get("port") or preferred_port))
        except Exception:
            pass

    use_existing = _env_flag_enabled("XIAOYOU_BENCHMARK_USE_EXISTING")
    if not use_existing:
        try:
            if await _try_health(int(preferred_port)):
                use_existing = True
        except Exception:
            use_existing = False

    creationflags = 0
    if os.name == "nt":
        try:
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        except Exception:
            creationflags = 0

    proc = None
    if not use_existing:
        proc = subprocess.Popen(
            [python_exe, "-u", os.path.join(project_root, "main.py")],
            cwd=project_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )

    def _terminate_process_tree(timeout: float = 8.0):
        if proc is None:
            return
        if proc.poll() is not None:
            return
        if psutil is not None:
            try:
                p = psutil.Process(proc.pid)
                for child in p.children(recursive=True):
                    try:
                        child.kill()
                    except Exception:
                        pass
                try:
                    p.kill()
                except Exception:
                    pass
            except Exception:
                pass
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=timeout)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    import atexit

    atexit.register(_terminate_process_tree)

    output_lines: Deque[str] = deque(maxlen=200)
    found_port: Dict[str, Optional[int]] = {"port": None}

    def _drain_output():
        if proc.stdout is None:
            return
        for line in proc.stdout:
            output_lines.append(line.rstrip("\n"))
            print(line, end="")
            if found_port["port"] is None:
                try:
                    import re

                    m = re.search(r"XiaoYou Core ready on http://[^:]+:(\d+)", line)
                    if not m:
                        m = re.search(r"Uvicorn running on http://[^:]+:(\d+)", line)
                    if not m:
                        m = re.search(r"http://[^:]+:(\d+)", line)
                    if not m:
                        m = re.search(r"Switched to (\d+)", line)
                    if not m:
                        m = re.search(r"切换到 (\d+)", line)
                    if m:
                        found_port["port"] = int(m.group(1))
                except Exception:
                    pass

    t = threading.Thread(target=_drain_output, daemon=True)
    t.start()

    async def _try_health(port: int) -> bool:
        urls = [
            f"http://{host}:{port}/health",
            f"http://{host}:{port}/health/",
        ]
        try:
            async with httpx.AsyncClient(timeout=health_timeout) as client:
                for url in urls:
                    r = await client.get(url)
                    if r.status_code == 200:
                        return True
                return False
        except Exception:
            return False

    async def _find_server_port(preferred: int = 8000, max_tries: int = 100, timeout: float = 180.0) -> Optional[int]:
        start = time.time()
        while time.time() - start < timeout:
            if found_port.get("port"):
                try:
                    if await _try_health(int(found_port["port"])):
                        return int(found_port["port"])
                except Exception:
                    pass
            for port in range(preferred, preferred + max_tries):
                if await _try_health(port):
                    return port
            await asyncio.sleep(0.5)
        return None

    port = None
    try:
        startup_timeout = _get_float_env("XIAOYOU_BENCHMARK_STARTUP_TIMEOUT", 180.0)
        port = await _find_server_port(timeout=startup_timeout)
        if port is None:
            fallback_port = _get_int_env("XIAOYOU_BENCHMARK_FALLBACK_PORT", 8000)
            if yaml is not None:
                try:
                    from config.yaml_loader import load_resolved_yaml_config_from_disk

                    cfg, _, _ = load_resolved_yaml_config_from_disk(
                        Path("config/yaml/app.yaml")
                    )
                    if isinstance(cfg, dict):
                        fallback_port = int(((cfg.get("server") or {}).get("port") or fallback_port))
                except Exception:
                    pass
            print(f"[MAIN] WARN: 启动后在 {startup_timeout:.0f}s 内未找到可用 /health 端口，改用 {fallback_port}")
            port = fallback_port

        if not await _try_health(int(port)):
            print(f"[MAIN] ERROR: 目标端口 {port} 无法通过 /health 验证")
            if output_lines:
                print("[MAIN] 最近输出：")
                for ln in list(output_lines)[-40:]:
                    print(ln)
            return

        ws_url = f"ws://{host}:{port}/api/v1/ws"
        msg_id = str(int(time.time() * 1000))
        req_id = msg_id
        conversation_id = "benchmark_main"

        payload: Dict[str, Any] = {
            "type": "chat",
            "content": prompt,
            "message_id": msg_id,
            "request_id": req_id,
            "conversation_id": conversation_id,
        }

        print(f"[MAIN] connected_target=http://{host}:{port}")
        print(f"[MAIN] ws_url={ws_url}")

        ws_deadline = time.time() + _get_float_env("XIAOYOU_BENCHMARK_WS_CONNECT_TIMEOUT", 120.0)
        last_error = None
        while time.time() < ws_deadline:
            t0 = time.time()
            first_token_cost = None
            text_parts: List[str] = []
            try:
                async with websockets.connect(ws_url, open_timeout=10, close_timeout=3) as ws:
                    await ws.send(json.dumps(payload, ensure_ascii=False))

                    while True:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=120.0)
                        except asyncio.TimeoutError:
                            print("[MAIN] ERROR: 120s 内未收到任何消息")
                            break

                        try:
                            msg = json.loads(raw)
                        except Exception:
                            continue

                        if isinstance(msg, dict) and msg.get("type") == "error":
                            print(f"[MAIN] ERROR: {msg.get('error') or msg.get('message')}")
                            break

                        if msg.get("type") == "message" and msg.get("subtype") == "response_chunk":
                            chunk = str(msg.get("content") or "")
                            if chunk:
                                if first_token_cost is None:
                                    first_token_cost = time.time() - t0
                                    print(f"[MAIN] first_token_cost={first_token_cost:.3f}s")
                                text_parts.append(chunk)

                        if msg.get("type") == "message" and msg.get("subtype") == "response_done":
                            break

                    total_cost = time.time() - t0
                    text = "".join(text_parts).strip()
                    print(f"[MAIN] total_cost={total_cost:.3f}s, output_chars={len(text)}")
                    if text:
                        print("=" * 40)
                        print(text)
                        print("=" * 40)
                    return
            except Exception as e:
                last_error = e
                await asyncio.sleep(1.0)
                continue

        print(f"[MAIN] ERROR: 无法连接 WebSocket: {last_error}")
    finally:
        _terminate_process_tree()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["raw", "module", "main", "cpp", "tts", "tts_concurrent"],
        default=str(os.getenv("XIAOYOU_BENCHMARK_MODE", "raw") or "raw").strip().lower(),
        help="测试模式: raw(原生 llama-cpp), module(项目 LLM 模块), main(HTTP API), cpp(C++ 调度器), tts(TTS in-process)",
    )
    parser.add_argument("--model-path", default=os.getenv("XIAOYOU_BENCHMARK_MODEL_PATH"))
    parser.add_argument("--prompt", default=str(os.getenv("XIAOYOU_BENCHMARK_PROMPT", "你好，你是谁？") or "你好，你是谁？"))
    parser.add_argument("--tts-text", default=str(os.getenv("XIAOYOU_BENCHMARK_TTS_TEXT", "你好，我是小友。") or "你好，我是小友。"))
    parser.add_argument("--tts-rounds", type=int, default=_get_int_env("XIAOYOU_BENCHMARK_TTS_ROUNDS", 5))
    parser.add_argument("--tts-warmup", type=int, default=_get_int_env("XIAOYOU_BENCHMARK_TTS_WARMUP", 1))
    parser.add_argument("--tts-concurrency", type=int, default=_get_int_env("XIAOYOU_BENCHMARK_TTS_CONCURRENCY", 4))
    parser.add_argument("--tts-ref-wav", default=str(os.getenv("XIAOYOU_BENCHMARK_TTS_REF_WAV", "") or ""))
    args = parser.parse_args()

    if args.mode == "raw":
        benchmark_raw_llama_cpp(model_path=args.model_path)
        return

    import asyncio

    if args.mode == "module":
        asyncio.run(benchmark_module(model_path=args.model_path))
        return

    if args.mode == "cpp":
        asyncio.run(benchmark_cpp_scheduler(model_path=args.model_path))
        return

    if args.mode == "tts":
        asyncio.run(
            benchmark_tts_inprocess(
                text=str(args.tts_text or "你好，我是小友。"),
                rounds=int(args.tts_rounds) if args.tts_rounds is not None else 5,
                warmup=int(args.tts_warmup) if args.tts_warmup is not None else 1,
                ref_wav=str(args.tts_ref_wav or ""),
            )
        )
        return

    if args.mode == "tts_concurrent":
        asyncio.run(
            benchmark_tts_concurrent(
                text=str(args.tts_text or "你好，我是小友。"),
                rounds=int(args.tts_rounds) if args.tts_rounds is not None else 5,
                warmup=int(args.tts_warmup) if args.tts_warmup is not None else 1,
                concurrency=int(args.tts_concurrency) if args.tts_concurrency is not None else 4,
                ref_wav=str(args.tts_ref_wav or ""),
            )
        )
        return

    asyncio.run(benchmark_main(prompt=str(args.prompt or "你好，你是谁？")))


if __name__ == "__main__":
    main()
