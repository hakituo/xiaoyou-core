import os
import sys
import time
import argparse
from pathlib import Path

try:
    from llama_cpp import Llama
except Exception as e:
    print(f"导入llama_cpp失败: {e}")
    sys.exit(1)


def load_yaml_config():
    p = Path("config/yaml/app.yaml")
    if p.exists():
        try:
            from config.yaml_loader import load_resolved_yaml_config_from_disk

            cfg, _, _ = load_resolved_yaml_config_from_disk(p)
            return cfg
        except Exception as e:
            print(f"读取配置失败: {e}")
    return {}


def resolve_model_path(cfg):
    env_path = os.getenv("XIAOYOU_TEXT_MODEL_PATH", "").strip()
    if env_path:
        return env_path
    model_path = ""
    try:
        model_path = cfg.get("model", {}).get("path") or ""
    except Exception:
        model_path = ""
    if model_path:
        p = Path(model_path)
        if not p.is_absolute():
            p = Path(__file__).resolve().parents[1] / p
        return str(p)
    candidates = [
        Path(__file__).resolve().parents[1]
        / "models"
        / "llm"
        / "Qwen2___5-7B-Instruct-Q4_K_M.gguf",
        Path(__file__).resolve().parents[1]
        / "models"
        / "llm"
        / "L3-8B-Stheno-v3.2-Q5_K_M.gguf",
    ]
    for c in candidates:
        if Path(c).exists():
            return str(c)
    return ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt", nargs="?", default="测试一下，你还活着吗？")
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--n-ctx", type=int, default=None)
    parser.add_argument("--n-gpu-layers", type=int, default=None)
    parser.add_argument("--n-batch", type=int, default=None)
    parser.add_argument("--n-threads", type=int, default=None)
    parser.add_argument(
        "--use-mmap",
        type=str,
        default="auto",
        choices=["auto", "true", "false"],
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    cfg = load_yaml_config()
    model_path = resolve_model_path(cfg)
    if not model_path:
        print("未找到本地GGUF模型路径")
        sys.exit(1)

    try:
        n_ctx = 2048
        n_gpu_layers = -1
        max_tokens = int(args.max_tokens)
        temperature = 0.9
        n_batch = 256
        n_threads = 0

        try:
            m = cfg.get("model", {}) if isinstance(cfg.get("model", {}), dict) else {}
            if isinstance(m.get("n_ctx"), int) and m.get("n_ctx") > 0:
                n_ctx = int(m.get("n_ctx"))
            if isinstance(m.get("n_gpu_layers"), int):
                n_gpu_layers = int(m.get("n_gpu_layers"))
            g = (
                m.get("generation", {})
                if isinstance(m.get("generation", {}), dict)
                else {}
            )
            if isinstance(g.get("temperature"), (int, float)):
                temperature = float(g.get("temperature"))
        except Exception:
            pass

        if isinstance(args.n_ctx, int) and args.n_ctx > 0:
            n_ctx = int(args.n_ctx)
        if isinstance(args.n_gpu_layers, int):
            n_gpu_layers = int(args.n_gpu_layers)
        if isinstance(args.temperature, (int, float)):
            temperature = float(args.temperature)

        if isinstance(args.n_batch, int) and args.n_batch > 0:
            n_batch = int(args.n_batch)
        elif n_ctx > 0:
            n_batch = min(n_batch, int(n_ctx))

        if isinstance(args.n_threads, int) and args.n_threads > 0:
            n_threads = int(args.n_threads)
        else:
            env_threads = str(os.getenv("XIAOYOU_LLM_THREADS", "") or "").strip()
            if env_threads:
                try:
                    n_threads = int(env_threads)
                except Exception:
                    n_threads = 0
        if n_threads <= 0:
            try:
                cpu_count = int(os.cpu_count() or 0)
            except Exception:
                cpu_count = 0
            if cpu_count > 0:
                n_threads = max(1, min(4, cpu_count // 2))

        print(f"加载模型: {model_path}")
        print(
            f"参数: n_ctx={n_ctx}, n_gpu_layers={n_gpu_layers}, n_batch={n_batch}, n_threads={n_threads}, max_tokens={max_tokens}, temperature={temperature}"
        )

        t0 = time.time()
        if str(args.use_mmap).lower() == "true":
            mmap_candidates = [True]
        elif str(args.use_mmap).lower() == "false":
            mmap_candidates = [False]
        else:
            mmap_candidates = [True, False]

        llm = None
        last_load_error = None
        for use_mmap in mmap_candidates:
            try:
                print(f"尝试加载(use_mmap={use_mmap})...")
                try:
                    llm = Llama(
                        model_path=model_path,
                        n_ctx=n_ctx,
                        n_gpu_layers=n_gpu_layers,
                        n_batch=n_batch,
                        n_threads=n_threads,
                        use_mmap=bool(use_mmap),
                        verbose=bool(args.verbose),
                    )
                except TypeError:
                    try:
                        llm = Llama(
                            model_path=model_path,
                            n_ctx=n_ctx,
                            n_gpu_layers=n_gpu_layers,
                            n_threads=n_threads,
                            use_mmap=bool(use_mmap),
                            verbose=bool(args.verbose),
                        )
                    except TypeError:
                        llm = Llama(
                            model_path=model_path,
                            n_ctx=n_ctx,
                            n_gpu_layers=n_gpu_layers,
                            use_mmap=bool(use_mmap),
                            verbose=bool(args.verbose),
                        )
                break
            except Exception as e:
                last_load_error = e
                print(f"加载失败(use_mmap={use_mmap}): {e}")
                llm = None

        if llm is None:
            raise RuntimeError(f"模型加载失败: {last_load_error}")
        print(f"模型加载耗时: {time.time() - t0:.2f}s")

        prompt = str(args.prompt)

        messages = [{"role": "user", "content": prompt}]
        print("开始推理(流式)...")
        t_start = time.time()
        stream = llm.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )

        first = True
        full = []
        chunk_count = 0
        for chunk in stream:
            delta = chunk["choices"][0].get("delta", {})
            content = delta.get("content") or ""
            if not content:
                continue
            if first:
                print(f"首个token耗时: {time.time() - t_start:.4f}s")
                first = False
            full.append(content)
            chunk_count += 1

        text = "".join(full).strip()
        total_cost = time.time() - t_start
        print("推理完成")
        if total_cost > 0:
            print(f"总耗时: {total_cost:.2f}s, chunks: {chunk_count}")
        print("输出内容:")
        print(text if text else "(空)")

    except Exception as e:
        print(f"推理失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
