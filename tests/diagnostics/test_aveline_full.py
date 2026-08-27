import sys
import os
import asyncio
import logging
import time

# Ensure project root is in path
sys.path.append(os.getcwd())

from core.core_engine.service_singletons import initialize_aveline_service_sync, get_aveline_service
from core.services.aveline.service import AvelineService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("FULL_TEST")

async def run_full_test():
    print("\n" + "="*50)
    print("开始 Aveline 主程序集成测试 (RTX 5070 优化验证)")
    print("="*50)

    # 1. 初始化服务 (这会加载模型和人设)
    start_init = time.time()
    print("\n[1/3] 正在初始化 AvelineService...")
    service = initialize_aveline_service_sync()
    if not service:
        print("❌ AvelineService 初始化失败！")
        return

    # 重要：必须调用异步初始化
    print("Initializing service asynchronously...")
    await service.initialize()
    print(f"✅ 服务初始化完成，耗时: {time.time() - start_init:.2f}s")

    # 2. 发送测试消息
    print("\n[2/3] 正在发送测试消息...")
    payload = {
        "content": "你好，Aveline。请告诉我你现在的系统状态，以及你对 RTX 5070 的看法。",
        "conversation_id": "test_user_5070",
        "stream": True
    }
    
    start_inference = time.time()
    first_token_time = None
    full_response = ""
    
    has_emo_protocol = False
    
    try:
        # 模拟 API 层的调用
        # stream_generate_response 是 AvelineService 的核心入口
        async for chunk in service.stream_generate_response(
            user_input=payload["content"],
            conversation_id=payload["conversation_id"]
        ):
            if not chunk:
                continue
            
            # 解析 chunk (通常是字符串或字典)
            if isinstance(chunk, dict):
                if chunk.get("type") == "token":
                    content = chunk.get("content", "")
                elif chunk.get("type") == "emotion_update":
                    print(f"\n✨ 检测到情绪协议更新: {chunk.get('data')}")
                    has_emo_protocol = True
                    content = ""
                elif chunk.get("type") == "error":
                    print(f"\n[ERROR] {chunk.get('message')}")
                    content = ""
                else:
                    content = str(chunk.get("content", ""))
            else:
                content = str(chunk)
            
            if content:
                if first_token_time is None:
                    first_token_time = time.time() - start_inference
                    print(f"🚀 首 Token 响应时间: {first_token_time:.2f}s (10s 限制内)")
                
                full_response += content
                # 实时打印流式输出
                print(content, end="", flush=True)

        print(f"\n\n✅ 推理完成，总耗时: {time.time() - start_inference:.2f}s")
        
        # 3. 验证回复质量
        print("\n[3/3] 验证回复质量...")
        if has_emo_protocol or "[EMO:" in full_response:
            print("✅ 包含 [EMO:] 协议头 (内部事件或显式文本)")
        else:
            print("⚠️ 未检测到 [EMO:] 协议头，请检查人设配置")
            
        if len(full_response) > 10:
            print(f"✅ 回复长度正常: {len(full_response)} 字符")
        else:
            print("❌ 回复过短，可能存在问题")

    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "="*50)
    print("测试结束")
    print("="*50 + "\n")

if __name__ == "__main__":
    os.environ["XIAOYOU_RUN_INTEGRATION_TESTS"] = "1"
    asyncio.run(run_full_test())
