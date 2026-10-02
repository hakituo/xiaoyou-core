# -*- coding: utf-8 -*-
"""按登记表逐个复核「已拆分门面」的对外契约是否仍然完好。

逐个调 `verify_module_split_contract.py --base <拆分提交>^ --pair <模块>=<路径>`，
比对「拆分前 vs 当前工作区」，只报**缺失**的名字（新增不报）。
因此这个脚本可以长期当回归网：有人从门面里删掉/改名一个对外符号，这里就会红。

为什么用子进程逐个跑：契约校验会把拆分前的源码写成同目录临时模块再 import，
同一个进程里跑多个会有 import 副作用与名字残留，逐个起进程最干净。

用法：
    venv_core\\Scripts\\python.exe tests\\scripts\\docs\\verify_all_split_contracts.py
    venv_core\\Scripts\\python.exe tests\\scripts\\docs\\verify_all_split_contracts.py --manifest <路径>
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST = pathlib.Path(__file__).resolve().parent / "split_contract_manifest.json"
CONTRACT_SCRIPT = pathlib.Path(__file__).resolve().parent / "verify_module_split_contract.py"


def main() -> int:
    parser = argparse.ArgumentParser(description="按登记表复核所有已拆分门面的对外契约")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="登记表路径")
    args = parser.parse_args()

    manifest = pathlib.Path(args.manifest)
    if not manifest.exists():
        print(f"❌ 登记表不存在: {manifest}")
        return 1

    data = json.loads(manifest.read_text(encoding="utf-8"))
    entries = data.get("entries", [])
    if not entries:
        print("⚠️ 登记表为空，无需校验")
        return 0

    print("=" * 72)
    print(f"已拆分门面契约复核（共 {len(entries)} 项，基线 = 各自的拆分提交）")
    print("=" * 72)

    failed: list[str] = []
    for entry in entries:
        module = entry["module"]
        path = entry["path"]
        commit = entry["split_commit"]

        cmd = [
            sys.executable,
            str(CONTRACT_SCRIPT),
            "--base",
            f"{commit}^",
            "--pair",
            f"{module}={path}",
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        ok = proc.returncode == 0
        print(f"  {'✅' if ok else '❌'} {module}  (split={commit})")
        if not ok:
            failed.append(module)
            for line in (proc.stdout or "").splitlines():
                if line.startswith("❌") or line.lstrip().startswith("缺少名字"):
                    print(f"       {line.strip()}")

    print("=" * 72)
    if failed:
        print(f"❌ {len(failed)} 个门面的对外契约与拆分前不一致：{failed}")
        print("   若确属有意的契约变更（改名 / 移除对外符号），请同步更新本用例与登记表。")
        return 1
    print("✅ 所有已登记门面的对外契约仍然完好")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
