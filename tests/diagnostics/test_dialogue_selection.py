"""测试对话示例选择准确率"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agents.chat_agent_components.persona_system.prompt.dialogue_examples import (
    _load_real_chat_cache,
    _select_examples,
    tokenize_for_example_rank,
    _REAL_CHAT_CACHE,
)

def test_selection():
    """测试选择准确率"""
    # 加载数据
    print("加载Ling对话数据...")
    cache = _load_real_chat_cache("Ling")
    entries = cache.get("by_persona", {}).get("Ling", {}).get("entries", [])
    print(f"共加载 {len(entries)} 条对话示例\n")
    
    # 测试用例：(用户消息, 期望匹配的主题)
    test_cases = [
        ("今天吃什么", "吃饭/食物相关"),
        ("好困啊想睡觉", "睡觉/休息相关"),
        ("我们来打游戏吧", "游戏相关"),
        ("你下班了吗", "工作/下班相关"),
        ("抓娃娃好玩吗", "抓娃娃/娱乐相关"),
        ("奶茶好喝吗", "奶茶/饮料相关"),
        ("我想你了", "情感/想念相关"),
        ("今天天气怎么样", "天气相关"),
        ("学习好累啊", "学习/疲惫相关"),
        ("mua", "亲亲/亲密相关"),
    ]
    
    print("=" * 60)
    print("测试结果：")
    print("=" * 60)
    
    for message, expected_topic in test_cases:
        print(f"\n【用户消息】{message}")
        print(f"【期望主题】{expected_topic}")
        
        # 选择示例
        results = _select_examples(message, "Ling", cache, top_k=2, use_bert=False)
        
        if results:
            print(f"【选中 {len(results)} 条】")
            for i, r in enumerate(results):
                # 只显示前100个字符
                preview = r[:100] + "..." if len(r) > 100 else r
                print(f"  {i+1}. {preview}")
        else:
            print("【未选中任何示例】")
        
        # 显示分词结果
        tokens = tokenize_for_example_rank(message)
        print(f"【分词结果】{tokens}")
        print("-" * 60)

def test_token_matching():
    """测试 token 匹配逻辑"""
    print("\n\n" + "=" * 60)
    print("Token 匹配逻辑测试：")
    print("=" * 60)
    
    test_messages = [
        "今天吃什么",
        "我想打游戏",
        "好困想睡觉",
        "你下班了吗",
    ]
    
    for msg in test_messages:
        tokens = tokenize_for_example_rank(msg)
        print(f"\n消息: {msg}")
        print(f"分词: {tokens}")
        print(f"词数: {len(tokens)}")

if __name__ == "__main__":
    test_token_matching()
    print("\n\n")
    test_selection()
