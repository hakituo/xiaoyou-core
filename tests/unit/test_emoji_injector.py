import sys
import os
import asyncio

# Ensure project root is in path
sys.path.append(os.getcwd())

from clients.bots.qq.face import QQFaceInjector

def test_emoji_cleaning():
    print("\n" + "="*50)
    print("测试 QQFaceInjector 的表情保留和转换逻辑")
    print("="*50)

    injector = QQFaceInjector(enabled=True)
    
    test_cases = [
        {
            "name": "原生 Emoji 保留测试",
            "input": "你好啊 😋 😊 [微笑] 👍",
            "expected_contains": ["😋", "😊", "👍", "[CQ:face,id="],
        },
        {
            "name": "未定义表情保留测试",
            "input": "这是一个未定义的表情 🦄 和一个已定义的 ❤️",
            "expected_contains": ["🦄", "❤️"],
        },
        {
            "name": "颜文字优先级测试",
            "input": "我现在好开心 [开心]",
            "check_either": ["[CQ:face,id=", "(", ")"], # 应该是 QQ 表情或颜文字
        },
        {
            "name": "角括号标签兼容测试",
            "input": "嗯……【好奇】你刚刚说的是啥意思呀",
            "expected_contains": ["[CQ:face,id="],
            "not_expected": ["【好奇】"],
        },
        {
            "name": "疑惑别名兼容测试",
            "input": "咦？[疑惑]",
            "expected_contains": ["[CQ:face,id=32]"],
            "not_expected": ["[疑惑]"],
        },
    ]

    for case in test_cases:
        print(f"\n运行测试: {case['name']}")
        print(f"输入: {case['input']}")
        output = injector.apply(case['input'], scope="test")
        print(f"输出: {output}")
        
        passed = True
        if "expected_contains" in case:
            for exp in case["expected_contains"]:
                if exp not in output:
                    # 注意：[爱心] 可能会被转换成 [CQ:face,id=66]
                    if exp == "[爱心]" and "[CQ:face,id=66]" in output:
                        continue
                    print(f"❌ 缺少预期内容: {exp}")
                    passed = False
        
        if "not_expected" in case:
            for not_exp in case["not_expected"]:
                if not_exp in output:
                    print(f"❌ 包含不应出现的内容: {not_exp}")
                    passed = False
                    
        if passed:
            print("✅ 测试通过")
        else:
            print("❌ 测试失败")

        assert passed, f"测试失败: {case['name']}"

if __name__ == "__main__":
    test_emoji_cleaning()
