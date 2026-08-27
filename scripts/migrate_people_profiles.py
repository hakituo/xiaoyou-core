#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人物档案迁移脚本

把 core_aveline.json 和 core_ling.json 里硬编码的人设信息迁移到
companion_data 下的结构化档案文件。

迁移产物：
1. user_data/person_profile.json          — Master的自身档案
2. user_data/people_profiles/wang_ling.json — Master视角下的Ling
3. user_data/people_profiles/aveline.json   — Master视角下的 Aveline
4. aveline_data/persona_data/profiles/Aveline_Qi.json      — Aveline 面对Master
5. aveline_data/persona_data/profiles/Aveline_Ling.json    — Aveline 面对Ling
6. aveline_data/persona_data/profiles/Aveline_default.json — Aveline 默认兜底
7. ling_data/persona_data/profiles/Ling_Qi.json            — Ling面对Master
8. ling_data/persona_data/profiles/Ling_Aveline.json       — Ling面对 Aveline
9. ling_data/persona_data/profiles/Ling_default.json       — Ling默认兜底

用法：
    venv_core/Scripts/python.exe scripts/migrate_people_profiles.py           # 迁移
    venv_core/Scripts/python.exe scripts/migrate_people_profiles.py --dry-run # 预览
    venv_core/Scripts/python.exe scripts/migrate_people_profiles.py --force    # 覆盖已有
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.character.people.models import PersonProfile, ProfileTarget, ProfileType
from core.utils.data_paths import (
    get_role_profile_path,
    get_user_people_profile_path,
    get_user_person_profile_path,
)
from core.utils.time_utils import get_current_time


def load_persona_json(filename: str) -> Dict[str, Any]:
    """加载人设 JSON 配置文件"""
    path = PROJECT_ROOT / "core" / "character" / "configs" / filename
    if not path.exists():
        print(f"[WARN] 人设文件不存在: {path}")
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def now_str() -> str:
    return get_current_time().strftime("%Y-%m-%d %H:%M:%S")


# ========== 迁移函数 ==========

def build_user_self_profile(
    aveline_json: Dict[str, Any],
    ling_json: Dict[str, Any],
) -> PersonProfile:
    """
    构建用户自身档案（Master）

    合并 core_aveline.json 和 core_ling.json 中 relationship 下的用户信息。
    注意：relationship.user 是字符串（用户名），其他字段（birth_date/tall/role/description）
    直接挂在 relationship 下。
    """
    aveline_identity = aveline_json.get("identity") or {}
    aveline_rel = aveline_identity.get("relationship") or {}

    ling_identity = ling_json.get("identity") or {}
    ling_rel = ling_identity.get("relationship") or {}

    # relationship.user 是用户名字符串
    name = str(aveline_rel.get("user") or ling_rel.get("user") or "Master").strip()
    description = str(aveline_rel.get("description") or ling_rel.get("description") or "").strip()

    core_fields: Dict[str, Any] = {}
    for key in ("birth_date", "tall", "role"):
        val = aveline_rel.get(key) or ling_rel.get(key)
        if val:
            core_fields[key] = val

    # 补充Ling视角下的关系描述（如果有差异）
    ling_desc = str(ling_rel.get("description") or "").strip()
    if ling_desc and ling_desc != description:
        core_fields["alt_description_from_ling"] = ling_desc

    return PersonProfile(
        profile_id="_self",
        profile_type=ProfileType.SELF,
        name=name,
        aliases=["Master", "Creator"],
        core_fields=core_fields,
        description=description,
        detailed={},
        source="seeded_from_persona",
        first_mentioned=now_str(),
        last_mentioned=now_str(),
        mention_count=0,
        updated_at=now_str(),
    )


def build_person_profile_wang_ling(aveline_json: Dict[str, Any]) -> PersonProfile:
    """
    构建Master视角下的Ling档案

    来源：core_aveline.json 的 relationship.sibling（Aveline 视角下的Ling）
    """
    identity = aveline_json.get("identity") or {}
    rel = identity.get("relationship") or {}
    sibling = rel.get("sibling") or {}

    name = str(sibling.get("name") or "Ling").strip()
    role = str(sibling.get("role") or "").strip()
    desc = str(sibling.get("description") or "").strip()

    core_fields: Dict[str, Any] = {}
    if role:
        core_fields["role"] = role
    core_fields["relation_to_user"] = "室友/妹妹"

    return PersonProfile(
        profile_id="wang_ling",
        profile_type=ProfileType.PERSON,
        name=name,
        aliases=["玲", "小玲", "Ling"],
        core_fields=core_fields,
        description=desc,
        detailed={},
        source="seeded_from_persona",
        first_mentioned=now_str(),
        last_mentioned=now_str(),
        mention_count=0,
        updated_at=now_str(),
    )


def build_person_profile_aveline(aveline_json: Dict[str, Any]) -> PersonProfile:
    """
    构建Master视角下的 Aveline 档案

    来源：core_aveline.json 的 identity（Aveline 的客观信息）
    """
    identity = aveline_json.get("identity") or {}
    name = str(identity.get("cn_name") or identity.get("name") or "七濑 澪").strip()
    cn_name = str(identity.get("cn_name") or "").strip()
    birth_date = str(identity.get("birth_date") or "").strip()
    context = str(identity.get("context") or "").strip()

    core_fields: Dict[str, Any] = {}
    if cn_name:
        core_fields["cn_name"] = cn_name
    if birth_date:
        core_fields["birth_date"] = birth_date
    core_fields["role"] = "companion"

    return PersonProfile(
        profile_id="aveline",
        profile_type=ProfileType.PERSON,
        name=name,
        aliases=["澪", "Aveline", "澪姐", "七濑澪"],
        core_fields=core_fields,
        description=context,
        detailed={},
        source="seeded_from_persona",
        first_mentioned=now_str(),
        last_mentioned=now_str(),
        mention_count=0,
        updated_at=now_str(),
    )


def build_role_profile(
    scope: str,
    role_name: str,
    target: ProfileTarget,
    persona_json: Dict[str, Any],
    *,
    description_override: str = "",
    core_fields_override: Dict[str, Any] = None,
) -> PersonProfile:
    """
    构建角色多版本人设档案

    Args:
        scope: 角色域（aveline/ling）
        role_name: 角色名（Aveline/Ling）
        target: 面向对象
        persona_json: 源人设 JSON
        description_override: 覆盖描述（用于从 sibling 提取的版本）
        core_fields_override: 覆盖核心字段
    """
    identity = persona_json.get("identity") or {}
    name = str(identity.get("cn_name") or identity.get("name") or role_name).strip()
    cn_name = str(identity.get("cn_name") or "").strip()
    birth_date = str(identity.get("birth_date") or "").strip()
    context = str(identity.get("context") or "").strip()

    core_fields: Dict[str, Any] = {}
    if cn_name:
        core_fields["cn_name"] = cn_name
    if birth_date:
        core_fields["birth_date"] = birth_date
    if core_fields_override:
        core_fields.update(core_fields_override)

    description = description_override or context

    detailed: Dict[str, Any] = {}
    # 所有版本都应该携带 personality/language_style/interaction_logic
    for key in ("personality", "language_style", "interaction_logic", "epistemic_policy"):
        val = persona_json.get(key)
        if val is None:
            # interaction_logic 可能在顶层
            if key == "epistemic_policy":
                interaction = persona_json.get("interaction_logic") or {}
                val = interaction.get("epistemic_policy")
        if val:
            detailed[key] = val

    return PersonProfile(
        profile_id=f"{role_name}_{target.value}",
        profile_type=ProfileType.ROLE,
        name=name,
        aliases=[],
        role_scope=scope,
        target=target,
        core_fields=core_fields,
        description=description,
        detailed=detailed,
        source="seeded_from_persona",
        first_mentioned=now_str(),
        last_mentioned=now_str(),
        mention_count=0,
        updated_at=now_str(),
    )


# ========== 主迁移逻辑 ==========

def run_migration(*, dry_run: bool = False, force: bool = False) -> None:
    """执行迁移"""
    print("=" * 60)
    print("人物档案迁移脚本")
    print(f"模式: {'预览' if dry_run else '执行'}{' (强制覆盖)' if force else ''}")
    print("=" * 60)

    # 加载源人设 JSON
    aveline_json = load_persona_json("core_aveline.json")
    ling_json = load_persona_json("core_ling.json")

    if not aveline_json and not ling_json:
        print("[ERROR] 未找到任何人设 JSON，终止迁移")
        return

    # 构建所有档案
    profiles_to_migrate: list[tuple[PersonProfile, Path]] = []

    # 1. 用户自身档案
    user_self = build_user_self_profile(aveline_json, ling_json)
    profiles_to_migrate.append((user_self, get_user_person_profile_path()))

    # 2. Master视角下的人物档案
    wang_ling_profile = build_person_profile_wang_ling(aveline_json)
    profiles_to_migrate.append((wang_ling_profile, get_user_people_profile_path("wang_ling")))

    aveline_person_profile = build_person_profile_aveline(aveline_json)
    profiles_to_migrate.append((aveline_person_profile, get_user_people_profile_path("aveline")))

    # 3. Aveline 多版本人设
    # Aveline_Qi: 从 core_aveline.json 完整迁移
    aveline_qi = build_role_profile("aveline", "Aveline", ProfileTarget.QI, aveline_json)
    profiles_to_migrate.append((aveline_qi, get_role_profile_path("aveline", "Aveline", ProfileTarget.QI.value)))

    # Aveline_Ling: Aveline 面对Ling时的人设
    # - 名字和基本信息从 aveline_json.identity 提取（Aveline 自己）
    # - 描述从 ling_json.relationship.sibling 提取（Ling视角下的 Aveline）
    ling_identity = ling_json.get("identity") or {}
    ling_rel = ling_identity.get("relationship") or {}
    ling_sibling = ling_rel.get("sibling") or {}
    aveline_ling = build_role_profile(
        "aveline", "Aveline", ProfileTarget.LING, aveline_json,  # ← 用 aveline_json 提取 Aveline 自己的名字
        description_override=str(ling_sibling.get("description") or "").strip(),
        core_fields_override={
            "cn_name": str(aveline_json.get("identity", {}).get("cn_name") or "七濑 澪").strip(),
            "role": str(ling_sibling.get("role") or "室友/姐姐").strip(),
        },
    )
    profiles_to_migrate.append((aveline_ling, get_role_profile_path("aveline", "Aveline", ProfileTarget.LING.value)))

    # Aveline_default: 复制 Qi
    aveline_default = build_role_profile("aveline", "Aveline", ProfileTarget.DEFAULT, aveline_json)
    profiles_to_migrate.append((aveline_default, get_role_profile_path("aveline", "Aveline", ProfileTarget.DEFAULT.value)))

    # 4. Ling多版本人设
    # Ling_Qi: 从 core_ling.json 完整迁移
    ling_qi = build_role_profile("ling", "Ling", ProfileTarget.QI, ling_json)
    profiles_to_migrate.append((ling_qi, get_role_profile_path("ling", "Ling", ProfileTarget.QI.value)))

    # Ling_Aveline: Ling面对 Aveline 时的人设
    # - 名字和基本信息从 ling_json.identity 提取（Ling自己）
    # - 描述从 aveline_json.relationship.sibling 提取（Aveline 视角下的Ling）
    aveline_identity = aveline_json.get("identity") or {}
    aveline_rel = aveline_identity.get("relationship") or {}
    aveline_sibling = aveline_rel.get("sibling") or {}
    ling_aveline = build_role_profile(
        "ling", "Ling", ProfileTarget.AVELINE, ling_json,  # ← 用 ling_json 提取Ling自己的名字
        description_override=str(aveline_sibling.get("description") or "").strip(),
        core_fields_override={
            "cn_name": str(ling_json.get("identity", {}).get("cn_name") or "Ling").strip(),
            "role": str(aveline_sibling.get("role") or "室友/妹妹").strip(),
        },
    )
    profiles_to_migrate.append((ling_aveline, get_role_profile_path("ling", "Ling", ProfileTarget.AVELINE.value)))

    # Ling_default: 复制 Qi
    ling_default = build_role_profile("ling", "Ling", ProfileTarget.DEFAULT, ling_json)
    profiles_to_migrate.append((ling_default, get_role_profile_path("ling", "Ling", ProfileTarget.DEFAULT.value)))

    # 执行迁移
    print(f"\n共 {len(profiles_to_migrate)} 个档案待迁移:\n")
    migrated = 0
    skipped = 0

    for profile, path in profiles_to_migrate:
        exists = path.exists()
        action = ""

        if exists and not force:
            action = "[SKIP] 已存在"
            skipped += 1
        elif dry_run:
            action = "[DRY] 将创建"
        else:
            profile.save(path)
            action = "[OK] 已创建"
            migrated += 1

        print(f"  {action} {path.relative_to(PROJECT_ROOT)}")
        print(f"    profile_id={profile.profile_id}, type={profile.profile_type.value}, name={profile.name}")
        if profile.description:
            desc_preview = profile.description[:60] + "..." if len(profile.description) > 60 else profile.description
            print(f"    description: {desc_preview}")
        print()

    print("=" * 60)
    print(f"迁移完成: 创建 {migrated} 个, 跳过 {skipped} 个")
    if skipped > 0 and not force:
        print("提示: 使用 --force 覆盖已有档案")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="人物档案迁移脚本")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="预览模式，不实际写文件",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="覆盖已存在的档案文件",
    )
    args = parser.parse_args()

    run_migration(dry_run=args.dry_run, force=args.force)


if __name__ == "__main__":
    main()
