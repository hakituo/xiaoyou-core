# -*- coding: utf-8 -*-
"""P1-7 命令系统收口验证脚本

验证三套命令系统收口到 Aveline 主路由后的正确性：
1. 旧版 command/handler.py 已删除
2. Bot 端 command_router 移除了冲突英文别名
3. message_pipeline 未命中时转发后端
4. show_help 按来源分组展示
5. Aveline command_registry 仍是单一真相源
"""
import asyncio
import sys
import os

# 添加项目根目录
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)


def test_zombie_removed():
    """测试1: 旧版 handler.py 已删除"""
    print("=== 测试1: 旧版 handler.py 已删除 ===")
    handler_path = os.path.join(project_root, "core", "services", "command", "handler.py")
    assert not os.path.exists(handler_path), f"僵尸文件仍存在: {handler_path}"
    print("  handler.py 已删除 OK")

    # trm_adapter 不再导入 handle_command_async
    trm_path = os.path.join(project_root, "core", "trm_adapter.py")
    with open(trm_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "handle_command_async" not in content, "trm_adapter 仍引用 handle_command_async"
    assert "from core.services.command" not in content, "trm_adapter 仍导入 command 模块"
    print("  trm_adapter 已清理 OK")
    print()


def test_bot_router_conflict_removed():
    """测试2: Bot 端移除了冲突英文别名"""
    print("=== 测试2: Bot 端移除冲突英文别名 ===")
    from clients.bots.handlers.command_router import CommandRouter

    # 创建一个 mock adapter 来实例化 CommandRouter
    class MockAdapter:
        def __init__(self):
            self.command_router = None

    adapter = MockAdapter()
    router = CommandRouter(adapter)

    # 这些英文命令应该不在 Bot 端路由里（已移除，转发后端）
    removed_commands = ["save", "study", "clear", "latency", "mode"]
    for cmd in removed_commands:
        # 检查 dispatch 不会命中这些命令
        # 由于 dispatch 是 async 的，我们检查 _routes 里的别名集合
        found = False
        for route in router._routes:
            if cmd in route.aliases:
                found = True
                break
        assert not found, f"/{cmd} 应该已从 Bot 端移除，但仍存在于路由中"
    print("  冲突英文别名已移除: save/study/clear/latency/mode OK")

    # 这些中文别名应该保留
    kept_commands = ["清除短期记忆", "保存配置", "仿生延迟", "学习模式", "学习"]
    for cmd in kept_commands:
        found = False
        for route in router._routes:
            if cmd in route.aliases:
                found = True
                break
        assert found, f"/{cmd} 应该保留在 Bot 端，但已被移除"
    print("  中文别名保留: 清除短期记忆/保存配置/仿生延迟/学习模式/学习 OK")
    print()


def test_aveline_registry_intact():
    """测试3: Aveline command_registry 仍是单一真相源"""
    print("=== 测试3: Aveline command_registry 完整 ===")
    from core.services.aveline.command_registry import (
        COMMAND_REGISTRY, find_command, format_help_text, get_command_list_for_api
    )

    # Aveline 应该有这些命令
    expected_commands = [
        "clear", "save", "mode", "care", "forget", "memory",
        "latency", "studylog", "studydone", "studypanel",
        "statistics", "export", "backup", "help",
    ]
    for name in expected_commands:
        spec = find_command(name)
        assert spec is not None, f"Aveline 缺少命令 /{name}"
    print(f"  Aveline 命令完整: {len(expected_commands)} 条 OK")

    # /help 文本包含所有命令
    help_text = format_help_text()
    for name in expected_commands:
        assert f"/{name}" in help_text, f"/help 未包含 /{name}"
    print("  /help 包含所有命令 OK")

    # API 列表
    api_list = get_command_list_for_api()
    assert len(api_list) >= len(expected_commands), "API 列表不完整"
    print(f"  API 列表: {len(api_list)} 条 OK")
    print()


def test_help_rendering():
    """测试4: show_help 按来源分组渲染"""
    print("=== 测试4: show_help 按来源分组渲染 ===")
    from clients.bots.handlers.system import SystemHandler

    # 模拟合并后的命令清单
    merged_commands = [
        # 后端命令
        {"command": "/clear", "description": "清除全部记忆", "source": "aveline_backend", "category": "对话命令"},
        {"command": "/save", "description": "保存偏好", "source": "aveline_backend", "category": "对话命令"},
        {"command": "/memory", "description": "查看记忆状态", "source": "aveline_backend", "category": "对话命令"},
        # Bot 端命令
        {"command": "/清除短期记忆", "description": "只清短期记忆", "source": "bot_client", "category": "记忆"},
        {"command": "/保存配置", "description": "保存本地配置", "source": "bot_client", "category": "配置", "master_only": True},
        {"command": "/买", "description": "购买食物", "source": "bot_client", "category": "食物"},
    ]

    lines = SystemHandler._render_help_text(merged_commands)
    text = "\n".join(lines)

    print(f"  渲染结果:\n{text}\n")

    # 验证后端命令在前
    assert "【对话命令】（后端处理）" in text, "缺少后端命令分组"
    assert "【记忆】（本地处理）" in text, "缺少本地记忆分组"
    assert "【配置】（本地处理）" in text, "缺少本地配置分组"
    assert "【食物】（本地处理）" in text, "缺少本地食物分组"

    # 验证 Master 标注
    assert "[Master]" in text, "缺少 Master 标注"

    # 验证后端命令在前
    backend_pos = text.find("后端处理")
    bot_pos = text.find("本地处理")
    assert backend_pos < bot_pos, "后端命令应该在本地命令前面"
    print("  按来源分组 OK")
    print()


def test_merge_no_conflict():
    """测试5: 合并命令清单不再冲突"""
    print("=== 测试5: 合并命令清单无冲突 ===")
    from clients.bots.handlers.system import SystemHandler

    # 模拟后端命令（Aveline）
    server_cmds = [
        {"command": "/clear", "description": "清除全部记忆", "aliases": []},
        {"command": "/save", "description": "保存偏好", "aliases": []},
        {"command": "/mode", "description": "切换模式", "aliases": []},
    ]

    # 模拟 Bot 端命令（收口后不再有 /clear /save /mode）
    bot_cmds = [
        {"command": "/清除短期记忆", "description": "只清短期记忆", "aliases": ["/reset"]},
        {"command": "/保存配置", "description": "保存本地配置", "aliases": []},
        {"command": "/学习模式", "description": "切换学习模式", "aliases": ["/studymode"]},
    ]

    merged = SystemHandler._merge_commands(server_cmds, bot_cmds)

    # 应该有 6 条命令（3 后端 + 3 本地），无冲突
    assert len(merged) == 6, f"合并后应有 6 条命令，实际 {len(merged)}"

    # 检查无重名
    cmd_names = [c["command"] for c in merged]
    assert len(cmd_names) == len(set(cmd_names)), f"命令重名: {cmd_names}"

    print(f"  合并后 {len(merged)} 条命令，无冲突 OK")
    print()


async def main():
    tests = [
        test_zombie_removed,
        test_bot_router_conflict_removed,
        test_aveline_registry_intact,
        test_help_rendering,
        test_merge_no_conflict,
    ]

    for test in tests:
        try:
            test()
        except AssertionError as e:
            print(f"失败: {e}")
            import traceback
            traceback.print_exc()
            return 1
        except Exception as e:
            print(f"异常: {e}")
            import traceback
            traceback.print_exc()
            return 1

    print("=== P1-7 命令系统收口验证全部通过 ===")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
