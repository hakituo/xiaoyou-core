"""
模型目录解析与自动探测
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from config.cache_manager import build_path_signature

logger = logging.getLogger("config")


def get_normalize_local_path():
    try:
        import importlib.util
        import sys
        _utils_path = str(
            Path(__file__).resolve().parent.parent
            / "core" / "modules" / "llm" / "utils.py"
        )
        spec = importlib.util.spec_from_file_location(
            "core.modules.llm.utils", _utils_path,
            submodule_search_locations=[],
        )
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            sys.modules["core.modules.llm.utils"] = mod
            spec.loader.exec_module(mod)
            return mod.normalize_local_path
    except Exception:

        def fallback_normalize(path):
            if not path:
                return ""
            return os.path.normcase(os.path.abspath(str(path)))

        return fallback_normalize


def resolve_models_dir(settings: Any, project_root: Path) -> Path:
    root = Path(project_root)
    model_dir = str(getattr(settings.model, "model_dir", "") or "").strip()
    models_dir = Path(model_dir) if model_dir else (root / "models")
    if not models_dir.is_absolute():
        models_dir = root / models_dir
    return models_dir.resolve()


# 即使 modeling.yaml 没声明候选，也固定监控这些位置
_BASE_WATCH_SUBDIRS: tuple = (
    ("llm",),
    ("Image", "check_point"),
    ("voice", "GPT"),
    ("voice", "SoVITS"),
)

# modeling.yaml 里声明“候选清单”与“当前生效路径”的字段名
_CANDIDATE_FIELDS: tuple = (
    "llm_candidates",
    "image_candidates",
    "vision_candidates",
    "asr_candidates",
)
_ACTIVE_PATH_FIELDS: tuple = (
    "text_path",
    "vision_path",
    "whisper_path",
    "image_gen_path",
)


def declared_model_paths(settings: Any) -> list[str]:
    """汇总 modeling.yaml 声明的本地模型路径（候选清单 + 当前生效值）。

    本地模型的唯一真源是 config/yaml/sections/modeling.yaml，
    本模块只消费声明，不内置任何模型名。
    """
    paths: list[str] = []
    for field in _CANDIDATE_FIELDS:
        for item in getattr(settings.model, field, None) or []:
            text = str(item or "").strip()
            if text:
                paths.append(text)
    for field in _ACTIVE_PATH_FIELDS:
        text = str(getattr(settings.model, field, "") or "").strip()
        if text:
            paths.append(text)
    return paths


def resolve_declared_path(candidate: str, project_root: Path) -> Path:
    """把声明里的相对路径按项目根解析为绝对路径。"""
    path = Path(str(candidate))
    if not path.is_absolute():
        path = Path(project_root) / path
    return path


def first_existing_path(candidates: list, project_root: Path) -> str:
    """按声明顺序返回第一个存在的候选路径；都不存在则返回空串。"""
    for candidate in candidates or []:
        path = resolve_declared_path(candidate, project_root)
        try:
            if path.exists():
                return str(path)
        except OSError:
            continue
    return ""


def get_model_watch_paths(
    models_dir: Path, settings: Any = None, project_root: Optional[Path] = None
) -> list[Path]:
    """模型探测缓存需要监控的路径。

    由 modeling.yaml 声明的候选路径（及其父目录）加固定位置派生，
    不再写死具体模型文件名——模型换了只要改 modeling.yaml。
    """
    paths: list[Path] = [Path(models_dir)]
    for parts in _BASE_WATCH_SUBDIRS:
        paths.append(Path(models_dir).joinpath(*parts))
    if settings is not None and project_root is not None:
        for candidate in declared_model_paths(settings):
            candidate_path = resolve_declared_path(candidate, project_root)
            paths.append(candidate_path)
            paths.append(candidate_path.parent)

    unique: list[Path] = []
    seen: set = set()
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def build_model_detection_signature(settings: Any, project_root: Path) -> Dict[str, Any]:
    models_dir = resolve_models_dir(settings, project_root)
    return {
        "models_dir": str(models_dir),
        "env": {
            "XIAOYOU_DISABLE_LOCAL_LLM": os.getenv("XIAOYOU_DISABLE_LOCAL_LLM", ""),
            "XIAOYOU_TEXT_MODEL_PATH": os.getenv("XIAOYOU_TEXT_MODEL_PATH", ""),
            "XIAOYOU_SD_MODEL_PATH": os.getenv("XIAOYOU_SD_MODEL_PATH", ""),
        },
        "watch_paths": [
            build_path_signature(path)
            for path in get_model_watch_paths(models_dir, settings, project_root)
        ],
    }


def build_model_cache_entry(
    settings: Any, detected_paths: Dict[str, str], project_root: Path
) -> Dict[str, Any]:
    return {
        "signature": build_model_detection_signature(settings, project_root),
        "detected_paths": detected_paths,
    }


def apply_detected_model_paths(settings: Any, detected_paths: Dict[str, str]):
    normalize_local_path = get_normalize_local_path()
    text_path = str(detected_paths.get("text_path", "") or "").strip()
    if text_path and (
        not settings.model.text_path or not os.path.exists(settings.model.text_path)
    ):
        settings.model.text_path = normalize_local_path(text_path)

    image_gen_path = str(detected_paths.get("image_gen_path", "") or "").strip()
    if image_gen_path and not settings.model.image_gen_path:
        settings.model.image_gen_path = image_gen_path

    vision_path = str(detected_paths.get("vision_path", "") or "").strip()
    if vision_path and not settings.model.vision_path:
        settings.model.vision_path = vision_path

    whisper_path = str(detected_paths.get("whisper_path", "") or "").strip()
    if whisper_path and not settings.model.whisper_path:
        settings.model.whisper_path = whisper_path

    if hasattr(settings, "voice"):
        gpt_model_path = str(detected_paths.get("gpt_model_path", "") or "").strip()
        if gpt_model_path and not settings.voice.gpt_model_path:
            settings.voice.gpt_model_path = gpt_model_path

        sovits_model_path = str(
            detected_paths.get("sovits_model_path", "") or ""
        ).strip()
        if sovits_model_path and not settings.voice.sovits_model_path:
            settings.voice.sovits_model_path = sovits_model_path


def get_cached_model_detection(
    settings: Any, startup_cache: Dict[str, Any], project_root: Path
) -> Optional[Dict[str, str]]:
    entry = startup_cache.get("model_detection")
    if not isinstance(entry, dict):
        return None
    if entry.get("signature") != build_model_detection_signature(settings, project_root):
        return None
    detected_paths = entry.get("detected_paths")
    if not isinstance(detected_paths, dict):
        return None
    for path in detected_paths.values():
        if path and not Path(path).exists():
            return None
    logger.info("Loaded model auto-detection from startup cache")
    return detected_paths


def auto_detect_models(settings: Any, project_root: Path) -> Dict[str, str]:
    detected_paths: Dict[str, str] = {}
    models_dir = str(resolve_models_dir(settings, project_root))
    logger.info(f"Model auto-detection using base dir: {models_dir}")

    if not settings.model.text_path or not os.path.exists(settings.model.text_path):
        llm_path = os.environ.get("XIAOYOU_TEXT_MODEL_PATH", "").strip()
        if not llm_path:
            llm_path = first_existing_path(
                list(settings.model.llm_candidates), Path(project_root)
            )
            if llm_path:
                logger.info(f"Auto-detected LLM Model (Declared): {llm_path}")

        if not llm_path:
            # 兜底扫描：只扫模型根目录与 models/llm，且排除 mmproj。
            # mmproj 是视觉投影层（如 mmproj-BF16.gguf），不能被当成可独立加载的语言模型。
            for scan_dir in (models_dir, os.path.join(models_dir, "llm")):
                if not os.path.isdir(scan_dir):
                    continue
                found = [
                    os.path.join(scan_dir, name)
                    for name in os.listdir(scan_dir)
                    if name.lower().endswith(".gguf") and "mmproj" not in name.lower()
                ]
                if found:
                    found.sort(key=os.path.getmtime, reverse=True)
                    llm_path = found[0]
                    logger.info(f"Auto-detected LLM Model (Scan): {llm_path}")
                    break

        if llm_path:
            normalize_local_path = get_normalize_local_path()
            settings.model.text_path = normalize_local_path(llm_path)
            detected_paths["text_path"] = settings.model.text_path

    if not settings.model.image_gen_path:
        sd_path = os.environ.get("XIAOYOU_SD_MODEL_PATH", "").strip()
        if not sd_path:
            sd_path = first_existing_path(
                list(settings.model.image_candidates), Path(project_root)
            )
            if sd_path:
                logger.info(f"Auto-detected SD Model: {sd_path}")
        if sd_path:
            settings.model.image_gen_path = sd_path
            detected_paths["image_gen_path"] = sd_path

    if not settings.model.vision_path:
        vision_path = first_existing_path(
            list(settings.model.vision_candidates), Path(project_root)
        )
        if vision_path:
            logger.info(f"Auto-detected Vision Model: {vision_path}")
            settings.model.vision_path = vision_path
            detected_paths["vision_path"] = vision_path

    if hasattr(settings, "voice"):
        if not settings.voice.gpt_model_path:
            gpt_candidates = [
                os.path.join(models_dir, "voice", "GPT", "流萤-e10.ckpt"),
            ]
            gpt_dir = os.path.join(models_dir, "voice", "GPT")
            if os.path.exists(gpt_dir):
                for file_name in os.listdir(gpt_dir):
                    if file_name.endswith(".ckpt"):
                        gpt_candidates.append(os.path.join(gpt_dir, file_name))
            for path in gpt_candidates:
                if os.path.exists(path):
                    settings.voice.gpt_model_path = path
                    detected_paths["gpt_model_path"] = path
                    logger.info(f"Auto-detected GPT Model: {path}")
                    break

        if not settings.voice.sovits_model_path:
            sovits_candidates = [
                os.path.join(models_dir, "voice", "SoVITS", "Aveline_Violet_Mix.pth"),
            ]
            sovits_dir = os.path.join(models_dir, "voice", "SoVITS")
            if os.path.exists(sovits_dir):
                for file_name in os.listdir(sovits_dir):
                    if file_name.endswith(".pth"):
                        sovits_candidates.append(os.path.join(sovits_dir, file_name))
            for path in sovits_candidates:
                if os.path.exists(path):
                    settings.voice.sovits_model_path = path
                    detected_paths["sovits_model_path"] = path
                    logger.info(f"Auto-detected SoVITS Model: {path}")
                    break

    if not settings.model.whisper_path:
        whisper_path = first_existing_path(
            list(settings.model.asr_candidates), Path(project_root)
        )
        if whisper_path:
            logger.info(f"Auto-detected Whisper Model: {whisper_path}")
            settings.model.whisper_path = whisper_path
            detected_paths["whisper_path"] = whisper_path

    return detected_paths
