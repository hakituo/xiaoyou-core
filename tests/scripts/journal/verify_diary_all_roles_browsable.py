"""验证「日记可浏览所有角色（含已下线的历史角色）」：

- 后端浏览视角的读取 scope = 主人 + 当前注册角色 + 画像表里的历史角色；
  写入/生成视角仍只用注册角色（不扩大写入面）。
- 每条日记带 source_label（作者展示名），前端据此显示，不再硬编码角色名。
- 安卓端日记 UI 与模型里不再出现写死的角色名单 / 角色名。

运行：
    venv_core\\Scripts\\python.exe tests\\scripts\\journal\\verify_diary_all_roles_browsable.py
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PASSED: list[str] = []
FAILED: list[str] = []


def _check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASSED.append(name)
        print(f"[OK] {name}")
    else:
        FAILED.append(name)
        print(f"[FAIL] {name} {detail}")


def _verify_read_scopes() -> None:
    """浏览 scope 覆盖注册角色 + 历史角色，写链路 scope 保持不变。"""
    from core.services.dual_role.personas import PERSONAS
    from core.services.journal.diary_personas import (
        get_diary_entry_scopes,
        get_diary_persona_ids,
        get_diary_read_scopes,
    )

    entry_scopes = get_diary_entry_scopes()
    read_scopes = get_diary_read_scopes()
    registered = set(get_diary_persona_ids())

    _check("浏览 scope 以主人手记开头", read_scopes[0] == "user", f"scopes={read_scopes}")
    _check(
        "浏览 scope 覆盖写链路 scope（主人 + 注册角色）",
        set(entry_scopes).issubset(set(read_scopes)),
        f"entry={entry_scopes} read={read_scopes}",
    )
    _check(
        "浏览 scope 覆盖画像表里所有角色（历史角色也在内）",
        set(PERSONAS.keys()).issubset(set(read_scopes)),
        f"personas={sorted(PERSONAS)} read={read_scopes}",
    )
    _check(
        "浏览 scope 无重复",
        len(read_scopes) == len(set(read_scopes)),
        f"read={read_scopes}",
    )

    historical = [role_id for role_id in PERSONAS if role_id not in registered]
    if historical:
        for role_id in historical:
            _check(
                f"历史角色 {role_id} 不在写链路 scope（不再新增日记）",
                role_id not in set(entry_scopes),
                f"entry={entry_scopes}",
            )
            _check(
                f"历史角色 {role_id} 在浏览 scope（历史日记仍可读）",
                role_id in set(read_scopes),
                f"read={read_scopes}",
            )
    else:
        print("[SKIP] 当前所有画像角色都在注册名单里，历史角色分支无样本")


def _verify_source_label() -> None:
    """展示名来自权威画像：主人→我，角色→权威名，未知→原样（绝不猜）。"""
    from core.services.journal.diary_personas import get_diary_source_label

    _check("user → 我", get_diary_source_label("user") == "我")
    _check("aveline → Aveline", get_diary_source_label("aveline") == "Aveline")
    _check("ling → Ling", get_diary_source_label("ling") == "Ling")
    _check("ye → Ye", get_diary_source_label("ye") == "Ye")
    _check(
        "未知 source 原样返回，不猜成别的角色",
        get_diary_source_label("someone_new") == "someone_new",
    )


def _verify_storage_scan() -> None:
    """扫描层：默认只扫注册角色，显式传 read scopes 才扫到历史角色。"""
    from core.services.journal.diary_personas import (
        get_diary_persona_ids,
        get_diary_read_scopes,
    )
    from core.services.journal.models import JournalEntry
    from core.services.journal.storage import JournalStorage

    dt = datetime(2026, 9, 23)
    written = ["user", "aveline", "ye", "ling"]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        storage = JournalStorage()
        # 角色目录重定向到临时目录，避免写进真实 companion_data
        storage._get_scope_base_dir = lambda scope: root / scope

        for index, scope in enumerate(written):
            diary_dir = root / scope / "daily" / "2026" / "09" / "23" / "diary"
            diary_dir.mkdir(parents=True, exist_ok=True)
            entry = JournalEntry(
                timestamp=dt.timestamp() + index,
                time_str=f"{index:02d}:00:00",
                type="daily",
                content=f"{scope} 的日记",
                source=scope,
            )
            (diary_dir / "entry.json").write_text(
                entry.model_dump_json(), encoding="utf-8"
            )

        default_sources = {e.source for e in asyncio.run(storage.get_entries(dt))}
        read_sources = {
            e.source
            for e in asyncio.run(storage.get_entries(dt, scopes=get_diary_read_scopes()))
        }

        expected_write = {"user", *get_diary_persona_ids()} & set(written)
        _check(
            "默认读取 = 主人 + 当前注册角色（写链路语义不变）",
            default_sources == expected_write,
            f"got={sorted(default_sources)} expected={sorted(expected_write)}",
        )
        _check(
            "浏览读取能拿到全部角色（含历史角色）",
            read_sources == set(written),
            f"got={sorted(read_sources)} expected={sorted(written)}",
        )
        if "ling" not in get_diary_persona_ids():
            _check(
                "未注册的Ling：默认读不到、浏览能读到",
                "ling" not in default_sources and "ling" in read_sources,
                f"default={sorted(default_sources)} read={sorted(read_sources)}",
            )


def _verify_workspace_get_diary() -> None:
    """/api/v1/diary 走浏览 scope，且每条带 source_label。"""
    from core.services.journal.diary_personas import get_diary_read_scopes
    from core.services.journal.models import JournalEntry
    from core.services.workspace.service import WorkspaceService

    captured: dict[str, tuple] = {}
    entries = [
        JournalEntry(timestamp=1.0, time_str="01:00:00", type="daily", content="手记", source="user"),
        JournalEntry(timestamp=2.0, time_str="02:00:00", type="daily", content="Aveline", source="aveline"),
        JournalEntry(timestamp=3.0, time_str="03:00:00", type="daily", content="玲", source="ling"),
        JournalEntry(timestamp=4.0, time_str="04:00:00", type="daily", content="叶", source="ye"),
        JournalEntry(timestamp=5.0, time_str="05:00:00", type="daily", content="新", source="brand_new"),
    ]

    class _StubJournalService:
        async def get_entries(self, date=None, scopes=None):
            captured["scopes"] = tuple(scopes or ())
            return entries

    with mock.patch(
        "core.services.journal.service.get_journal_service",
        return_value=_StubJournalService(),
    ):
        result = asyncio.run(WorkspaceService().get_diary("2026-09-23"))

    labels = {entry.source: entry.source_label for entry in result}
    _check(
        "浏览日记传的是 read scopes",
        captured.get("scopes") == get_diary_read_scopes(),
        f"scopes={captured.get('scopes')}",
    )
    _check("主人条目标注为「我」", labels.get("user") == "我", f"labels={labels}")
    _check("aveline 条目标注为 Aveline", labels.get("aveline") == "Aveline", f"labels={labels}")
    _check("历史角色 ling 仍被标注为Ling", labels.get("ling") == "Ling", f"labels={labels}")
    _check("新角色给原样标签，不丢空", bool(labels.get("brand_new")), f"labels={labels}")
    _check(
        "所有条目都带非空 source_label",
        all(entry.source_label.strip() for entry in result),
        f"labels={labels}",
    )


def _verify_android_no_hardcode() -> None:
    """安卓端日记链路不再出现写死的角色名单 / 角色名。"""
    base = (
        ROOT
        / "clients"
        / "frontend"
        / "aveline-android"
        / "android"
        / "app"
        / "src"
        / "main"
        / "java"
        / "com"
        / "aveline"
        / "ai"
        / "mobile"
    )
    forbidden = ["Ling", "Aveline", "Coco", "Frost", "Ye"]
    for relative in (
        "presentation/study/StudyDiaryTab.kt",
        "domain/models/StudyDailyModels.kt",
    ):
        path = base / relative
        if not path.exists():
            _check(f"安卓端文件存在: {relative}", False)
            continue
        text = path.read_text(encoding="utf-8")
        # 去掉注释后再查，注释里举例说明角色名是允许的
        code_lines = [
            line for line in text.splitlines() if not line.strip().startswith(("//", "*", "/*"))
        ]
        code = "\n".join(code_lines)
        hit = [word for word in forbidden if word in code]
        _check(f"{relative} 代码里无写死的角色名", not hit, f"命中={hit}")


def main() -> int:
    _verify_read_scopes()
    _verify_source_label()
    _verify_storage_scan()
    _verify_workspace_get_diary()
    _verify_android_no_hardcode()
    print("-" * 60)
    print(f"通过 {len(PASSED)}，失败 {len(FAILED)}")
    if FAILED:
        for name in FAILED:
            print(f"  - {name}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
