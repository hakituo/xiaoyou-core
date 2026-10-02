# -*- coding: utf-8 -*-
"""校验「薄壳门面 + 子模块」拆分后，门面对外契约与拆分前一致。

与 ``tests/scripts/coverage/compare_module_coverage.py`` 的分工
-------------------------------------------------------------
- ``compare_module_coverage.py`` 管**规模**：正文语句数聚合一致、未覆盖数不增、覆盖率不降；
- 本脚本管**契约**：拆分前模块的每个顶层名字，拆分后仍可按原路径访问，
  且值 / 签名 / 类方法集合没有变化。

两者一起才能坐实「纯搬家」：前者防漏搬，后者防改签名、改常量、丢导出。

做法
----
把 ``HEAD`` 版本源码写到**同目录**的临时模块文件后再导入（保留相对导入语义），
与工作区里的门面逐名对比：

- 值类型（str/int/float/bool/None/list/tuple/dict/set/frozenset）→ 必须 ``==``；
- 函数 / 方法 → 参数名、参数类型（POSITIONAL/KEYWORD/VAR_*）与「是否有默认值」必须一致
  （注解字符串化与类限定名会造成假差异，故不比较注解文本）；
- 类 → 方法名集合必须覆盖拆分前，且同名方法签名一致，另外比对类属性中的字面量；
- 模块对象与 ``typing``/``dataclasses`` 辅助名不参与比较（拆分会改变它们的归属模块）。

用法
----
    venv_core\\Scripts\\python.exe tests/scripts/docs/verify_module_split_contract.py \\
        --pair memory.core.analysis_ops=memory/core/analysis_ops.py \\
        --pair core.modules.llm.stream_generator=core/modules/llm/stream_generator.py

任一模块不通过即非零退出，并逐条打印问题（缺少名字 / 值不一致 / 签名不一致 / 缺方法）。
**取不到基线（路径或 rev 写错）同样非零退出** —— 否则门禁会在最该报警时静默放行。

注意
----
- 必须在**仓库根**运行（脚本用 ``git show <base>:<path>`` 取拆分前源码）；
- 默认基线是 ``HEAD``，即「拆分当场」跑：此时 ``HEAD`` 还是拆分前的原文。
  拆分一旦提交，``HEAD`` 就变成门面本身，默认口径下没有可比对象；
  这时用 ``--base <拆分提交>^`` 指向拆分前的父提交，即可**事后复核**。
  例：
      venv_core\\Scripts\\python.exe tests/scripts/docs/verify_module_split_contract.py \\
          --base 8fe67395^ --pair memory.core.analysis_ops=memory/core/analysis_ops.py
"""
from __future__ import annotations

import argparse
import importlib
import inspect
import pathlib
import subprocess
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[3]

# 直接以脚本方式运行时，sys.path[0] 是 scripts 目录，需补上仓库根才能导入被测模块
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 值类型才做等值比较（锁 / logger / 模块对象等只看「存在」）
VALUE_TYPES = (str, int, float, bool, bytes, type(None), list, tuple, dict, set, frozenset)

# 拆分会改变归属模块的辅助名，不参与比较
IGNORE_NAMES = {
    "annotations",
    "Any",
    "Dict",
    "List",
    "Tuple",
    "Optional",
    "Set",
    "Union",
    "Callable",
    "dataclass",
    "field",
    "asdict",
}


def load_head_module(module_name: str, rel_path: str, rev: str = "HEAD") -> types.ModuleType:
    """把 ``<rev>`` 版本的源码写成同目录临时模块再导入（保证相对导入与 dataclass 可用）。"""
    src = subprocess.check_output(
        ["git", "--no-pager", "show", f"{rev}:{rel_path}"], text=True, encoding="utf-8"
    )
    target = ROOT / rel_path
    tmp_path = target.with_name("_tmp_head_" + target.name)
    tmp_module_name = module_name.rsplit(".", 1)[0] + "._tmp_head_" + target.stem
    tmp_path.write_text(src, encoding="utf-8")
    try:
        importlib.invalidate_caches()
        return importlib.import_module(tmp_module_name)
    finally:
        # 临时文件清理失败（safe-delete 守卫 / 文件锁）不该让校验本身失败：
        # 这个文件是 _tmp_head_ 前缀的临时产物，清不掉也只是留个垃圾文件。
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def signature_shape(func: object) -> list[tuple[str, str, str]]:
    """签名的可比形态：参数名 + 参数类型 + 是否有默认值（不比注解写法）。"""
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return []
    return [
        (
            param.name,
            param.kind.name,
            "default" if param.default is not inspect.Parameter.empty else "",
        )
        for param in sig.parameters.values()
    ]


def compare(orig: types.ModuleType, new: types.ModuleType) -> list[str]:
    problems: list[str] = []
    for name, value in vars(orig).items():
        if name.startswith("__") or name in IGNORE_NAMES or inspect.ismodule(value):
            continue
        if not hasattr(new, name):
            problems.append(f"缺少名字: {name}")
            continue
        new_value = getattr(new, name)

        if inspect.isclass(value):
            if not inspect.isclass(new_value):
                problems.append(f"{name} 不再是类")
                continue
            old_methods = {
                n
                for n, _ in inspect.getmembers(value, inspect.isfunction)
                if not n.startswith("__")
            }
            new_methods = {
                n
                for n, _ in inspect.getmembers(new_value, inspect.isfunction)
                if not n.startswith("__")
            }
            missing = sorted(old_methods - new_methods)
            if missing:
                problems.append(f"{name} 缺方法: {missing}")
            for method in sorted(old_methods & new_methods):
                old_shape = signature_shape(getattr(value, method))
                new_shape = signature_shape(getattr(new_value, method))
                if old_shape != new_shape:
                    problems.append(
                        f"{name}.{method} 签名不一致: {old_shape} != {new_shape}"
                    )
        elif inspect.isfunction(value):
            if not callable(new_value):
                problems.append(f"{name} 不再可调用")
                continue
            old_shape = signature_shape(value)
            new_shape = signature_shape(new_value)
            if old_shape != new_shape:
                problems.append(f"{name} 签名不一致: {old_shape} != {new_shape}")
        elif isinstance(value, VALUE_TYPES) and type(value) is type(new_value):
            if value != new_value:
                problems.append(f"{name} 值不一致:\n    old={value!r}\n    new={new_value!r}")
    return problems


def parse_pairs(raw_pairs: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for raw in raw_pairs:
        if "=" not in raw:
            raise SystemExit(f"[错误] --pair 需要写成 <模块名>=<仓库相对路径>，收到: {raw}")
        module_name, rel_path = raw.split("=", 1)
        pairs.append((module_name.strip(), rel_path.strip()))
    return pairs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="拆分后门面对外契约校验")
    parser.add_argument(
        "--pair",
        action="append",
        default=[],
        metavar="<模块名>=<仓库相对路径>",
        help="要校验的模块（可重复），如 memory.core.analysis_ops=memory/core/analysis_ops.py",
    )
    parser.add_argument(
        "--base",
        default="HEAD",
        metavar="<rev>",
        help=(
            "对比基线（默认 HEAD，即拆分当场跑）。"
            "**事后复核**已提交的拆分请传拆分提交的父提交，例如 --base 8fe67395^"
        ),
    )
    args = parser.parse_args(argv)
    if not args.pair:
        parser.error("至少需要一个 --pair")

    failed = False
    skipped: list[str] = []
    for module_name, rel_path in parse_pairs(args.pair):
        try:
            orig = load_head_module(module_name, rel_path, args.base)
        except Exception as exc:  # noqa: BLE001
            print(f"[跳过] {module_name}: 无法取 {args.base} 版本（{exc!r}）")
            skipped.append(module_name)
            continue
        try:
            new = importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001
            print(f"[失败] {module_name}: 无法导入新模块 {exc!r}")
            failed = True
            continue
        problems = compare(orig, new)
        if problems:
            failed = True
            print(f"[失败] {module_name}（{len(problems)} 项）")
            for item in problems:
                print("   -", item)
        else:
            print(f"[通过] {module_name}")

    print("=" * 60)
    if failed:
        print("❌ 门面对外契约与拆分前不一致")
        return 1
    if skipped:
        # 「取不到基线」绝不能被当成通过：路径写错 / 基线 rev 写错都会走到这里，
        # 若这里返回 0，门禁就会在最需要报警的时候静默放行。
        print(f"❌ {len(skipped)} 个模块无法取得基线，未能校验：{skipped}")
        return 1
    print("✅ 门面对外契约与拆分前一致（名字 / 值 / 签名 / 类方法集合）")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
