#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
蒸馏功能验证脚本

验证：
1. 蒸馏模型配置是否正确加载
2. NightlyProcessor 能否正常初始化
3. 蒸馏逻辑是否能正常执行（不实际调用 LLM）
"""

import os
import sys
import time

# 添加项目根目录到 path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from config.model_config import load_model_config  # noqa: E402
from memory.nightly_processor import (  # noqa: E402
    DEFAULT_NIGHTLY_CONFIG,
    NightlyProcessor,
    get_memory_distillation_model,
)


def test_model_config():
    """测试蒸馏模型配置"""
    print("=" * 60)
    print("1. 测试蒸馏模型配置")
    print("=" * 60)

    config = load_model_config()
    memory_models = config.get("memory_models", {})
    distillation_model = memory_models.get("distillation")

    if distillation_model:
        print(f"✓ 蒸馏模型配置已找到: {distillation_model}")
        return True
    else:
        print("✗ 蒸馏模型配置未找到")
        print(f"  当前 memory_models 配置: {memory_models}")
        return False


def test_get_distillation_model():
    """测试 get_memory_distillation_model 函数"""
    print("\n" + "=" * 60)
    print("2. 测试 get_memory_distillation_model 函数")
    print("=" * 60)

    model = get_memory_distillation_model()

    if model:
        print(f"✓ get_memory_distillation_model() 返回: {model}")
        return True
    else:
        print("✗ get_memory_distillation_model() 返回 None")
        return False


def test_nightly_processor_init():
    """测试 NightlyProcessor 初始化"""
    print("\n" + "=" * 60)
    print("3. 测试 NightlyProcessor 初始化")
    print("=" * 60)

    try:
        # 使用手动模式（不启动定时任务）
        config = DEFAULT_NIGHTLY_CONFIG.copy()
        config["auto_run"] = False  # 不启动定时任务

        processor = NightlyProcessor(config=config)
        status = processor.get_status()

        print("✓ NightlyProcessor 初始化成功")
        print(f"  - enabled: {status['enabled']}")
        print(f"  - running: {status['running']}")
        print(f"  - config: {status['config']}")

        # 停止处理器
        processor.stop()
        return True
    except Exception as e:
        print(f"✗ NightlyProcessor 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_distillation_logic():
    """测试蒸馏逻辑（不实际调用 LLM）"""
    print("\n" + "=" * 60)
    print("4. 测试蒸馏逻辑")
    print("=" * 60)

    try:
        # 创建一个模拟的 memory manager
        class MockMemoryManager:
            def __init__(self):
                self.lock = None
                self.user_id = "test_user"
                self.weighted_memories = {
                    "msg_1": {
                        "id": "msg_1",
                        "content": "这是一条测试记忆，内容足够长以便进行蒸馏处理。用户讨论了关于人工智能和机器学习的话题。",
                        "timestamp": time.time() - 7200,  # 2小时前
                        "is_distilled": False
                    },
                    "msg_2": {
                        "id": "msg_2",
                        "content": "短",  # 太短，应该跳过
                        "timestamp": time.time() - 3600,
                        "is_distilled": False
                    },
                    "msg_3": {
                        "id": "msg_3",
                        "content": "这是一条已经蒸馏过的记忆。",
                        "timestamp": time.time() - 7200,
                        "is_distilled": True  # 已蒸馏
                    }
                }

            def update_memory_distillation(
                self,
                memory_id,
                summary,
                keywords,
                distillation_metadata=None,
            ):
                print(f"  - 更新记忆 {memory_id}: summary={summary[:30]}..., keywords={keywords}")
                return True

        # 初始化处理器
        config = DEFAULT_NIGHTLY_CONFIG.copy()
        config["auto_run"] = False
        processor = NightlyProcessor(config=config)

        # 测试提示词生成
        test_content = "用户讨论了关于人工智能和机器学习的话题"
        prompt = processor._generate_distillation_prompt(test_content)
        print("✓ 提示词生成成功:")
        print(f"  - 前100字符: {prompt[:100]}...")

        # 测试响应解析
        test_response = "【梗概】：用户讨论了AI和机器学习\n【关键词】：人工智能, 机器学习, 深度学习"
        summary, keywords = processor._parse_distillation_response(test_response)
        print("✓ 响应解析成功:")
        print(f"  - summary: {summary}")
        print(f"  - keywords: {keywords}")

        # 停止处理器
        processor.stop()
        return True
    except Exception as e:
        print(f"✗ 蒸馏逻辑测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("蒸馏功能验证")
    print("=" * 60)

    results = []

    # 运行测试
    results.append(("蒸馏模型配置", test_model_config()))
    results.append(("get_distillation_model", test_get_distillation_model()))
    results.append(("NightlyProcessor 初始化", test_nightly_processor_init()))
    results.append(("蒸馏逻辑", test_distillation_logic()))

    # 输出总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)

    all_passed = True
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {name}")
        if not passed:
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("✓ 所有测试通过！蒸馏功能配置正确。")
    else:
        print("✗ 部分测试失败，请检查配置。")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
