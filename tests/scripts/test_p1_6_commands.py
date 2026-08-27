# -*- coding: utf-8 -*-
"""P1-6 新增 /export /backup /statistics 命令验证脚本

为避免启动完整 ChatAgent 导致测试卡住，本脚本只验证：
1. 命令在 registry 中正确注册
2. /help 文本包含新命令
3. API 列表包含新命令
4. /export /backup /statistics 命令能被 handle_system_command 路由识别
   （使用 MockService 避免触发真实 ChatAgent）

注：/export /backup /statistics 的完整功能验证需要在真实运行的服务里测，
本脚本只验证"命令被识别且不会因为路由问题被漏掉"。
"""
import asyncio
import sys
import os

# 添加项目根目录（脚本在 tests/scripts/ 下，需要回退两层）
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from core.services.aveline.command_registry import (
    format_help_text, find_command, get_command_list_for_api
)


def test_registry():
    """测试命令注册"""
    print("=== 测试命令注册 ===")

    # 三个命令都应该在注册表里
    for name in ["statistics", "export", "backup"]:
        spec = find_command(name)
        assert spec is not None, f"{name} 未注册"
        print(f"  /{name}: {spec.description}")

    # 别名
    stats_spec = find_command("stats")
    assert stats_spec is not None, "stats 别名未注册"
    assert stats_spec.name == "statistics"
    print("  /stats 别名 OK")

    # /help 文本应包含三个新命令
    help_text = format_help_text()
    assert "/statistics" in help_text, "/help 未包含 /statistics"
    assert "/export" in help_text, "/help 未包含 /export"
    assert "/backup" in help_text, "/help 未包含 /backup"
    print("  /help 包含三个新命令 OK")

    # API 列表
    api_list = get_command_list_for_api()
    api_names = {item["command"] for item in api_list}
    assert "/statistics" in api_names, "API 列表未包含 /statistics"
    assert "/export" in api_names, "API 列表未包含 /export"
    assert "/backup" in api_names, "API 列表未包含 /backup"
    print("  API 列表包含三个新命令 OK")

    print("=== 注册测试通过 ===\n")


async def test_command_routing():
    """测试命令能被 handle_system_command 识别

    使用 MockService 避免触发完整 ChatAgent 初始化。
    /statistics /export /backup 都会在执行中遇到依赖缺失而返回 error，
    但只要返回的不是 None（表示命令被识别），就说明路由正确。
    """
    print("=== 测试命令路由识别 ===")

    # 延迟导入，避免模块加载时触发 ChatAgent 初始化
    from core.services.aveline.command_handler import handle_system_command

    class MockService:
        """模拟 service 对象"""
        def __init__(self):
            self.chat_agent = None

    service = MockService()
    test_cases = [
        ("/statistics", "test_user"),
        ("/stats", "test_user"),
        ("/export", "test_user"),
        ("/export diary", "test_user"),
        ("/backup", "test_user"),
    ]

    for cmd, user_id in test_cases:
        result = await handle_system_command(service, cmd, user_id)
        # result 为 None 表示命令未被识别（路由失败）
        # result 不为 None 表示命令被识别并尝试执行（即使执行失败返回 error 也是 OK）
        assert result is not None, f"命令 '{cmd}' 未被识别（路由失败）"
        text, meta = result
        status = meta.get("status", "unknown")
        print(f"  {cmd}: status={status}, text={text[:60]}...")
        # 至少命令应该被路由到对应的处理器
        assert "command" in meta, f"命令 '{cmd}' 返回缺少 command 字段"

    print("=== 命令路由测试通过 ===\n")


async def test_export_invalid_arg():
    """测试 /export 非法参数提示"""
    print("=== 测试 /export 非法参数提示 ===")
    from core.services.aveline.command_handler import handle_system_command

    class MockService:
        def __init__(self):
            self.chat_agent = None

    service = MockService()
    result = await handle_system_command(service, "/export invalid", "test_user")
    assert result is not None
    text, meta = result
    assert meta["status"] == "info", f"非法参数应返回 info，实际: {meta}"
    assert "用法" in text, "非法参数应返回用法提示"
    print(f"  /export invalid -> {text[:80]}")
    print("=== 非法参数测试通过 ===\n")


async def main():
    try:
        test_registry()
    except AssertionError as e:
        print(f"注册测试失败: {e}")
        return 1

    try:
        await test_command_routing()
        await test_export_invalid_arg()
    except AssertionError as e:
        print(f"命令测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"命令测试异常: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print("=== P1-6 路由与注册测试通过 ===")
    print("注：完整功能验证（实际导出/备份）需在真实运行的服务里测试")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
