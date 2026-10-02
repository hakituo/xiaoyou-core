# -*- coding: utf-8 -*-
"""对比「拆分前单个大文件」与「拆分后一组子文件」的覆盖率口径是否等价。

背景
----
仓库惯例是「薄壳门面 + 按职责拆子模块」（Python 单文件 >300 行该拆，见 `.trae/rules/RULES.md` §2）。源码拆分属**纯搬家**，
因此拆分前后该模块的覆盖率口径必须能逐条解释：差异只应来自 import 与门面转发的样板行，
**正文语句数必须一模一样**。

用法
----
    venv_core\\Scripts\\python.exe tests/scripts/coverage/compare_module_coverage.py \\
        --before-json .tmp/cov_before.json \\
        --after-json  .tmp/cov_after.json \\
        --before-src  .tmp/signal_detector.py.orig \\
        --after-src   "core/services/study/signal_*.py"

两个 coverage.json 用 ``coverage json`` 生成（量覆盖率必须 ``-n 0``，见
``.workbuddy-ai/TEST_HARDENING_PROGRESS.md`` 的「已知坑」）。

断言
----
1. **正文语句数聚合一致**：去掉 ``import`` / ``from ... import`` 样板行后，前后相等；
2. **未覆盖行数聚合不增加**；
3. **聚合 percent_covered 不低于拆分前**。
任一条不满足即非零退出，并打印明细。

注意
----
``--before-src`` 指向**拆分前的源码副本**。拆分完成后原路径已被门面覆盖，所以要么先用
``git show HEAD:<原文件> > <副本>`` 留一份，要么跳过正文语句数的断言（脚本会告警）。
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def norm(path: str) -> str:
    """统一成 POSIX 风格，便于跨平台匹配。"""
    return str(path).replace("\\", "/")


def load_coverage_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "files" not in data:
        raise SystemExit(f"[错误] {path} 不是 coverage json（缺 files 字段）")
    return data


def select(files: dict, pattern: str) -> list[str]:
    """从 coverage.json 的 files 里挑出目标文件。

    ``pattern`` 含通配符时按 fnmatch 匹配，否则按「后缀相等」匹配。
    """
    has_glob = any(ch in pattern for ch in "*?[")
    picked = []
    for key in files:
        key_n = norm(key)
        if has_glob:
            if fnmatch.fnmatch(key_n, pattern) or fnmatch.fnmatch(key_n, "*/" + pattern):
                picked.append(key)
        elif key_n == pattern or key_n.endswith("/" + pattern):
            picked.append(key)
    return sorted(picked)


def aggregate(files: dict, keys: list[str]) -> dict:
    stmts = missing = 0
    rows = []
    for key in keys:
        info = files[key]
        summary = info.get("summary", {})
        n = int(summary.get("num_statements", 0))
        m = int(summary.get("missing_lines", 0))
        stmts += n
        missing += m
        rows.append((norm(key), n, m))
    covered = stmts - missing
    percent = (covered / stmts * 100.0) if stmts else 100.0
    return {"statements": stmts, "missing": missing, "percent": percent, "rows": rows}


def is_boilerplate_line(line: str) -> bool:
    """``import`` / ``from ... import`` 行（含 ``from __future__``）算样板行。"""
    stripped = line.strip()
    return stripped.startswith("import ") or stripped.startswith("from ")


def classify_sources(patterns: list[str]) -> dict:
    """按 glob 收集源码，用 coverage 自己的解析器统计「样板行 / 正文行」。"""
    from coverage.parser import PythonParser

    paths: list[Path] = []
    for pattern in patterns:
        if any(ch in pattern for ch in "*?["):
            paths.extend(sorted(ROOT.glob(pattern)))
        else:
            path = ROOT / pattern
            if path.exists():
                paths.append(path)
    if not paths:
        return {"found": False, "paths": [], "total": 0, "boilerplate": 0, "code": 0}

    total = boilerplate = 0
    for path in paths:
        text = path.read_text(encoding="utf-8")
        parser = PythonParser(text=text, filename=str(path))
        parser.parse_source()
        lines = text.splitlines()
        for lineno in parser.statements:
            total += 1
            raw = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
            if is_boilerplate_line(raw):
                boilerplate += 1
    return {
        "found": True,
        "paths": [norm(str(p.relative_to(ROOT))) for p in paths],
        "total": total,
        "boilerplate": boilerplate,
        "code": total - boilerplate,
    }


def print_rows(title: str, agg: dict) -> None:
    print(f"--- {title} ---")
    for name, stmts, missing in agg["rows"]:
        cover = ((stmts - missing) / stmts * 100.0) if stmts else 100.0
        print(f"  {stmts:5d} stmts  {missing:4d} miss  {cover:5.1f}%  {name}")
    print(
        f"  合计: {agg['statements']} stmts / {agg['missing']} miss / {agg['percent']:.1f}%"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="拆分前后覆盖率口径对比")
    parser.add_argument("--before-json", required=True, help="拆分前的 coverage.json")
    parser.add_argument("--after-json", required=True, help="拆分后的 coverage.json")
    parser.add_argument(
        "--before-src",
        default="",
        help="拆分前的源码副本（文件路径或 glob）；缺失时跳过正文语句数断言",
    )
    parser.add_argument(
        "--after-src",
        default="",
        help="拆分后的一组源码（glob），如 'core/services/study/signal_*.py'",
    )
    args = parser.parse_args(argv)

    before_files = load_coverage_json(Path(args.before_json))["files"]
    after_files = load_coverage_json(Path(args.after_json))["files"]

    # coverage.json 里的键就是被测量的文件路径；按「出现在 before/after 各自集合」自动分组
    before_keys = sorted(before_files)
    after_keys = sorted(after_files)
    if args.before_src:
        picked = select(before_files, args.before_src)
        if picked:
            before_keys = picked
    if args.after_src:
        picked = select(after_files, args.after_src)
        if picked:
            after_keys = picked

    before_agg = aggregate(before_files, before_keys)
    after_agg = aggregate(after_files, after_keys)
    print_rows("拆分前", before_agg)
    print_rows("拆分后", after_agg)

    failures: list[str] = []

    before_src = classify_sources([args.before_src] if args.before_src else [])
    after_src = classify_sources([args.after_src] if args.after_src else [])
    if before_src["found"] and after_src["found"]:
        print("--- 语句构成（coverage 解析器口径）---")
        print(
            f"  拆分前: 共 {before_src['total']} = 样板 {before_src['boilerplate']}"
            f" + 正文 {before_src['code']}"
        )
        print(
            f"  拆分后: 共 {after_src['total']} = 样板 {after_src['boilerplate']}"
            f" + 正文 {after_src['code']}"
        )
        delta = after_src["code"] - before_src["code"]
        print(f"  正文语句数差: {delta:+d}（纯搬家必须为 0）")
        if delta != 0:
            failures.append(
                f"正文语句数前后不一致：{before_src['code']} -> {after_src['code']}（{delta:+d}）"
            )
    else:
        print(
            "[告警] 缺少 --before-src / --after-src 的可用源码，"
            "跳过「正文语句数一致」断言"
        )

    if after_agg["missing"] > before_agg["missing"]:
        failures.append(
            f"未覆盖行数增加：{before_agg['missing']} -> {after_agg['missing']}"
        )
    if after_agg["percent"] + 1e-9 < before_agg["percent"]:
        failures.append(
            f"聚合覆盖率下降：{before_agg['percent']:.2f}% -> {after_agg['percent']:.2f}%"
        )

    print("=" * 64)
    if failures:
        for item in failures:
            print(f"❌ {item}")
        return 1
    print("✅ 拆分前后覆盖率口径等价（正文语句数一致、未覆盖数不增、覆盖率不降）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
