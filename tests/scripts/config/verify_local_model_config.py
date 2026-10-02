"""校验本地模型配置的统一性：真源声明、磁盘一致、无残留硬编码。

背景（2026-09-24）：本地模型路径曾同时写在 modeling.yaml、
integrated_config.py、model_detector.py、core/modules/llm/module.py 四处，
彼此不一致，导致自动探测出来的模型与配置对不上（甚至把 mmproj 当成主模型）。
统一后的约定是：本地模型的路径与候选清单只在
``config/yaml/sections/modeling.yaml`` 声明一次，其他模块一律从 settings 读取。
本脚本守住这条约定，并校验声明与磁盘实际文件一致。
"""

from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from config.integrated_config import get_settings  # noqa: E402
from config.model_detector import (  # noqa: E402
    declared_model_paths,
    get_model_watch_paths,
    resolve_models_dir,
)


# 统一后不应再出现在运行期代码里的旧模型名 / 旧路径
FORBIDDEN_PATTERNS = (
    "Qwen2.5-7B-Instruct-abliterated",
    "L3-8B-Stheno",
    "Qwen3-8B-Hivemind",
    "Qwen2___5-7B",
    "./models/qwen",
    "models/whisper",
    "models/vision/Qwen2-VL-2B",
    "Illustrious-XL-v2.0",
    "ponyDiffusionV6XL",
    "sensitive_v10.safetensors",
    "download_embedding_model.py",
)

# 只扫描运行期代码；docs/、Question_Reviewer/ 等历史记录不属于本约定范围
SCAN_DIRS = ("config", "core", "routers", "services", "memory", "maintenance")

# Forge 上游（webui-user.bat 那套）已从本机移除，我们的适配代码按约定保留、
# 其中的底模映射也不再参与运行（image_provider 已切到 comfyui），故不纳入扫描
SCAN_SKIP_FILES = (
    "core/modules/forge_client.py",
    "core/image/_image_forge_backend_mixin.py",
)


def _iter_python_files():
    for name in SCAN_DIRS:
        base = PROJECT_ROOT / name
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            if path.relative_to(PROJECT_ROOT).as_posix() in SCAN_SKIP_FILES:
                continue
            yield path


def _is_outside_project(path: Path) -> bool:
    """判断路径是否落在项目目录之外（典型情况：模型放在外接盘/另一个卷）。"""
    try:
        path.resolve().relative_to(PROJECT_ROOT)
        return False
    except ValueError:
        return True


def verify_declared_paths_exist() -> None:
    """当前生效的本地模型必须可达；候选允许部分缺失但声明不能为空。

    项目内的路径缺失视为配置错误（硬失败）；项目外的绝对路径缺失只告警——
    那通常是外接盘没插（见 config/README.md 的「把模型放外接盘」）。
    """
    model = get_settings().model

    text_path = str(model.text_path or "").strip()
    assert text_path, "model.text_path 为空：请检查 modeling.yaml 的 model.path"
    text_path_obj = Path(text_path)
    if text_path_obj.exists():
        print(f"  文本模型: {text_path}")
    elif _is_outside_project(text_path_obj):
        print(
            f"  [告警] 文本模型在项目目录之外且当前不可达：{text_path}"
            "（外接盘未挂载时属预期，插上盘再复跑一次即可确认）"
        )
    else:
        raise AssertionError(f"本地文本模型不存在: {text_path}")

    whisper_path = str(model.whisper_path or "").strip()
    assert whisper_path, "model.whisper_path 为空：请检查 modeling.yaml"
    assert Path(whisper_path).exists(), f"语音识别模型不存在: {whisper_path}"

    for field in ("llm_candidates", "image_candidates", "asr_candidates"):
        declared = [str(item) for item in (getattr(model, field) or [])]
        assert declared, f"modeling.yaml 未声明 {field}（真源缺失）"
        missing = [item for item in declared if not (PROJECT_ROOT / item).exists()]
        print(f"  {field}: {len(declared)} 条声明，{len(missing)} 条当前不存在（候选允许缺失）")

    assert str(model.image_provider).strip().lower() == "comfyui", (
        "生图默认后端应为 comfyui（Forge 上游已从本机移除），"
        f"当前为 {model.image_provider}"
    )


def verify_image_aliases_point_to_disk() -> None:
    """生图底模别名表必须全部命中 check_point 目录，默认/备用底模必须是表里的别名。"""
    settings = get_settings()
    model = settings.model
    aliases = {str(k): str(v) for k, v in (model.image_model_aliases or {}).items()}
    assert aliases, "model.image_model_aliases 未声明（生图底模别名表缺失）"

    check_point_dir = resolve_models_dir(settings, PROJECT_ROOT) / "Image" / "check_point"
    if check_point_dir.is_dir():
        for alias, filename in aliases.items():
            target = check_point_dir / filename
            assert target.exists(), f"底模别名 {alias} -> {filename} 磁盘不存在: {target}"
        print(f"  底模别名 {len(aliases)} 条全部命中 {check_point_dir.name} 目录")
    else:
        # 生图资产允许整体挪到外接盘（见 config/README.md 的「把模型放外接盘」）：
        # 我们的代码只把文件名发给 ComfyUI，文件位置由 ComfyUI 自己的
        # extra_model_paths.yaml 决定，因此这里只告警、不判失败。
        print(
            f"  [告警] 本机没有 {check_point_dir}：生图资产可能已移到外接盘，"
            "跳过别名存在性校验（ComfyUI 侧路径由 extra_model_paths.yaml 负责）"
        )

    for field in ("default_image_model", "fallback_image_model"):
        value = str(getattr(model, field) or "").strip()
        assert value, f"model.{field} 为空"
        assert value in aliases, (
            f"model.{field}={value} 不在 image_model_aliases 中："
            "默认底模应写成别名，且别名表要指向磁盘上真实存在的文件"
        )


def verify_no_hardcoded_model_names() -> None:
    """运行期代码里不应再出现旧模型名，模型名只允许在 modeling.yaml 出现。"""
    hits = []
    scanned = 0
    for path in _iter_python_files():
        scanned += 1
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in FORBIDDEN_PATTERNS:
            if pattern in text:
                hits.append(f"{path.relative_to(PROJECT_ROOT)} -> {pattern}")
    assert not hits, "仍有硬编码的旧模型名/旧路径：\n    " + "\n    ".join(hits)
    print(f"  已扫描 {scanned} 个运行期 py 文件，无旧模型名残留")


def verify_watch_paths_clean() -> None:
    """模型探测的监控路径应来自声明或固定位置，不再包含已移除的 Forge 目录。"""
    settings = get_settings()
    models_dir = resolve_models_dir(settings, PROJECT_ROOT)
    watch = [str(path) for path in get_model_watch_paths(models_dir, settings, PROJECT_ROOT)]

    stale = [item for item in watch if "stable-diffusion-webui-forge-main" in item]
    assert not stale, f"模型探测仍在监控已移除的 Forge 目录: {stale}"

    for declared in declared_model_paths(settings):
        resolved = str(
            declared if Path(declared).is_absolute() else PROJECT_ROOT / declared
        )
        assert resolved in watch, f"声明路径未被纳入探测监控: {declared}"
    print(f"  探测监控 {len(watch)} 条路径，全部来自声明或固定位置")


def verify_persona_source_paths() -> None:
    """人设配置里的语料 source_path 必须指向真实存在的文件。"""
    stale_marker = "ling_data/import_sources"
    hits = []
    for path in (PROJECT_ROOT / "core/character/configs").rglob("*.json"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if stale_marker in text:
            hits.append(str(path.relative_to(PROJECT_ROOT)))
    assert not hits, f"人设配置仍指向不存在的语料目录 {stale_marker}: {hits}"

    pairs = PROJECT_ROOT / "data/pretrained/私聊_玲🍀.pairs.txt"
    assert pairs.exists(), f"Ling语料不存在: {pairs}"
    print(f"  人设语料存在: {pairs.name}")


def main() -> None:
    print("1/5 校验 modeling.yaml 声明的本地模型路径")
    verify_declared_paths_exist()
    print("2/5 校验生图底模别名与磁盘一致")
    verify_image_aliases_point_to_disk()
    print("3/5 校验运行期代码无硬编码旧模型名")
    verify_no_hardcoded_model_names()
    print("4/5 校验模型探测监控路径")
    verify_watch_paths_clean()
    print("5/5 校验人设语料 source_path")
    verify_persona_source_paths()
    print("本地模型配置统一性验证通过")


if __name__ == "__main__":
    main()
