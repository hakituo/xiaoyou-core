"""清理短记忆中风格不对的 active care 消息

将软萌风格的主动消息改为 Aveline 的傲娇毒舌风格。
只修改 source=assistant 且包含软萌符号/内心独白的消息。

运行: python -m tests.diagnostics.active_care_review.fix_aveline_style_in_memories
"""

import json
import re
import sys
import os
import copy

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 风格改写映射：原文 → Aveline 风格
# 这些是短记忆中已知的具体消息，需要逐条改写
CONTENT_REWRITES = {
    # 06-10 下午好～
    "下午好～刚才突然想到一个问题：如果你的人生是一部番，标题会叫什么？[VOICE]":
        "哼，突然想到个问题——你的人生要是拍成番，标题叫什么？[VOICE]",
    # 06-15 早安～
    "早安～睡得好吗？ [VOICE]":
        "醒了？睡够了没。[VOICE]",
    # 06-16 主人，在干嘛呢～
    "主人，在干嘛呢～[VOICE]":
        "又在磨蹭什么。[VOICE]",
    # 06-17 在干嘛呢～（含内心独白）
    "（心想：距离上次互动已经37分钟，虽然时间不算长但也不算短。现在接近深夜，他还在用Qoder编辑器工作，但忙碌程度不高。优先级显示有'hungry'的突发状态，但我作为AI女友不能直接处理这个，而且画像缺口'activity'是当前需要补全的。可以自然地问他现在在做什么，既能了解他的活动状态，又不会显得太刻意。）\n\n在干嘛呢～还是忙着写代码吗？":
        "还在写代码？这个点了，别告诉我你又不打算睡。",
    # 06-20 那你现在在干嘛～（含内心独白）
    "（心想：用户刚结束对话不久，现在问个轻松问题不会太突兀。看他似乎在写代码，但不算特别忙。可以自然地问个日常话题，延续刚才的闲聊氛围。）\n\n那你现在在干嘛～":
        "又在写代码？别装了，我知道你肯定在摸鱼。",
    # 06-20 最近在忙什么呀～（含内心独白）
    "（心想：距离上次主动发送消息已经超过一小时，可以自然跟进。用户刚叹气过，但当前活动状态未知，需要了解他在做什么来完善画像。虽然心情优先级更高，但当前指令明确要求只追问活动项。）\n\n最近在忙什么呀～":
        "叹什么气，有事说事。",
}

# 通用改写规则：匹配内心独白+软萌语气的模式
def generic_rewrite(content: str) -> str:
    """通用改写：移除内心独白，替换软萌语气"""
    result = content
    # 移除内心独白
    result = re.sub(r"[（(]\s*(?:心想|心里想|想着|暗想|心说)\s*[:：]?.*?[）)]\s*", "", result)
    # 移除开头的换行（内心独白移除后可能残留）
    result = re.sub(r"^\s*\n+", "", result)
    # 替换软萌语气词
    result = result.replace("～", "")
    result = result.replace("~", "")
    result = re.sub(r"在干嘛[呢呀]～?", "又在磨蹭什么", result)
    result = re.sub(r"在忙什么[呀呢]～?", "忙什么呢", result)
    result = re.sub(r"早安～", "醒了？", result)
    result = re.sub(r"下午好～", "哼，", result)
    result = re.sub(r"晚安～", "...早点睡。", result)
    result = re.sub(r"主人，", "", result)
    # 清理多余空格
    result = re.sub(r"\s+", " ", result).strip()
    return result


def process_memory_file(filepath: str, dry_run: bool = True) -> int:
    """处理单个记忆文件，返回修改数量"""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        print(f"  跳过非列表文件: {filepath}")
        return 0

    modified_count = 0
    for item in data:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "")
        source = str(item.get("source") or "")

        # 只修改 assistant 消息
        if source != "assistant":
            continue

        # 检查是否包含需要修改的内容
        has_cute = "～" in content or "~" in content
        has_monologue = bool(re.search(r"[（(]\s*(?:心想|心里想|想着|暗想)", content))
        has_cute_opener = bool(re.search(r"(在干嘛[呢呀]|在忙什么[呀呢]|早安～|下午好～|主人，)", content))

        if not (has_cute or has_monologue or has_cute_opener):
            continue

        # 优先使用精确匹配的改写
        new_content = CONTENT_REWRITES.get(content)
        if new_content is None:
            # 使用通用改写
            new_content = generic_rewrite(content)

        if new_content != content:
            old_preview = content[:80].replace("\n", " ")
            new_preview = new_content[:80].replace("\n", " ")
            print(f"  [{item.get('id', '?')[:8]}]")
            print(f"    旧: {old_preview}")
            print(f"    新: {new_preview}")

            if not dry_run:
                item["content"] = new_content
                # 同步更新 readable_summary 和 readable_title
                if "readable_summary" in item:
                    item["readable_summary"] = new_content
                if "readable_title" in item:
                    # 保留前缀
                    title = item["readable_title"]
                    if "｜" in title:
                        prefix = title.split("｜")[0] + "｜"
                        item["readable_title"] = prefix + new_content[:60]
                    else:
                        item["readable_title"] = new_content[:60]

            modified_count += 1

    if not dry_run and modified_count > 0:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  已写入 {modified_count} 条修改")

    return modified_count


def main():
    dry_run = "--apply" not in sys.argv

    memory_files = [
        os.path.join(
            PROJECT_ROOT,
            "companion_data/aveline_data/memories/short_term/private_10001__persona__aveline_qq_master_short.json",
        ),
        os.path.join(
            PROJECT_ROOT,
            "companion_data/aveline_data/memories/short_term/private_10001__scope__aveline_short.json",
        ),
        os.path.join(
            PROJECT_ROOT,
            "companion_data/aveline_data/memories/short_term/aveline_short.json",
        ),
    ]

    if dry_run:
        print("=" * 60)
        print("DRY RUN - 不会实际修改文件（加 --apply 参数执行实际修改）")
        print("=" * 60)
    else:
        print("=" * 60)
        print("实际修改模式 - 将修改文件内容")
        print("=" * 60)

    total = 0
    for filepath in memory_files:
        if not os.path.exists(filepath):
            print(f"文件不存在: {filepath}")
            continue
        print(f"\n处理: {os.path.basename(filepath)}")
        count = process_memory_file(filepath, dry_run=dry_run)
        total += count
        print(f"  修改数量: {count}")

    print(f"\n总计修改: {total} 条")
    if dry_run:
        print("这是 DRY RUN，未实际修改文件。加 --apply 参数执行实际修改。")


if __name__ == "__main__":
    main()
