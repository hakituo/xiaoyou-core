"""验证 QQ 启动入口默认使用与主程序一致的 CPU 虚拟环境。"""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _read(relative_path: str) -> str:
    """读取启动脚本文本。"""
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def main() -> None:
    """检查各 QQ 启动入口的环境优先级与 Adapter 入口。"""
    batch_launcher_paths = (
        "start_scripts/start_qq_bot.bat",
        "start_multi_qq_bot.bat",
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


if __name__ == "__main__":
    main()
