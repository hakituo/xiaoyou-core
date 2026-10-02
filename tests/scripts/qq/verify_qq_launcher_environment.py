"""验证 QQ 启动入口默认使用与主程序一致的 CPU 虚拟环境，并校验
Linux 主启动器的环境优先级、可执行位与跨目录路径自适应。"""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _read(relative_path: str) -> str:
    """读取启动脚本文本。"""
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def main() -> None:
    """检查各 QQ 启动入口的环境优先级与 Adapter 入口。"""
    batch_launcher_paths = (
        "start_scripts/start_qq_bot.bat",
        "start_scripts/start_multi_qq_bot.bat",
        "start_scripts/start_qq_official.bat",
    )

    for relative_path in batch_launcher_paths:
        content = _read(relative_path).lower()
        cpu_assignment = 'set "venv=venv_cpu"'
        core_assignment = 'set "venv=venv_core"'
        assert cpu_assignment in content, f"{relative_path} 未优先声明 venv_cpu"
        assert core_assignment in content, f"{relative_path} 缺少 venv_core 回退"
        assert content.index(cpu_assignment) < content.index(core_assignment), (
            f"{relative_path} 的环境优先级不是 venv_cpu -> venv_core"
        )

    adapter_script = _read("clients/bots/scripts/start_adapter.ps1").lower()
    cpu_resolution = '"venv_cpu\\scripts\\python.exe"'
    core_resolution = '"venv_core\\scripts\\python.exe"'
    assert adapter_script.index(cpu_resolution) < adapter_script.index(core_resolution)
    assert "clients\\bots\\multi_qq_adapter.py" in adapter_script

    main_launcher = _read("start.bat").lower()
    assert "set venv=venv_cpu" in main_launcher

    print("PASS: QQ Adapter 与主程序均优先使用 venv_cpu")

    # ---- start_scripts/ 下 bat 的跨目录路径自适应 ----
    for relative_path in batch_launcher_paths:
        content = _read(relative_path)
        assert 'set "SCRIPT_DIR=%~dp0"' in content, f"{relative_path} 缺少脚本目录解析"
        assert r'%SCRIPT_DIR%\main.py' in content, (
            f"{relative_path} 缺少根目录锚点 main.py"
        )
        assert r'%SCRIPT_DIR%\..\main.py' in content, (
            f"{relative_path} 缺少父目录回退，无法放子目录运行"
        )

    # ---- Linux 主启动器 ----
    start_sh = PROJECT_ROOT / "start.sh"
    gpu_sh = PROJECT_ROOT / "start_venv_core.sh"
    assert start_sh.is_file() and os.access(start_sh, os.X_OK), "start.sh 缺失或不可执行"
    assert gpu_sh.is_file() and os.access(gpu_sh, os.X_OK), (
        "start_venv_core.sh 缺失或不可执行"
    )
    start_text = start_sh.read_text(encoding="utf-8")
    gpu_text = gpu_sh.read_text(encoding="utf-8")
    cpu_pos = start_text.find("venv_cpu/bin/python")
    dot_pos = start_text.find(".venv/bin/python")
    core_pos = start_text.find("venv_core/bin/python")
    assert cpu_pos != -1 and cpu_pos < dot_pos and cpu_pos < core_pos, (
        "start.sh 环境优先级不是 venv_cpu -> venv_core -> .venv"
    )
    assert "BASH_SOURCE[0]" in start_text and "main.py" in start_text, (
        "start.sh 缺少 main.py 锚点自适应"
    )
    assert 'exec "$PYTHON_EXE" main.py' in start_text, "start.sh 未 exec python main.py"
    assert "XIAOYOU_START_LOCAL_LLM=1" in gpu_text, (
        "start_venv_core.sh 缺少本地 LLM 开关"
    )
    print("PASS: Linux 主启动器可执行、默认 venv_cpu、路径自适应、GPU 入口开关齐备")


if __name__ == "__main__":
    main()
