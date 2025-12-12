#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API路由模块
处理常规HTTP请求端点
"""
import logging
import asyncio
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Path, Body, UploadFile, File, WebSocket, WebSocketDisconnect, Request
from starlette.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
import base64
import io
import os
import json
import re
import time
import numpy as np
import soundfile as sf

from core.services.scheduler.task_scheduler_adapter import io_task
from core.services.scheduler.cpu_task_processor import cpu_task
from core.services.life_simulation.service import get_life_simulation_service
from memory.weighted_memory_manager import get_weighted_memory_manager

# 安全配置常量
MAX_FEEDBACK_LENGTH = 2000
MAX_CONVERSATION_ID_LENGTH = 64
VALID_FEEDBACK_TYPES = ["bug", "suggestion", "feedback", "question"]
SENSITIVE_FIELDS = ["password", "token", "key", "secret", "credit_card", "ssn", "phone", "email"]

# 导入真实的Aveline服务和配置管理器
from core.core_engine.lifecycle_manager import get_aveline_service as real_get_aveline_service
from core.core_engine.config_manager import ConfigManager, get_config_manager
from core.voice import get_tts_manager, get_speakers, get_stt_manager
from core.modules.voice.utils.text_processor import TextProcessor
from core.core_engine.model_manager import get_model_manager
from config.integrated_config import get_settings
from core.llm import get_llm_module

try:
    # ModelAdapter is deprecated but might be referenced for type hinting or legacy code
    # from core.model_adapter import ModelAdapter
    ModelAdapter = None
except Exception:
    ModelAdapter = None

def get_aveline_service():
    """获取Aveline服务实例"""
    return real_get_aveline_service()

logger = logging.getLogger(__name__)
# 初始化配置管理器
config_manager = get_config_manager()

router = APIRouter(prefix="/api/v1", tags=["api"])

def _project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _memory_dir():
    d = os.path.join(_project_root(), "output", "memory", "conversations")
    os.makedirs(d, exist_ok=True)
    return d

def _voice_dir():
    d = os.path.join(_project_root(), "output", "voice")
    os.makedirs(d, exist_ok=True)
    return d

async def process_message_with_async(content, conversation_id, model, aveline_service, max_tokens):
    """
    异步处理消息的辅助函数
    """
    try:
        response_text, metadata = await aveline_service.generate_response(
            user_input=content,
            conversation_id=conversation_id,
            max_tokens=max_tokens,
            model_hint=model
        )
        
        result = {
            "reply": response_text,
            "conversation_id": conversation_id,
            "model": metadata.get("model"),
            "tokens_used": metadata.get("tokens_used"),
            "emotion": metadata.get("emotion"),
            "voice_id": metadata.get("voice_id"),
            "image_prompt": metadata.get("image_prompt")
        }

        # 1. Handle Auto Image Generation
        if metadata.get("image_prompt"):
            try:
                from core.image.image_manager import get_image_manager, ImageGenerationConfig
                from config.integrated_config import get_settings
                
                logger.info(f"Auto-generating image for prompt: {metadata['image_prompt']}")
                settings = get_settings()
                manager = await get_image_manager()
                
                config = ImageGenerationConfig(
                    prompt=metadata['image_prompt'],
                    width=settings.model.image_gen_width,
                    height=settings.model.image_gen_height,
                    num_inference_steps=settings.model.image_gen_steps,
                )
                
                gen_result = await manager.generate_image(
                    prompt=metadata['image_prompt'],
                    model_id=settings.model.default_image_model,
                    config=config,
                    save_to_file=True
                )
                
                if gen_result.get('success') and gen_result.get('image_path'):
                    import base64
                    with open(gen_result['image_path'], "rb") as img_file:
                        b64_string = base64.b64encode(img_file.read()).decode('utf-8')
                        result["image_base64"] = f"data:image/png;base64,{b64_string}"
                        result["image_path"] = gen_result['image_path']
                        
                        # Generate relative URL for frontend
                        # Assuming gen_result['image_path'] is absolute path inside project/static
                        # We want /static/images/generated/...
                        if "static" in gen_result['image_path']:
                            parts = gen_result['image_path'].split("static")
                            if len(parts) > 1:
                                result["image_url"] = f"/static{parts[-1].replace(os.sep, '/')}"
            except Exception as e:
                logger.error(f"Auto image generation failed: {e}")

        # 2. Handle Auto Voice Generation
        if metadata.get("voice_id"):
            try:
                from core.voice import get_tts_manager
                tts_manager = get_tts_manager()
                
                # The text to speak is the response text
                # We might want to strip any remaining tags if they exist, but generate_response should have cleaned them
                speak_text = response_text
                
                if speak_text:
                    logger.info(f"Auto-generating voice ({metadata['voice_id']}) for text: {speak_text[:30]}...")
                    # Note: text_to_speech might be blocking or async depending on implementation
                    # Using run_in_threadpool if it's blocking, but tts_manager.text_to_speech seems to be sync in the search result
                    # but it calls an async engine? No, it calls new engine synchronously?
                    # Let's assume it's safe or wrap it.
                    audio_path = await run_in_threadpool(
                        tts_manager.text_to_speech, 
                        speak_text, 
                        # You might map voice_id to specific style/speed/emotion if supported
                        # emotion=metadata.get("emotion") 
                    )
                    
                    if audio_path and os.path.exists(audio_path):
                        import base64
                        with open(audio_path, "rb") as audio_file:
                            b64_string = base64.b64encode(audio_file.read()).decode('utf-8')
                            result["audio_base64"] = b64_string # Raw base64 for audio
                            result["audio_path"] = audio_path
            except Exception as e:
                logger.error(f"Auto voice generation failed: {e}")

        return result
    except Exception as e:
        logger.error(f"Process message error: {e}")
        raise e

@router.get("/memory/clear")
async def clear_memory_endpoint():
    """
    Clear conversation memory (stub for now, needs implementation)
    """
    # TODO: Implement actual memory clearing logic
    return {"status": "success", "message": "Memory cleared"}

@router.get("/memory/weighted")
async def get_weighted_memories(
    limit: int = Query(20, description="Number of memories to return"),
    min_weight: float = Query(1.0, description="Minimum weight threshold")
):
    """
    获取加权记忆列表
    """
    request_id = str(uuid.uuid4())
    try:
        # 暂时使用 default 用户，后续应从 auth 获取
        user_id = "default" 
        manager = get_weighted_memory_manager(user_id)
        
        # 获取所有加权记忆并按权重排序
        all_memories = list(manager.weighted_memories.values())
        
        # 过滤和排序
        filtered = [
            m for m in all_memories 
            if m.get("weight", 0) >= min_weight
        ]
        filtered.sort(key=lambda x: x.get("weight", 0), reverse=True)
        
        # 取前N条
        results = filtered[:limit]
        
        return {
            "status": "success",
            "data": results,
            "stats": {
                "total_weighted": len(all_memories),
                "topic_weights": manager.topic_weights,
                "emotion_map_keys": list(manager.emotion_memory_map.keys())
            },
            "request_id": request_id,
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"获取加权记忆失败: {e}", exc_info=True)
        return {
            "status": "error",
            "error_code": "MEMORY_FETCH_FAILED",
            "detail": str(e),
            "request_id": request_id,
            "timestamp": time.time()
        }

@router.get("/image/models")
async def get_image_models():
    """
    Get available image generation models (SD1.5 checkpoints, LoRAs, SDXL)
    """
    from core.image.image_manager import get_image_manager
    try:
        manager = await get_image_manager()
        return {
            "status": "success",
            "data": await manager.list_models()
        }
    except Exception as e:
        logger.error(f"Failed to list image models: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

@router.post("/image/generate")
async def generate_image(
    request: Request,
    data: Dict[str, Any] = Body(..., description="Image generation parameters")
):
    """
    生成图像
    """
    from core.image.image_manager import get_image_manager, ImageGenerationConfig
    
    prompt = data.get('prompt')
    model_path = data.get('modelPath') or data.get('model_path')
    lora_path = data.get('loraPath') or data.get('lora_path')
    lora_weight = data.get('loraWeight') or data.get('lora_weight') or 0.7
    
    if not prompt:
        return JSONResponse(status_code=400, content={'error': 'Prompt is required'})
        
    logger.info(f"Received image generation request: {prompt[:30]}... Model: {model_path}")
    
    try:
        manager = await get_image_manager()
        settings = get_settings()
        
        # Config
        config = ImageGenerationConfig(
            prompt=prompt,
            width=settings.model.image_gen_width,
            height=settings.model.image_gen_height,
            num_inference_steps=settings.model.image_gen_steps,
            lora_path=lora_path,
            lora_weight=float(lora_weight) if lora_weight else 0.7
        )
        
        # Generate
        result = await manager.generate_image(
            prompt=prompt,
            model_id=model_path or settings.model.default_image_model, # Use default if not provided
            config=config,
            save_to_file=True
        )
        
        if result.get('success'):
            # Read the generated file and convert to base64
            import base64
            image_path = result.get('image_path')
            if image_path and os.path.exists(image_path):
                with open(image_path, "rb") as img_file:
                    b64_string = base64.b64encode(img_file.read()).decode('utf-8')
                    return {
                        'success': True,
                        'image_base64': f"data:image/png;base64,{b64_string}",
                        'image_path': image_path
                    }
            return JSONResponse(status_code=500, content={'success': False, 'error': 'Image file not found'})
        else:
            return JSONResponse(status_code=500, content={'success': False, 'error': result.get('error')})

    except Exception as e:
        logger.error(f"Image generation error: {str(e)}")
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={'error': str(e)})

@router.get("/system/resources")
async def get_system_resources():
    """
    获取系统资源使用情况
    """
    try:
        manager = get_model_manager()
        return {
            "status": "success",
            "data": manager.detect_system_resources(),
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"获取系统资源失败: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

# --- Notification & Study Endpoints ---

from core.managers.notification_manager import get_notification_manager
from core.tools.study.english.vocabulary_manager import VocabularyManager

@router.get("/notifications")
async def get_notifications(user_id: str = "default"):
    """
    Poll for pending notifications (push messages, active voice, etc.)
    """
    nm = get_notification_manager()
    notifs = nm.get_pending_notifications(user_id)
    return {
        "status": "success",
        "data": notifs,
        "timestamp": time.time()
    }

@router.get("/study/vocabulary/daily")
async def get_daily_vocabulary(limit: int = 20):
    """
    Get daily vocabulary list (20 words)
    """
    try:
        vm = VocabularyManager()
        words = vm.get_daily_words(limit=limit)
        return {
            "status": "success",
            "data": words,
            "count": len(words),
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"Failed to get daily vocabulary: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

@router.post("/study/vocabulary/trigger")
async def trigger_vocabulary_push(user_id: str = "default"):
    """
    Manually trigger a vocabulary push notification
    """
    try:
        vm = VocabularyManager()
        words = vm.get_daily_words(limit=20)
        
        nm = get_notification_manager()
        nm.add_notification(
            user_id=user_id,
            type="vocabulary",
            title="今日单词打卡",
            content=f"今日需复习 {len(words)} 个单词",
            payload={"words": words}
        )
        
        return {
            "status": "success",
            "message": "Vocabulary push triggered",
            "count": len(words)
        }
    except Exception as e:
        logger.error(f"Failed to trigger vocabulary push: {e}")
        return {
            "status": "error",
            "message": str(e)
        }


@router.post("/analyze_screen")
async def analyze_screen(
    data: Dict[str, Any] = Body(..., description="Screen image data")
):
    """
    Analyze screen image
    """
    request_id = str(uuid.uuid4())
    logger.info(f"Received screen analysis request: ID={request_id}")
    
    try:
        # 1. 解析图像数据
        image_data = data.get("image")
        if not image_data:
            image_data = data.get("image_base64")
        if not image_data:
            image_data = data.get("content")
            
        if not image_data:
             return {
                "status": "error", 
                "error_code": "MISSING_IMAGE",
                "detail": "未提供图像数据",
                "request_id": request_id,
                "timestamp": time.time()
            }

        # 2. 获取服务
        aveline = get_aveline_service()
        if not aveline:
            return {
                "status": "error", 
                "error_code": "SERVICE_UNAVAILABLE",
                "detail": "Aveline service not ready"
            }
            
        # 3. 调用服务
        prompt = data.get("prompt", "描述屏幕上的内容，特别是任何可见的文本、窗口或图标。")
        result = await aveline.analyze_screen(
            image_data=image_data,
            prompt=prompt,
            max_tokens=data.get("max_tokens", 512),
            temperature=data.get("temperature", 0.7)
        )
        
        if result.get("status") == "error":
            return {
                "status": "error",
                "error_code": "ANALYSIS_FAILED",
                "detail": result.get("error"),
                "request_id": request_id,
                "timestamp": time.time()
            }
            
        return {
            "status": "success",
            "description": result.get("description"),
            "elements": [], 
            "request_id": request_id,
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"屏幕分析失败: {e}", exc_info=True)
        return {
            "status": "error",
            "error_code": "ANALYSIS_FAILED",
            "detail": str(e),
            "request_id": request_id,
            "timestamp": time.time()
        }


@router.get("/persona")
async def get_persona():
    """
    获取当前角色配置
    """
    try:
        aveline_service = get_aveline_service()
        config = aveline_service.character_config
        return {
            "status": "success",
            "data": config,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"获取角色配置失败: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "error_code": "INTERNAL_SERVER_ERROR",
            "detail": "获取角色配置失败",
            "timestamp": datetime.now().isoformat()
        }


@router.get("/status/life")
async def get_life_status():
    """
    获取Aveline的生活模拟状态
    """
    try:
        sim = get_life_simulation_service()
        return {
            "status": "success",
            "data": sim.get_state(),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"获取生活模拟状态失败: {e}")
        return {
            "status": "error",
            "message": str(e)
        }


@router.get("/greeting")
async def get_greeting():
    """
    获取主动问候消息
    """
    try:
        aveline_service = get_aveline_service()
        if not aveline_service:
             # 尝试初始化
             try:
                from core.lifecycle_manager import initialize_aveline_service
                aveline_service = await initialize_aveline_service()
             except Exception:
                 pass
        
        if not aveline_service:
            return {
                "status": "error", 
                "message": "Service not ready",
                "greeting": "系统初始化中..."
            }

        # 生成问候
        # Run in thread pool to avoid blocking
        # greeting = await run_in_threadpool(aveline_service.generate_proactive_message)
        greeting = await aveline_service.generate_proactive_message()
        
        return {
            "status": "success",
            "greeting": greeting,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"获取问候失败: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "message": str(e),
            "greeting": "你好。" # Fallback
        }


@router.post("/message")
async def handle_message(
    message: Dict[str, Any] = Body(..., description="用户消息内容"),
    conversation_id: Optional[str] = Query(None, description="会话ID"),
    model: Optional[str] = Query(None, description="使用的模型")
):
    """
    处理用户消息 - 优化版
    支持与前端一致的消息格式和错误处理
    
    Args:
        message: 消息内容，包含content字段
        conversation_id: 会话ID，用于上下文管理
        model: 指定使用的模型
    """
    import uuid
    import time
    
    # 生成请求ID
    request_id = str(uuid.uuid4())
    
    try:
        # 验证消息格式
        if not isinstance(message, dict):
            return {
                "status": "error",
                "error_code": "INVALID_MESSAGE_FORMAT",
                "detail": "消息格式无效，必须是JSON对象",
                "request_id": request_id,
                "timestamp": time.time()
            }
        
        # 提取消息内容 - 支持多种字段命名以增强兼容性
        content = ""
        for field in ["content", "message", "text"]:
            if field in message:
                content = str(message[field]).strip()
                break
        
        # 尝试从body中获取 conversation_id (如果query param未提供)
        if not conversation_id and "conversation_id" in message:
            conversation_id = str(message["conversation_id"])
        
        # 如果还是没有，且没有request_id (通常不会，因为request_id是生成的)，
        # 我们不能使用request_id作为conversation_id，因为它每次都变。
        # 如果前端没有传 conversation_id，我们假设它是 default_user
        if not conversation_id:
             # 为了保持向后兼容，如果真没有，暂且用 request_id (但这会导致记忆丢失)
             # 或者使用固定ID 'default_user'
             # 考虑到之前的逻辑可能是依靠近期上下文，或者前端一直没传过ID
             # 如果前端没传，就生成一个新的并在响应中返回，让前端保存?
             # 暂时保持原样(使用 None -> AvelineService处理?)
             # AvelineService generate_response 需要 conversation_id。
             # 如果 None，它会怎样？
             pass
             
        # 在调用 process_message_with_async 时，如果 conversation_id 是 None, 
        # 我们应该给一个默认值，或者让 AvelineService 处理。
        # 但 api_router.py 里的 process_message_with_async 直接传递了。
        
        if not content or not isinstance(content, str):
            return {
                "status": "error",
                "error_code": "EMPTY_CONTENT",
                "detail": "消息内容不能为空且必须是字符串",
                "request_id": request_id,
                "timestamp": time.time()
            }
        
        # 验证内容长度
        if len(content) > 10000:  # 限制消息长度
            return {
                "status": "error",
                "error_code": "CONTENT_TOO_LARGE",
                "detail": "消息内容过长，请减少内容后重试",
                "request_id": request_id,
                "timestamp": time.time()
            }
        
        # 记录请求信息（不记录具体内容，只记录长度和会话ID）
        logger.info(f"收到消息请求: 请求ID={request_id} 长度={len(content)} 会话ID={conversation_id or 'new'}")
        
        # 获取Aveline服务
        aveline_service = get_aveline_service()
        
        if aveline_service is None:
            # 尝试重新初始化
            logger.warning(f"Aveline服务未初始化，尝试在请求中初始化... 请求ID={request_id}")
            try:
                from core.lifecycle_manager import initialize_aveline_service
                aveline_service = await initialize_aveline_service()
            except Exception as e:
                logger.error(f"请求中初始化Aveline服务失败: {e}")
        
        if aveline_service is None:
            logger.error(f"无法获取Aveline服务实例，请求ID={request_id}")
            return {
                "status": "error",
                "error_code": "SERVICE_UNAVAILABLE",
                "detail": "核心服务暂时不可用，正在尝试恢复，请稍后重试",
                "request_id": request_id,
                "timestamp": time.time()
            }
        
        try:
            # 创建任务并设置超时
            max_tokens_override = 0
            try:
                if isinstance(message, dict):
                    mt = message.get("max_tokens")
                    if isinstance(mt, int):
                        max_tokens_override = mt
            except Exception:
                pass
            cfg_max = config_manager.get("limits.max_tokens", 0)
            if not isinstance(cfg_max, int):
                cfg_max = 0
            if max_tokens_override <= 0:
                max_tokens_override = cfg_max
            task = asyncio.create_task(process_message_with_async(
                content=content,
                conversation_id=conversation_id,
                model=model,
                aveline_service=aveline_service,
                max_tokens=max_tokens_override
            ))
            
            # 从配置中获取超时时间
            timeout_seconds = config_manager.get("limits.message_timeout", 300)  # 默认300秒 (5分钟)
            # 设置超时
            response = await asyncio.wait_for(task, timeout=timeout_seconds)
            
            # 统一响应格式 - 确保与前端期望格式一致
            response_data = {
                "status": "success",
                "response": response.get("reply", response.get("response", "")),
                "request_id": request_id,
                "timestamp": time.time(),
                "message_id": str(uuid.uuid4()),
                "conversation_id": response.get("conversation_id", conversation_id),
                "voice_id": response.get("voice_id"),
                "image_prompt": response.get("image_prompt")
            }
            
            # 附加生成的媒体数据
            if "image_base64" in response:
                response_data["image_base64"] = response["image_base64"]
            if "image_path" in response:
                response_data["image_path"] = response["image_path"]
            if "audio_base64" in response:
                response_data["audio_base64"] = response["audio_base64"]
            if "audio_path" in response:
                response_data["audio_path"] = response["audio_path"]

            m_used = response.get("model") or model
            if m_used:
                response_data["model"] = m_used
            
            # 传递情绪信息
            if response.get("emotion"):
                response_data["emotion"] = response.get("emotion")

            # 如果有token使用信息，也返回
            if "tokens_used" in response:
                response_data["tokens_used"] = response["tokens_used"]
            
            return response_data
            
        except asyncio.TimeoutError:
            # 取消超时的任务
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
                
            logger.error(f"消息处理超时: 请求ID={request_id} 会话ID={conversation_id}")
            # 不抛异常而是直接返回错误响应，避免HTTP 504错误页面
            return {
                "status": "error",
                "error_code": "PROCESSING_TIMEOUT",
                "detail": "消息处理超时，请稍后再试",
                "request_id": request_id,
                "timestamp": time.time()
            }
        
    except Exception as e:
        # 记录详细错误日志，但返回通用错误信息
        logger.error(f"处理消息时出错: 请求ID={request_id} {str(e)}", exc_info=True)
        # 不抛异常而是直接返回错误响应，保持与前端的JSON交互一致性
        return {
            "status": "error",
            "error_code": "INTERNAL_SERVER_ERROR",
            "detail": "服务器内部错误，请稍后再试",
            "request_id": request_id,
            "timestamp": time.time()
        }


@io_task
async def _generate_tts_with_async(text: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    异步生成TTS，使用核心语音服务
    """
    import os
    import io
    import base64
    import uuid
    import numpy as np
    import soundfile as sf
    from datetime import datetime
    from core.voice import get_tts_manager
    
    # 强制使用线程执行，避免阻塞事件循环
    # TTS生成是计算密集型任务，不应在事件循环中直接运行
    # 虽然io_task装饰器会处理，但这里我们确保它在线程池中运行
    
    # 1. 确定参考音频
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ref_wav = params.get("speaker_wav") or params.get("reference_audio")
    
    # 默认参考音频逻辑
    if not ref_wav:
        default_ref = os.path.join(base_dir, "ref_audio", "female", "ref_calm.wav")
        ref_wav = os.environ.get("XIAOYOU_TTS_DEFAULT_REF_WAV") or default_ref
        
    # 检查文件是否存在
    if ref_wav and not os.path.exists(ref_wav):
         # 尝试在 ref_audio/female 下寻找
         potential = os.path.join(base_dir, "ref_audio", "female", os.path.basename(ref_wav))
         if os.path.exists(potential):
             ref_wav = potential
    
    # 如果还是找不到，记录警告但尝试继续（可能由TTS服务处理默认值）
    if not ref_wav or not os.path.exists(ref_wav):
        logger.warning(f"参考音频不存在: {ref_wav}")

    # 2. 确定提示文本 (Prompt Text)
    prompt_text = params.get("prompt_text")
    if not prompt_text and ref_wav and os.path.exists(ref_wav):
        # 尝试读取同名的 .txt 或 .lab 文件
        base_path = os.path.splitext(ref_wav)[0]
        for ext in [".txt", ".lab"]:
            txt_path = base_path + ext
            if os.path.exists(txt_path):
                try:
                    with open(txt_path, "r", encoding="utf-8") as f:
                        prompt_text = f.read().strip()
                    if prompt_text:
                        break
                except Exception:
                    pass
        
        # 如果还是没有提示文本，尝试使用STT自动识别
        if not prompt_text:
            try:
                from core.voice import get_stt_manager
                logger.info(f"未找到参考音频提示文本，尝试自动识别: {ref_wav}")
                stt_mgr = await get_stt_manager()
                stt_engine = await stt_mgr.get_engine()
                
                with open(ref_wav, "rb") as f:
                    audio_bytes = f.read()
                
                res = await stt_engine.transcribe(audio_bytes)
                if res and res.get("text"):
                    prompt_text = res.get("text")
                    logger.info(f"自动识别成功: {prompt_text}")
                    # 缓存到 .txt 文件
                    try:
                        txt_path = base_path + ".txt"
                        with open(txt_path, "w", encoding="utf-8") as f:
                            f.write(prompt_text)
                    except Exception as e:
                        logger.warning(f"缓存提示文本失败: {e}")
            except Exception as e:
                logger.warning(f"自动识别提示文本失败: {e}")

    
    # 3. 调用 TTS Manager
    try:
        mgr = await get_tts_manager()
        
        # 如果请求中包含 gpt_sovits_weights，尝试切换模型权重
        weights_path = params.get("gpt_sovits_weights")
        # 过滤掉 "default" 或空值，避免将 speaker ID 当作路径
        if weights_path and weights_path.lower() != "default" and hasattr(mgr.engine, "set_gpt_weights"):
            try:
                # 简单检查是否看起来像文件路径 (包含扩展名或分隔符)
                if "." in weights_path or "/" in weights_path or "\\" in weights_path:
                    logger.info(f"Switching GPT-SoVITS weights to: {weights_path}")
                    await mgr.engine.set_gpt_weights(weights_path)
                else:
                    logger.debug(f"Skipping set_gpt_weights for non-path ID: {weights_path}")
            except Exception as w_err:
                logger.warning(f"Failed to switch GPT-SoVITS weights: {w_err}")
        
        def _map_lang(l):
            l = str(l or "zh").lower()
            if "en" in l: return "en"
            if "ja" in l: return "ja"
            return "zh"

        # 准备参数
        clone_params = {
            "text": text,
            "reference_audio": ref_wav,
            "text_lang": _map_lang(params.get("text_lang")),
            "prompt_text": prompt_text,
            "prompt_lang": _map_lang(params.get("prompt_lang")),
            "speed": float(params.get("speed", 1.0)),
            "top_k": int(params.get("top_k", 15)),
            "top_p": float(params.get("top_p", 1.0)),
            "temperature": float(params.get("temperature", 1.0)),
            "pitch": float(params.get("pitch", 1.0)),
        }
        
        # 执行克隆 - 使用 run_in_executor 防止阻塞
        # 虽然 mgr.clone 是 async 的，但内部可能有 CPU 密集操作
        # 更好的做法是确保 mgr.clone 内部处理好了，或者这里再次包装
        
        # 由于 mgr.clone 已经是 async 的，我们直接调用
        # 但为了防止它长时间占用事件循环（如果是伪 async），我们增加超时保护
        try:
            # 使用 asyncio.wait_for 增加一层超时保护，给它更多时间（300秒）
            audio_data = await asyncio.wait_for(mgr.clone(**clone_params), timeout=300.0)
        except asyncio.TimeoutError:
            logger.error("TTS生成超时 (300s)")
            raise RuntimeError("TTS生成超时")
        
        if audio_data is None or len(audio_data) == 0:
            raise RuntimeError("TTS生成结果为空")

        # 4. 编码输出
        sr = mgr.sample_rate
        max_amplitude = np.max(np.abs(audio_data)) if audio_data.size > 0 else 0
        logger.info(f"TTS generation complete. Audio shape: {audio_data.shape}, Sample rate: {sr}, Max Amplitude: {max_amplitude:.4f}")

        # 转换为 int16 PCM
        # 注意：audio_data 是 float32，范围通常在 -1.0 到 1.0
        
        # 检查音频是否静音
        if np.max(np.abs(audio_data)) < 0.01:
            logger.warning("生成音频似乎是静音 (max amplitude < 0.01)")
        
        # 需要裁剪防止爆音
        audio_data = np.clip(audio_data, -1.0, 1.0)
        pcm = (audio_data * 32767).astype(np.int16)
        
        # 再次检查PCM数据长度
        if len(pcm) < sr * 0.1: # 小于0.1秒
             logger.warning(f"生成音频过短: {len(pcm)} samples")
        
        buf = io.BytesIO()
        sf.write(buf, pcm, sr, format="WAV", subtype="PCM_16")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        
        # 保存文件
        out_dir = _voice_dir()
        fname = f"tts_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.wav"
        fpath = os.path.join(out_dir, fname)
        rel_path = ""
        try:
            sf.write(fpath, pcm, sr, format="WAV", subtype="PCM_16")
            rel_path = f"output/voice/{fname}"
        except Exception as e:
            logger.warning(f"保存TTS文件失败: {e}")
            
        return {
            "audio_base64": f"data:audio/wav;base64,{b64}", 
            "sample_rate": sr, 
            "file_path": rel_path, 
            "text": text, 
            "source": "core_voice"
        }
        
    except Exception as e:
        logger.error(f"TTS生成过程中出错: {e}", exc_info=True)
        raise


@router.post("/stt")
async def stt_endpoint(
    file: UploadFile = File(...),
    model_size: str = Query("base", regex="^(tiny|base|small|medium|large|large-v2|large-v3)$")
):
    """
    语音转文字端点
    """
    request_id = str(uuid.uuid4())
    try:
        logger.info(f"收到STT请求, 请求ID: {request_id}, 模型大小: {model_size}")
        
        # 读取音频文件
        audio_data = await file.read()
        
        # 获取STT引擎
        stt_manager = await get_stt_manager()
        engine = await stt_manager.get_engine()
        
        # 执行转录
        result = await engine.transcribe(audio_data)
        
        return {
            "status": "success",
            "text": result.get("text", ""),
            "segments": result.get("segments", []),
            "language": result.get("language", ""),
            "request_id": request_id,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"STT处理失败: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "error_code": "STT_FAILED",
            "detail": str(e),
            "request_id": request_id,
            "timestamp": datetime.now().isoformat()
        }


@router.get("/voice/reference-audio")
async def list_reference_audio():
    """
    列出可用的参考音频文件
    """
    try:
        ref_audio_dir = os.path.join(os.getcwd(), "ref_audio", "female")
        if not os.path.exists(ref_audio_dir):
            return {
                "status": "success",
                "files": []
            }
        
        files = []
        for f in os.listdir(ref_audio_dir):
            if f.lower().endswith(('.wav', '.mp3', '.ogg', '.flac')):
                files.append({
                    "name": f,
                    "path": os.path.join("ref_audio", "female", f).replace("\\", "/")
                })
        
        return {
            "status": "success",
            "files": files
        }
    except Exception as e:
        logger.error(f"获取参考音频列表失败: {e}")
        return {
            "status": "error",
            "message": str(e)
        }


@router.post("/tts")
async def tts(
    payload: Dict[str, Any] = Body(...)
):
    request_id = str(uuid.uuid4())
    try:
        if not isinstance(payload, dict):
            return {
                "status": "error",
                "error_code": "INVALID_PAYLOAD",
                "detail": "请求体必须是JSON对象",
                "request_id": request_id,
                "timestamp": datetime.now().isoformat()
            }
        text = str(payload.get("text", "")).strip()
        if not text:
            return {
                "status": "error",
                "error_code": "EMPTY_TEXT",
                "detail": "文本不能为空",
                "request_id": request_id,
                "timestamp": datetime.now().isoformat()
            }
        if len(text) > 20000:
            text = text[:20000]
        # 文本清理与标记提取
        tp = TextProcessor(max_segment_length=1000)
        cleaned1, markers = tp.extract_markers(text)
        cleaned1 = tp.remove_bracketed(cleaned1)
        cleaned1 = tp.normalize_text(cleaned1)
        cleaned1 = re.sub(r"#([^#]{1,64})#", " ", cleaned1)
        cleaned1 = re.sub(r"\s{2,}", " ", cleaned1).strip()
        try:
            cleaned1 = re.sub(r"([。！？!?])\1+", r"\1", cleaned1)
            cleaned1 = re.sub(r"(\S{6,})\1+", r"\1", cleaned1)
        except Exception:
            pass
        try:
            nm = str(payload.get("assistant_name") or "Aveline")
            cleaned1 = re.sub(r"^\s*(用户)\s*:\s*", "", cleaned1)
            cleaned1 = re.sub(r"^\s*" + re.escape(nm) + r"\s*:\s*", "", cleaned1)
        except Exception:
            pass
        params = payload.copy()
        params.pop("text", None)
        # 避免重复传递
        if "speed" in params:
            try:
                params["speed"] = float(params["speed"])  # 标准化
            except Exception:
                params["speed"] = 1.0
        if "pitch" in params:
            try:
                params["pitch"] = float(params["pitch"])  # 标准化
            except Exception:
                params["pitch"] = 1.0
        def _norm_lang(x: str) -> str:
            x = str(x or '').strip()
            return {
                '中文': 'zh',
                '英文': 'en',
                '日文': 'ja',
                '中英混合': 'mix',
                'zh': 'zh', 'en': 'en', 'ja': 'ja', 'mix': 'mix'
            }.get(x, 'zh')
        if 'text_language' in params and 'text_lang' not in params:
            params['text_lang'] = _norm_lang(params.pop('text_language'))
        elif 'text_lang' in params:
            params['text_lang'] = _norm_lang(params['text_lang'])
        if 'prompt_language' in params and 'prompt_lang' not in params:
            params['prompt_lang'] = _norm_lang(params.pop('prompt_language'))
        elif 'prompt_lang' in params:
            params['prompt_lang'] = _norm_lang(params['prompt_lang'])
        if "speed" not in params and "speed" in markers:
            params["speed"] = float(markers.get("speed", 1.0))
        if "pitch" not in params and "pitch" in markers:
            params["pitch"] = float(markers.get("pitch", 1.0))
        if "style" not in params and "style" in markers:
            params["style"] = markers.get("style")
        for k in ("xfade_ms", "pause_second", "noise_gate_threshold", "hp_cut", "lp_cut", "fade_ms"):
            if k in payload:
                params[k] = payload[k]
        if "xfade_ms" not in params:
            params["xfade_ms"] = 20
        if "pause_second" not in params:
            params["pause_second"] = 0.25
        if "noise_gate_threshold" not in params:
            params["noise_gate_threshold"] = 0.006
        if "hp_cut" not in params:
            params["hp_cut"] = 100.0
        if "lp_cut" not in params:
            params["lp_cut"] = 6000.0
        if "fade_ms" not in params:
            params["fade_ms"] = 20
        if "downsample_sr" in params and not params["downsample_sr"]:
            params.pop("downsample_sr", None)
        text = cleaned1
        timeout_seconds = ConfigManager().get("limits.tts_timeout", 120)
        task = asyncio.create_task(_generate_tts_with_async(text=text, params=params))
        result = await asyncio.wait_for(task, timeout=timeout_seconds)
        return {
            "status": "success",
            "data": result,
            "request_id": request_id,
            "timestamp": datetime.now().isoformat()
        }
    except asyncio.TimeoutError:
        return {
            "status": "error",
            "error_code": "TTS_TIMEOUT",
            "detail": "语音合成超时",
            "request_id": request_id,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"TTS生成失败: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "error_code": "TTS_ERROR",
            "detail": str(e) or "语音合成失败",
            "request_id": request_id,
            "timestamp": datetime.now().isoformat()
        }


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    request_id = str(uuid.uuid4())
    try:
        out_dir = _voice_dir()
        os.makedirs(out_dir, exist_ok=True)
        fname = f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}_{file.filename or 'file'}"
        fpath = os.path.join(out_dir, fname)
        content = await file.read()
        with open(fpath, "wb") as f:
            f.write(content)
        rel = f"output/voice/{fname}"
        return {
            "status": "success",
            "data": {"file_path": rel},
            "request_id": request_id,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"文件上传失败: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "error_code": "UPLOAD_FAILED",
            "detail": "文件上传失败",
            "request_id": request_id,
            "timestamp": datetime.now().isoformat()
        }

@router.post("/search/web")
async def search_web(
    payload: Dict[str, Any] = Body(...)
):
    request_id = str(uuid.uuid4())
    try:
        if not isinstance(payload, dict):
            return {
                "status": "error",
                "error_code": "INVALID_PAYLOAD",
                "detail": "请求体必须是JSON对象",
                "request_id": request_id,
                "timestamp": datetime.now().isoformat()
            }
        query = str(payload.get("query", "")).strip()
        provider = str(payload.get("provider", "bocha")).lower()
        if not query:
            return {
                "status": "error",
                "error_code": "EMPTY_QUERY",
                "detail": "查询内容不能为空",
                "request_id": request_id,
                "timestamp": datetime.now().isoformat()
            }
        if provider not in ("bocha", "tavily"):
            return {
                "status": "error",
                "error_code": "UNSUPPORTED_PROVIDER",
                "detail": f"不支持的provider: {provider}",
                "request_id": request_id,
                "timestamp": datetime.now().isoformat()
            }
        if provider == "bocha":
            api_key = os.environ.get("BOCHA_API_KEY")
            if not api_key:
                return {
                    "status": "error",
                    "error_code": "MISSING_API_KEY",
                    "detail": "未配置BOCHA_API_KEY，已留API占位",
                    "request_id": request_id,
                    "timestamp": datetime.now().isoformat(),
                    "data": {"placeholder": True}
                }
            try:
                import requests as _req
                url = "https://api.bochaai.com/v1/web-search"
                body = {
                    "query": query,
                    "freshness": payload.get("freshness", "noLimit"),
                    "summary": bool(payload.get("summary", True)),
                    "count": int(payload.get("count", 3))
                }
                headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
                resp = _req.post(url, json=body, headers=headers, timeout=30)
                data = {}
                try:
                    data = resp.json()
                except Exception:
                    data = {"status_code": resp.status_code, "text": resp.text[:1000]}
                return {
                    "status": "success" if resp.status_code == 200 else "error",
                    "data": data,
                    "request_id": request_id,
                    "timestamp": datetime.now().isoformat()
                }
            except Exception as e:
                logger.error(f"Bocha搜索失败: {e}", exc_info=True)
                return {
                    "status": "error",
                    "error_code": "SEARCH_FAILED",
                    "detail": "搜索服务调用失败",
                    "request_id": request_id,
                    "timestamp": datetime.now().isoformat()
                }
        else:
            return {
                "status": "error",
                "error_code": "MISSING_API_KEY",
                "detail": "未配置TAVILY_API_KEY，已留API占位",
                "request_id": request_id,
                "timestamp": datetime.now().isoformat(),
                "data": {"placeholder": True}
            }
    except Exception as e:
        logger.error(f"搜索接口失败: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "error_code": "INTERNAL_SERVER_ERROR",
            "detail": "服务器内部错误",
            "request_id": request_id,
            "timestamp": datetime.now().isoformat()
        }

@router.get("/models")
async def list_models(type: Optional[str] = Query(None, description="Filter by model type (e.g., 'llm', 'image_gen')")):
    """
    获取可用模型列表
    """
    request_id = str(uuid.uuid4())
    try:
        manager = get_model_manager()
        models = manager.list_models(model_type=type)
        return {
            "status": "success",
            "data": models,
            "models": models, # Backward compatibility
            "request_id": request_id,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"获取模型列表失败: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "error_code": "INTERNAL_SERVER_ERROR",
            "detail": "获取模型列表失败",
            "request_id": request_id,
            "timestamp": datetime.now().isoformat()
        }


@router.get("/system/stats")
async def get_system_stats():
    """
    获取系统状态统计
    """
    from core.async_monitor import get_performance_monitor
    request_id = str(uuid.uuid4())
    try:
        monitor = get_performance_monitor()
        metrics = monitor.get_current_metrics()
        return {
            "status": "success",
            "metrics": metrics,  # Frontend expects 'metrics' at top level
            "data": metrics,     # Keep 'data' for backward compatibility
            "request_id": request_id,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"获取系统统计失败: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "error_code": "INTERNAL_SERVER_ERROR",
            "detail": "获取系统统计失败",
            "request_id": request_id,
            "timestamp": datetime.now().isoformat()
        }


@router.delete("/memory/clear")
async def clear_memory():
    """
    清除短期记忆
    """
    request_id = str(uuid.uuid4())
    try:
        from memory.weighted_memory_manager import get_weighted_memory_manager
        # 获取默认用户的记忆管理器
        manager = get_weighted_memory_manager("default")
        
        # 清除记忆
        with manager.lock:
            manager.short_term_memory = []
            # 可选：是否清除长期记忆？通常只清除短期记忆，但用户意图可能是全部
            # 这里我们只清除短期记忆，或者根据参数决定。
            # 为了安全起见，我们假设是清除短期上下文。
            # 如果需要完全重置，可以 uncomment 下面这行:
            # manager.long_term_memory = [] 
            
            # 保存空状态
            manager.save_memory()
            
        logger.info(f"已清除用户 default 的记忆: {request_id}")
        
        return {
            "status": "success",
            "message": "Memory cleared",
            "request_id": request_id,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"清除记忆失败: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "error_code": "INTERNAL_SERVER_ERROR",
            "detail": "清除记忆失败",
            "request_id": request_id,
            "timestamp": datetime.now().isoformat()
        }

@router.get("/voices")
async def list_voices():
    request_id = str(uuid.uuid4())
    try:
        spks = await get_speakers()
        voices = [{"id": str(s), "name": str(s)} for s in spks]
        return {
            "status": "success",
            "data": {"voices": voices},
            "request_id": request_id,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"获取声音列表失败: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "error_code": "VOICES_ERROR",
            "detail": "无法获取声音列表",
            "request_id": request_id,
            "timestamp": datetime.now().isoformat()
        }

@router.post("/generate")
async def generate_endpoint(payload: Dict[str, Any] = Body(...)):
    llm = get_llm_module()
    prompt = payload.get("prompt")
    messages = payload.get("messages")
    max_tokens = int(payload.get("max_tokens", 512))
    
    try:
        # Check if initialization is needed (for LocalLLMAdapter)
        if hasattr(llm, 'initialize'):
            # It's better to ensure it's initialized. 
            # In production, this should be done at startup, but for safety:
             await llm.initialize()

        if messages:
            # Chat completion
            response = await llm.chat(
                messages=messages,
                max_tokens=max_tokens
            )
        else:
            # Text completion (treat as chat with one user message)
            if isinstance(prompt, str):
                msgs = [{"role": "user", "content": prompt}]
            else:
                msgs = [{"role": "user", "content": str(prompt)}]
                
            response = await llm.chat(
                messages=msgs,
                max_tokens=max_tokens
            )
        
        # Handle response format (some llm.chat returns dict, some string)
        if isinstance(response, dict) and "response" in response:
            final_text = response["response"]
        else:
            final_text = str(response)

        return {
            "status": "success",
            "text": final_text,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Generation error: {e}")
        return {
            "status": "error",
            "message": str(e)
        }
