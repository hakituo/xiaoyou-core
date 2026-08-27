"""
测试断句功能 - 确保分段数量在 7 句以内，长度可以不同
"""
import sys
sys.path.insert(0, 'clients/bots')

from qq_adapter_utils import _split_message_for_qq, _merge_chunks_to_limit

def test_split_and_merge():
    """测试断句和合并功能"""
    print("=" * 60)
    print("测试 1: 几百字长文本 - 智能合并")
    print("=" * 60)
    long_text = (
        "今天天气真好，阳光明媚，微风徐徐。" * 5 +
        "我们一家人决定去公园野餐。" * 5 +
        "带上好吃的三明治和水果，还有饮料。" * 5 +
        "孩子们在草地上奔跑嬉戏，非常开心。" * 5 +
        "这样的周末真是太棒了！"
    )
    result = _split_message_for_qq(long_text, max_len=60)
    print(f"原文长度：{len(long_text)}")
    print(f"分段数量：{len(result)} (目标: ≤7)")
    for i, chunk in enumerate(result, 1):
        print(f"  [{i}] (len={len(chunk)}): {chunk}")
    print()

    print("=" * 60)
    print("测试 2: 短对话 - 正常断句")
    print("=" * 60)
    short_text = "你好啊！今天天气真不错。"
    result = _split_message_for_qq(short_text, max_len=60)
    print(f"原文长度：{len(short_text)}")
    print(f"分段数量：{len(result)}")
    for i, chunk in enumerate(result, 1):
        print(f"  [{i}] (len={len(chunk)}): {chunk}")
    print()

    print("=" * 60)
    print("测试 3: _merge_chunks_to_limit 智能合并")
    print("=" * 60)
    # 模拟很多短分段的场景
    chunks = ["今天", "天气", "真好", "我们", "出去", "野餐", "带上", "三明治", "和", "水果"]
    print(f"原始分段: {chunks}")
    print(f"分段数量: {len(chunks)}")
    result = _merge_chunks_to_limit(chunks, max_chunks=7)
    print(f"合并后分段: {result}")
    print(f"分段数量: {len(result)}")
    print()
    for i, chunk in enumerate(result, 1):
        print(f"  [{i}] (len={len(chunk)}): {chunk}")
    print()

    print("=" * 60)
    print("测试 4: 普通长度文本 - 不需要合并")
    print("=" * 60)
    normal_text = "今天天气真好，我们出去玩吧！"
    result = _split_message_for_qq(normal_text, max_len=60)
    print(f"原文长度：{len(normal_text)}")
    print(f"分段数量：{len(result)}")
    for i, chunk in enumerate(result, 1):
        print(f"  [{i}] (len={len(chunk)}): {chunk}")
    print()

if __name__ == "__main__":
    test_split_and_merge()
