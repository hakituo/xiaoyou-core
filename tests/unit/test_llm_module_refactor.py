"""
测试LLM模块重构是否成功

验证内容：
1. 所有模块可以正常导入
2. 错误处理与工具函数行为正确
3. LLMModule 结构（含向后兼容方法）保持完整
4. 拆分后的文件结构未被重新合并
"""
import sys
from pathlib import Path

# 添加项目根目录到路径（tests/unit/xxx.py -> 仓库根）
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))


def test_imports():
    """测试所有模块可以正常导入"""
    from core.modules.llm import (
        GPUManager,
        LLMModule,
        ModelLoader,
        StreamGenerator,
        SyncGenerator,
        build_llama_cpp_chat_kwargs,
        clamp_messages,
        clamp_text,
        expand_gpu_layer_candidates,
        get_error_message,
        get_torch,
        is_cuda_backend_error,
        is_oom_error,
        normalize_local_path,
    )

    for obj in (
        LLMModule,
        ModelLoader,
        StreamGenerator,
        SyncGenerator,
        GPUManager,
        is_oom_error,
        is_cuda_backend_error,
        get_error_message,
        expand_gpu_layer_candidates,
        get_torch,
        normalize_local_path,
        clamp_text,
        clamp_messages,
        build_llama_cpp_chat_kwargs,
    ):
        assert obj is not None


def test_error_handler():
    """测试错误处理模块"""
    from core.modules.llm.error_handler import (
        expand_gpu_layer_candidates,
        get_error_message,
        is_cuda_backend_error,
        is_oom_error,
    )

    assert is_oom_error("CUDA out of memory")
    assert not is_oom_error("normal error")

    assert is_cuda_backend_error("ggml-cuda error")
    assert not is_cuda_backend_error("normal error")

    msg = get_error_message("model_not_found", "/path/to/model")
    assert "/path/to/model" in msg

    candidates = expand_gpu_layer_candidates(-1)
    assert -1 in candidates
    assert 0 in candidates


def test_utils():
    """测试工具模块"""
    from core.modules.llm import build_llama_cpp_chat_kwargs, clamp_messages, clamp_text

    # clamp_text 保留尾部内容，避免截断丢掉最新的用户输入
    assert clamp_text("hello world", 5) == "world"
    assert clamp_text("hello world", 0) == "hello world"

    messages = [
        {"role": "system", "content": "system message"},
        {"role": "user", "content": "user message"},
    ]
    clamped = clamp_messages(messages, 100)
    assert isinstance(clamped, list)
    assert [m["role"] for m in clamped] == ["system", "user"]

    # 预算极小也要保留最后一条用户消息
    tight = clamp_messages(messages, 20)
    assert tight[-1]["role"] == "user"

    kwargs = build_llama_cpp_chat_kwargs(
        max_tokens=100,
        temperature=0.7,
        top_p=0.9,
        repetition_penalty=1.1,
    )
    assert kwargs["max_tokens"] == 100
    assert kwargs["temperature"] == 0.7
    assert kwargs["top_p"] == 0.9
    # repetition_penalty 需要映射成 llama.cpp 的 repeat_penalty
    assert kwargs["repeat_penalty"] == 1.1
    assert "stream" not in kwargs

    stream_kwargs = build_llama_cpp_chat_kwargs(
        max_tokens=100,
        temperature=0.7,
        top_p=0.9,
        repetition_penalty=1.1,
        stream=True,
    )
    assert stream_kwargs["stream"] is True


def test_llm_module_structure():
    """测试LLMModule结构"""
    from core.modules.llm import LLMModule

    for name in (
        "stream_chat",
        "chat",
        "reload",
        "unload_model",
        "get_current_model_name",
        "release_llm_vram_for_image_gen",
        "restore_llm_to_gpu",
    ):
        assert callable(getattr(LLMModule, name, None)), f"LLMModule 缺少方法 {name}"

    # 子模块获取方法
    for name in (
        "_get_model_loader",
        "_get_stream_generator",
        "_get_sync_generator",
        "_get_gpu_manager",
    ):
        assert callable(getattr(LLMModule, name, None)), f"LLMModule 缺少子模块入口 {name}"

    # 向后兼容方法：仍通过私有入口构造 llama.cpp 参数
    assert callable(getattr(LLMModule, "_build_llama_cpp_chat_kwargs", None))


def test_file_structure():
    """测试拆分后的文件结构仍然存在"""
    expected_files = [
        "core/modules/llm/__init__.py",
        "core/modules/llm/module.py",
        "core/modules/llm/model_loader.py",
        "core/modules/llm/stream_generator.py",
        "core/modules/llm/sync_generator.py",
        "core/modules/llm/gpu_manager.py",
        "core/modules/llm/error_handler.py",
        "core/modules/llm/utils.py",
        "core/modules/llm/inference_utils.py",
    ]

    missing = [name for name in expected_files if not (project_root / name).exists()]
    assert missing == [], f"缺少拆分后的文件: {missing}"


def test_no_god_file_after_split():
    """拆分后不应重新合并成超大文件"""
    split_files = [
        "core/modules/llm/module.py",
        "core/modules/llm/model_loader.py",
        "core/modules/llm/stream_generator.py",
        "core/modules/llm/sync_generator.py",
        "core/modules/llm/gpu_manager.py",
        "core/modules/llm/error_handler.py",
    ]

    for name in split_files:
        line_count = len((project_root / name).read_text(encoding="utf-8").splitlines())
        assert line_count <= 1500, f"{name} 膨胀到 {line_count} 行，拆分可能已被回退"


def main():
    """以脚本方式逐个执行检查并汇总结果"""
    checks = [
        ("模块导入", test_imports),
        ("错误处理", test_error_handler),
        ("工具模块", test_utils),
        ("LLMModule结构", test_llm_module_structure),
        ("文件结构", test_file_structure),
        ("拆分后无超大文件", test_no_god_file_after_split),
    ]

    passed = 0
    for name, check in checks:
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - 脚本模式需要汇总所有检查
            print(f"✗ 失败: {name}: {exc}")
        else:
            passed += 1
            print(f"✓ 通过: {name}")

    print(f"\n总计: {passed}/{len(checks)} 检查通过")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
