#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 core.utils 分组重构修复：import 不死锁、单例模块未被污染、日志颜色恢复。

背景（2026-08-13）：
- 解耦 chat_handlers.py 改变了模块导入时机，暴露出 core.utils 分组重构遗留的隐藏问题：
  1) logger 用普通 threading.Lock() 导致初始化期同一线程递归 get_logger 死锁（启动卡死无输出）
  2) logger 模块替换未复制原模块属性，from core.utils.logger import get_logger 报 (unknown location)
  3) core.utils.concurrency.singleton 的同名函数污染了 sys.modules['core.utils.singleton']，
     导致工具注册 from core.utils.singleton import singleton 失败
  4) 日志分组重构删除了 colorama 颜色，控制台日志变黑白

本脚本在子进程中做带超时的 import，避免卡死拖垮主测试进程。
运行：
    venv_cpu\\Scripts\\python.exe tests/scripts/verify_core_utils_refactor.py
"""
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_PASSED = 0
_FAILED = 0


def _report(name: str, ok: bool, detail: str = ""):
    global _PASSED, _FAILED
    if ok:
        _PASSED += 1
        print(f"[PASS] {name}" + (f" - {detail}" if detail else ""))
    else:
        _FAILED += 1
        print(f"[FAIL] {name}" + (f" - {detail}" if detail else ""))


def _run_subprocess(code: str, timeout: int = 40) -> tuple[int, str]:
    """在子进程里跑一段 Python，返回 (返回码, stdout+stderr)。超时杀掉。"""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"


def _verify_import_no_deadlock():
    """子进程 import main 应能在超时内正常完成（不死锁）。"""
    code = (
        "import sys\n"
        "import faulthandler\n"
        "faulthandler.dump_traceback_later(30, repeat=False, exit=True)\n"
        "import main\n"
        "print('MAIN_IMPORT_OK')\n"
    )
    rc, out = _run_subprocess(code, timeout=40)
    ok = rc == 0 and "MAIN_IMPORT_OK" in out
    detail = f"rc={rc}, out_tail={out.strip()[-120:]!r}" if not ok else "import main 正常完成"
    _report("import main 不卡死", ok, detail)


def _verify_singleton_module():
    """core.utils.singleton 必须是真实模块，且能 import 到 singleton/SingletonFactory。"""
    code = (
        "import sys\n"
        "from core.utils import logger  # 触发 core.utils 完整初始化\n"
        "m = sys.modules.get('core.utils.singleton')\n"
        "assert hasattr(m, '__spec__') and hasattr(m, '__file__'), 'not a real module'\n"
        "from core.utils.singleton import singleton, SingletonFactory\n"
        "print('SINGLETON_OK')\n"
    )
    rc, out = _run_subprocess(code, timeout=40)
    ok = rc == 0 and "SINGLETON_OK" in out
    detail = f"rc={rc}, out_tail={out.strip()[-120:]!r}" if not ok else "core.utils.singleton 是真实模块"
    _report("core.utils.singleton 模块未污染", ok, detail)


def _verify_console_formatter_color():
    """console 格式串应含 colorama 转义（时间青/名字品红），ColoredFormatter 不应整行染色。"""
    code = (
        "import inspect\n"
        "from core.utils.logging import registry\n"
        "from core.utils.logging import formatters\n"
        "src = inspect.getsource(registry)\n"
        "assert 'colorama.Fore.CYAN' in src and 'colorama.Fore.MAGENTA' in src, 'console fmt no color'\n"
        "fmt_src = inspect.getsource(formatters)\n"
        "assert 'return super().format(record)' in fmt_src, 'ColoredFormatter changed'\n"
        "print('COLOR_OK')\n"
    )
    rc, out = _run_subprocess(code, timeout=40)
    ok = rc == 0 and "COLOR_OK" in out
    detail = f"rc={rc}, out_tail={out.strip()[-120:]!r}" if not ok else "console 格式串含 colorama 转义"
    _report("console 日志颜色恢复", ok, detail)


def main() -> int:
    print(f"验证 core.utils 分组重构修复（项目根: {PROJECT_ROOT}）")
    _verify_import_no_deadlock()
    _verify_singleton_module()
    _verify_console_formatter_color()
    print(f"\n结果: {_PASSED} 通过, {_FAILED} 失败")
    return 0 if _FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
