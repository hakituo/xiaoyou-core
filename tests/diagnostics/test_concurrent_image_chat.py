import asyncio
import time
import logging
import sys
import os

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.image.image_manager import get_image_manager, ImageGenerationConfig
from core.resource_manager import get_global_resource_manager, ResourceType, ResourceState
from core.llm import get_llm_module

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("ConcurrentTest")

async def simulate_chat(llm, chat_id: int):
    """模拟一次聊天请求"""
    start_time = time.time()
    logger.info(f"[Chat {chat_id}] 发起聊天请求...")
    try:
        # 简单的提示词
        messages = [{"role": "user", "content": "你好，请简单自我介绍一下。"}]
        response = ""
        async for chunk in llm.stream_chat(messages):
            if isinstance(chunk, dict) and "content" in chunk:
                response += chunk["content"]
            elif isinstance(chunk, str):
                response += chunk
            
            if len(response) > 50: # 只取前50个字，节省时间
                break
        
        duration = time.time() - start_time
        logger.info(f"[Chat {chat_id}] 聊天回复成功 (耗时: {duration:.2f}s): {response[:30]}...")
        return True
    except Exception as e:
        logger.error(f"[Chat {chat_id}] 聊天失败: {e}")
        return False

async def run_test():
    logger.info("=== 开始并发生图与聊天测试 ===")
    
    # 1. 获取组件
    rm = await get_global_resource_manager()
    im = await get_image_manager()
    llm = get_llm_module()
    
    # 初始化 LLM (如果是第一次使用)
    await llm.initialize()
    
    # 确保 LLM 已加载到 GPU (模拟初始状态)
    logger.info("准备阶段：确保 LLM 在 GPU...")
    # 这里我们通过 resource_manager 检查
    state = rm.monitor.get_resource_state(ResourceType.GPU_MEMORY)
    logger.info(f"当前 GPU 状态: {state}")

    # 2. 定义生图任务
    config = ImageGenerationConfig(
        prompt="A high-tech cyberpunk city, neon lights, rainy street, 8k resolution",
        width=512,
        height=512,
        steps=20
    )
    
    logger.info("--- 步骤 1: 启动异步生图任务 ---")
    # 我们使用 asyncio.create_task 让它在后台跑
    image_task = asyncio.create_task(im.generate_image("forge", config))
    
    # 等待一小会儿，让生图逻辑触发资源准备（卸载 LLM）
    await asyncio.sleep(1.5)
    
    logger.info("--- 步骤 2: 在生图期间发起并发聊天 ---")
    chat_tasks = [
        asyncio.create_task(simulate_chat(llm, 1)),
        asyncio.create_task(simulate_chat(llm, 2))
    ]
    
    # 3. 等待所有聊天完成
    chat_results = await asyncio.gather(*chat_tasks)
    
    logger.info("--- 步骤 3: 等待生图任务完成 ---")
    image_result = await image_task
    
    # 4. 结果汇总
    logger.info("=== 测试结果汇总 ===")
    if image_result.get("success"):
        logger.info("✅ 生图任务: 成功")
    else:
        logger.info(f"❌ 生图任务: 失败 ({image_result.get('error')})")
        if image_result.get("raw_error") == "gpu_memory_pressure":
            logger.info("ℹ️ 生图被拒绝是符合预期的（如果显存压力真的很大）")

    all_chats_ok = all(chat_results)
    if all_chats_ok:
        logger.info("✅ 并发聊天: 全部成功 (说明 LLM 成功在 CPU/GPU 切换期间保持服务)")
    else:
        logger.info("❌ 并发聊天: 存在失败请求")

    # 5. 检查回迁状态
    await asyncio.sleep(2) # 等待回迁逻辑执行
    logger.info(f"最终 GPU 状态: {rm.monitor.get_resource_state(ResourceType.GPU_MEMORY)}")
    
    logger.info("=== 测试结束 ===")

if __name__ == "__main__":
    try:
        asyncio.run(run_test())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"测试运行崩溃: {e}", exc_info=True)
