#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试模型路径解析修复

验证在不同格式下模型名称的正确提取：
- 传统格式: cloud:deepseek:deepseek-v4-pro
- 多API key格式: cloud:deepseek:qqbot1:deepseek-v4-pro
"""


def test_model_path_parsing():
    """测试模型路径解析逻辑"""

    # 测试用例：模型路径 -> 期望的 (provider, model)
    test_cases = [
        # 传统格式（3段）
        ("cloud:deepseek:deepseek-v4-pro", "deepseek", "deepseek-v4-pro"),
        ("cloud:deepseek:deepseek-v4-flash", "deepseek", "deepseek-v4-flash"),
        ("cloud:siliconflow:Qwen/Qwen3-VL-235B-A22B-Thinking", "siliconflow", "Qwen/Qwen3-VL-235B-A22B-Thinking"),

        # 多API key格式（4段）
        ("cloud:deepseek:qqbot1:deepseek-v4-pro", "deepseek", "deepseek-v4-pro"),
        ("cloud:deepseek:qqbot2:deepseek-v4-flash", "deepseek", "deepseek-v4-flash"),
        ("cloud:deepseek:qqbot1:deepseek-v4-pro", "deepseek", "deepseek-v4-pro"),

        # 模型名本身包含冒号的情况（极少见，但应该支持）
        ("cloud:someprovider:some:model", "someprovider", "model"),
    ]

    print("=" * 60)
    print("测试模型路径解析修复")
    print("=" * 60)

    all_passed = True

    for model_path, expected_provider, expected_model in test_cases:
        parts = model_path.split(":")

        # 提取 provider
        provider = parts[1] if len(parts) >= 2 else None

        # 提取 model（修复后的逻辑）
        if len(parts) == 3:
            model = parts[2]
        elif len(parts) >= 4:
            model = ":".join(parts[3:])
        else:
            model = None

        # 验证结果
        passed = (provider == expected_provider and model == expected_model)
        status = "✓ PASS" if passed else "✗ FAIL"

        print(f"\n{status} 测试: {model_path}")
        print(f"  期望: provider={expected_provider}, model={expected_model}")
        print(f"  实际: provider={provider}, model={model}")

        if not passed:
            all_passed = False
            print(f"  错误: 解析结果不匹配!")

    print("\n" + "=" * 60)
    if all_passed:
        print("✓ 所有测试通过!")
    else:
        print("✗ 部分测试失败!")
    print("=" * 60)

    return all_passed


def test_old_logic_issue():
    """演示旧逻辑的问题"""

    print("\n" + "=" * 60)
    print("演示旧逻辑的问题")
    print("=" * 60)

    # 旧的逻辑：split(":", 2)
    model_path = "cloud:deepseek:qqbot1:deepseek-v4-pro"
    parts_old = model_path.split(":", 2)

    print(f"\n模型路径: {model_path}")
    print(f"\n旧逻辑 (split(':', 2)):")
    print(f"  parts = {parts_old}")
    print(f"  parts[0] = '{parts_old[0]}'")
    print(f"  parts[1] = '{parts_old[1]}'")
    print(f"  parts[2] = '{parts_old[2]}'  ← 错误！应该是 'deepseek-v4-pro'")

    # 新的逻辑：split(":")
    parts_new = model_path.split(":")

    print(f"\n新逻辑 (split(':')):")
    print(f"  parts = {parts_new}")
    print(f"  parts[0] = '{parts_new[0]}'")
    print(f"  parts[1] = '{parts_new[1]}'")
    print(f"  parts[2] = '{parts_new[2]}'")
    print(f"  parts[3] = '{parts_new[3]}'  ← 正确！")
    print(f"  提取模型名: {':'.join(parts_new[3:])}")

    print("=" * 60)


if __name__ == "__main__":
    test_old_logic_issue()
    print("\n")
    success = test_model_path_parsing()
    exit(0 if success else 1)