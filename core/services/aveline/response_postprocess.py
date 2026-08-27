import asyncio
import base64
import io
import os
import re
import time
import uuid
from typing import Any, Dict, Optional, Tuple

from core.utils.logger import get_logger

logger = get_logger("AVELINE_RESPONSE_POSTPROCESS")


async def postprocess_generated_response(
    service: Any,
    *,
    user_input: str,
    conversation_id: str,
    full_response: str,
    metadata: Dict[str, Any],
    model_hint: Optional[str],
    save_history: bool,
    start_time: float,
) -> Tuple[str, Dict[str, Any]]:
    original_full_response = full_response.strip()
    final_content, emotion_label = service.chat_agent.extract_and_strip_emotion(full_response)
    final_content = await _maybe_rewrite_response(
        service=service,
        final_content=final_content,
        user_input=user_input,
        conversation_id=conversation_id,
        model_hint=model_hint,
    )

    final_emotion_label = _apply_emotion_metadata(
        service=service,
        conversation_id=conversation_id,
        metadata=metadata,
        emotion_label=emotion_label,
    )
    if final_emotion_label:
        _trigger_vts_emotion(final_emotion_label)

    final_content, metadata = await _handle_media_tags(
        service=service,
        final_content=final_content,
        metadata=metadata,
        conversation_id=conversation_id,
        save_history=save_history,
    )

    final_content = _fallback_when_empty(final_content, original_full_response, emotion_label)
    metadata["processing_time_ms"] = int((time.time() - start_time) * 1000)
    return final_content, metadata


async def _maybe_rewrite_response(
    *,
    service: Any,
    final_content: str,
    user_input: str,
    conversation_id: str,
    model_hint: Optional[str],
) -> str:
    try:
        from config.integrated_config import get_settings

        rewrite_cfg = getattr(get_settings().chat, "rewrite", None)
    except Exception:
        rewrite_cfg = None

    if not (
        rewrite_cfg
        and bool(getattr(rewrite_cfg, "enabled", False))
        and isinstance(final_content, str)
        and final_content.strip()
    ):
        return final_content

    try:
        from core.managers.preference_manager import get_preference_manager

        prefs = get_preference_manager()
        if prefs.get_mode() == "privacy":
            return final_content
    except Exception:
        pass

    max_src = int(getattr(rewrite_cfg, "max_source_chars", 0) or 0)
    if max_src <= 0:
        max_src = 900

    tag_patterns = [r"\[GEN_IMG:[^\]]+\]", r"\[VOICE:[^\]]+\]"]
    preserved_tags = []
    for pat in tag_patterns:
        for m in re.finditer(pat, final_content, flags=re.IGNORECASE):
            preserved_tags.append(m.group(0))

    visible_text = final_content
    for pat in tag_patterns:
        visible_text = re.sub(pat, "", visible_text, flags=re.IGNORECASE)
    visible_text = str(visible_text or "").strip()
    if not visible_text or len(visible_text) > max_src:
        return final_content

    rewrite_messages = [
        {
            "role": "system",
            "content": (
                "你是对话润色器。把原回复改写得更像真人口语、更贴近角色语气。"
                "保持事实与信息不变，不要添加新观点。"
                "不要出现‘作为AI/助手/模型’之类自我说明，不要模板化道歉/感谢。"
                "语气要跟着用户走：用户更正式就更正式，用户更口语就更口语；用户主要用英文就尽量保持英文。"
                "默认使用‘你’进行称呼与指代；除非用户主动使用‘您/请您’或明确要求敬语，否则不要用‘您’，也不要写成客服腔。"
                "默认短句、自然停顿；语气词可以有但别刻意、别堆。"
                "只输出润色后的最终回复正文，不要解释、不加标题。"
            ),
        },
        {"role": "user", "content": f"用户刚说：{user_input}\n\n原回复：{visible_text}"},
    ]
    try:
        rewritten = await service.chat_agent.llm_module.chat(
            rewrite_messages,
            temperature=float(getattr(rewrite_cfg, "temperature", 0.35) or 0.35),
            max_tokens=int(getattr(rewrite_cfg, "max_tokens", 220) or 220),
            model_path=model_hint,
            conversation_id=conversation_id,
        )
    except Exception:
        return final_content

    rewritten_text = str(rewritten or "").strip()
    if not rewritten_text or rewritten_text.lower().startswith("error:"):
        return final_content
    if preserved_tags:
        rewritten_text = rewritten_text.rstrip() + "\n" + "\n".join(preserved_tags)
    return rewritten_text


def _apply_emotion_metadata(
    *,
    service: Any,
    conversation_id: str,
    metadata: Dict[str, Any],
    emotion_label: Optional[str],
) -> Optional[str]:
    effective_payload = None
    try:
        effective_payload = service.chat_agent.emotion_manager.get_effective_payload(
            conversation_id
        )
    except Exception:
        effective_payload = None

    final_emotion_label = (effective_payload or {}).get("primary_emotion") or emotion_label
    if final_emotion_label:
        metadata["emotion"] = final_emotion_label
    if isinstance((effective_payload or {}).get("sub_emotions"), dict) and (
        effective_payload or {}
    ).get("sub_emotions"):
        metadata["emotion_internal"] = (effective_payload or {}).get("sub_emotions")
    if (effective_payload or {}).get("intensity") is not None:
        metadata["emotion_intensity"] = (effective_payload or {}).get("intensity")
    if (effective_payload or {}).get("confidence") is not None:
        metadata["emotion_confidence"] = (effective_payload or {}).get("confidence")
    return final_emotion_label


def _trigger_vts_emotion(final_emotion_label: str) -> None:
    try:
        from core.services.vtube.service import get_vtube_service

        from core.utils.async_tasks import spawn_bg_task
        spawn_bg_task(get_vtube_service().send_emotion(final_emotion_label), name="vtube_emotion")
    except Exception as e:
        logger.warning(f"Failed to trigger VTS emotion: {e}")


async def _handle_media_tags(
    *,
    service: Any,
    final_content: str,
    metadata: Dict[str, Any],
    conversation_id: str,
    save_history: bool,
) -> Tuple[str, Dict[str, Any]]:
    final_content, metadata = await _handle_image_tag(
        service=service,
        final_content=final_content,
        metadata=metadata,
        conversation_id=conversation_id,
        save_history=save_history,
    )
    final_content, metadata = _handle_voice_tag(final_content=final_content, metadata=metadata)
    return final_content, metadata


async def _handle_image_tag(
    *,
    service: Any,
    final_content: str,
    metadata: Dict[str, Any],
    conversation_id: str,
    save_history: bool,
) -> Tuple[str, Dict[str, Any]]:
    img_match = re.search(r"\[GEN_IMG:\s*(.*?)\]", final_content)
    if not img_match:
        return final_content, metadata

    tag_content = img_match.group(1)
    final_content = final_content.replace(img_match.group(0), "")
    parts = tag_content.split("|")
    image_prompt = parts[0].strip()
    model_name = None
    vae_name = None
    for part in parts[1:]:
        part = part.strip()
        if part.startswith("model="):
            model_name = part.split("=", 1)[1].strip()
        elif part.startswith("vae="):
            vae_name = part.split("=", 1)[1].strip()

    metadata["image_prompt"] = image_prompt
    if model_name:
        metadata["model_name"] = model_name
    if vae_name:
        metadata["vae_name"] = vae_name

    is_math_formula = re.search(r"[=><]|\\[a-zA-Z]+|\^|\_", image_prompt) and not re.search(
        r"plot|graph|draw|chart|diagram", image_prompt.lower()
    )
    if is_math_formula and len(image_prompt) < 50:
        logger.info(f"Skipping image generation for apparent math formula: {image_prompt}")
        return final_content, metadata

    try:
        logger.info(
            f"Triggering image generation for prompt: {image_prompt}, model: {model_name}, vae: {vae_name}"
        )
        img_result = await service._generate_image_task(image_prompt, model_name, vae_name)
        if img_result.get("status") == "success":
            images = img_result.get("images", [])
            if images:
                await _persist_generated_image(
                    service=service,
                    pil_img=images[0],
                    metadata=metadata,
                    conversation_id=conversation_id,
                    save_history=save_history,
                )
    except Exception as e:
        logger.error(f"Failed to process image generation: {e}")
    return final_content, metadata


async def _persist_generated_image(
    *,
    service: Any,
    pil_img: Any,
    metadata: Dict[str, Any],
    conversation_id: str,
    save_history: bool,
) -> None:
    file_name = ""
    file_path = None
    try:
        output_dir = service._get_project_root() / "output" / "image"
        output_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"gen_{int(time.time())}_{uuid.uuid4().hex[:8]}.png"
        file_path = output_dir / file_name

        def _save_img():
            pil_img.save(file_path, format="PNG")

        await asyncio.to_thread(_save_img)
        relative_path = f"output/image/{file_name}"
        metadata["image_path"] = relative_path
        logger.info(f"Generated image saved to: {relative_path}")
    except Exception as se:
        logger.error(f"Failed to save generated image: {se}")
        return

    if file_path is not None:
        await _analyze_generated_image(
            service=service,
            file_path=str(file_path),
            metadata=metadata,
            conversation_id=conversation_id,
            save_history=save_history,
        )

    try:
        metadata["image_url"] = f"/output/image/{file_name}"
    except Exception:
        pass

    if str(os.getenv("XIAOYOU_SEND_IMAGE_BASE64", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        buffered = io.BytesIO()
        pil_img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
        metadata["image_base64"] = "data:image/png;base64," + img_str
        logger.info("Image attached to response metadata")


async def _analyze_generated_image(
    *,
    service: Any,
    file_path: str,
    metadata: Dict[str, Any],
    conversation_id: str,
    save_history: bool,
) -> None:
    try:
        vision_result = await service.analyze_screen(
            image_data=file_path,
            prompt="这是你刚刚生成的图像，请简洁地描述图像中的主要内容（1-2句话），以便你在后续对话中记得它。",
        )
        if vision_result.get("status") != "success":
            logger.warning(f"Self-vision analysis failed: {vision_result.get('error')}")
            return
        img_description = vision_result.get("description", "")
        metadata["image_description"] = img_description
        logger.info(f"Self-vision analysis success: {img_description}")
        if not (save_history and service.chat_agent):
            return
        try:
            from core.agents.chat_agent_components.history import save_conversation_history

            observation_msg = f"[系统通知：你刚才画了一张图，内容描述为：{img_description}]"
            await save_conversation_history(
                agent=service.chat_agent,
                user_id=conversation_id,
                user_msg="",
                assistant_msg=observation_msg,
                message_id=str(uuid.uuid4()),
            )
            logger.info("Image description saved to conversation memory as observation.")
        except Exception as me:
            logger.warning(f"Failed to save image observation to memory: {me}")
    except Exception as ve:
        logger.error(f"Error during self-vision analysis: {ve}")


def _handle_voice_tag(*, final_content: str, metadata: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """处理 VOICE 标签，同时支持半角 [VOICE] 和全角 ［VOICE］ 括号。"""
    # 1. Try to match with ID first（半角/全角括号均可）
    voice_match = re.search(r"[\[［]VOICE[：:]\s*(.*?)[\]］]", final_content)
    if voice_match:
        metadata["voice_id"] = voice_match.group(1).strip()
        final_content = final_content.replace(voice_match.group(0), "")
        return final_content, metadata
        
    # 2. Try to match simple tag（半角/全角括号均可）
    voice_match_simple = re.search(r"[\[［]VOICE[\]］]", final_content)
    if voice_match_simple:
        # Use "default" or empty string to signal voice generation without specific ID override
        metadata["voice_id"] = "default" 
        final_content = final_content.replace(voice_match_simple.group(0), "")
        return final_content, metadata

    return final_content, metadata


def _fallback_when_empty(
    final_content: str, original_full_response: str, emotion_label: Optional[str]
) -> str:
    final_content = final_content.strip()
    if final_content:
        return final_content
    if original_full_response:
        if emotion_label:
            return f"（当前情绪：{emotion_label}，但这次没有额外的文字回复。）"
        return "（系统生成了标记信息，但没有可显示的文字内容。）"
    return "这次我没回出来，可能是输入太长，或者模型刚刚卡了一下。你把重点再发一遍试试？"
