"""验证 QQ Official scope 修复效果"""
import sys
from pathlib import Path

# 让项目根目录可被导入
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.utils.data_paths import (
    resolve_data_scope_from_conversation_id,
    resolve_memory_user_id,
    get_role_data_dir,
    get_role_chat_history_dir,
    get_role_memories_dir,
    normalize_data_scope,
)


def check(name: str, actual: str, expected: str) -> bool:
    ok = actual == expected
    flag = "[OK]" if ok else "[FAIL]"
    print(f"  {flag} {name}: actual={actual!r}, expected={expected!r}")
    return ok


def main() -> int:
    print("=== 1. resolve_data_scope_from_conversation_id ===")
    cases = [
        # 旧 cid
        ("private_B78B23BF9C7F51857AEB19891AE32C1D__persona__qq_official_1", "xiaolu"),
        ("private_B78B23BF9C7F51857AEB19891AE32C1D__persona__qq_official_2", "yeye"),
        # 新 cid（persona 改名后）
        ("private_B78B23BF9C7F51857AEB19891AE32C1D__persona__Xiaolu", "xiaolu"),
        ("private_B78B23BF9C7F51857AEB19891AE32C1D__persona__Yeye", "yeye"),
        # scope 格式（memory_user_id）
        ("private_B78B23BF9C7F51857AEB19891AE32C1D__scope__xiaolu", "xiaolu"),
        ("private_B78B23BF9C7F51857AEB19891AE32C1D__scope__yeye", "yeye"),
        # peer 前缀（dual_role）
        ("peer_private_B78B23BF9C7F51857AEB19891AE32C1D__persona__qq_official_1", "dual_role"),
        ("peer_private_B78B23BF9C7F51857AEB19891AE32C1D__persona__qq_official_2", "dual_role"),
        # 原有 Aveline/Ling 不受影响
        ("private_10001__persona__aveline_qq_master", "aveline"),
        ("private_10001__persona__ling_qq_master", "ling"),
        ("private_10001__persona__core_aveline", "aveline"),
        ("private_10001__persona__core_ling", "ling"),
        # 默认 cid（无 persona）
        ("default_user", "user"),
    ]
    all_ok = True
    for cid, expected in cases:
        actual = resolve_data_scope_from_conversation_id(cid)
        all_ok = check(f"cid={cid!r}", actual, expected) and all_ok

    print("\n=== 2. resolve_memory_user_id ===")
    cases2 = [
        ("private_B78B23BF9C7F51857AEB19891AE32C1D__persona__qq_official_2",
         "private_B78B23BF9C7F51857AEB19891AE32C1D__scope__yeye"),
        ("private_B78B23BF9C7F51857AEB19891AE32C1D__persona__Yeye",
         "private_B78B23BF9C7F51857AEB19891AE32C1D__scope__yeye"),
        ("private_B78B23BF9C7F51857AEB19891AE32C1D__persona__qq_official_1",
         "private_B78B23BF9C7F51857AEB19891AE32C1D__scope__xiaolu"),
        # Aveline/Ling 不受影响
        ("private_10001__persona__aveline_qq_master",
         "private_10001__scope__aveline"),
        ("private_10001__persona__ling_qq_master",
         "private_10001__scope__ling"),
    ]
    for cid, expected in cases2:
        actual = resolve_memory_user_id(cid)
        all_ok = check(f"cid={cid!r}", actual, expected) and all_ok

    print("\n=== 3. normalize_data_scope ===")
    cases3 = [
        ("xiaolu", "xiaolu"),
        ("yeye", "yeye"),
        ("XIAOLU", "xiaolu"),
        ("YEye", "yeye"),
        ("aveline", "aveline"),
        ("ling", "ling"),
        ("unknown", "user"),  # 未知值走 default
    ]
    for value, expected in cases3:
        actual = normalize_data_scope(value, default="user")
        all_ok = check(f"scope={value!r}", actual, expected) and all_ok

    print("\n=== 4. 路径解析 ===")
    cases4 = [
        ("yeye", "yeye_data"),
        ("xiaolu", "xiaolu_data"),
        ("aveline", "aveline_data"),
        ("ling", "ling_data"),
        ("user", "user_data"),
    ]
    for scope, dirname in cases4:
        data_dir = get_role_data_dir(scope)
        expected = Path("companion_data") / dirname
        actual = data_dir.parts[-2:]
        ok = tuple(actual) == ("companion_data", dirname)
        flag = "[OK]" if ok else "[FAIL]"
        print(f"  {flag} scope={scope!r}: {data_dir}")
        all_ok = ok and all_ok

        chat_dir = get_role_chat_history_dir(scope)
        expected_chat = expected / "chat_history"
        ok_chat = chat_dir.parts[-3:] == ("companion_data", dirname, "chat_history")
        flag = "[OK]" if ok_chat else "[FAIL]"
        print(f"  {flag} chat_history: {chat_dir}")
        all_ok = ok_chat and all_ok

        mem_dir = get_role_memories_dir(scope)
        expected_mem = expected / "memories"
        ok_mem = mem_dir.parts[-3:] == ("companion_data", dirname, "memories")
        flag = "[OK]" if ok_mem else "[FAIL]"
        print(f"  {flag} memories: {mem_dir}")
        all_ok = ok_mem and all_ok

    print(f"\n=== 总结: {'全部通过' if all_ok else '存在失败'} ===")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
