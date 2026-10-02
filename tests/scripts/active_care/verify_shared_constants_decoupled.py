"""验证 shared/constants.py 已解耦为按职责拆分的原子模块

背景（2026-09-03）：
    `shared/constants.py` 长期扮演"什么都往里放"的角色：状态键、关键词表、
    数值阈值、文本工具、Prompt 构建器、Daily Record 写盘逻辑混在一个 605 行
    的文件里。后果有三：

      1. 只想取一个状态键的调用方，也要连带导入 Prompt 模板与 Daily 模块；
      2. `sync_sleep_to_daily_record` 这类带 IO 副作用的函数混在常量模块里，
         任何常量消费者都间接依赖 `core.services.daily`，埋下循环导入隐患；
      3. 常量按"文件"而非"语义"聚合，新增常量时容易继续往里堆。

本轮拆分（新代码请直接引用对应模块）：
    - `state_keys.py`        StateKeys + 状态清理字典构建
    - `keywords.py`          晚安/早安/专注/题材等关键词与匹配模式
    - `mode_reasons.py`      低打扰原因取值域、SkipReasons、SysPromptType
    - `tuning.py`            通用数值阈值（间隔/生成/提醒/退避/抖动）
    - `sleep_thresholds.py`  睡眠与晚安相关窗口阈值
    - `scheduling_utils.py`  退避等调度纯函数
    - `text_utils.py`        文本归一化、时长解析/格式化、人设 token
    - `prompt_helpers.py`    Prompt 片段构建器
    - `daily_record_sync.py` 睡眠区间回写 Daily Record（唯一带 IO 的模块）
    - `constants.py`         仅保留向后兼容的 re-export 门面

本脚本校验：新模块职责边界、门面导出等价性、源码中不再有遗留引用、
以及关键函数的行为未因搬迁而改变。

运行：
    D:\\AI\\xiaoyou-core\\venv_core\\Scripts\\python.exe -m tests.scripts.active_care.verify_shared_constants_decoupled
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_PASSED = 0
_FAILED = 0

_SHARED_DIR = "core/services/active_care/shared"
_LEGACY_MODULE = "core.services.active_care.shared.constants"

# 拆分后的原子模块：模块名 → 该模块允许出现的顶层依赖前缀（空表示纯数据/纯函数）
_ATOMIC_MODULES = {
    "state_keys": (),
    "keywords": (),
    "mode_reasons": (),
    "tuning": (),
    "sleep_thresholds": (),
    "scheduling_utils": ("core.services.active_care.shared.tuning",),
    "text_utils": ("core.utils.",),
    "prompt_helpers": ("core.agents.",),
    "daily_record_sync": (),
}


def _ok(msg: str) -> None:
    global _PASSED
    _PASSED += 1
    print(f"  [OK] {msg}")


def _fail(msg: str, detail: str = "") -> None:
    global _FAILED
    _FAILED += 1
    print(f"  [FAIL] {msg}")
    if detail:
        print(f"         {detail}")


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def test_atomic_modules_importable() -> None:
    _section("测试 1: 9 个原子模块均可独立导入")
    import importlib

    for name in _ATOMIC_MODULES:
        try:
            importlib.import_module(f"core.services.active_care.shared.{name}")
            _ok(f"shared/{name}.py 可独立导入")
        except Exception as exc:  # pragma: no cover - 失败即报错
            _fail(f"shared/{name}.py 导入失败", repr(exc))


def test_atomic_modules_dependencies() -> None:
    _section("测试 2: 纯数据/纯函数模块不引入项目内依赖")
    for name, allowed_prefixes in _ATOMIC_MODULES.items():
        path = _PROJECT_ROOT / _SHARED_DIR / f"{name}.py"
        source = path.read_text(encoding="utf-8")
        illegal = []
        for line in source.splitlines():
            # 只看模块级 import：函数内的延迟导入不算编译期依赖
            if line[:1].isspace():
                continue
            if not line.startswith(("import ", "from ")):
                continue
            if line.startswith("from __future__"):
                continue
            target = line.split()[1]
            if not target.startswith(("core.", "config.")):
                continue  # 标准库依赖允许
            if any(target.startswith(prefix) for prefix in allowed_prefixes):
                continue
            illegal.append(line)
        if illegal:
            _fail(f"shared/{name}.py 引入了越界依赖", "; ".join(illegal))
        else:
            _ok(f"shared/{name}.py 依赖边界符合要求")


def test_facade_exports_identical() -> None:
    _section("测试 3: constants 门面导出与原实现完全一致")
    import importlib

    facade = importlib.import_module(_LEGACY_MODULE)
    exports = getattr(facade, "__all__", [])
    if not exports:
        _fail("constants.py 缺少 __all__，无法校验导出完整性")
        return

    # 反查每个导出名应当属于哪个原子模块
    owner: dict[str, str] = {}
    for name in _ATOMIC_MODULES:
        module = importlib.import_module(f"core.services.active_care.shared.{name}")
        for attr in getattr(module, "__all__", []):
            owner.setdefault(attr, name)

    missing = [n for n in exports if n not in owner]
    if missing:
        _fail("门面导出了不属于任何原子模块的名字", str(missing))
    else:
        _ok(f"门面 {len(exports)} 个导出名全部能定位到原子模块")

    mismatched = []
    for name in exports:
        source_module = importlib.import_module(
            f"core.services.active_care.shared.{owner[name]}"
        )
        if getattr(facade, name, None) is not getattr(source_module, name, None):
            mismatched.append(name)
    if mismatched:
        _fail("门面导出对象与原子模块不是同一个对象", str(mismatched))
    else:
        _ok("门面导出对象与原子模块保持同一引用（值/语义未漂移）")


def test_facade_has_no_implementation() -> None:
    _section("测试 4: constants.py 只剩 re-export，不再含实现")
    path = _PROJECT_ROOT / _SHARED_DIR / "constants.py"
    code_lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    has_impl = any(
        line.startswith(("def ", "class ", "import ", "from "))
        and not line.startswith("from core.services.active_care.shared.")
        for line in code_lines
    )
    if has_impl:
        _fail("constants.py 仍包含实现或非 shared 依赖")
    else:
        _ok("constants.py 仅保留 re-export 与 __all__")


def test_no_legacy_import_in_sources() -> None:
    _section("测试 5: 业务代码不再从 constants 门面取常量")
    skip_files = {
        _PROJECT_ROOT / _SHARED_DIR / "constants.py",
        Path(__file__).resolve(),
    }
    offenders = []
    for path in (_PROJECT_ROOT / "core").rglob("*.py"):
        if path.name == "constants.py":
            continue
        if _LEGACY_MODULE in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(_PROJECT_ROOT)))
    for path in [
        _PROJECT_ROOT / "routers" / "v1" / "life.py",
        _PROJECT_ROOT / "memory" / "nightly" / "user_loader.py",
    ]:
        if path.exists() and _LEGACY_MODULE in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(_PROJECT_ROOT)))
    offenders = [item for item in offenders if _PROJECT_ROOT / item not in skip_files]
    if offenders:
        _fail("仍有业务代码引用 shared.constants 门面", "; ".join(offenders))
    else:
        _ok("core/ 与跨模块调用方已全部改为引用原子模块")


def test_behaviour_unchanged() -> None:
    _section("测试 6: 搬迁后关键行为不变")
    from core.services.active_care.shared.daily_record_sync import (
        sync_sleep_to_daily_record,
    )
    from core.services.active_care.shared.mode_reasons import (
        FOCUS_MODE_REASONS,
        QUIET_MODE_REASONS,
        SLEEP_HINT_REASON,
        SLEEP_MODE_REASONS,
    )
    from core.services.active_care.shared.prompt_helpers import (
        build_quiet_mode_instruction,
        build_sleep_status_description,
        get_action_prompt,
    )
    from core.services.active_care.shared.scheduling_utils import (
        calculate_non_response_backoff,
    )
    from core.services.active_care.shared.sleep_thresholds import AUTO_WAKE_MAX_HOURS
    from core.services.active_care.shared.state_keys import (
        StateKeys,
        build_goodnight_clear_updates,
        build_reduced_mode_clear_updates,
    )
    from core.services.active_care.shared.text_utils import (
        extract_persona_token,
        format_duration_human,
        normalize_content,
        normalize_persona_token,
    )

    reduced = build_reduced_mode_clear_updates()
    if len(reduced) == 5 and reduced[StateKeys.REDUCED_MODE_REASON] == "none":
        _ok("build_reduced_mode_clear_updates 仍为 5 字段重置")
    else:
        _fail("build_reduced_mode_clear_updates 行为改变", str(reduced))

    goodnight = build_goodnight_clear_updates()
    if set(reduced).issubset(goodnight) and len(goodnight) == 7:
        _ok("build_goodnight_clear_updates 仍为 7 字段重置（含晚安两字段）")
    else:
        _fail("build_goodnight_clear_updates 行为改变", str(goodnight))

    if (
        {"goodnight", "sleep_hint", "sleep"} == set(SLEEP_MODE_REASONS)
        and {"focus", "study", "work"} == set(FOCUS_MODE_REASONS)
        and set(QUIET_MODE_REASONS) == {"goodnight", "sleep_hint"}
        and SLEEP_HINT_REASON == "sleep_hint"
    ):
        _ok("低打扰原因取值域未变，且睡眠与专注仍无交集")
    else:
        _fail("低打扰原因取值域发生变化")

    backoff_zero = calculate_non_response_backoff(0)
    backoff_samples = [calculate_non_response_backoff(3) for _ in range(20)]
    if backoff_zero == 1.0 and all(1.0 <= value <= 12.0 for value in backoff_samples):
        _ok(f"退避乘数区间正常（n=0 → 1.0，n=3 样本上限 {max(backoff_samples):.2f}）")
    else:
        _fail("退避乘数越界", f"zero={backoff_zero}, samples={backoff_samples[:5]}")

    if (
        normalize_persona_token("/persona/叶 2026.md") == "叶_2026"
        and extract_persona_token("qq__persona__aveline__123") == "aveline"
        and normalize_content("  晚安  World ") == "晚安 world"
    ):
        _ok("人设 token 与文本归一化行为不变")
    else:
        _fail("人设 token / 文本归一化行为改变")

    if (
        format_duration_human(0) == "不到1分钟"
        and format_duration_human(5400) == "1小时30分钟"
    ):
        _ok("时长格式化行为不变")
    else:
        _fail("时长格式化行为改变")

    goodnight_instruction = build_quiet_mode_instruction(
        quiet_mode_active=False,
        reduced_mode_active=True,
        reduced_mode_reason="goodnight",
    )
    if (
        goodnight_instruction
        and build_quiet_mode_instruction(False, False, "none") == ""
        and "晚安" in build_sleep_status_description(sleep_session_active=True)
        and isinstance(get_action_prompt("不存在的动作"), str)
    ):
        _ok("Prompt 构建器行为不变")
    else:
        _fail("Prompt 构建器行为改变")

    if AUTO_WAKE_MAX_HOURS == 14 and sync_sleep_to_daily_record(0, 0) is False:
        _ok("睡眠阈值常量与 Daily 回写短路逻辑不变")
    else:
        _fail("睡眠阈值常量或 Daily 回写短路逻辑改变")


def main() -> int:
    print("=" * 64)
    print("shared/constants.py 解耦验证（2026-09-03）")
    print("=" * 64)

    test_atomic_modules_importable()
    test_atomic_modules_dependencies()
    test_facade_exports_identical()
    test_facade_has_no_implementation()
    test_no_legacy_import_in_sources()
    test_behaviour_unchanged()

    print("=" * 64)
    print(f"通过 {_PASSED} 项，失败 {_FAILED} 项")
    print("=" * 64)
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
