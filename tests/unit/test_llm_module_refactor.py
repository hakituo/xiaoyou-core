"""
测试LLM模块重构是否成功

验证内容：
1. 所有模块可以正常导入
2. LLMModule类可以正常实例化
3. 各子模块可以正常工作
4. 向后兼容性
"""
import sys
import asyncio
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_imports():
    """测试所有模块可以正常导入"""
    print("=" * 60)
    print("测试1: 模块导入")
    print("=" * 60)

    try:
        # 测试主模块导入
        from core.modules.llm import LLMModule
        print("✓ LLMModule 导入成功")

        # 测试子模块导入
        from core.modules.llm import ModelLoader
        print("✓ ModelLoader 导入成功")

        from core.modules.llm import StreamGenerator
        print("✓ StreamGenerator 导入成功")

        from core.modules.llm import SyncGenerator
        print("✓ SyncGenerator 导入成功")

        from core.modules.llm import GPUManager
        print("✓ GPUManager 导入成功")

        # 测试错误处理函数导入
        from core.modules.llm import (
            is_oom_error,
            is_cuda_backend_error,
            get_error_message,
            expand_gpu_layer_candidates,
        )
        print("✓ 错误处理函数导入成功")

        # 测试工具函数导入
        from core.modules.llm import (
            get_torch,
            normalize_local_path,
            clamp_text,
            clamp_messages,
            build_llama_cpp_chat_kwargs,
        )
        print("✓ 工具函数导入成功")

        print("\n所有模块导入成功！\n")
        return True

    except Exception as e:
        print(f"✗ 导入失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_error_handler():
    """测试错误处理模块"""
    print("=" * 60)
    print("测试2: 错误处理模块")
    print("=" * 60)

    try:
        from core.modules.llm.error_handler import (
            is_oom_error,
            is_cuda_backend_error,
            get_error_message,
            expand_gpu_layer_candidates,
        )

        # 测试OOM错误检测
        assert is_oom_error("CUDA out of memory") == True
        assert is_oom_error("normal error") == False
        print("✓ is_oom_error 工作正常")

        # 测试CUDA错误检测
        assert is_cuda_backend_error("ggml-cuda error") == True
        assert is_cuda_backend_error("normal error") == False
        print("✓ is_cuda_backend_error 工作正常")

        # 测试错误消息获取
        msg = get_error_message("model_not_found", "/path/to/model")
        assert "/path/to/model" in msg
        print("✓ get_error_message 工作正常")

        # 测试GPU层数候选
        candidates = expand_gpu_layer_candidates(-1)
        assert -1 in candidates
        assert 0 in candidates
        print("✓ expand_gpu_layer_candidates 工作正常")

        print("\n错误处理模块测试通过！\n")
        return True

    except Exception as e:
        print(f"✗ 错误处理模块测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_utils():
    """测试工具模块"""
    print("=" * 60)
    print("测试3: 工具模块")
    print("=" * 60)

    try:
        from core.modules.llm.text_utils import clamp_text, clamp_messages
        from core.modules.llm.inference_utils import build_llama_cpp_chat_kwargs

        # 测试文本截断
        result = clamp_text("hello world", 5)
        assert len(result) <= 5
        print("✓ clamp_text 工作正常")

        # 测试消息截断
        messages = [
            {"role": "system", "content": "system message"},
            {"role": "user", "content": "user message"},
        ]
        result = clamp_messages(messages, 100)
        assert isinstance(result, list)
        print("✓ clamp_messages 工作正常")

        # 测试llama_cpp参数构建
        kwargs = build_llama_cpp_chat_kwargs(
            max_tokens=100,
            temperature=0.7,
            top_p=0.9,
            repetition_penalty=1.1,
        )
        assert kwargs["max_tokens"] == 100
        assert kwargs["temperature"] == 0.7
        print("✓ build_llama_cpp_chat_kwargs 工作正常")

        print("\n工具模块测试通过！\n")
        return True

    except Exception as e:
        print(f"✗ 工具模块测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_llm_module_structure():
    """测试LLMModule结构"""
    print("=" * 60)
    print("测试4: LLMModule结构")
    print("=" * 60)

    try:
        from core.modules.llm import LLMModule

        # 检查主要方法存在
        assert hasattr(LLMModule, 'stream_chat')
        assert hasattr(LLMModule, 'chat')
        assert hasattr(LLMModule, 'reload')
        assert hasattr(LLMModule, 'unload_model')
        assert hasattr(LLMModule, 'get_current_model_name')
        assert hasattr(LLMModule, 'release_llm_vram_for_image_gen')
        assert hasattr(LLMModule, 'restore_llm_to_gpu')
        print("✓ LLMModule 主要方法存在")

        # 检查子模块获取方法
        assert hasattr(LLMModule, '_get_model_loader')
        assert hasattr(LLMModule, '_get_stream_generator')
        assert hasattr(LLMModule, '_get_sync_generator')
        assert hasattr(LLMModule, '_get_gpu_manager')
        print("✓ LLMModule 子模块获取方法存在")

        # 检查向后兼容方法
        assert hasattr(LLMModule, '_build_llama_cpp_chat_kwargs')
        assert hasattr(LLMModule, '_clamp_text')
        assert hasattr(LLMModule, '_clamp_messages')
        print("✓ LLMModule 向后兼容方法存在")

        print("\nLLMModule结构测试通过！\n")
        return True

    except Exception as e:
        print(f"✗ LLMModule结构测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_file_structure():
    """测试文件结构"""
    print("=" * 60)
    print("测试5: 文件结构")
    print("=" * 60)

    expected_files = [
        'core/modules/llm/__init__.py',
        'core/modules/llm/module.py',
        'core/modules/llm/model_loader.py',
        'core/modules/llm/stream_generator.py',
        'core/modules/llm/sync_generator.py',
        'core/modules/llm/gpu_manager.py',
        'core/modules/llm/error_handler.py',
        'core/modules/llm/utils.py',
        'core/modules/llm/text_utils.py',
        'core/modules/llm/inference_utils.py',
    ]

    all_exist = True
    for file_path in expected_files:
        full_path = project_root / file_path
        if full_path.exists():
            print(f"✓ {file_path} 存在")
        else:
            print(f"✗ {file_path} 不存在")
            all_exist = False

    if all_exist:
        print("\n文件结构测试通过！\n")
        return True
    else:
        print("\n文件结构测试失败！\n")
        return False


def test_line_counts():
    """测试代码行数"""
    print("=" * 60)
    print("测试6: 代码行数统计")
    print("=" * 60)

    files_to_check = {
        'core/modules/llm/module.py': 456,
        'core/modules/llm/model_loader.py': 498,
        'core/modules/llm/stream_generator.py': 890,
        'core/modules/llm/sync_generator.py': 495,
        'core/modules/llm/gpu_manager.py': 375,
        'core/modules/llm/error_handler.py': 140,
    }

    total_lines = 0
    for file_path, expected_max in files_to_check.items():
        full_path = project_root / file_path
        if full_path.exists():
            with open(full_path, 'r', encoding='utf-8') as f:
                lines = len(f.readlines())
                total_lines += lines
                status = "✓" if lines <= expected_max else "⚠"
                print(f"{status} {file_path}: {lines} 行")
        else:
            print(f"✗ {file_path}: 文件不存在")

    print(f"\n总代码行数: {total_lines}")
    print(f"原代码行数: 2303")
    print(f"减少: {2303 - total_lines} 行 ({(2303 - total_lines) / 2303 * 100:.1f}%)\n")

    return True


def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("LLM模块重构验证测试")
    print("=" * 60 + "\n")

    results = []

    # 运行所有测试
    results.append(("模块导入", test_imports()))
    results.append(("错误处理", test_error_handler()))
    results.append(("工具模块", test_utils()))
    results.append(("LLMModule结构", test_llm_module_structure()))
    results.append(("文件结构", test_file_structure()))
    results.append(("代码行数", test_line_counts()))

    # 打印总结
    print("=" * 60)
    print("测试总结")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        print(f"{status}: {name}")

    print(f"\n总计: {passed}/{total} 测试通过")

    if passed == total:
        print("\n🎉 所有测试通过！重构成功！")
        return 0
    else:
        print(f"\n⚠️ 有 {total - passed} 个测试失败，请检查")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
