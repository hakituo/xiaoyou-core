import base64
import os
import uuid
from typing import Any, Dict, Optional

from core.utils.logger import get_logger

logger = get_logger("AVELINE_RESPONSE_MEDIA")


def _is_enabled_env(name: str) -> bool:
    return str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}


async def enrich_result_with_auto_media(
    service: Any,
    result: Dict[str, Any],
    metadata: Dict[str, Any],
    response_text: str,
    voice_id: Optional[str],
    conversation_id: str,
) -> Dict[str, Any]:
    try:
        await _apply_auto_image(result, metadata)
    except Exception as e:
        logger.error(f"Auto image generation failed: {e}")

    try:
        await _apply_auto_tts(result, response_text, voice_id)
    except Exception as e:
        logger.error(f"Auto voice generation failed: {e}")

    if result.get("message_type") == "voice" and not (
        result.get("audio_base64") or result.get("audio_path")
    ):
        result.pop("message_type", None)

    try:
        await _append_assistant_metadata(
            service=service,
            conversation_id=conversation_id,
            response_text=response_text,
            result=result,
        )
    except Exception as e:
        logger.error(f"保存历史记录失败: {e}")

    return result


async def _apply_auto_image(result: Dict[str, Any], metadata: Dict[str, Any]) -> None:
    allow_image_base64 = _is_enabled_env("XIAOYOU_SEND_IMAGE_BASE64")
    try:
        max_b64_bytes = int(os.getenv("XIAOYOU_IMAGE_BASE64_MAX_BYTES", "2097152") or "2097152")
    except Exception:
        max_b64_bytes = 2097152

    if allow_image_base64 and metadata.get("image_base64"):
        result["image_base64"] = metadata.get("image_base64")

    if metadata.get("image_prompt") and ("image_url" not in result and "image_path" not in result):
        from config.integrated_config import get_settings
        from core.image.image_manager import ImageGenerationConfig, get_image_manager

        settings = get_settings()
        manager = await get_image_manager()
        config = ImageGenerationConfig(
            prompt=metadata["image_prompt"],
            width=settings.model.image_gen_width,
            height=settings.model.image_gen_height,
            num_inference_steps=settings.model.image_gen_steps,
        )
        gen_result = await manager.generate_image(
            prompt=metadata["image_prompt"],
            model_id=settings.model.default_image_model,
            config=config,
            save_to_file=True,
        )

        if gen_result.get("success"):
            if gen_result.get("image_path"):
                result["image_path"] = gen_result.get("image_path")
            if gen_result.get("url"):
                result["image_url"] = gen_result.get("url")

            if (
                allow_image_base64
                and gen_result.get("image_path")
                and isinstance(max_b64_bytes, int)
                and max_b64_bytes > 0
            ):
                try:
                    img_path = str(gen_result.get("image_path"))
                    if os.path.exists(img_path) and os.path.getsize(img_path) <= max_b64_bytes:
                        with open(img_path, "rb") as img_file:
                            b64_string = base64.b64encode(img_file.read()).decode("utf-8")
                        result["image_base64"] = f"data:image/png;base64,{b64_string}"
                except Exception:
                    pass


async def _apply_auto_tts(
    result: Dict[str, Any], response_text: str, voice_id: Optional[str]
) -> None:
    cfg_auto_tts = False
    try:
        from core.core_engine.config_manager import get_config_manager

        cfg_auto_tts = bool(
            get_config_manager().get(
                "limits.auto_tts_in_message",
                get_config_manager().get("voice.auto_tts_in_message", False),
            )
        )
    except Exception:
        cfg_auto_tts = False

    target_voice_id = result.get("voice_id") or voice_id
    if not (cfg_auto_tts and target_voice_id and response_text):
        return

    from core.voice import get_tts_manager

    tts_manager = await get_tts_manager()
    if (
        "." in target_voice_id
        or "/" in target_voice_id
        or os.sep in target_voice_id
    ) and hasattr(tts_manager.engine, "set_gpt_weights"):
        try:
            await tts_manager.engine.set_gpt_weights(target_voice_id)
        except Exception:
            pass

    audio_data = await tts_manager.synthesize(response_text, voice=target_voice_id)
    if audio_data is None or len(audio_data) <= 0:
        return

    project_root = os.getcwd()
    out_dir = os.path.join(project_root, "output", "voice")
    os.makedirs(out_dir, exist_ok=True)
    fname = f"auto_tts_{uuid.uuid4().hex[:8]}.wav"
    audio_path = os.path.join(out_dir, fname)
    sr = getattr(tts_manager, "sample_rate", 24000)
    import soundfile as sf

    sf.write(audio_path, audio_data, sr)
    if os.path.exists(audio_path):
        with open(audio_path, "rb") as audio_file:
            b64_string = base64.b64encode(audio_file.read()).decode("utf-8")
        result["audio_base64"] = f"data:audio/wav;base64,{b64_string}"
        result["audio_path"] = audio_path
        result["voice_id"] = target_voice_id


async def _append_assistant_metadata(
    service: Any,
    conversation_id: str,
    response_text: str,
    result: Dict[str, Any],
) -> None:
    if not getattr(service, "chat_agent", None):
        return

    mm = service.chat_agent._get_memory_manager(conversation_id)
    assistant_metadata = {
        "image_url": result.get("image_url"),
        "image_path": result.get("image_path"),
        "audio_base64": result.get("audio_base64"),
        "audio_path": result.get("audio_path"),
        "voice_id": result.get("voice_id"),
        "message_type": result.get("message_type"),
        "image_prompt": result.get("image_prompt"),
    }
    if _is_enabled_env("XIAOYOU_SEND_IMAGE_BASE64"):
        assistant_metadata["image_base64"] = result.get("image_base64")
    assistant_metadata = {k: v for k, v in assistant_metadata.items() if v is not None}
    if not assistant_metadata:
        return

    updated = False
    with mm.lock:
        for mem in reversed(getattr(mm, "short_term_memory", []) or []):
            if mem.get("source") == "assistant" and mem.get("content") == response_text:
                meta = mem.get("metadata")
                if not isinstance(meta, dict):
                    meta = {}
                meta.update(assistant_metadata)
                mem["metadata"] = meta
                updated = True
                break
        if not updated:
            for mem in reversed(list(getattr(mm, "weighted_memories", {}).values())):
                if mem.get("source") == "assistant" and mem.get("content") == response_text:
                    meta = mem.get("metadata")
                    if not isinstance(meta, dict):
                        meta = {}
                    meta.update(assistant_metadata)
                    mem["metadata"] = meta
                    updated = True
                    break
    if updated and hasattr(mm, "_schedule_save"):
        mm._schedule_save()
