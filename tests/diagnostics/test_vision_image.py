#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实际测试图片识别功能 - 使用根目录的测试图片
"""
import asyncio
import os
import sys

# 添加项目根目录到 Python 路径
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, project_root)

from core.utils.logger import get_logger
logger = get_logger("test_vision_image")

async def test_image_recognition():
    """实际测试图片识别"""
    try:
        # 清理缓存，重新加载配置
        import config.integrated_config
        if hasattr(config.integrated_config, '_settings_cache'):
            delattr(config.integrated_config, '_settings_cache')
        
        from config.model_config import reload_model_config
        reload_model_config()
        
        from core.core_engine.service_singletons import get_vision_module
        
        logger.info("正在初始化 VisionModule...")
        vision_module = get_vision_module()
        
        if not vision_module:
            logger.error("VisionModule 初始化失败！")
            return False
        
        logger.info(f"✅ VisionModule 初始化成功！Provider: {vision_module.provider}")
        logger.info(f"   模型: {vision_module.settings.model.vision.model}")
        
        # 测试图片路径
        test_image_path = os.path.join(project_root, "b1bc6096f6335f1aca979d8e3cd14950.jpg")
        
        if not os.path.exists(test_image_path):
            logger.error(f"❌ 测试图片不存在！路径: {test_image_path}")
            return False
        
        logger.info(f"📷 找到测试图片：{test_image_path}")
        logger.info("正在调用视觉识别...")
        
        # 调用 describe_image
        result = await vision_module.describe_image(test_image_path)
        
        logger.info(f"\n{'='*80}")
        logger.info("📝 识别结果:")
        logger.info(f"{'='*80}")
        
        if result.get("status") == "success":
            logger.info(f"✅ 识别成功！")
            logger.info(result.get("response"))
            logger.info(f"{'='*80}\n")
            return True
        else:
            logger.error(f"❌ 识别失败！")
            logger.error(f"错误信息: {result.get('error')}")
            logger.info(f"{'='*80}\n")
            return False
        
    except Exception as e:
        logger.error(f"❌ 测试异常！", exc_info=True)
        return False

if __name__ == "__main__":
    print("="*80)
    print("实际测试图片识别功能 - glm-4.6v")
    print("="*80)
    success = asyncio.run(test_image_recognition())
    print("\n" + "="*80)
    if success:
        print("✅ 识别测试通过！")
    else:
        print("❌ 识别测试失败！")
    print("="*80)
