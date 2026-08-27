"""
双角色互聊剧本生成测试脚本

验证:
1. 剧本JSON解析是否正确
2. 延迟计算是否合理
3. Prompt构建是否完整
"""

import sys
import os
from unittest.mock import patch

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def test_parse_script():
    """测试剧本JSON解析"""
    from clients.bots.qq.peer_chat import PeerChatManager

    # 正常JSON
    raw1 = '{"script": [{"role": "aveline", "content": "你吃饭了吗"}, {"role": "ling", "content": "还没"}, {"role": "aveline", "content": "那主人呢"}, {"role": "ling", "content": "噢噢，我去问问", "mention_user": true}]}'
    result1 = PeerChatManager.parse_script(raw1)
    assert len(result1) == 4, f"期望4条，实际{len(result1)}"
    assert result1[0]["role"] == "aveline"
    assert result1[0]["content"] == "你吃饭了吗"
    assert not result1[0]["mention_user"]
    assert result1[3]["mention_user"]
    print("[PASS] 正常JSON解析")

    # 带markdown代码块
    raw2 = '```json\n{"script": [{"role": "aveline", "content": "你好"}, {"role": "ling", "content": "昂"}]}\n```'
    result2 = PeerChatManager.parse_script(raw2)
    assert len(result2) == 2
    print("[PASS] markdown代码块解析")

    # 列表格式
    raw3 = '[{"role": "aveline", "content": "嗨"}, {"role": "ling", "content": "噢"}]'
    result3 = PeerChatManager.parse_script(raw3)
    assert len(result3) == 2
    print("[PASS] 列表格式解析")

    # 空内容
    result4 = PeerChatManager.parse_script("")
    assert result4 == []
    print("[PASS] 空内容返回空列表")

    # 无效JSON
    result5 = PeerChatManager.parse_script("这不是JSON")
    assert result5 == []
    print("[PASS] 无效JSON返回空列表")

    # 带LLM解释文字
    raw6 = '好的，这是剧本：\n{"script": [{"role": "aveline", "content": "测试"}]}\n以上。'
    result6 = PeerChatManager.parse_script(raw6)
    assert len(result6) == 1
    print("[PASS] 带解释文字的JSON解析")


def test_calc_message_delay():
    """测试延迟计算"""
    from clients.bots.qq.peer_chat import PeerChatManager

    # 短消息
    delay_short = PeerChatManager.calc_message_delay("噢")
    assert 0.5 <= delay_short <= 7.5, f"短消息延迟异常: {delay_short}"
    print(f"[PASS] 短消息延迟: {delay_short:.2f}s")

    # 中等消息
    delay_mid = PeerChatManager.calc_message_delay("你吃饭了吗")
    assert 0.5 <= delay_mid <= 7.5, f"中等消息延迟异常: {delay_mid}"
    print(f"[PASS] 中等消息延迟: {delay_mid:.2f}s")

    # 长消息
    delay_long = PeerChatManager.calc_message_delay("我刚才去楼下超市买了一堆东西，花了好多钱")
    assert 0.5 <= delay_long <= 7.5, f"长消息延迟异常: {delay_long}"
    print(f"[PASS] 长消息延迟: {delay_long:.2f}s")

    # 多次计算应该有随机性
    delays = [PeerChatManager.calc_message_delay("测试") for _ in range(10)]
    unique_count = len(set(delays))
    assert unique_count > 1, "延迟应该有随机性"
    print(f"[PASS] 延迟随机性: {unique_count}/10种不同值")


def test_build_script_generation_prompt():
    """测试剧本生成prompt构建"""
    # 直接导入模块文件，避免依赖链问题
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "qq_peer_context",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                     "core", "agents", "chat_agent_components", "persona_system", "prompt", "qq_peer_context.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    prompt_result = mod.build_script_generation_prompt(
        role_name="七濑 澪",
        peer_name="Ling",
        role_id="aveline",
        peer_role_id="ling",
        topic="约吃饭",
        situation="看到Ling在摸鱼，想约她吃饭",
        opening_idea="直接问她要不要一起吃",
        recent_master_history="【和主人的最近聊天】\n- 主人: 晚上吃什么\n- 我: 随便",
        recent_peer_scripts="【之前的互聊记录】\n- 七濑 澪: 你干嘛呢",
        time_str="2026年05月29日 18点30分",
    )

    prompt = prompt_result.system_prompt + "\n" + prompt_result.user_prompt
    assert "七濑 澪" in prompt
    assert "Ling" in prompt
    assert "约吃饭" in prompt
    assert "主人的最近聊天" in prompt
    assert "之前的互聊记录" in prompt
    assert "18点30分" in prompt
    assert "mention_user" in prompt
    assert "script" in prompt
    print("[PASS] prompt构建完整")
    print(f"\nprompt长度: {len(prompt)}字")


def test_profiles():
    """测试角色配置"""
    from clients.bots.qq.peer_chat import PeerChatManager

    aveline = PeerChatManager.PEER_PROFILES.get("aveline")
    ling = PeerChatManager.PEER_PROFILES.get("ling")

    assert aveline is not None
    assert ling is not None
    # 角色名已统一为带空格的权威名（与 core_aveline.json 一致）
    assert aveline["role_name"] == "七濑 澪"
    assert ling["role_name"] == "Ling"
    print("[PASS] 角色配置正确")


def test_detect_peer_mention():
    """测试提及对方检测"""
    from clients.bots.qq.peer_chat import PeerChatManager

    # 避免异步文件日志线程晚于 pytest 输出流关闭，污染测试结果。
    with patch("clients.bots.qq.peer_chat.logger"):
        # 七濑澪的视角：提及Ling
        assert PeerChatManager.detect_peer_mention("我去帮Ling看看她今天怎么了", "aveline") == "ling"
        assert PeerChatManager.detect_peer_mention("玲玲在吗", "aveline") == "ling"
        assert PeerChatManager.detect_peer_mention("小玲今天心情不好", "aveline") == "ling"

        # Ling的视角：提及七濑澪
        assert PeerChatManager.detect_peer_mention("澪姐在干嘛", "ling") == "aveline"
        assert PeerChatManager.detect_peer_mention("我去找小澪", "ling") == "aveline"
        assert PeerChatManager.detect_peer_mention("七濑澪帮我看看", "ling") == "aveline"

        # 不提及对方
        assert PeerChatManager.detect_peer_mention("今天天气真好", "aveline") == ""
        assert PeerChatManager.detect_peer_mention("我要吃饭了", "ling") == ""

    print("[PASS] 提及对方检测")


if __name__ == "__main__":
    print("=" * 50)
    print("双角色互聊剧本生成测试")
    print("=" * 50)

    test_profiles()
    test_parse_script()
    test_calc_message_delay()
    test_build_script_generation_prompt()
    test_detect_peer_mention()

    print("\n" + "=" * 50)
    print("所有测试通过!")
    print("=" * 50)
