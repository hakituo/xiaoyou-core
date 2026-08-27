#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qwen3-TTS GPU优化验证脚本
用于验证GPU利用率优化是否生效

运行方式:
    venv_core\Scripts\python tests\scripts\verify_qwen3_tts_gpu_optimization.py

验证项:
    1. torch.compile 是否正确编译模型
    2. CUDA流是否创建并使用
    3. TF32是否启用
    4. 推理速度是否有提升
    5. GPU利用率是否提高
"""

import sys
import os
import time
import asyncio

sys.path.insert(0, os.getcwd())


def check_torch_compile():
    """检查torch.compile是否可用"""
    import torch
    has_compile = hasattr(torch, "compile")
    print(f"[检查] torch.compile 可用: {has_compile}")
    if has_compile:
        print(f"       PyTorch版本: {torch.__version__}")
    return has_compile


def check_cuda_optimizations():
    """检查CUDA优化环境"""
    import torch
    if not torch.cuda.is_available():
        print("[错误] CUDA不可用，无法进行GPU优化验证")
        return False

    gpu_name = torch.cuda.get_device_name(0)
    cc_major, cc_minor = torch.cuda.get_device_capability(0)
    compute_capability = cc_major * 10 + cc_minor

    print(f"[检查] CUDA可用: True")
    print(f"       GPU: {gpu_name}")
    print(f"       CUDA版本: {torch.version.cuda}")
    print(f"       计算能力: {cc_major}.{cc_minor} (SM{compute_capability})")

    # 架构检测
    gpu_name_lower = gpu_name.lower()
    is_blackwell = compute_capability >= 100 or "rtx 50" in gpu_name_lower
    is_hopper = compute_capability >= 90 and compute_capability < 100
    is_ada = compute_capability == 89 or "rtx 40" in gpu_name_lower
    is_ampere = compute_capability >= 80 and compute_capability < 89

    if is_blackwell:
        print("[检查] 架构: Blackwell (RTX 50系列)")
        print("[检查] 推荐编译模式: max-autotune")
    elif is_hopper:
        print("[检查] 架构: Hopper (H100)")
        print("[检查] 推荐编译模式: max-autotune")
    elif is_ada:
        print("[检查] 架构: Ada Lovelace (RTX 40系列)")
        print("[检查] 推荐编译模式: max-autotune")
    elif is_ampere:
        print("[检查] 架构: Ampere (RTX 30系列)")
        print("[检查] 推荐编译模式: reduce-overhead")
    else:
        print(f"[检查] 架构: 其他 (SM{compute_capability})")

    # 检查TF32设置
    cudnn_tf32 = torch.backends.cudnn.allow_tf32
    matmul_tf32 = torch.backends.cuda.matmul.allow_tf32
    print(f"[检查] TF32设置: cudnn={cudnn_tf32}, matmul={matmul_tf32}")

    # 检查Flash SDP
    flash_sdp = torch.backends.cuda.flash_sdp_enabled()
    mem_eff_sdp = torch.backends.cuda.mem_efficient_sdp_enabled()
    print(f"[检查] Flash SDP: {flash_sdp}, Memory Efficient SDP: {mem_eff_sdp}")

    return True


async def test_engine_optimizations():
    """测试引擎优化是否正确加载"""
    print("\n[测试] 初始化Qwen3TTSEngine并检查优化...")

    from core.voice.tts_engine import Qwen3TTSEngine

    engine = Qwen3TTSEngine()

    # 检查初始状态
    print(f"[检查] 初始状态:")
    print(f"       _cuda_stream: {engine._cuda_stream}")
    print(f"       _use_compile: {engine._use_compile}")
    print(f"       _compiled: {engine._compiled}")
    print(f"       _executor: {engine._executor}")

    # 尝试初始化（如果有模型的话）
    model_path, path_exists = engine._resolve_model_path()
    print(f"[检查] 模型路径: {model_path}")
    print(f"[检查] 模型存在: {path_exists}")

    if not path_exists:
        print("[跳过] 模型不存在，跳过初始化测试")
        print("       如需完整测试，请先下载Qwen3-TTS模型")
        return None

    try:
        await engine.initialize()
        print(f"\n[检查] 初始化后状态:")
        print(f"       _cuda_stream: {engine._cuda_stream is not None}")
        print(f"       _use_compile: {engine._use_compile}")
        print(f"       _compiled: {engine._compiled}")
        print(f"       current_device: {engine.current_device}")

        if engine._cuda_stream is not None:
            print("[成功] CUDA独立流已创建")
        else:
            print("[警告] CUDA独立流未创建")

        if engine._compiled:
            print("[成功] torch.compile已编译模型")
        else:
            print("[信息] torch.compile未启用（可能PyTorch版本不支持或环境变量禁用）")

        return engine

    except Exception as e:
        print(f"[错误] 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return None


async def benchmark_inference(engine, text: str = "你好，这是一个测试。", warmup: bool = True):
    """基准测试推理速度"""
    if engine is None or engine._model is None:
        print("\n[跳过] 引擎未初始化，跳过基准测试")
        return None

    print(f"\n[基准测试] 测试文本: '{text}'")

    # Warmup
    if warmup:
        print("[基准测试] 预热中...")
        try:
            await engine.synthesize_bytes(text)
        except Exception as e:
            print(f"[警告] 预热失败: {e}")

    # 实际测试
    import torch
    times = []
    gpu_utils = []

    for i in range(3):
        # 清除缓存
        if torch.cuda.is_available():
            torch.cuda.synchronize()
            torch.cuda.empty_cache()

        start = time.perf_counter()
        try:
            result = await engine.synthesize_bytes(text)
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            elapsed = time.perf_counter() - start
            times.append(elapsed)

            # 获取GPU利用率（Windows需要pynvml）
            try:
                import pynvml
                pynvml.nvmlInit()
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                gpu_utils.append(util.gpu)
            except Exception:
                pass

            print(f"[基准测试] 第{i+1}次: {elapsed:.3f}s", end="")
            if gpu_utils:
                print(f", GPU利用率: {gpu_utils[-1]}%")
            else:
                print()

        except Exception as e:
            print(f"[错误] 第{i+1}次测试失败: {e}")

    if times:
        avg_time = sum(times) / len(times)
        print(f"\n[结果] 平均推理时间: {avg_time:.3f}s")
        if gpu_utils:
            avg_gpu = sum(gpu_utils) / len(gpu_utils)
            print(f"[结果] 平均GPU利用率: {avg_gpu:.1f}%")
        return {"avg_time": avg_time, "gpu_util": sum(gpu_utils)/len(gpu_utils) if gpu_utils else 0}
    return None


def print_optimization_summary():
    """打印优化摘要"""
    print("\n" + "="*60)
    print("Qwen3-TTS GPU优化验证摘要")
    print("="*60)
    print("""
优化项说明:
-----------
1. torch.compile (核心优化)
   - 参考: https://github.com/diodiogod/TTS-Audio-Suite/blob/main/docs/qwen3_tts_optimizations.md
   - 社区实测RTX4090: 1.7倍加速 (5.0 it/s -> 8.5 it/s)
   - Windows推荐mode="default"（最稳定）
   - Linux可尝试mode="reduce-overhead"（包含自动CUDA Graph）
   - 首次编译需要30-60秒，后续推理使用缓存的kernel
   - 注意: HuggingFace官方文档警告不要手动compile，但社区实测有效

2. TF32加速
   - Ampere/Ada/Blackwell架构均支持
   - 自动启用，无需额外配置

3. FlashAttention SDP
   - 启用内存高效的Scaled Dot Product Attention
   - 减少显存占用，提高吞吐量

4. 专用线程池
   - 使用单线程专用线程池执行推理
   - 避免默认线程池的竞争

5. 其他社区方案（未集成）:
   - faster-qwen3-tts: https://github.com/andimarafioti/faster-qwen3-tts
     使用CUDA Graph，支持流式/非流式生成
   - qwen3-tts-triton: https://github.com/newgrit1004/qwen3-tts-triton
     使用Triton kernel fusion，RTX5090实测5倍加速

已知问题:
---------
- Qwen3-TTS官方Issue #132: Blackwell GPU利用率低
  https://github.com/QwenLM/Qwen3-TTS/issues/132
  官方暂未解决，需依赖社区优化方案

环境变量:
---------
- QWEN3_TTS_COMPILE=0 可禁用torch.compile（如果编译出错）

预期效果:
---------
- GPU利用率: 自回归模型理论上限60-80%，无法达到90%+
- 推理速度: torch.compile mode="default" 可提供约1.7倍加速
""")


async def main():
    print("="*60)
    print("Qwen3-TTS GPU优化验证脚本")
    print("="*60)

    # 1. 检查torch.compile
    has_compile = check_torch_compile()

    # 2. 检查CUDA环境
    cuda_ok = check_cuda_optimizations()

    if not cuda_ok:
        print("\n[退出] CUDA环境不满足，测试结束")
        return 1

    # 3. 测试引擎优化
    engine = await test_engine_optimizations()

    # 4. 基准测试
    if engine:
        result = await benchmark_inference(engine)

        # 清理
        await engine.shutdown()

    # 5. 打印摘要
    print_optimization_summary()

    print("\n[完成] 验证结束")
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
