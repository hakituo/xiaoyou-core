#!/usr/bin/env python3
"""
调试 Active Care 人设选择问题
检查为什么消息从错误的 QQ 账号发送
"""
import asyncio
import sys
import os
from pathlib import Path
# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

async def debug_active_care_persona_selection():
    print("=== Active Care 人设选择调试 ===")
    
    # 1. 获取当前 persona_filename
    try:
        from core.character.managers.persona_manager import get_persona_manager
        pm = get_persona_manager()
        current_filename = pm.get_current_filename()
        print(f"1. 当前 persona_filename: {current_filename}")
    except Exception as e:
        print(f"1. 获取当前 persona 失败: {e}")
    
    # 2. 获取 Active Care 服务实例
    try:
        from core.services.active_care.core.service import get_active_care_service
        service = get_active_care_service()
        if not service:
            print("2. Active Care 服务未初始化，尝试创建...")
            from core.services.active_care.core.service import ActiveCareService
            service = ActiveCareService()
            # 注意：不初始化，只获取实例
        print(f"2. Active Care 服务实例: {service}")
    except Exception as e:
        print(f"2. 获取 Active Care 服务失败: {e}")
        return
    
    # 3. 检查 _recent_user_message_cache
    try:
        context = service.context
        cache = context._recent_user_message_cache
        print(f"3. _recent_user_message_cache 内容 ({len(cache)} 项):")
        for cid, data in list(cache.items())[:10]:  # 只显示前10项
            print(f"   - {cid}: {data}")
    except Exception as e:
        print(f"3. 获取缓存失败: {e}")
    
    # 4. 检查 QQ 连接实例
    try:
        executor = service.executor
        connections = executor._get_qq_connections()
        print(f"4. QQ 连接实例 ({len(connections)} 个):")
        for conn in connections:
            print(f"   - user_id: {conn.get('user_id')}, persona_filename: {conn.get('persona_filename')}, adapter_type: {conn.get('adapter_type')}")
    except Exception as e:
        print(f"4. 获取 QQ 连接失败: {e}")
    
    # 5. 检查 resolve_primary_conversation_id 结果
    try:
        primary_cid = await context.resolve_primary_conversation_id()
        print(f"5. resolve_primary_conversation_id 结果: {primary_cid}")
    except Exception as e:
        print(f"5. 解析主会话 ID 失败: {e}")
    
    # 6. 检查 _get_qq_user_id_from_connections 结果
    try:
        qq_user_id = executor._get_qq_user_id_from_connections()
        print(f"6. _get_qq_user_id_from_connections 结果: {qq_user_id}")
    except Exception as e:
        print(f"6. 获取 QQ 用户 ID 失败: {e}")
    
    # 7. 检查当前 persona 的 scope
    try:
        scope = storage.resolve_scope_from_conversation_id(primary_cid) if 'primary_cid' in locals() else "未知"
        print(f"7. 当前 scope: {scope}")
    except Exception as e:
        print(f"7. 获取 scope 失败: {e}")
    
    print("\n=== 调试完成 ===")

if __name__ == "__main__":
    asyncio.run(debug_active_care_persona_selection())