"""清理互聊消息污染：将主人 conversation 中的 peer_chat 消息迁移到 peer_{role_id} conversation。

问题：之前互聊消息被存到了 private_{master_qq_id}__persona__xxx conversation 中，
和主人的聊天记录混在一起。此脚本将这些消息迁移到独立的 peer_{role_id} conversation，
并从原 conversation 中删除。

用法：python -m tests.diagnostics.active_care_review.migrate_peer_chat_history
"""

import json
import os
import sys

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def find_peer_chat_memories(mm) -> list:
    """从 WeightedMemoryManager 中找出所有 peer_chat 类别的记忆"""
    peer_chat_memories = []
    try:
        all_memories = mm.get_weighted_memories(min_weight=-999, limit=99999)
        for mem in all_memories:
            if mem.get("category") == "peer_chat":
                peer_chat_memories.append(mem)
    except Exception as e:
        print(f"  查找 peer_chat 记忆失败: {e}")
    return peer_chat_memories


def migrate_conversation(conversation_id: str) -> dict:
    """迁移单个 conversation 中的 peer_chat 消息"""
    from memory.weighted_memory_manager import get_weighted_memory_manager

    result = {"conversation_id": conversation_id, "found": 0, "migrated": 0, "deleted": 0, "errors": []}

    mm = get_weighted_memory_manager(conversation_id)
    if not mm:
        result["errors"].append("WeightedMemoryManager 不可用")
        return result

    # 找出所有 peer_chat 消息
    peer_chat_mems = find_peer_chat_memories(mm)
    result["found"] = len(peer_chat_mems)

    if not peer_chat_mems:
        return result

    # 按 role_id 分组
    by_role = {}
    for mem in peer_chat_mems:
        role_id = str(mem.get("metadata", {}).get("peer_speaker", "")).strip()
        # 从 peer_speaker 推断 role_id
        if "澪" in role_id or "aveline" in role_id.lower():
            rid = "aveline"
        elif "玲" in role_id or "ling" in role_id.lower():
            rid = "ling"
        else:
            # 从 conversation_id 推断
            cid_lower = conversation_id.lower()
            if "aveline" in cid_lower:
                rid = "aveline"
            elif "ling" in cid_lower:
                rid = "ling"
            else:
                rid = "unknown"
        by_role.setdefault(rid, []).append(mem)

    # 迁移到 peer_{role_id} conversation
    for role_id, mems in by_role.items():
        if role_id == "unknown":
            result["errors"].append(f"跳过 {len(mems)} 条无法识别 role_id 的消息")
            continue

        peer_conv_id = f"peer_{role_id}"
        peer_mm = get_weighted_memory_manager(peer_conv_id)
        if not peer_mm:
            result["errors"].append(f"无法获取 peer conversation: {peer_conv_id}")
            continue

        for mem in mems:
            try:
                # 添加到 peer conversation
                peer_mm.add_memory(
                    content=mem.get("content", ""),
                    role=mem.get("role", "assistant"),
                    is_important=mem.get("is_important", True),
                    source="peer_chat",
                    category="peer_chat",
                    scopes=mem.get("scopes", ["local", "cloud"]),
                    metadata=mem.get("metadata", {}),
                )
                result["migrated"] += 1

                # 从原 conversation 删除
                mem_id = mem.get("id") or mem.get("memory_id", "")
                if mem_id:
                    mm.delete_memory(mem_id)
                    result["deleted"] += 1
            except Exception as e:
                result["errors"].append(f"迁移失败 (id={mem.get('id', '?')}): {e}")

    return result


def main():
    print("=" * 60)
    print("互聊消息污染清理脚本")
    print("=" * 60)

    # 加载 .env
    try:
        from dotenv import load_dotenv
        env_path = os.path.join(PROJECT_ROOT, ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path)
    except ImportError:
        pass

    # 找出所有可能被污染的 conversation
    # 读取 multi_qq_config.json 获取 persona 信息
    config_path = os.path.join(PROJECT_ROOT, "clients", "bots", "multi_qq_config.json")
    master_qq_id = os.getenv("XIAOYOU_QQ_MASTER_ID", "").strip()

    conversations_to_check = []

    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            multi_cfg = json.load(f)
        for role_id, role_cfg in multi_cfg.items():
            if not isinstance(role_cfg, dict):
                continue
            persona_fn = str(role_cfg.get("persona_filename") or "").strip()
            qq_id = str(role_cfg.get("master_qq_id") or "").strip()
            if not qq_id:
                qq_id = master_qq_id
            if qq_id and persona_fn:
                from clients.bots.qq.utils import build_persona_conversation_id
                cid = build_persona_conversation_id(f"private_{qq_id}", persona_fn)
                conversations_to_check.append(cid)

    if not conversations_to_check:
        print("未找到需要检查的 conversation（可能 multi_qq_config.json 不存在或 master_qq_id 为空）")
        return

    print(f"需要检查的 conversation: {conversations_to_check}")
    print()

    total_found = 0
    total_migrated = 0
    total_deleted = 0

    for cid in conversations_to_check:
        print(f"检查: {cid}")
        result = migrate_conversation(cid)
        total_found += result["found"]
        total_migrated += result["migrated"]
        total_deleted += result["deleted"]
        print(f"  找到 {result['found']} 条 peer_chat 消息")
        print(f"  迁移 {result['migrated']} 条")
        print(f"  删除 {result['deleted']} 条")
        if result["errors"]:
            for err in result["errors"]:
                print(f"  错误: {err}")
        print()

    print("=" * 60)
    print(f"总计: 找到 {total_found} 条, 迁移 {total_migrated} 条, 删除 {total_deleted} 条")
    if total_found == 0:
        print("没有需要清理的污染数据。")
    elif total_migrated == total_found:
        print("所有污染数据已成功迁移！")
    else:
        print(f"注意: 有 {total_found - total_migrated} 条未能迁移，请检查错误信息。")
    print("=" * 60)


if __name__ == "__main__":
    main()
