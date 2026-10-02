# -*- coding: utf-8 -*-
"""验证 RAG 检索精准度修复效果

背景：搜"初中女生"搜不到、搜"初二"能搜到。根因：
1. chat_history 查询按空格切分，中文整串子串匹配
2. extract_keywords 伪分词（正则整串+bigram）
3. 主存储落盘时 pop embedding，重启后向量检索失效
4. RAG 向量阈值兜底值 0.72 过严

本脚本逐项验证修复：
1. _tokenize_query 分词后"初中女生"能匹配"初二的女生"原文
2. extract_keywords 索引/查询词面可相交
3. compact_weighted_memory_record(keep_embedding=True) 保留向量
"""
import sys
import tempfile
from pathlib import Path

# 项目根目录加入 sys.path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    status = "PASS" if ok else "FAIL"
    if ok:
        PASS += 1
    else:
        FAIL += 1
    print(f"[{status}] {name}" + (f" | {detail}" if detail else ""))


def test_chat_history_tokenizer():
    """验证1：聊天记录查询分词"""
    from core.services.chat_history_store import _tokenize_query

    tokens = _tokenize_query("初中女生")
    check("分词包含『初中』", "初中" in tokens, f"tokens={tokens}")
    check("分词包含『女生』", "女生" in tokens, f"tokens={tokens}")
    check("保留整串兜底", "初中女生" in tokens, f"tokens={tokens}")

    # 单字过滤
    tokens2 = _tokenize_query("初二")
    check("短查询保留有效词", "初二" in tokens2, f"tokens={tokens2}")


def test_chat_history_search():
    """验证2：分词后中文近义查询能命中聊天原文"""
    from core.services.chat_history_store import ChatHistoryStore

    with tempfile.TemporaryDirectory() as tmp:
        store = ChatHistoryStore(base_dir=Path(tmp))
        store.append_event(
            conversation_id="verify_rag",
            role="user",
            content="那个初二的女生今天又叫我嘉豪，无语",
            message_id="msg_1",
        )
        store.append_event(
            conversation_id="verify_rag",
            role="user",
            content="今天天气不错，出去骑车了",
            message_id="msg_2",
        )

        # 修复前：整串"初中女生"匹配不到"初二的女生" → 空结果
        results = store.list_conversation_events(
            conversation_id="verify_rag", query="初中女生"
        )
        hit = any("初二" in (r.get("content") or "") for r in results)
        check("搜『初中女生』命中初二女生记录", hit, f"返回{len(results)}条")

        # 原有能力不回退：精确短语仍可命中
        results2 = store.list_conversation_events(
            conversation_id="verify_rag", query="初二"
        )
        hit2 = any("初二" in (r.get("content") or "") for r in results2)
        check("搜『初二』仍命中", hit2, f"返回{len(results2)}条")

        # 不相关查询不误伤（OR 语义下"骑车"token 只命中原含词记录）
        results3 = store.list_conversation_events(
            conversation_id="verify_rag", query="开车去上班"
        )
        hit3 = any("初二" in (r.get("content") or "") for r in results3)
        check("无关查询不误命中初二记录", not hit3, f"返回{len(results3)}条")


def test_extract_keywords():
    """验证3：关键词提取的索引/查询词面相交"""
    from memory.core.utils import extract_keywords

    q_kws = extract_keywords("初中女生")
    mem_kws = extract_keywords("她是初二女生")
    inter = q_kws & mem_kws
    check("『初中女生』与『初二女生』词面相交", bool(inter), f"交集={sorted(inter)}")

    q2 = extract_keywords("初二")
    mem2 = extract_keywords("那个初二的小鬼又叫我嘉豪")
    inter2 = q2 & mem2
    check("『初二』与『初二的小鬼』词面相交", bool(inter2), f"交集={sorted(inter2)}")

    # 英文/数字保持可用
    en = extract_keywords("用Python 3.12写了脚本")
    check("英文关键词仍提取", any("python" in k for k in en), f"kw={sorted(en)}")


def test_compact_keep_embedding():
    """验证4：主存储落盘保留 embedding"""
    from memory.core.readable_ops import compact_weighted_memory_record

    class FakeManager:
        def _normalize_memory_record(self, memory):
            return memory, False

    mgr = FakeManager()
    memory = {
        "id": "m1",
        "content": "她是初二女生",
        "category": "daily",
        "metadata": {"event_ref": {"event_id": "e1", "relative_path": "x.jsonl"}},
        "embedding": "QUJD",  # 模拟 base64 向量
    }

    kept = compact_weighted_memory_record(mgr, dict(memory), keep_embedding=True)
    check(
        "keep_embedding=True 保留向量",
        kept.get("embedding") == "QUJD",
        f"embedding={kept.get('embedding')!r}",
    )
    check(
        "keep_embedding=True 仍清空冗余 content(event_ref 型)",
        kept.get("content") == "",
        f"content={kept.get('content')!r}",
    )

    dropped = compact_weighted_memory_record(mgr, dict(memory))
    check(
        "默认(可读镜像)仍丢弃向量",
        "embedding" not in dropped,
        "镜像瘦身行为不变",
    )


def main():
    print("=" * 64)
    print("RAG 精准度修复验证")
    print("=" * 64)
    test_chat_history_tokenizer()
    print("-" * 64)
    test_chat_history_search()
    print("-" * 64)
    test_extract_keywords()
    print("-" * 64)
    test_compact_keep_embedding()
    print("=" * 64)
    print(f"结果: {PASS} 通过, {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
