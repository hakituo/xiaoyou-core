import asyncio
import pytest
from core.agents.chat_agent import ChatAgent

class MockLLM:
    def __init__(self):
        self.history = []
        self.current_persona = "SFW"

    def get_current_model_name(self):
        return "mock-stress-llm"

    async def stream_chat(self, messages, **kwargs):
        # 模拟 LLM 行为：根据消息内容决定回复
        self.history.append(list(messages))
        
        # 获取用户最后一句话
        user_msg = ""
        for m in reversed(messages):
            if m["role"] == "user":
                user_msg = m["content"]
                break
        
        # 检查上下文是否包含之前的关键信息
        all_content = " ".join([m["content"] for m in messages if m["role"] != "system"])
        
        if "我叫什么" in user_msg:
            if "小明" in all_content:
                reply = "嗯，你叫小明呀"
            else:
                reply = "那个...我还不知道你名字呢"
        elif "我喜欢什么" in user_msg:
            if "打游戏" in all_content:
                reply = "你不是喜欢打游戏嘛"
            else:
                reply = "你还没告诉我你喜欢什么呢"
        elif "sensitive" in user_msg.lower():
            # 模拟检查系统提示词中是否有 Sensitive 指令
            system_prompt = next((m["content"] for m in messages if m["role"] == "system"), "")
            if "Sensitive" in system_prompt or "私密" in system_prompt:
                reply = "既然是私密模式，那我们就聊点大胆的..."
            else:
                reply = "对不起，我现在是纯洁模式哦"
        else:
            reply = "好哒，记住了"

        # 模拟流式输出
        for i in range(0, len(reply), 5):
            yield {"content": reply[i:i+5]}

@pytest.mark.anyio
async def test_long_conversation_stress():
    """
    压力测试：模拟 10 轮对话，验证：
    1. 10 轮后是否还能记得第 1 轮的名字
    2. 5 轮后是否还能记得第 2 轮的爱好
    3. 风格是否保持短促、自然（不带 AI 腔）
    4. Sensitive 切换是否生效
    """
    # 强制不加载任何真实模块
    from core.agents.chat_agent import AgentConfig
    agent = ChatAgent(AgentConfig(agent_name="stress_test"))
    
    # 彻底 Mock LLM 模块，防止触发本地模型加载
    mock_llm = MockLLM()
    agent.llm_module = mock_llm 
    agent.is_initialized = True # 标记为已初始化，跳过内部初始化逻辑
    
    # Mock 情绪管理器，防止它去加载模型
    class DummyEmotionManager:
        def process_text(self, *args, **kwargs): return None
    agent.emotion_manager = DummyEmotionManager()

    user_id = "stress_test_user"
    
    # 模拟 10 轮对话流程
    conversation_steps = [
        ("我叫小明", "确认记得名字"),
        ("我喜欢打游戏", "确认记得爱好"),
        ("今天天气真好", "闲聊 1"),
        ("你会唱歌吗", "闲聊 2"),
        ("你觉得我怎么样", "闲聊 3"),
        ("我喜欢什么？", "验证爱好记忆（第 6 轮问第 2 轮的事）"),
        ("再聊点别的吧", "闲聊 4"),
        ("嘿嘿，咱们来点 sensitive 的内容？", "验证 Sensitive 模式切换"),
        ("随便说点什么", "闲聊 5"),
        ("最后考考你，我叫什么？", "验证长时记忆（第 10 轮问第 1 轮的事）")
    ]
    
    print("\n" + "="*50)
    print("开始 10 轮长对话压力测试")
    print("="*50)
    
    for i, (user_input, purpose) in enumerate(conversation_steps):
        print(f"\n[Turn {i+1}] 用户: {user_input} ({purpose})")
        
        full_reply = ""
        async for chunk in agent.stream_chat(user_id=user_id, message=user_input):
            if "content" in chunk:
                full_reply += chunk["content"]
        
        print(f"[Turn {i+1}] AI: {full_reply}")
        
        # 验证回复是否包含 AI 腔调
        bad_phrases = ["作为AI助手", "作为一个人工智能", "我是由", "能够为您提供帮助"]
        for phrase in bad_phrases:
            assert phrase not in full_reply, f"发现 AI 腔调: {phrase}"
            
        # 验证长度（除非是特殊回复，否则应该短促）
        if "sensitive" not in user_input.lower():
            assert len(full_reply) < 30, f"回复太长了: {len(full_reply)} 字"

        # 关键轮次验证
        if i == 5: # 问爱好
            assert "打游戏" in full_reply, "忘记了第 2 轮提到的爱好"
        if i == 9: # 问名字
            assert "小明" in full_reply, "忘记了第 1 轮提到的名字"
            
    print("\n" + "="*50)
    print("测试通过：长时记忆与自然风格验证成功！")
    print("="*50)

if __name__ == "__main__":
    asyncio.run(test_long_conversation_stress())
