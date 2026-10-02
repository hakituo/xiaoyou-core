import asyncio
import time
from typing import Any


async def save_llm_state_emergency(engine: Any, llm_instance: Any, logger) -> Any:
    if llm_instance is None:
        engine._saved_llm_state = None
        engine._saved_llm_state_ts = 0.0
        return None
    try:
        logger.info("Emergency Mode: 正在保存 KV Cache...")
        state = await asyncio.to_thread(llm_instance.save_state)
        engine._saved_llm_state = state
        engine._saved_llm_state_ts = time.time()
        logger.info("Emergency Mode: KV Cache 保存完成")
        return state
    except Exception as e:
        logger.warning(f"Emergency Mode: KV Cache 保存失败（非致命）: {e}")
        engine._saved_llm_state = None
        engine._saved_llm_state_ts = 0.0
        return None


async def restore_llm_state_emergency(engine: Any, llm_instance: Any, logger) -> bool:
    state = getattr(engine, "_saved_llm_state", None)
    if llm_instance is None or state is None:
        return False
    try:
        logger.info("Emergency Mode: 正在恢复 KV Cache...")
        await asyncio.to_thread(llm_instance.load_state, state)
        engine._saved_llm_state = None
        engine._saved_llm_state_ts = 0.0
        logger.info("Emergency Mode: KV Cache 恢复完成")
        return True
    except Exception as e:
        logger.warning(f"Emergency Mode: KV Cache 恢复失败（非致命）: {e}")
        return False
