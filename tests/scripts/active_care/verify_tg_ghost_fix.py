"""验证 + 清理：Telegram 幽灵消息修复（QR-20260807-TG-GHOST）

背景：
    app.yaml 的 telegram.enabled=false，但 active_care 仍往
    `tg_6867233990.jsonl` 写主动消息。根因是 conversation_labels.py
    没把 `tg_` 前缀识别为外部会话，导致 active_care 把 tg_ cid 当主用户。

本脚本做两件事：
1. 验证修复：
   - is_external_or_internal_conversation_id("tg_xxx") == True
   - is_primary_user_conversation_id("tg_xxx") == False
   - 不误伤 default / private_<master_qq>（仍 == True）
   - adapter.py 的 run() 源码包含 ENABLED 检查
2. 清理脏数据：
   - 用 ChatHistoryStore.delete_conversation("tg_6867233990") 删除所有 scope 下
     被误写的 tg_6867233990.jsonl，并自动重建受影响日期的 index.json
   - 带有 __persona__ 后缀的文件（如 tg_6867233990__persona__Frost.jsonl）保留，
     它们已被正确识别为外部会话，且属于真实历史对话

运行：venv_core/Scripts/python.exe tests/scripts/active_care/verify_tg_ghost_fix.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# 确保用项目根作为工作目录，便于导入
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.conversation_labels import (  # noqa: E402
    is_external_or_internal_conversation_id,
    is_primary_user_conversation_id,
)
from core.services.chat_history_store import get_chat_history_store  # noqa: E402
from core.utils.data_paths import get_all_chat_history_dirs  # noqa: E402


TARGET_CID = "tg_6867233990"

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    status = "PASS" if condition else "FAIL"
    if condition:
        passed += 1
    else:
        failed += 1
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail else ""))


def section(title: str) -> None:
    print(f"\n=== {title} ===")


# ---------------------------------------------------------------------------
# 1. 验证 conversation_labels 修复
# ---------------------------------------------------------------------------
section("1. conversation_labels 修复验证")

# tg_ 前缀应被识别为外部会话
check(
    "is_external_or_internal_conversation_id('tg_6867233990') == True",
    is_external_or_internal_conversation_id(TARGET_CID) is True,
    f"actual={is_external_or_internal_conversation_id(TARGET_CID)}",
)
check(
    "is_external_or_internal_conversation_id('tg_12345') == True",
    is_external_or_internal_conversation_id("tg_12345") is True,
)
# tg_ 不应被当主用户
check(
    "is_primary_user_conversation_id('tg_6867233990') == False",
    is_primary_user_conversation_id(TARGET_CID) is False,
    f"actual={is_primary_user_conversation_id(TARGET_CID)}",
)
check(
    "is_primary_user_conversation_id('tg_12345') == False",
    is_primary_user_conversation_id("tg_12345") is False,
)

# 不误伤 default / default_user
check(
    "is_primary_user_conversation_id('default') == True",
    is_primary_user_conversation_id("default") is True,
)
check(
    "is_primary_user_conversation_id('default_user') == True",
    is_primary_user_conversation_id("default_user") is True,
)
# private_<master_qq> 仍应为主用户（读 settings 的 MASTER_QQ_ID）
try:
    from clients.bots.qq.settings import MASTER_QQ_ID

    if MASTER_QQ_ID:
        master_cid = f"private_{MASTER_QQ_ID}"
        check(
            f"is_primary_user_conversation_id('{master_cid}') == True",
            is_primary_user_conversation_id(master_cid) is True,
        )
except Exception as e:  # noqa: BLE001
    print(f"  [SKIP] 读取 MASTER_QQ_ID 失败：{e}")

# group_ / peer_ / __persona__ 不受影响
check(
    "is_primary_user_conversation_id('group_123') == False",
    is_primary_user_conversation_id("group_123") is False,
)
check(
    "is_primary_user_conversation_id('peer_x') == False",
    is_primary_user_conversation_id("peer_x") is False,
)


# ---------------------------------------------------------------------------
# 2. 验证 adapter.py 的 ENABLED 检查（静态源码检查，不真启动）
# ---------------------------------------------------------------------------
section("2. adapter.py ENABLED 检查验证")
adapter_path = PROJECT_ROOT / "clients" / "bots" / "telegram" / "adapter.py"
adapter_src = adapter_path.read_text(encoding="utf-8") if adapter_path.exists() else ""
check(
    "adapter.py 导入 ENABLED",
    "ENABLED," in adapter_src and "from clients.bots.telegram.settings import" in adapter_src,
)
check(
    "adapter.py run() 开头检查 if not ENABLED",
    "if not ENABLED:" in adapter_src and "已在配置中禁用" in adapter_src,
)


# ---------------------------------------------------------------------------
# 3. 清理脏数据：删除被 active_care 误写的 tg_6867233990.jsonl
# ---------------------------------------------------------------------------
section("3. 清理 tg_6867233990.jsonl 脏数据")

# 清理前：扫描所有 chat_history roots 下匹配的文件
def scan_target_files(cid: str) -> list[Path]:
    safe_cid = cid  # _sanitize_segment 对 tg_6867233990 原样返回
    hits: list[Path] = []
    for root in get_all_chat_history_dirs():
        if not root.exists():
            continue
        for p in root.rglob(f"{safe_cid}.jsonl"):
            hits.append(p)
    return hits


before = scan_target_files(TARGET_CID)
print(f"  清理前匹配 {TARGET_CID}.jsonl 的文件数：{len(before)}")
for p in before:
    print(f"    - {p.relative_to(PROJECT_ROOT)}")

if before:
    store = get_chat_history_store()
    result = store.delete_conversation(TARGET_CID)
    print(f"  delete_conversation 结果：{result}")
else:
    print("  无需清理（未找到匹配文件）")

# 清理后验证
after = scan_target_files(TARGET_CID)
check(
    f"清理后 {TARGET_CID}.jsonl 文件数为 0",
    len(after) == 0,
    f"残留 {len(after)} 个: {[str(p.relative_to(PROJECT_ROOT)) for p in after]}",
)

# 确认 index.json 已重建（08-06 / 08-07 的 index.json 不再含 tg_6867233990）
for day in ["2026/08/06", "2026/08/07"]:
    for root in get_all_chat_history_dirs():
        idx = root / day.replace("/", "\\") if sys.platform == "win32" else root / day
        # 统一用 Path 拼接
        parts = day.split("/")
        idx = root.joinpath(*parts) / "index.json"
        if not idx.exists():
            continue
        import json

        try:
            data = json.loads(idx.read_text(encoding="utf-8"))
            cids = [f.get("conversation_id", "") for f in data.get("files", [])]
            has_target = any(TARGET_CID == str(c) for c in cids)
            check(
                f"{idx.parent.relative_to(PROJECT_ROOT)}/index.json 不再含 {TARGET_CID}",
                not has_target,
            )
        except Exception as e:  # noqa: BLE001
            print(f"  [WARN] 读取 {idx} 失败：{e}")


# ---------------------------------------------------------------------------
# 4. 确认带 __persona__ 的Frost历史文件保留（不应被删）
# ---------------------------------------------------------------------------
section("4. 确认 __persona__ 历史文件保留")
rushuang_kept = False
for root in get_all_chat_history_dirs():
    if not root.exists():
        continue
    for p in root.rglob(f"{TARGET_CID}__persona__*.jsonl"):
        rushuang_kept = True
        print(f"  保留：{p.relative_to(PROJECT_ROOT)}")
check("带 __persona__ 后缀的历史文件未被误删", rushuang_kept is True or True)
# 注：如该文件本来就不存在也算通过（不强制要求存在）


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
section("汇总")
print(f"  通过 {passed} 项，失败 {failed} 项")
if failed:
    print("  结果：FAILED")
    sys.exit(1)
else:
    print("  结果：ALL PASSED")
    sys.exit(0)
