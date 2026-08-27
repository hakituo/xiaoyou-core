"""数据路径迁移逻辑（从 data_paths.py 抽离）。

处理历史数据布局迁移：
- 旧版 Aveline_daily_data → companion_data
- user_data 下混放的聊天记录/日记/事件按 scope 分桶
- 错放在 aveline_data 的 ling/peer 文件归位
- 自主进食记录按角色拆分
- persona export 目录重命名
- 旧版 memory/ 目录合并进 memories/core_memory/

本模块由 data_paths.py 的 _ensure_initialized 延迟 import 调用，
避免循环依赖。迁移函数依赖 data_paths.py 的路径常量和 scope_registry 的解析结果。
"""
import json
import shutil
from pathlib import Path
from typing import Iterable

import structlog

from config.debug_config import is_debug_enabled

# 从 data_paths 导入路径常量（data_paths 在本模块被 import 之前已完全加载）
from .data_paths import (
    _AVELINE_DIR,
    _BASE_NAME,
    _LEGACY_BASE_NAME,
    _LING_DIR,
    _LING_SELF_MEAL_PREFIXES,
    _USER_DIR,
    _XIAOLU_DIR,
    _YEYE_DIR,
)
# 从 scope_registry 导入 scope 解析（独立模块，无循环）
from .scope_registry import (
    _DYNAMIC_SCOPES,
    _VALID_SCOPES,
    resolve_data_scope_from_source,
)

logger = structlog.get_logger(__name__)


def _move_path_merge(src: Path, dst: Path) -> None:
    """将 src 移动到 dst，若 dst 已存在则递归合并。"""
    if not src.exists():
        return
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return
    if src.is_file() and dst.is_file():
        return
    if src.is_file() and dst.is_dir():
        return
    if src.is_dir() and dst.is_file():
        return
    for child in list(src.iterdir()):
        _move_path_merge(child, dst / child.name)
    try:
        src.rmdir()
    except Exception:
        if is_debug_enabled("data_paths"):
            logger.info("删除源目录失败", path=str(src), exc_info=True)


def _scope_to_chat_history_root(base: Path, scope: str) -> Path:
    """根据 scope 返回对应的 chat_history 根目录。"""
    scope = scope if scope in _VALID_SCOPES else "aveline"
    if scope == "user":
        return (base / _USER_DIR / "chat_history").resolve()
    if scope == "ling":
        return (base / _LING_DIR / "chat_history").resolve()
    if scope == "xiaolu":
        return (base / _XIAOLU_DIR / "chat_history").resolve()
    if scope == "yeye":
        return (base / _YEYE_DIR / "chat_history").resolve()
    if scope == "dual_role":
        # dual_role 没有 chat_history 目录，归到 aveline_data
        return (base / _AVELINE_DIR / "chat_history").resolve()
    # 动态 scope（通过 persona meta.scope 声明的角色）
    if scope in _DYNAMIC_SCOPES:
        return (base / _DYNAMIC_SCOPES[scope]["dir"] / "chat_history").resolve()
    return (base / _AVELINE_DIR / "chat_history").resolve()


def iter_existing_chat_history_roots(base: Path) -> Iterable[Path]:
    """枚举所有已存在的 chat_history 根目录（含动态 scope）。"""
    user_chat = (base / _USER_DIR / "chat_history").resolve()
    aveline_chat = (base / _AVELINE_DIR / "chat_history").resolve()
    ling_chat = (base / _LING_DIR / "chat_history").resolve()
    xiaolu_chat = (base / _XIAOLU_DIR / "chat_history").resolve()
    yeye_chat = (base / _YEYE_DIR / "chat_history").resolve()
    roots = [user_chat, aveline_chat, ling_chat, xiaolu_chat, yeye_chat]
    # 动态 scope 的 chat_history 目录
    for info in _DYNAMIC_SCOPES.values():
        roots.append((base / info["dir"] / "chat_history").resolve())
    for path in roots:
        if path.exists():
            yield path


def _resolve_scope_from_chat_history_path(rel_parts: list[str]) -> str:
    """从聊天记录相对路径推断 scope。"""
    normalized = [str(part or "").strip() for part in rel_parts if str(part or "").strip()]
    joined = "/".join(normalized)
    lower_joined = joined.lower()
    if any("Ling" in part for part in normalized) or "ling" in lower_joined:
        return "ling"
    return "aveline"


def _target_chat_history_parts(rel_parts: list[str]) -> list[str]:
    """计算迁移目标路径的 parts（去掉中间多余层级）。"""
    normalized = [str(part or "").strip() for part in rel_parts if str(part or "").strip()]
    if len(normalized) >= 5:
        return normalized[:3] + normalized[4:]
    return normalized


def _split_daily_event_scope(line: str, *, default_scope: str) -> str:
    """从 daily event JSON 行解析 scope。"""
    try:
        payload = json.loads(line)
    except Exception:
        if is_debug_enabled("data_paths"):
            logger.info("解析daily event JSON失败", exc_info=True)
        return default_scope
    if not isinstance(payload, dict):
        return default_scope
    conversation_id = str(payload.get("conversation_id") or "").strip()
    if conversation_id:
        # 延迟 import 避免循环依赖
        from .scope_registry import resolve_data_scope_from_conversation_id
        return resolve_data_scope_from_conversation_id(
            conversation_id, default=default_scope
        )
    source = str(payload.get("source") or "").strip()
    if source:
        return resolve_data_scope_from_source(source, default=default_scope)
    return default_scope


def _migrate_active_care_layout(base: Path) -> None:
    """迁移旧版 active_care 布局到按角色分桶。"""
    legacy_root = (base / "active_care").resolve()
    if not legacy_root.exists():
        return
    for scope in ("aveline", "ling"):
        src = legacy_root / scope
        if not src.exists():
            continue
        dst = (base / (_AVELINE_DIR if scope == "aveline" else _LING_DIR) / "active_care").resolve()
        _move_path_merge(src, dst)
    try:
        legacy_root.rmdir()
    except Exception:
        if is_debug_enabled("data_paths"):
            logger.info("删除旧active_care目录失败", path=str(legacy_root), exc_info=True)


def _migrate_user_chat_history_layout(base: Path) -> None:
    """将 user_data 下混放的聊天记录按 scope 分桶到各角色目录。"""
    user_chat = (base / _USER_DIR / "chat_history").resolve()
    if not user_chat.exists():
        return
    for file_path in sorted(user_chat.rglob("*.jsonl")):
        try:
            rel_parts = list(file_path.relative_to(user_chat).parts)
        except Exception:
            if is_debug_enabled("data_paths"):
                logger.info("获取聊天记录相对路径失败", path=str(file_path), exc_info=True)
            continue
        scope = _resolve_scope_from_chat_history_path(rel_parts)
        target_root = _scope_to_chat_history_root(base, scope)
        target_rel_parts = _target_chat_history_parts(rel_parts)
        target_path = target_root.joinpath(*target_rel_parts)
        _move_path_merge(file_path, target_path)
    for index_path in sorted(user_chat.rglob("index.json")):
        try:
            index_path.unlink()
        except Exception:
            if is_debug_enabled("data_paths"):
                logger.info("删除index.json失败", path=str(index_path), exc_info=True)


def _migrate_daily_diary_layout(base: Path) -> None:
    """将 user_data/daily 下混放的日记按 scope 分桶。"""
    user_daily = (base / _USER_DIR / "daily").resolve()
    if not user_daily.exists():
        return
    for file_path in sorted(user_daily.rglob("diary/*.json")):
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception:
            if is_debug_enabled("data_paths"):
                logger.info("解析日记JSON失败", path=str(file_path), exc_info=True)
            continue
        scope = resolve_data_scope_from_source(
            payload.get("source"), default="user"
        )
        if scope not in {"aveline", "ling"}:
            continue
        try:
            rel_parts = list(file_path.relative_to(user_daily).parts)
        except Exception:
            if is_debug_enabled("data_paths"):
                logger.info("获取日记相对路径失败", path=str(file_path), exc_info=True)
            continue
        target_root = (
            (base / _AVELINE_DIR / "daily").resolve()
            if scope == "aveline"
            else (base / _LING_DIR / "daily").resolve()
        )
        target_path = target_root.joinpath(*rel_parts)
        _move_path_merge(file_path, target_path)


def _migrate_daily_event_layout(base: Path) -> None:
    """将 user_data/daily 下混放的 events 按 scope 拆分到各角色目录。"""
    user_daily = (base / _USER_DIR / "daily").resolve()
    if not user_daily.exists():
        return
    for event_file in sorted(user_daily.rglob("events/*.jsonl")):
        try:
            rel_parts = list(event_file.relative_to(user_daily).parts)
        except Exception:
            if is_debug_enabled("data_paths"):
                logger.info("获取事件文件相对路径失败", path=str(event_file), exc_info=True)
            continue
        try:
            lines = event_file.read_text(encoding="utf-8").splitlines()
        except Exception:
            if is_debug_enabled("data_paths"):
                logger.info("读取事件文件失败", path=str(event_file), exc_info=True)
            continue
        buckets = {"aveline": [], "ling": []}
        for line in lines:
            text = str(line or "").strip()
            if not text:
                continue
            scope = _split_daily_event_scope(text, default_scope="aveline")
            if scope in buckets:
                buckets[scope].append(text)
        for scope, items in buckets.items():
            if not items:
                continue
            target_root = (
                (base / _AVELINE_DIR / "daily").resolve()
                if scope == "aveline"
                else (base / _LING_DIR / "daily").resolve()
            )
            target_path = target_root.joinpath(*rel_parts)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if target_path.exists():
                existing = target_path.read_text(encoding="utf-8").splitlines()
            else:
                existing = []
            merged = existing + [x for x in items if x not in existing]
            target_path.write_text("\n".join(merged) + ("\n" if merged else ""), encoding="utf-8")


def _migrate_misplaced_memory_files(base: Path) -> None:
    """将 aveline_data/memories 中 misplaced 的文件迁移到正确的角色目录。

    处理的场景：
    1. peer_ling 文件被错误放在 aveline_data 下（应放在 dual_role 或 ling_data）
    2. private_*__persona__ling_love 文件被错误放在 aveline_data 下（应放在 ling_data）
    """
    aveline_memories = (base / _AVELINE_DIR / "memories").resolve()
    ling_memories = (base / _LING_DIR / "memories").resolve()
    dual_role_memories = (base / "dual_role" / "memories").resolve()

    if not aveline_memories.exists():
        return

    # 需要迁移的文件模式
    for src_file in aveline_memories.rglob("*.json"):
        if not src_file.is_file():
            continue

        filename = src_file.name
        # 提取 conversation_id（去掉 _weighted.json 或 _short.json 后缀）
        cid = filename
        for suffix in ["_weighted.json", "_short.json"]:
            if cid.endswith(suffix):
                cid = cid[:-len(suffix)]
                break

        # 判断目标目录
        target_root = None
        if cid.startswith("peer_ling") or cid == "peer_ling":
            # peer_ling 属于 dual_role
            target_root = dual_role_memories
        elif cid.startswith("peer_aveline") or cid == "peer_aveline":
            # peer_aveline 属于 dual_role
            target_root = dual_role_memories
        elif "__persona__ling" in cid or "__scope__ling" in cid:
            # ling 相关的 persona/scope 文件
            target_root = ling_memories

        if target_root is None:
            continue

        # 计算目标路径（保持相对路径结构）
        try:
            rel_path = src_file.relative_to(aveline_memories)
        except ValueError:
            continue

        dst_file = target_root / rel_path

        # 执行迁移
        if dst_file.exists():
            # 如果目标已存在，比较文件大小，保留更大的
            src_size = src_file.stat().st_size
            dst_size = dst_file.stat().st_size
            if src_size <= dst_size:
                src_file.unlink()
                if is_debug_enabled("data_paths"):
                    logger.info("删除 misplaced 文件（目标已存在且更大）", src=str(src_file), dst=str(dst_file))
                continue
            else:
                dst_file.unlink()

        # 移动文件
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        src_file.rename(dst_file)
        if is_debug_enabled("data_paths"):
            logger.info("迁移 misplaced 文件", src=str(src_file), dst=str(dst_file))


def _migrate_role_layout(base: Path) -> None:
    """按角色重新组织数据布局（合并多个子迁移）。"""
    _migrate_active_care_layout(base)
    _migrate_user_chat_history_layout(base)
    _migrate_daily_diary_layout(base)
    _migrate_daily_event_layout(base)
    _migrate_misplaced_memory_files(base)
    legacy_background_circle = (base / _USER_DIR / "background_circle").resolve()
    dual_role_background_circle = (base / "dual_role" / "background_circle").resolve()
    _move_path_merge(legacy_background_circle, dual_role_background_circle)


def _migrate_legacy_layout(project_root: Path) -> None:
    """迁移旧版 Aveline_daily_data 目录到 companion_data。"""
    legacy_base = (project_root / _LEGACY_BASE_NAME).resolve()
    if not legacy_base.exists():
        return
    base = (project_root / _BASE_NAME).resolve()
    user = base / _USER_DIR
    aveline = base / _AVELINE_DIR
    user.mkdir(parents=True, exist_ok=True)
    aveline.mkdir(parents=True, exist_ok=True)
    mapping = {
        "daily": user / "daily",
        "daily_records": user / "daily_records",
        "schedule": user / "schedule",
        "status": user / "status",
        "monthly": user / "monthly",
        "templates": user / "templates",
        "reminders.json": user / "reminders.json",
        "latest_device_context.json": user / "latest_device_context.json",
        "index.json": user / "index.json",
        "aveline_life": aveline / "aveline_life",
    }
    for item in list(legacy_base.iterdir()):
        target = mapping.get(item.name)
        if target is None:
            target = user / "legacy_misc" / item.name
        _move_path_merge(item, target)
    try:
        legacy_base.rmdir()
    except Exception:
        if is_debug_enabled("data_paths"):
            logger.info("删除旧版数据目录失败", path=str(legacy_base), exc_info=True)


def _migrate_self_meals_from_user_records(base: Path) -> None:
    """将 user daily_records 里的自主进食记录按角色拆分到对应角色目录。"""
    user_records = (base / _USER_DIR / "daily_records").resolve()
    if not user_records.exists():
        return
    for record_path in user_records.rglob("daily_record.json"):
        try:
            payload = json.loads(record_path.read_text(encoding="utf-8"))
        except Exception:
            if is_debug_enabled("data_paths"):
                logger.info("解析daily_record.json失败", path=str(record_path), exc_info=True)
            continue
        meals = payload.get("meals")
        if not isinstance(meals, list) or not meals:
            continue
        user_meals = []
        aveline_self_meals = []
        ling_self_meals = []
        for meal in meals:
            if not isinstance(meal, dict):
                continue
            content = str(meal.get("content") or "")
            lowered = content.lower()
            if any(lowered.startswith(prefix) for prefix in _LING_SELF_MEAL_PREFIXES):
                ling_self_meals.append(meal)
            elif content.startswith("自主进食:"):
                aveline_self_meals.append(meal)
            elif lowered.startswith("投喂(ling):") or lowered.startswith("投喂(ling):".lower()):
                ling_self_meals.append(meal)
            elif lowered.startswith("投喂:") or lowered.startswith("投喂:".lower()):
                aveline_self_meals.append(meal)
            else:
                user_meals.append(meal)
        if not aveline_self_meals and not ling_self_meals:
            continue
        payload["meals"] = user_meals
        try:
            record_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            logger.warning("写入daily_record.json失败", path=str(record_path), exc_info=True)
            continue
        for meal in aveline_self_meals:
            try:
                y, m, d = record_path.parts[-4], record_path.parts[-3], record_path.parts[-2]
                target_dir = (base / _AVELINE_DIR / "life_records" / y / m / d).resolve()
                target_dir.mkdir(parents=True, exist_ok=True)
                target_file = target_dir / "daily_record.json"
                a_payload = {"date": f"{y}-{int(m):02d}-{int(d):02d}", "meals": []}
                if target_file.exists():
                    try:
                        a_payload = json.loads(target_file.read_text(encoding="utf-8"))
                    except Exception:
                        if is_debug_enabled("data_paths"):
                            logger.info("解析aveline daily_record.json失败，使用默认值", path=str(target_file), exc_info=True)
                        a_payload = {"date": f"{y}-{int(m):02d}-{int(d):02d}", "meals": []}
                a_meals = a_payload.get("meals")
                if not isinstance(a_meals, list):
                    a_meals = []
                    a_payload["meals"] = a_meals
                if meal not in a_meals:
                    a_meals.append(meal)
                target_file.write_text(
                    json.dumps(a_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                logger.warning("写入aveline自主进食记录失败", path=str(target_file), exc_info=True)
                continue
        for meal in ling_self_meals:
            try:
                y, m, d = record_path.parts[-4], record_path.parts[-3], record_path.parts[-2]
                target_dir = (base / _LING_DIR / "life_records" / y / m / d).resolve()
                target_dir.mkdir(parents=True, exist_ok=True)
                target_file = target_dir / "daily_record.json"
                l_payload = {"date": f"{y}-{int(m):02d}-{int(d):02d}", "meals": []}
                if target_file.exists():
                    try:
                        l_payload = json.loads(target_file.read_text(encoding="utf-8"))
                    except Exception:
                        if is_debug_enabled("data_paths"):
                            logger.info("解析ling daily_record.json失败，使用默认值", path=str(target_file), exc_info=True)
                        l_payload = {"date": f"{y}-{int(m):02d}-{int(d):02d}", "meals": []}
                l_meals = l_payload.get("meals")
                if not isinstance(l_meals, list):
                    l_meals = []
                    l_payload["meals"] = l_meals
                if meal not in l_meals:
                    l_meals.append(meal)
                target_file.write_text(
                    json.dumps(l_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                logger.warning("写入ling自主进食记录失败", path=str(target_file), exc_info=True)
                continue


def _is_ling_persona_name(name: str) -> bool:
    """判断 persona 名是否属于Ling。"""
    text = str(name or "").strip().lower()
    return text in {"Ling", "ling", "wang_ling", "wangling"}


def _migrate_persona_export_layout(base: Path) -> None:
    """迁移 persona export 目录布局（Ling相关归到 ling_data）。"""
    old_persona_root = (base / _AVELINE_DIR / "persona_data").resolve()
    if not old_persona_root.exists():
        return
    ling_persona_root = (base / _LING_DIR / "persona_data").resolve()
    ling_persona_root.mkdir(parents=True, exist_ok=True)
    for child in list(old_persona_root.iterdir()):
        if not _is_ling_persona_name(child.name):
            continue
        _move_path_merge(child, ling_persona_root / child.name)
    _move_path_merge(ling_persona_root / "Ling", ling_persona_root / "ling")
    _move_path_merge(old_persona_root / "七濑 澪", old_persona_root / "aveline")


def _migrate_core_memory_layout(base: Path) -> None:
    """将各角色目录下旧版 memory/（核心记忆归档与每日日志）合并进 memories/core_memory/。

    旧布局：{role}_data/memory/{archive/, YYYY-MM-DD.md}
    新布局：{role}_data/memories/core_memory/{archive/, YYYY-MM-DD.md}
    避免与对话记忆系统的 memories/ 目录名称混淆。
    """
    if not base.exists():
        return
    for role_dir in list(base.iterdir()):
        if not role_dir.is_dir():
            continue
        legacy_memory = (role_dir / "memory").resolve()
        if not legacy_memory.is_dir():
            continue
        target = (role_dir / "memories" / "core_memory").resolve()
        try:
            _move_path_merge(legacy_memory, target)
        except Exception:
            logger.warning(
                "迁移核心记忆目录失败", src=str(legacy_memory), dst=str(target), exc_info=True
            )


def run_all_migrations(base: Path, project_root: Path) -> None:
    """执行全部数据布局迁移（由 data_paths._ensure_initialized 调用）。

    Args:
        base: companion_data 根目录
        project_root: 项目根目录
    """
    _migrate_legacy_layout(project_root)
    _migrate_role_layout(base)
    _migrate_self_meals_from_user_records(base)
    _migrate_persona_export_layout(base)
    _migrate_core_memory_layout(base)
