#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
聊天模型偏好解析

把 WebSocket 连接上的强制模型偏好 / 全局配置 / 人设映射，
统一解析成最终交给后端的模型标识。
"""

from core.utils.logger import get_logger

logger = get_logger(__name__)


def apply_model_preference(
    websocket,
    model: str,
    incoming_model_str: str,
    persona_filename: str = "",
) -> str:
    """应用强制模型偏好，返回最终模型标识。"""
    forced_model = getattr(websocket, "forced_model_preference", None)

    if forced_model:
        incoming_model = str(model or "").strip()

        if forced_model == "cloud":
            # 只有当请求明确是本地时才拦截
            if incoming_model == "local" or incoming_model.startswith("local:"):
                model = "cloud"
                logger.info(f"应用强制云端偏好: 覆盖 {incoming_model} -> cloud")

        elif forced_model == "local":
            # 只有当请求明确是云端时才拦截
            if incoming_model == "cloud" or incoming_model.startswith("cloud:"):
                model = "local"
                logger.info(f"应用强制本地偏好: 覆盖 {incoming_model} -> local")

        else:
            # 移动端模型列表发送的是完整路由（例如 cloud:provider:model）。
            # 旧逻辑只处理 cloud/local 两个模式值，导致具体模型虽然写入连接，
            # 后续聊天却完全没有使用它。
            model = str(forced_model).strip()
            logger.info(f"应用移动端指定模型: {incoming_model} -> {model}")

    else:
        # 从全局配置同步模型
        model = sync_with_global_config(model, incoming_model_str, persona_filename)

    return model


def sync_with_global_config(
    model: str, incoming_model_str: str, persona_filename: str = ""
) -> str:
    """与全局配置同步模型设置。"""
    try:
        from config.integrated_config import get_settings

        settings = get_settings()

        global_provider = settings.model.llm.provider
        should_override = False

        if not model:
            should_override = True
        else:
            is_client_cloud = str(model).startswith("cloud:")
            is_global_cloud = global_provider != "local"

            # 全局是云端，客户端传的是本地
            if is_global_cloud and not is_client_cloud:
                client_model_lower = str(model).lower().strip()
                if client_model_lower in ["default", "auto", ""]:
                    should_override = True
                    logger.info(
                        f"检测到通用默认请求：全局为云端({global_provider})，"
                        f"客户端请求({model}) -> 强制覆盖"
                    )

        if should_override:
            if global_provider == "local":
                if settings.model.text_path:
                    model = settings.model.text_path
                    logger.info(f"注入全局本地模型配置: {model}")
                else:
                    model = "local"
            else:
                # 云端模型：优先按 persona 选模型
                persona_model = resolve_model_by_persona(settings, persona_filename)
                if persona_model:
                    model = persona_model
                    logger.info(
                        f"按人设注入云端模型配置: {model} (persona={persona_filename})"
                    )
                else:
                    # 回退：从 model_routing 获取默认模型
                    from config.model_config import get_default_chat_model

                    default_model = get_default_chat_model()
                    if default_model and default_model.startswith("cloud:"):
                        model = default_model
                    else:
                        llm_model = settings.model.llm.model
                        if llm_model:
                            model = f"cloud:{global_provider}:{llm_model}"
                        else:
                            model = f"cloud:{global_provider}:deepseek-v4-flash"
                    logger.info(f"注入全局云端模型配置: {model}")

    except Exception as e:
        logger.warning(f"尝试注入/同步全局模型配置失败: {e}")

    return model


def resolve_model_by_persona(settings, persona_filename: str) -> str:
    """根据人设文件名从 persona_model_map 中查找对应的模型。"""
    if not persona_filename:
        return ""
    try:
        persona_model_map = getattr(settings.model, "persona_model_map", None)
        if not persona_model_map:
            return ""
        persona_lower = str(persona_filename).strip().lower()
        for persona_key, model_hint in persona_model_map.items():
            key_lower = str(persona_key).strip().lower()
            if key_lower in persona_lower:
                return model_hint
    except Exception as e:
        logger.warning(f"按人设解析模型失败: {e}")
    return ""
