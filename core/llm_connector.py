import asyncio
import os
import logging
import base64
import re
from typing import Optional
import aiofiles

from memory.memory_manager import MemoryManager
from core.text_infer import generate_response
from core.services.command.handler import handle_command_async
from config.integrated_config import get_settings

# Import ImageManager components
try:
    from core.image.image_manager import get_image_manager, ImageGenerationConfig
    image_generation_available = True
except ImportError:
    logger = logging.getLogger(__name__)
    logger.warning("ImageManager not available, image generation disabled.")
    image_generation_available = False

# Configure logger
logger = logging.getLogger(__name__)

# =======================================================
# Model Management
# =======================================================
# Removed global automatic load_model() to improve startup time and decoupling.
# Models should be loaded by the ModelManager or lazily when needed.

# Custom AI Personality Configuration
CUSTOM_PERSONALITY = ""

# =======================================================
# 3. Optimized LLM Query Function
# =======================================================

async def _process_image_file(file_path):
    """
    Process image file for analysis (Async)
    
    Args:
        file_path: Path to the image file
    
    Returns:
        str: Base64 encoded image data
    """
    try:
        # Check if file exists
        if not os.path.exists(file_path):
            logger.error(f"Image file not found: {file_path}")
            return None
        
        # Check file size
        settings = get_settings()
        max_size = settings.server.max_upload_image_size
        if os.path.getsize(file_path) > max_size:
            logger.error(f"Image file too large: {file_path} (Max: {max_size} bytes)")
            return None
        
        # Open and process the image asynchronously
        async with aiofiles.open(file_path, 'rb') as f:
            image_data = await f.read()
            
        # Encode image to base64
        # encoding is fast enough to run in main thread for reasonable image sizes,
        # but for safety with large images we can offload it
        encoded_image = await asyncio.to_thread(
            lambda: base64.b64encode(image_data).decode('utf-8')
        )
        return encoded_image
    except Exception as e:
        logger.error(f"Error processing image file: {e}")
        return None

# =======================================================
# Intent Detection Constants
# =======================================================
IMAGE_ANALYSIS_KEYWORDS = ['分析', '描述', '识别', '是什么', '内容']
IMAGE_OBJECT_KEYWORDS = ['图片', '图像', '照片', '图']
IMAGE_GENERATION_KEYWORDS = ['生成', '画', '绘制', '创建', '造']
IMAGE_GENERATION_OBJECTS = ['图片', '图像', '照片', '图']

# Regex for more robust detection
# Matches patterns like "帮我画一张图", "生成图片", "绘制照片"
IMAGE_GEN_PATTERN = re.compile(
    r'(?:帮我|请)?(?:生成|画|绘制|创建|造)(?:一下|一张|一个|幅)?(?:的)?.*(?:图片|图像|照片|图)',
    re.IGNORECASE
)

def _is_image_query(text):
    """
    Check if the query contains image ANALYSIS keywords
    """
    # If it's a generation query, it's not analysis
    if _is_image_generation_query(text):
        return False
        
    has_object = any(k in text for k in IMAGE_OBJECT_KEYWORDS)
    has_action = any(k in text for k in IMAGE_ANALYSIS_KEYWORDS)
    
    return has_object and has_action

def _is_image_generation_query(text):
    """
    Check if the query contains image GENERATION keywords
    """
    # 1. Regex check (Most robust)
    if IMAGE_GEN_PATTERN.search(text):
        return True

    # 2. Keyword combination check (Fallback)
    has_gen = any(k in text for k in IMAGE_GENERATION_KEYWORDS)
    has_obj = any(k in text for k in IMAGE_GENERATION_OBJECTS)
    
    if has_gen and has_obj:
        return True
        
    # 3. Direct commands (Strict startswith)
    # Only match if it starts with these verbs AND implies an object or creative act
    if text.startswith("画") or text.startswith("生成") or text.startswith("绘制") or text.startswith("创建"):
        # Avoid false positives like "画风不错"
        if len(text) < 2: return False
        
        # Special handling for "画" to avoid "画风", "画质", "画面"
        if text.startswith("画"):
             # Exclude "画风...", "画质...", "画面..." (unless it's "画风景", "画风车")
             if re.match(r'^画(?:风(?!景|车)|质|面)', text):
                 return False
                 
        # If it starts with action but has no object, we need to be careful.
        # "画一只猫" - valid
        # "画风" - invalid (caught above)
        # Simple heuristic: check if length > 2 (likely contains subject)
        if len(text) > 2:
            return True
        return True # "画画" ?
        
    return False

async def _handle_image_generation(text):
    """
    Handle image generation request
    """
    if not image_generation_available:
        return "抱歉，图像生成功能当前不可用。"
        
    try:
        manager = await get_image_manager()
        
        # Extract prompt (simple logic: remove keywords)
        prompt = text
        # Combine all keywords to remove
        remove_keywords = set(IMAGE_GENERATION_KEYWORDS + IMAGE_GENERATION_OBJECTS + ['一张', '个', '帮我', '请'])
        for k in remove_keywords:
            prompt = prompt.replace(k, " ")
        prompt = prompt.strip()
        
        if not prompt:
            prompt = "A beautiful artistic image" # Fallback
            
        logger.info(f"Detected image generation request. Prompt: {prompt}")
        
        # Ensure a model is loaded
        # We prefer the user's specified models if available
        settings = get_settings()
        target_model = settings.model.default_image_model
        fallback_model = settings.model.fallback_image_model
        
        # Check if any model is loaded
        available_models = await manager.get_available_models()
        if not available_models:
            logger.info(f"No models loaded. Attempting to load {target_model}...")
            try:
                await manager.load_model(target_model)
            except Exception as e:
                logger.error(f"Failed to load default model: {e}")
                # Try another one
                logger.info(f"Attempting to load fallback model {fallback_model}...")
                await manager.load_model(fallback_model)
                target_model = fallback_model
        else:
            # Use the first available model
            target_model = list(available_models.keys())[0]
            
        # Generate
        result = await manager.generate_image(
            prompt=prompt,
            model_id=target_model,
            config=ImageGenerationConfig(
                width=settings.model.image_gen_width, 
                height=settings.model.image_gen_height, 
                num_inference_steps=settings.model.image_gen_steps
            )
        )
        
        if result['success']:
            image_path = result['image_path']
            filename = os.path.basename(image_path)
            # Return a response that includes the image path/url
            # In a real app, this might need to be a special message type, 
            # but here we return text describing the result.
            return f"已为您生成图片：{prompt}\n文件保存于：{image_path}"
        else:
            return f"图片生成失败：{result.get('error', 'Unknown error')}"
            
    except Exception as e:
        logger.error(f"Image generation error: {e}", exc_info=True)
        return f"处理图片生成请求时出错：{str(e)}"

async def query_model(text, memory: MemoryManager):
    """
    Main query function to process user input and generate response
    
    Args:
        text: User input text
        memory: Memory manager instance
    
    Returns:
        str: Generated response
    """
    # First check if it's a command
    is_command, command_response = await handle_command_async(text, memory)
    if is_command:
        return command_response
    
    # Check for Image Generation Intent
    if _is_image_generation_query(text):
        return await _handle_image_generation(text)

    # Add user message to history
    user_content = f"User says: {text}"
    
    # Create history
    history = memory.get_history()
    
    # Check if we need to handle image-related content (Analysis)
    if _is_image_query(text):
        # Look for recent file uploads in history that might contain image paths
        image_paths = []
        for msg in reversed(history):
            if msg.get('role') == 'user' and 'image' in msg.get('content', '').lower():
                # Extract potential image path from message content
                if 'file_path' in msg.get('content', ''):
                    # This is a placeholder - in a real implementation, you would extract the actual path
                    image_paths.append("/path/to/recent/image.jpg")
                break
        
        # If we found image paths, process the first one
        if image_paths:
            encoded_image = await _process_image_file(image_paths[0])
            if encoded_image:
                # Add multimodal prompt to user content
                user_content += "\n[Image analysis request]"
                logger.info("Processing image analysis request")
    
    # Add the current user message to history
    history = history + [{"role": "user", "content": user_content}]
    
    # Generate response
    try:
        # For image analysis, we'll add a special prompt to guide the model
        if _is_image_query(text):
            # Prepend system message for image analysis
            system_prompt = {"role": "system", "content": "You are an AI assistant that can analyze images. Please provide a detailed description of the image content, including objects, text, colors, and overall scene. Then address the user's specific question about the image."}
            history_with_system = [system_prompt] + history
            reply_text = await asyncio.to_thread(generate_response, history_with_system)
        else:
            # Standard text generation
            reply_text = await asyncio.to_thread(generate_response, history)
        
        return reply_text
    except Exception as e:
        logger.error(f"Error generating response: {e}")
        return "抱歉，我暂时无法生成响应。请稍后再试。"
