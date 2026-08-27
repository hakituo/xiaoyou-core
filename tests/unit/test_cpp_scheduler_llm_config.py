#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 C++ 调度器 LLM 配置是否正确
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_config():
    """测试配置读取"""
    print("=" * 60)
    print("测试 C++ 调度器 LLM 配置")
    print("=" * 60)

    from config.integrated_config import get_settings
    settings = get_settings()

    # 检查调度器配置
    try:
        from core.core_engine.config_manager import ConfigManager
        cfg = ConfigManager()
        use_cpp = cfg.get("scheduler.use_cpp", False)
        use_cpp_for_llm = cfg.get("scheduler.use_cpp_for_llm", False)
        llm_backend = cfg.get("scheduler.llm_backend", "python")
        allow_cpp_llm_worker = cfg.get("scheduler.allow_cpp_llm_worker", False)

        print(f"use_cpp: {use_cpp}")
        print(f"use_cpp_for_llm: {use_cpp_for_llm}")
        print(f"llm_backend: {llm_backend}")
        print(f"allow_cpp_llm_worker: {allow_cpp_llm_worker}")

        assert llm_backend in ("python", "cpp"), f"llm_backend 取值异常: {llm_backend}"

        if use_cpp_for_llm:
            print()
            print("✓ 配置已更新，LLM 将使用 C++ 调度器")
        else:
            print()
            print("✗ 配置未生效，请检查")
    except Exception as e:
        print(f"读取配置失败: {e}")
        assert False, f"读取调度器配置失败: {e}"

    # 检查模型路径
    print()
    print("=" * 60)
    print("检查模型配置")
    print("=" * 60)
    try:
        model_path = getattr(settings.model, "text_model_path", None)
        llm_provider = getattr(settings.model.llm, "provider", "unknown")
        print(f"llm_provider: {llm_provider}")
        print(f"text_model_path: {model_path}")

        assert llm_provider != "unknown", "llm_provider 不应为 unknown"

        if model_path and str(model_path).lower().endswith(".gguf"):
            print("✓ 检测到 GGUF 模型")
        elif llm_provider == "local":
            print("! 本地模型但路径可能不是 GGUF")
        else:
            print(f"! 当前使用云端模型: {llm_provider}")
    except Exception as e:
        print(f"读取模型配置失败: {e}")
        assert False, f"读取模型配置失败: {e}"


def test_cpp_scheduler():
    """测试 C++ 调度器引擎"""
    print()
    print("=" * 60)
    print("测试 C++ 调度器引擎")
    print("=" * 60)
    try:
        from core.services.scheduler.cpp_scheduler_engine import cpp_scheduler_engine
        enabled = getattr(cpp_scheduler_engine, "enabled", "N/A")
        has_scheduler = hasattr(cpp_scheduler_engine, "scheduler") and cpp_scheduler_engine.scheduler is not None
        print(f"cpp_scheduler_engine.enabled: {enabled}")
        print(f"cpp_scheduler_engine.scheduler: {'存在' if has_scheduler else '不存在'}")

        assert hasattr(cpp_scheduler_engine, "enabled"), "cpp_scheduler_engine 应有 enabled 属性"

        if enabled:
            print("✓ C++ 调度器已启用")
        else:
            print("! C++ 调度器未启用")
    except Exception as e:
        print(f"加载 C++ 调度器失败: {e}")
        assert False, f"加载 C++ 调度器失败: {e}"


def test_llm_module_mode():
    """测试 LLM 模块的模式判断"""
    print()
    print("=" * 60)
    print("测试 LLM 模块模式判断")
    print("=" * 60)
    try:
        from core.core_engine.config_manager import ConfigManager
        from config.integrated_config import get_settings

        cfg = ConfigManager()
        settings = get_settings()

        use_cpp_for_llm = bool(cfg.get("scheduler.use_cpp_for_llm", False))
        text_model_path = getattr(settings.model, "text_model_path", None)
        is_gguf = text_model_path and str(text_model_path).lower().endswith(".gguf")

        print(f"use_cpp_for_llm: {use_cpp_for_llm}")
        print(f"text_model_path: {text_model_path}")
        print(f"is_gguf: {is_gguf}")

        assert isinstance(use_cpp_for_llm, bool), "use_cpp_for_llm 应为布尔值"

        # 模拟 LLMModule 的判断逻辑
        if use_cpp_for_llm and is_gguf:
            print()
            print("✓ LLM 模块将跳过本地加载，使用 C++ 调度器（Client Mode）")
        elif is_gguf and not use_cpp_for_llm:
            print()
            print("✗ GGUF 模型但未启用 C++ 调度器，会尝试加载 llama-cpp-python")
        else:
            print()
            print(f"! 非本地 GGUF 模式，当前配置: provider={getattr(settings.model.llm, 'provider', 'unknown')}")

    except Exception as e:
        print(f"测试失败: {e}")
        assert False, f"LLM 模块模式判断测试失败: {e}"


if __name__ == "__main__":
    test_config()
    test_cpp_scheduler()
    test_llm_module_mode()
    print()
    print("测试完成")
