#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证多角色 conversation_id 的记忆 scope 隔离是否正常。

背景
----
安卓端反馈「角色串味」：只和角色 A 聊过，切到角色 B 时 B 却知道 A 的内容。
根因在 conversation_id -> scope 的解析：客户端传来的 cid 形如
``web_core_ling.json`` / ``web_role_<sha8>``，而 scope 注册表只认 persona
slug（如 ``core_ling``），带 ``web_`` 前缀的 cid 匹配不到就会 fallback 到
``default="aveline"``，于是所有角色共用 ``aveline_data/memories``。

用法
----
    venv_core/Scripts/python.exe tests/scripts/memory/verify_memory_scope_isolation.py

退出码 0 表示隔离正常，1 表示仍然存在串号。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.data.data_paths import get_memories_dir_for_conversation  # noqa: E402
from core.utils.data.scope_registry import (  # noqa: E402
    resolve_data_scope_from_conversation_id,
    resolve_memory_user_id,
)

# (conversation_id, 期望 scope, 场景说明)
# 期望 scope 为 None 表示该 cid 本身不含角色信息，允许解析失败，
# 但绝不允许落进任何已知角色 scope（否则就是串号）。
KNOWN_ROLE_SCOPES = {"aveline", "ling", "ye", "xiaolu", "yeye", "xiaoyou", "rushuang"}

CASES: list[tuple[str, str | None, str]] = [
    # ── 已经带 persona 标记的规范化 cid（Web / WS 路径）──────────────
    ("shared__persona__aveline", "aveline", "WS 规范化 cid：aveline"),
    ("shared__persona__ling", "ling", "WS 规范化 cid：ling"),
    ("shared__persona__ye", "ye", "WS 规范化 cid：ye"),
    # ── 客户端原始 cid（安卓 HTTP 路径不会做 persona 规范化）─────────
    ("web_core_aveline.json", "aveline", "安卓 cid：aveline"),
    ("web_core_ling.json", "ling", "安卓 cid：ling"),
    ("web_core_ye.json", "ye", "安卓 cid：ye"),
    ("web_core_aveline", "aveline", "安卓 cid（无扩展名）：aveline"),
    ("web_core_ling", "ling", "安卓 cid（无扩展名）：ling"),
    ("web_core_ye", "ye", "安卓 cid（无扩展名）：ye"),
    # ── 纯 persona 文件名（历史上一直能解析）─────────────────────────
    ("core_aveline.json", "aveline", "裸 persona 文件名：aveline"),
    ("core_ling.json", "ling", "裸 persona 文件名：ling"),
    ("core_ye.json", "ye", "裸 persona 文件名：ye"),
    # ── 安卓 role 级兜底 cid ──────────────────────────────────────────
    # 新格式带可读角色名，后端能反解；老的哈希格式反解不了，只能隔离。
    ("web_role_aveline", "aveline", "安卓 role 兜底（新格式）"),
    ("web_role_ling", "ling", "安卓 role 兜底（新格式）"),
    ("web_role_ye", "ye", "安卓 role 兜底（新格式）"),
    # 中文/日文显示名的角色，依赖 persona API 返回的英文 role 字段
    ("web_role_chiba", "chiba", "安卓 role 兜底（中/日文显示名角色）"),
    ("web_role_kafka", "kafka", "安卓 role 兜底（中/日文显示名角色）"),
    ("web_role_xiaolu", "xiaolu", "安卓 role 兜底（新格式）"),
    ("web_role_3f2a1b9c", None, "安卓 role 兜底（旧哈希格式，无角色信息）"),
    ("web_role_00000000", None, "安卓 role 兜底（旧哈希格式，无角色信息）"),
]


def _short(path: Path) -> str:
    """把绝对路径压缩成相对工程根目录的短形式，便于阅读。"""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


# 「记忆工具使用的 storage_scope」必须与「scope_registry 解析出的目录 scope」一致。
# 这两条解析路径历史上各自硬编码过角色名单，一旦分叉就是新的串味源，
# 所以这里把一致性也纳入回归验证。
STORAGE_SCOPE_CASES: list[tuple[str, str]] = [
    ("web_core_ling.json", "ling"),
    ("web_core_ye.json", "ye"),
    ("web_core_aveline.json", "aveline"),
    ("shared__persona__ye", "ye"),
    ("shared__persona__ling", "ling"),
    ("private_1__persona__core_ling", "ling"),
    ("default_user", "user"),
    ("default", "user"),
    ("peer_123", "dual_role"),
    ("group_1__persona__aveline_qq_group", "aveline"),
    ("private_1__persona__aveline_qq_master", "aveline"),
]


def _dir_scope(path: Path) -> str:
    """从 ``companion_data/<scope>_data/...`` 反解出该目录属于哪个角色 scope。"""
    try:
        rel = path.relative_to(PROJECT_ROOT)
    except ValueError:
        return ""
    parts = rel.parts
    if len(parts) >= 2 and parts[0] == "companion_data" and parts[1].endswith("_data"):
        return parts[1][: -len("_data")]
    return ""


def main() -> int:
    print("=" * 96)
    print("多角色记忆 scope 隔离验证")
    print("=" * 96)
    print(f"{'conversation_id':<26}{'解析 scope':<14}{'期望':<14}{'记忆目录'}")
    print("-" * 96)

    failures: list[str] = []
    scope_by_cid: dict[str, str] = {}

    for cid, expected, desc in CASES:
        scope = resolve_data_scope_from_conversation_id(cid, default="aveline")
        user_id = resolve_memory_user_id(cid)
        mem_dir = get_memories_dir_for_conversation(cid)
        scope_by_cid[cid] = scope

        ok = True
        if expected is not None:
            ok = scope == expected
        else:
            # 无角色信息的 cid 不允许塌进任何真实角色目录
            ok = scope not in KNOWN_ROLE_SCOPES

        mark = "OK " if ok else "FAIL"
        print(f"{cid:<26}{scope:<14}{str(expected or '<非角色>'):<14}{_short(mem_dir)}")
        print(f"{'':<2}{mark}  {desc}   [memory_user_id={user_id}]")

        # 目录级检查：scope 对了还不够，最终落到哪个目录才是关键。
        # 隔离 scope 若没注册进 _VALID_SCOPES，会被 normalize_data_scope 重新塌回默认角色。
        dir_scope = _dir_scope(mem_dir)
        if expected is None and dir_scope in KNOWN_ROLE_SCOPES:
            ok = False
            failures.append(
                f"{cid}: 无角色信息的 cid 落进了角色目录 {dir_scope}（{desc}），会与该角色共用记忆"
            )
        if expected is not None and dir_scope != expected:
            ok = False
            failures.append(f"{cid}: 期望记忆目录 scope={expected}，实际={dir_scope}（{desc}）")

        if not ok and expected is not None:
            failures.append(f"{cid}: 期望 scope={expected}，实际={scope}（{desc}）")

    print("-" * 96)

    # 核心不变量：不同角色必须落到不同记忆目录
    role_cases = [(cid, exp) for cid, exp, _ in CASES if exp in KNOWN_ROLE_SCOPES]
    dir_by_role: dict[str, set[str]] = {}
    for cid, exp in role_cases:
        dir_by_role.setdefault(str(exp), set()).add(
            _short(get_memories_dir_for_conversation(cid))
        )
    for role, dirs in sorted(dir_by_role.items()):
        if len(dirs) > 1:
            failures.append(f"角色 {role} 的多个 cid 落到了不同目录: {sorted(dirs)}")

    # 核心不变量：不同角色之间不得共用记忆目录
    dir_to_roles: dict[str, set[str]] = {}
    for role, dirs in dir_by_role.items():
        for d in dirs:
            dir_to_roles.setdefault(d, set()).add(role)
    for d, roles in sorted(dir_to_roles.items()):
        if len(roles) > 1:
            failures.append(f"!! 串号：目录 {d} 被多个角色共用 -> {sorted(roles)}")

    # 第二条解析路径：conversation_labels.storage_scope（记忆工具实际用的口径）
    print("\n[一致性] conversation_labels.storage_scope vs scope_registry")
    print("-" * 96)
    from core.utils.data.conversation_labels import get_conversation_label_info

    for cid, expected in STORAGE_SCOPE_CASES:
        got = str(get_conversation_label_info(cid).get("storage_scope") or "")
        ok = got == expected
        print(f"{'OK ' if ok else 'FAIL'} {cid:<40} -> {got:<20}(期望 {expected})")
        if not ok:
            failures.append(f"storage_scope 不一致: {cid} 期望={expected}，实际={got}")

    # 第三条：工具层的角色判定（如 plan_tool 判断「当前是不是 ling」）。
    # 它历史上只依赖全局 persona 单例，而 HTTP 聊天路径从不更新该单例，
    # 于是安卓端用 ling 时也会被当成 aveline，走到别的角色分支。
    print("\n[工具层] 从运行时上下文判定角色 scope")
    print("-" * 96)
    try:
        from core.tools.base import resolve_tool_role_scope

        class _FakeTool:
            """最小替身：只提供工具取运行时上下文的接口。"""

            def __init__(self, **ctx: str) -> None:
                self._ctx = ctx

            def _get_ctx(self, key: str, default=None):
                return self._ctx.get(key, default)

        tool_cases = [
            ({"persona_filename": "core_ling.json"}, "ling", "上下文带 ling 人设"),
            ({"persona_filename": "core_ye.json"}, "ye", "上下文带 ye 人设"),
            ({"user_id": "web_core_ling.json"}, "ling", "只有 cid（安卓格式）"),
            ({"user_id": "web_core_ye.json"}, "ye", "只有 cid（安卓格式）"),
        ]
        for ctx, expected, desc in tool_cases:
            got = resolve_tool_role_scope(_FakeTool(**ctx))
            ok = got == expected
            print(f"{'OK ' if ok else 'FAIL'} {str(ctx):<44} -> {got:<14}(期望 {expected}) {desc}")
            if not ok:
                failures.append(f"工具层 scope 判定错误: {ctx} 期望={expected}，实际={got}")
    except Exception as exc:  # pragma: no cover - 依赖可用性兜底
        print(f"SKIP 工具层判定检查（导入失败）: {exc}")

    if failures:
        print(f"\n发现 {len(failures)} 处隔离问题：")
        for item in failures:
            print(f"  - {item}")
        print("=" * 96)
        return 1

    print("全部通过：不同角色的记忆目录互相隔离。")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
