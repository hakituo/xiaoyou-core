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


def get_model_watch_paths(models_dir: Path) -> list[Path]:
    return [
        models_dir,
        models_dir / "llm",
        models_dir / "qwen",
        models_dir / "Image" / "check_point",
        models_dir
        / "Image"
        / "stable-diffusion-webui-forge-main"
        / "models"
        / "Stable-diffusion",
        models_dir / "vision",
        models_dir / "Qwen2-VL-7B-instruct" / "qwen" / "Qwen2-VL-7B-Instruct",
        models_dir / "voice" / "GPT",
        models_dir / "voice" / "SoVITS",
        models_dir / "whisper",
    ]


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
            build_path_signature(path) for path in get_model_watch_paths(models_dir)
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
            potential_models = [
                os.path.join(models_dir, "llm", "L3-8B-Stheno-v3.2-Q4_K_M.gguf"),
                os.path.join(
                    models_dir,
                    "llm",
                    "Qwen3-8B-Hivemind-Inst-Hrtic-Ablit-Uncensored-Q5_K_M-imat.gguf",
                ),
                os.path.join(models_dir, "qwen", "Qwen2___5-7B-Instruct-f16.gguf"),
            ]
            for path in potential_models:
                if os.path.exists(path):
                    llm_path = path
                    logger.info(f"Auto-detected LLM Model (Priority): {llm_path}")
                    break

            if not llm_path and os.path.exists(models_dir):
                import glob

                search_paths = [
                    os.path.join(models_dir, "*.gguf"),
                    os.path.join(models_dir, "llm", "*.gguf"),
                    os.path.join(models_dir, "qwen", "*.gguf"),
                ]
                for search_path in search_paths:
                    files = glob.glob(search_path)
                    if files:
                        files.sort(key=os.path.getmtime, reverse=True)
                        llm_path = files[0]
                        logger.info(f"Auto-detected LLM Model (Scan): {llm_path}")
                        break

        if llm_path:
            normalize_local_path = get_normalize_local_path()
            settings.model.text_path = normalize_local_path(llm_path)
            detected_paths["text_path"] = settings.model.text_path

    if not settings.model.image_gen_path:
        sd_path = os.environ.get("XIAOYOU_SD_MODEL_PATH", "").strip()
        if not sd_path:
            potential_paths = [
                os.path.join(
                    models_dir,
                    "Image",
                    "check_point",
                    "NoobAI-XL-Vpred-v1.0.safetensors",
                ),
                os.path.join(
                    models_dir,
                    "Image",
                    "check_point",
                    "Illustrious-XL-v2.0.safetensors",
                ),
                os.path.join(
                    models_dir,
                    "Image",
                    "stable-diffusion-webui-forge-main",
                    "models",
                    "Stable-diffusion",
                    "juggernautXL_ragnarokBy.safetensors",
                ),
                os.path.join(
                    models_dir,
                    "Image",
                    "stable-diffusion-webui-forge-main",
                    "models",
                    "Stable-diffusion",
                    "ponyDiffusionV6XL_v6StartWithThisOne.safetensors",
                ),
                os.path.join(
                    models_dir,
                    "Image",
                    "stable-diffusion-webui-forge-main",
                    "models",
                    "Stable-diffusion",
                    "ghostmix_v20Bakedvae.safetensors",
                ),
                os.path.join(
                    models_dir,
                    "Image",
                    "stable-diffusion-webui-forge-main",
                    "models",
                    "Stable-diffusion",
                    "chilloutmix_NiPrunedFp32Fix.safetensors",
                ),
            ]
            for path in potential_paths:
                if os.path.exists(path):
                    sd_path = path
                    logger.info(f"Auto-detected SD Model: {sd_path}")
                    break
        if sd_path:
            settings.model.image_gen_path = sd_path
            detected_paths["image_gen_path"] = sd_path

    if not settings.model.vision_path:
        vision_path = ""
        candidates = [
            Path(models_dir) / "vision" / "Qwen2-VL-2B",
            Path(models_dir) / "Qwen2-VL-7B-instruct" / "qwen" / "Qwen2-VL-7B-Instruct",
        ]
        for path in candidates:
            if path.exists():
                vision_path = str(path)
                logger.info(f"Auto-detected Vision Model: {vision_path}")
                break
        if vision_path:
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
        whisper_path = ""
        whisper_candidates = [
            os.path.join(models_dir, "whisper", "large-v3"),
            os.path.join(models_dir, "whisper", "base"),
            os.path.join(models_dir, "whisper", "small"),
        ]
        for path in whisper_candidates:
            if os.path.exists(path):
                whisper_path = path
                logger.info(f"Auto-detected Whisper Model: {whisper_path}")
                break
        if whisper_path:
            settings.model.whisper_path = whisper_path
            detected_paths["whisper_path"] = whisper_path

    return detected_paths
