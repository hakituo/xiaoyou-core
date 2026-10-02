"""验证依赖锁文件与当前虚拟环境的完整性。"""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import subprocess
import sys
from collections import Counter
from pathlib import Path

from packaging.requirements import Requirement


PROJECT_ROOT = Path(__file__).resolve().parents[3]
REQUIREMENTS_DIR = PROJECT_ROOT / "requirements"


def _read_pins(file_name: str) -> dict[str, str]:
    """读取 requirements 文件中的精确版本。"""
    pins: dict[str, str] = {}
    for raw_line in (REQUIREMENTS_DIR / file_name).read_text(
        encoding="utf-8"
    ).splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "--")):
            continue
        requirement = Requirement(line)
        exact_versions = [
            item.version for item in requirement.specifier if item.operator == "=="
        ]
        if len(exact_versions) != 1:
            raise AssertionError(f"{file_name} 必须使用单一精确版本: {line}")
        package_name = requirement.name.lower()
        if package_name in pins:
            raise AssertionError(f"{file_name} 存在重复依赖: {requirement.name}")
        pins[package_name] = exact_versions[0]
    return pins


def _verify_requirement_files() -> None:
    """验证已知的跨包兼容组合。"""
    base = _read_pins("base.txt")
    cpu = _read_pins("cpu.txt")
    gpu = _read_pins("gpu.txt")

    assert cpu == {
        "torch": "2.13.0+cpu",
        "torchvision": "0.28.0+cpu",
        "torchaudio": "2.11.0+cpu",
    }
    assert gpu == {
        "torch": "2.11.0",
        "torchvision": "0.26.0+cu128",
        "torchaudio": "2.11.0+cu128",
    }

    expected_shared = {
        "deprecated": "1.2.18",
        "protobuf": "3.20.2",
        "googleapis-common-protos": "1.65.0",
        "importlib-metadata": "8.4.0",
        "opentelemetry-api": "1.27.0",
        "opentelemetry-exporter-otlp-proto-common": "1.27.0",
        "opentelemetry-exporter-otlp-proto-grpc": "1.27.0",
        "opentelemetry-proto": "1.27.0",
        "opentelemetry-sdk": "1.27.0",
        "opentelemetry-semantic-conventions": "0.48b0",
        "gradio": "6.15.1",
        "gradio-client": "2.5.0",
        "hf-gradio": "0.4.1",
        "opencv-python": "4.11.0.86",
        "safehttpx": "0.1.7",
        "wrapt": "1.17.3",
        "zipp": "4.1.0",
    }
    for package_name, expected_version in expected_shared.items():
        assert base.get(package_name) == expected_version, (
            f"base.txt 中 {package_name} 应锁定为 {expected_version}"
        )

    cpu_text = (REQUIREMENTS_DIR / "cpu.txt").read_text(encoding="utf-8")
    gpu_text = (REQUIREMENTS_DIR / "gpu.txt").read_text(encoding="utf-8")
    assert "--index-url https://download.pytorch.org/whl/cpu" in cpu_text
    assert "--index-url https://download.pytorch.org/whl/cu128" in gpu_text


def _verify_environment(expected_environment: str) -> None:
    """验证当前解释器的包元数据和关键运行时。"""
    site_packages = Path(sys.prefix) / "Lib" / "site-packages"
    invalid_entries = sorted(
        item.name for item in site_packages.iterdir() if item.name.startswith(("~", "-"))
    )
    assert not invalid_entries, f"发现异常安装残留: {invalid_entries}"

    distribution_names = [
        (distribution.metadata.get("Name") or "").lower()
        for distribution in importlib.metadata.distributions(path=[str(site_packages)])
    ]
    duplicates = sorted(
        name for name, count in Counter(distribution_names).items() if name and count > 1
    )
    assert not duplicates, f"发现重复 dist-info: {duplicates}"

    pip_check = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert pip_check.returncode == 0, pip_check.stdout + pip_check.stderr

    import torch
    import torchaudio
    import torchvision
    import transformers
    from accelerate import Accelerator

    assert transformers.is_torch_available()
    assert Accelerator is not None
    assert importlib.util.find_spec("gradio") is not None
    assert importlib.metadata.version("protobuf") == "3.20.2"

    owners = importlib.metadata.packages_distributions().get("cv2") or []
    assert owners == ["opencv-python"], f"cv2 所属包异常: {owners}"

    if expected_environment == "cpu":
        assert torch.__version__ == "2.13.0+cpu"
        assert torchvision.__version__ == "0.28.0+cpu"
        assert torchaudio.__version__ == "2.11.0+cpu"
        assert not torch.cuda.is_available()
    else:
        assert torch.__version__ == "2.11.0+cu128"
        assert torchvision.__version__ == "0.26.0+cu128"
        assert torchaudio.__version__ == "2.11.0+cu128"
        assert torch.cuda.is_available()
        tensor = torch.tensor([2.0], device="cuda")
        assert (tensor * tensor).item() == 4.0


def main() -> None:
    """运行锁文件检查，并按需检查当前解释器。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", choices=("cpu", "gpu"))
    args = parser.parse_args()

    _verify_requirement_files()
    if args.environment:
        _verify_environment(args.environment)
    print("PASS: 运行时依赖约束与环境完整性检查通过")


if __name__ == "__main__":
    main()
