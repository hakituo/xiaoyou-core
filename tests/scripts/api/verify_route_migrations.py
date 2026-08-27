from __future__ import annotations

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[3]


def _read_text(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _assert_contains(text: str, needle: str, label: str, errors: list[str]) -> None:
    if needle not in text:
        errors.append(f"{label} 缺少：{needle}")


def _assert_not_contains(
    text: str,
    needle: str,
    label: str,
    errors: list[str],
) -> None:
    if needle in text:
        errors.append(f"{label} 仍残留旧路径：{needle}")


def verify_backend(errors: list[str]) -> None:
    admin_init = _read_text("routers/admin/__init__.py")
    memories_router = _read_text("routers/v1/memories.py")

    _assert_contains(
        admin_init,
        'router.include_router(memory_watchdog_router, prefix="/admin")',
        "后端 admin 聚合",
        errors,
    )
    _assert_contains(
        admin_init,
        "router.include_router(memory_watchdog_router)",
        "后端 memory_watchdog 兼容入口",
        errors,
    )
    _assert_contains(
        memories_router,
        "min_weight: Optional[float] = Query(None",
        "memories 路由",
        errors,
    )
    _assert_contains(
        memories_router,
        "manager.get_weighted_memories,\n            min_weight=min_weight,",
        "memories 路由",
        errors,
    )


def verify_web(errors: list[str]) -> None:
    api_service = _read_text("clients/frontend/aveline-web/src/api/apiService.ts")

    _assert_contains(
        api_service,
        "await del(`/api/v1/memories?user_id=${userId}`)",
        "Web apiService",
        errors,
    )
    _assert_contains(
        api_service,
        "await get('/api/v1/memories', { limit, min_weight: minWeight })",
        "Web apiService",
        errors,
    )
    _assert_contains(
        api_service,
        "await del(`/api/v1/memories/${memoryId}`)",
        "Web apiService",
        errors,
    )
    _assert_not_contains(
        api_service,
        "/api/v1/memory/weighted",
        "Web apiService",
        errors,
    )


def verify_android(errors: list[str]) -> None:
    android_root = REPO_ROOT / "clients/frontend/aveline-android"
    if not android_root.exists():
        errors.append("Android 项目目录不存在")
        return

    old_needles = (
        "/api/v1/memory/weighted",
        "/api/v1/admin/memory",
        "/api/v1/workspace/remote",
        "/api/v1/data-ops",
        "/api/v1/auto-heal",
    )
    source_roots = [
        android_root / "android/app/src",
        android_root / "android/src",
    ]
    text_files: list[Path] = []
    for source_root in source_roots:
        if not source_root.exists():
            continue
        text_files.extend(source_root.rglob("*.kt"))
        text_files.extend(source_root.rglob("*.kts"))
        text_files.extend(source_root.rglob("*.java"))

    for file_path in text_files:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        for needle in old_needles:
            if needle in content:
                rel_path = file_path.relative_to(REPO_ROOT)
                errors.append(f"Android 仍残留旧路径：{rel_path} -> {needle}")


def verify_qq(errors: list[str]) -> None:
    qq_system = _read_text("clients/bots/handlers/system.py")

    _assert_contains(
        qq_system,
        '"POST", "/api/v1/admin/remote/file/action", json_body=body',
        "QQ system handler",
        errors,
    )
    _assert_contains(
        qq_system,
        'endpoint = "/api/v1/admin/remote/reject" if is_reject else "/api/v1/admin/remote/approve"',
        "QQ system handler",
        errors,
    )
    _assert_not_contains(
        qq_system,
        "/api/v1/workspace/remote",
        "QQ system handler",
        errors,
    )


def main() -> int:
    errors: list[str] = []
    verify_backend(errors)
    verify_web(errors)
    verify_android(errors)
    verify_qq(errors)

    if errors:
        print("路由迁移校验失败：")
        for item in errors:
            print(f"- {item}")
        return 1

    print("路由迁移校验通过。")
    print("- 后端同时提供 admin/memory 规范入口和 memory 兼容入口")
    print("- Web 已切换到 /api/v1/memories")
    print("- Android 未发现本轮关注的旧路径残留")
    print("- QQ 仍使用 /api/v1/admin/remote 规范路径")
    return 0


if __name__ == "__main__":
    sys.exit(main())
