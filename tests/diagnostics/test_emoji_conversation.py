import sys
import os
import asyncio
import time
import logging

# Ensure project root is in path
sys.path.append(os.getcwd())

from core.core_engine.service_singletons import initialize_aveline_service_sync
from clients.bots.qq.face import QQFaceInjector

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("EMOJI_TEST")

async def run_emoji_test():
    print("\n" + "="*50)
    print("开始 Aveline 表情优先级与保留逻辑集成测试")
    print("="*50)

    # 1. 初始化服务
    print("\n[1/3] 正在初始化 AvelineService...")
    service = initialize_aveline_service_sync()
    if not service:
        print("❌ AvelineService 初始化失败！")
        return
    await service.initialize()
    
    # 2. 初始化表情注入器 (模拟 QQ 适配器行为)
    injector = QQFaceInjector(enabled=True)

    # 3. 发送测试消息，诱导模型使用表情和颜文字
    test_prompts = [
        "我有点难过... ❤️ 😊 给我点安慰好吗？记得用中文，不要发刚才那种红心和笑脸 Emoji，请务必使用 [爱心] 这个标签代替。"
    ]
    
    conversation_id = f"test_emoji_{int(time.time())}"
    
    for i, prompt in enumerate(test_prompts):
        print(f"\n--- 测试轮次 {i+1} ---")
        print(f"用户输入: {prompt}")
        
        raw_response = ""
        async for chunk in service.stream_generate_response(
            user_input=prompt,
            conversation_id=conversation_id
        ):
            if isinstance(chunk, dict):
                if chunk.get("type") == "token":
                    raw_response += chunk.get("content", "")
                elif chunk.get("type") == "emotion_update":
                    pass # 忽略情绪更新
            else:
                raw_response += str(chunk)
        
        print(f"模型原始输出: {raw_response}")
        
        # 应用表情注入 (模拟 QQ 适配器处理)
        processed_response = injector.apply(raw_response, scope="test")
        print(f"处理后输出: {processed_response}")
        
        # 4. 验证逻辑
        print("\n验证结果:")
        
        # 检查是否包含 Unicode Emoji
        import re
        unicode_emojis = re.findall(r'[\U00010000-\U0010ffff\u2600-\u26ff\u2700-\u27bf]', processed_response)
        if unicode_emojis:
            print(f"✅ Unicode Emoji 已保留: {unicode_emojis}")
        else:
            print("ℹ️ 未发现 Unicode Emoji，模型可能没有输出原生 Emoji")
            
        # 检查是否包含 QQ 表情或颜文字
        has_qq_face = "[CQ:face,id=" in processed_response
        has_kaomoji = any(c in processed_response for c in "()（）") # 粗略判断颜文字
        
        if has_qq_face:
            print("✅ 包含 QQ 表情")
        if has_kaomoji:
            print("✅ 包含颜文字")
            
        if not (has_qq_face or has_kaomoji):
            print("⚠️ 未发现表情或颜文字，模型可能未遵循引导")

if __name__ == "__main__":
    asyncio.run(run_emoji_test())
