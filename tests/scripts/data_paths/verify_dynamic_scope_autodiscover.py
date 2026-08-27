"""验证 persona meta.scope 是角色数据目录的唯一标识。

运行：venv_core\Scripts\python.exe tests/scripts/data_paths/verify_dynamic_scope_autodiscover.py
"""

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.data_paths import (  # noqa: E402
    get_role_data_dir,
    resolve_data_scope_from_conversation_id,
    resolve_memory_user_id,
)
from core.utils.scope_registry import (  # noqa: E402
    _DYNAMIC_SCOPES,
    _PERSONA_SLUG_TO_SCOPE,
    _VALID_SCOPES,
    refresh_scope_registry,
)


def _check(condition: bool, message: str) -> tuple[bool, str]:
    return condition, ("PASS: " if condition else "FAIL: ") + message


def _verify_current_personas(results: list[tuple[bool, str]]) -> None:
    expected = {
        "Frost": "rushuang",
        "Mian": "mianmian",
        "Kafka": "kafka",
        "Chiba": "chiba",
    }
    refresh_scope_registry()

    for slug, scope in expected.items():
        results.append(
            _check(
                scope in _DYNAMIC_SCOPES and scope in _VALID_SCOPES,
                f"{slug} 只注册稳定 scope={scope}",
            )
        )
        results.append(
            _check(
                _PERSONA_SLUG_TO_SCOPE.get(slug) == scope,
                f"中文文件名 {slug} 映射到 {scope}",
            )
        )
        for persona_slug in (slug, scope):
            conversation_id = f"shared__persona__{persona_slug}"
            resolved = resolve_data_scope_from_conversation_id(conversation_id)
            results.append(
                _check(
                    resolved == scope,
                    f"{conversation_id} 路由到 {scope}",
                )
            )
            results.append(
                _check(
                    resolve_memory_user_id(conversation_id) == f"shared__scope__{scope}",
                    f"{conversation_id} 共享同一 memory user_id",
                )
            )
        role_dir = get_role_data_dir(scope)
        results.append(
            _check(
                role_dir.name == f"{scope}_data",
                f"{scope} 的唯一目录名为 {scope}_data",
            )
        )


def _verify_future_persona(results: list[tuple[bool, str]]) -> None:
    """模拟未来只新增一个 JSON 配置，不修改任何 Python 白名单。"""
    with tempfile.TemporaryDirectory() as temp_dir:
        configs_dir = Path(temp_dir)
        config_path = configs_dir / "未来角色.json"
        config_path.write_text(
            json.dumps(
                {
                    "meta": {"scope": "future_role"},
                    "identity": {"name": "未来角色", "en_name": "Future Role"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        refresh_scope_registry(configs_dir)
        for slug in ("未来角色", "future_role", "Future Role"):
            conversation_id = f"shared__persona__{slug}"
            results.append(
                _check(
                    resolve_data_scope_from_conversation_id(conversation_id) == "future_role",
                    f"新角色别名 {slug} 自动路由到 future_role",
                )
            )

    # 避免临时注册表影响当前进程后续验证。
    refresh_scope_registry()


def main() -> int:
    results: list[tuple[bool, str]] = []
    _verify_current_personas(results)
    _verify_future_persona(results)

    print("\n" + "=" * 70)
    print("persona scope 唯一标准验证")
    print("=" * 70)
    for ok, message in results:
        print(f"  [{'✓' if ok else '✗'}] {message}")

    passed = sum(1 for ok, _ in results if ok)
    failed = len(results) - passed
    print("=" * 70)
    print(f"结果: {passed} 通过, {failed} 失败 / 共 {len(results)} 项")
    print("=" * 70)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
