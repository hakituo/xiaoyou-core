#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SSL 重试机制测试脚本
用于验证 OpenAI Client 的 SSL 错误处理和重试机制是否正常工作
"""

import asyncio
import sys
import os

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from core.llm.openai_compat import OpenAIClient


async def test_ssl_retry_mechanism():
    """测试 SSL 重试机制"""
    print("=" * 60)
    print("SSL 重试机制测试")
    print("=" * 60)
    
    # 创建客户端实例
    client = OpenAIClient(
        api_key=os.getenv("OPENAI_API_KEY", "test-key"),
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions"),
        model=os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
    )
    
    # 测试配置参数
    print(f"\n✓ 客户端配置:")
    print(f"  - 最大重试次数：{client.max_retries}")
    print(f"  - 基础重试延迟：{client.retry_delay}s")
    print(f"  - SSL 验证：{client.verify_ssl}")
    print(f"  - 超时时间：{client.timeout}s")
    
    # 测试 SSL 错误检测
    print(f"\n✓ SSL 错误检测测试:")
    
    test_errors = [
        ("sslv3 alert bad record mac", True),
        ("bad record mac", True),
        ("SSL alert certificate expired", True),
        ("Connection timeout", False),
        ("Invalid API key", False),
    ]
    
    for error_msg, expected_result in test_errors:
        error = Exception(error_msg)
        result = client._is_transient_ssl_error(error)
        status = "✓" if result == expected_result else "✗"
        print(f"  {status} '{error_msg}' -> {result} (期望：{expected_result})")
        assert result == expected_result, f"SSL 错误检测 '{error_msg}': 期望 {expected_result}, 得到 {result}"

    # 测试连接初始化
    print(f"\n✓ 连接初始化测试:")
    try:
        await client.initialize()
        print(f"  ✓ 客户端初始化成功")
        print(f"  ✓ Session 状态：{'active' if client.session else 'inactive'}")
        assert client.session is not None, "初始化后 session 不应为 None"
    except Exception as e:
        print(f"  ✗ 初始化失败：{e}")
        assert False, f"客户端初始化失败: {e}"

    # 测试配置灵活性
    print(f"\n✓ 配置灵活性测试:")
    client.max_retries = 5
    client.retry_delay = 2.0
    print(f"  ✓ 更新后最大重试次数：{client.max_retries}")
    print(f"  ✓ 更新后基础重试延迟：{client.retry_delay}s")

    assert client.max_retries == 5, "max_retries 更新后应为 5"
    assert client.retry_delay == 2.0, "retry_delay 更新后应为 2.0"
    
    # 清理资源
    await client.shutdown()
    print(f"\n✓ 资源已清理")
    
    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)
    
    return True


async def test_with_real_api():
    """使用真实 API 测试（可选）"""
    print("\n" + "=" * 60)
    print("真实 API 连接测试（需要有效的 API Key）")
    print("=" * 60)
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("\n⚠ 未设置 OPENAI_API_KEY 环境变量，跳过真实 API 测试")
        assert False, "未设置 OPENAI_API_KEY，跳过真实 API 测试"
        return False

    client = OpenAIClient(
        api_key=api_key,
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions"),
        model=os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
    )

    try:
        print("\n尝试发送测试消息...")
        messages = [
            {"role": "user", "content": "Hello, this is a test message."}
        ]

        response = await client.chat(messages, temperature=0.7)
        print(f"✓ 收到响应：{response[:100]}...")
        assert response is not None, "API 响应不应为 None"
        assert isinstance(response, str), "API 响应应为字符串"
        return True

    except Exception as e:
        print(f"✗ API 调用失败：{e}")
        assert False, f"API 调用失败: {e}"
        return False
    finally:
        await client.shutdown()


async def main():
    """主测试函数"""
    print("\n开始运行 SSL 重试机制测试...\n")
    
    # 运行基础测试
    await test_ssl_retry_mechanism()
    
    # 运行真实 API 测试（可选）
    # await test_with_real_api()
    
    print("\n✓ 所有测试完成！\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n测试被用户中断")
    except Exception as e:
        print(f"\n测试失败：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
