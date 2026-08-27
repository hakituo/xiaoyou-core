"""测试表情包语义检索效果。

模拟 LLM 可能发出的各种查询，看返回的图片是否相关。

用法：
    d:\\AI\\xiaoyou-core\\venv_cpu\\Scripts\\python.exe tests\\scripts\\meme\\test_semantic_search.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 测试用查询（模拟 LLM 在 [MEME:xxx] 标签里可能写的内容）
TEST_QUERIES = [
    # 直接情绪
    "愤怒警告",
    "委屈想哭",
    "惊讶震惊",
    "开心大笑",
    "害羞脸红",
    # 场景化
    "被气到想打人",
    "我受够了别惹我",
    "专注思考中",
    "被萌到捂心口",
    "刚解决问题如释重负",
    "得意地叉腰笑",
    # 动作描述
    "竖大拇指赞同",
    "持枪警告",
    # 复杂场景
    "对方闯祸后算账",
    "被误解时沉默",
    # 新增（覆盖 normal 文件夹）
    "慵懒地喝茶享受生活",
    "群聊被吓到社交恐惧",
    "认输服了",
    "被撩到心动",
    "看手机生气警告",
]


async def main():
    from clients.bots.qq.meme_search import pick_meme_by_semantic, get_status, reset_for_test

    reset_for_test()
    print("=" * 70)
    print("表情包语义检索测试")
    print("=" * 70)

    # 等索引加载
    print("\n加载索引中...")
    status = get_status()
    print(f"索引状态: {status}")

    print(f"\n共 {len(TEST_QUERIES)} 个测试查询\n")

    success = 0
    fail = 0
    for i, query in enumerate(TEST_QUERIES, 1):
        print(f"[{i}/{len(TEST_QUERIES)}] 查询: {query!r}")
        try:
            path = await asyncio.to_thread(pick_meme_by_semantic, query)
            if path:
                rel = path.relative_to(PROJECT_ROOT / "data" / "memes")
                print(f"  ✅ 命中: {rel}")
                success += 1
            else:
                print(f"  ❌ 未找到（相似度太低或索引为空）")
                fail += 1
        except Exception as e:
            print(f"  ❌ 异常: {type(e).__name__}: {e}")
            fail += 1

    print("\n" + "=" * 70)
    print(f"结果: 成功 {success}/{len(TEST_QUERIES)}, 失败 {fail}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
