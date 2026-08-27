import asyncio
import sys
import os
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from core.services.active_care.core.service import get_active_care_service

async def test():
    service = get_active_care_service()
    if not service:
        # 手动初始化
        from core.services.active_care.core.service import ActiveCareService
        service = ActiveCareService()
        await service.initialize()
    
    print("开始触发")
    try:
        await service._on_delayed_task_trigger(
            task_id="test_id_123",
            task_type="time_based_follow_up",
            context={"has_time_expectation": True, "expected_seconds": 60},
            source_message="一分钟后给我发消息",
            action_hint="一分钟"
        )
        print("触发完成")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test())
