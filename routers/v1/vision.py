# -*- coding: utf-8 -*-
"""视觉（vision）域。

包含图像生成、屏幕内容分析、图像描述三类能力。
"""

import base64
import logging
import os
import time
import uuid
from typing import Any, Dict

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from core.api.contract import error_response
from core.api.error_response import ErrorCode
from config.integrated_config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vision", tags=["视觉与图像"])


def _get_aveline_service():
    from core.core_engine.service_singletons import (
        get_aveline_service as real_get_aveline_service,
    )
    return real_get_aveline_service()


# ==================== 图像生成 ====================

@router.get("/image/models", summary="获取可用图像模型列表")
async def get_image_models():
    from core.image.image_manager import get_image_manager

    try:
        manager = await get_image_manager()
        return {"status": "success", "data": await manager.list_models()}
    except Exception as e:
        logger.error(f"Failed to list image models: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.post("/image/generate", summary="生成图像")
async def generate_image(
    request: Request,
    data: Dict[str, Any] = Body(..., description="Image generation parameters"),
):
    from core.image.image_manager import get_image_manager, ImageGenerationConfig

    prompt = data.get("prompt")
    prompts = data.get("prompts")
    model_path = data.get("modelPath") or data.get("model_path")
    lora_path = data.get("loraPath") or data.get("lora_path")
    lora_weight = data.get("loraWeight") or data.get("lora_weight") or 0.7

    width = data.get("width")
    height = data.get("height")
    steps = data.get("steps") or data.get("num_inference_steps")
    cfg_scale = data.get("cfgScale") or data.get("cfg_scale")
    seed = data.get("seed")
    negative_prompt = data.get("negativePrompt") or data.get("negative_prompt")

    num_images = data.get("numImages") or data.get("num_images")
    batch_size = data.get("batchSize") or data.get("batch_size")
    return_base64 = data.get("returnBase64")

    loras = data.get("loras")
    alwayson_scripts = data.get("alwayson_scripts")
    script_name = data.get("script_name")
    script_args = data.get("script_args")

    enable_hr = data.get("enable_hr")
    hr_scale = data.get("hr_scale")
    hr_upscaler = data.get("hr_upscaler")
    hr_second_pass_steps = data.get("hr_second_pass_steps")
    denoising_strength = data.get("denoising_strength")
    scheduler = data.get("scheduler")

    if not prompt and not prompts:
        return JSONResponse(
            status_code=400,
            content=error_response(
                ErrorCode.MISSING_PARAMETER,
                message="缺少 prompt/prompts 参数",
            ),
        )

    cleaned_prompts = None
    if prompts is not None:
        if not isinstance(prompts, list):
            return JSONResponse(
                status_code=400,
                content=error_response(
                    ErrorCode.MISSING_PARAMETER,
                    message="prompts 必须是数组",
                ),
            )
        cleaned_prompts = [str(p) for p in prompts if p is not None and str(p).strip()]
        if not cleaned_prompts:
            return JSONResponse(
                status_code=400,
                content=error_response(
                    ErrorCode.MISSING_PARAMETER,
                    message="prompts 不能为空",
                ),
            )

    prompt_preview = ""
    try:
        if isinstance(prompt, str) and prompt:
            prompt_preview = prompt[:30]
        elif cleaned_prompts:
            prompt_preview = str(cleaned_prompts[0])[:30]
        elif prompt is not None:
            prompt_preview = str(prompt)[:30]
    except Exception:
        prompt_preview = ""

    logger.info(
        f"Received image generation request: {prompt_preview}... Model: {model_path}"
    )

    try:
        manager = await get_image_manager()
        settings = get_settings()

        try:
            num_images_int = int(num_images) if num_images is not None else 1
        except Exception:
            num_images_int = 1
        if num_images_int < 1:
            num_images_int = 1

        try:
            batch_size_int = int(batch_size) if batch_size is not None else None
        except Exception:
            batch_size_int = None
        if batch_size_int is not None and batch_size_int < 1:
            batch_size_int = None

        if return_base64 is None:
            return_base64 = num_images_int <= 1

        try:
            lora_weight_f = float(lora_weight) if lora_weight is not None else 0.7
        except Exception:
            lora_weight_f = 0.7

        config = ImageGenerationConfig(
            width=width if width is not None else settings.model.image_gen_width,
            height=height if height is not None else settings.model.image_gen_height,
            num_inference_steps=steps
            if steps is not None
            else settings.model.image_gen_steps,
            guidance_scale=cfg_scale if cfg_scale is not None else 7.5,
            seed=seed,
            negative_prompt=negative_prompt,
            lora_path=lora_path,
            lora_weight=lora_weight_f,
            num_images=num_images_int,
            batch_size=batch_size_int,
            loras=loras,
            alwayson_scripts=alwayson_scripts,
            script_name=script_name,
            script_args=script_args,
            enable_hr=enable_hr,
            hr_scale=hr_scale,
            hr_upscaler=hr_upscaler,
            hr_second_pass_steps=hr_second_pass_steps,
            denoising_strength=denoising_strength,
            scheduler=scheduler,
        )

        if cleaned_prompts:
            result = await manager.generate_images(
                prompts=cleaned_prompts,
                model_id=model_path or settings.model.default_image_model,
                config=config,
                save_to_file=True,
            )
        else:
            result = await manager.generate_image(
                prompt=str(prompt),
                model_id=model_path or settings.model.default_image_model,
                config=config,
                save_to_file=True,
            )

        if result.get("success"):
            from core.image.image_utils import get_image_url

            resp = {"success": True}
            if prompt:
                resp["prompt"] = prompt

            images = result.get("images")
            image_path = result.get("image_path")

            if isinstance(images, list) and images:
                out = []
                for it in images:
                    p = it.get("image_path") if isinstance(it, dict) else None
                    if not p or not os.path.exists(p):
                        continue
                    item = {
                        "image_path": p,
                        "url": get_image_url(p),
                    }
                    if return_base64:
                        with open(p, "rb") as img_file:
                            b64_string = base64.b64encode(img_file.read()).decode(
                                "utf-8"
                            )
                        item["image_base64"] = f"data:image/png;base64,{b64_string}"
                    out.append(item)

                if out:
                    resp["images"] = out
                    resp["image_path"] = out[0]["image_path"]
                    resp["url"] = out[0]["url"]
                    if "image_base64" in out[0]:
                        resp["image_base64"] = out[0]["image_base64"]
                    return resp

            if image_path and os.path.exists(image_path):
                resp["image_path"] = image_path
                resp["url"] = get_image_url(image_path)
                if return_base64:
                    with open(image_path, "rb") as img_file:
                        b64_string = base64.b64encode(img_file.read()).decode("utf-8")
                    resp["image_base64"] = f"data:image/png;base64,{b64_string}"
                return resp

            return JSONResponse(
                status_code=500,
                content=error_response(
                    ErrorCode.RESOURCE_NOT_FOUND, message="生成的图像文件未找到"
                ),
            )

        return JSONResponse(
            status_code=500,
            content=error_response(
                ErrorCode.IMAGE_GENERATION_FAILED, message=result.get("error")
            ),
        )

    except Exception as e:
        logger.error(f"Image generation error: {str(e)}")
        return JSONResponse(
            status_code=500,
            content=error_response(ErrorCode.INTERNAL_ERROR, message=str(e)),
        )


# ==================== 视觉理解 ====================

@router.post("/describe", summary="描述图像内容")
async def vision_describe(payload: Dict[str, Any] = Body(...)):
    request_id = str(uuid.uuid4())
    try:
        aveline = _get_aveline_service()
        if not aveline:
            resp = error_response(
                ErrorCode.SERVICE_UNAVAILABLE,
                message="Aveline 服务未就绪",
                request_id=request_id,
            )
            resp["timestamp"] = time.time()
            return resp

        image_data = payload.get("image_base64") or payload.get("image_path")
        if not image_data:
            resp = error_response(
                ErrorCode.MISSING_IMAGE,
                message="未提供图像数据",
                request_id=request_id,
            )
            resp["timestamp"] = time.time()
            return resp

        prompt = payload.get("prompt", "描述这张图片的内容")
        result = await aveline.analyze_screen(image_data=image_data, prompt=prompt)

        logger.info(f"Vision describe result: status={result.get('status')}, description_len={len(result.get('description', '') or '')}, response_len={len(result.get('response', '') or '')}")

        if result.get("status") == "error":
            resp = error_response(
                ErrorCode.VISION_FAILED,
                message=result.get("error", "视觉任务失败"),
                request_id=request_id,
            )
            resp["timestamp"] = time.time()
            return resp

        description = result.get("description") or result.get("response") or ""
        logger.info(f"Vision describe final description (len={len(description)}): {description[:200]}...")

        return {
            "status": "success",
            "description": description,
            "request_id": request_id,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"Vision describe failed: {e}")
        resp = error_response(
            ErrorCode.INTERNAL_ERROR, message=str(e), request_id=request_id
        )
        resp["timestamp"] = time.time()
        return resp


@router.post("/analyze-screen", summary="分析屏幕内容")
async def analyze_screen(
    data: Dict[str, Any] = Body(..., description="Screen image data"),
):
    request_id = str(uuid.uuid4())
    logger.info(f"Received screen analysis request: ID={request_id}")

    try:
        image_data = data.get("image")
        if not image_data:
            image_data = data.get("image_base64")
        if not image_data:
            image_data = data.get("content")

        if not image_data:
            resp = error_response(
                ErrorCode.MISSING_IMAGE, message="未提供图像数据", request_id=request_id
            )
            resp["timestamp"] = time.time()
            return resp

        aveline = _get_aveline_service()
        if not aveline:
            return error_response(
                ErrorCode.SERVICE_UNAVAILABLE, message="Aveline service not ready"
            )

        prompt = data.get(
            "prompt", "描述屏幕上的内容，特别是任何可见的文本、窗口或图标。"
        )
        result = await aveline.analyze_screen(
            image_data=image_data,
            prompt=prompt,
            max_tokens=data.get("max_tokens", 512),
            temperature=data.get("temperature", 0.7),
        )

        if result.get("status") == "error":
            resp = error_response(
                ErrorCode.ANALYSIS_FAILED,
                message=result.get("error", "分析失败"),
                request_id=request_id,
            )
            resp["timestamp"] = time.time()
            return resp

        return {
            "status": "success",
            "description": result.get("description"),
            "elements": [],
            "request_id": request_id,
            "timestamp": time.time(),
        }

    except Exception as e:
        logger.error(f"屏幕分析失败: {e}", exc_info=True)
        resp = error_response(
            ErrorCode.ANALYSIS_FAILED, message=str(e), request_id=request_id
        )
        resp["timestamp"] = time.time()
        return resp
