"""验证 venv_core 启动器会在 YAML 加载后强制选择本地 LLM。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run_check() -> int:
    bat_path = ROOT / "start_venv_core.bat"
    bat_bytes = bat_path.read_bytes()
    if any(byte > 0x7F for byte in bat_bytes):
        print("FAIL: BAT 包含非 ASCII 字节，可能被 cmd.exe 错误解析")
        return 1
    if b"\n" in bat_bytes.replace(b"\r\n", b""):
        print("FAIL: BAT 包含非 CRLF 换行，可能破坏 cmd.exe 变量解析")
        return 2

    bat_text = bat_bytes.decode("ascii").lower()
    marker = "set xiaoyou_start_local_llm=1"
    if marker not in bat_text:
        print(f"FAIL: 启动器缺少本地 LLM 标记: {marker}")
        return 3

    cmd_check = subprocess.run(
        ["cmd.exe", "/d", "/c", str(bat_path), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if cmd_check.returncode != 0 or "[PASS] Launcher configuration valid" not in (
        cmd_check.stdout
    ):
        print("FAIL: cmd.exe 无法正确解析启动器")
        print(cmd_check.stdout)
        print(cmd_check.stderr)
        return 4

    os.environ["XIAOYOU_START_LOCAL_LLM"] = "1"

    from config.integrated_config import get_settings

    provider = get_settings().model.llm.provider
    if provider != "local":
        print(f"FAIL: YAML 加载后的 provider 仍为 {provider!r}")
        return 5

    print("PASS: start_venv_core.bat 启动时 provider=local")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_check())
