#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
使用ModelScope下载TTS模型脚本
此脚本使用阿里ModelScope SDK下载高质量的语音合成模型
"""

import os
import sys
import logging
import argparse
import subprocess
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 获取项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 模型存储目录
MODELS_DIR = PROJECT_ROOT / "models"
TTS_MODEL_DIR = MODELS_DIR / "tts"


def ensure_directory(directory):
    """确保目录存在"""
    directory.mkdir(parents=True, exist_ok=True)
    logger.info(f"确保目录存在: {directory}")


def install_modelscope():
    """安装ModelScope SDK"""
    logger.info("正在安装ModelScope SDK...")
    try:
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "modelscope"
        ])
        logger.info("ModelScope SDK安装成功")
    except subprocess.CalledProcessError as e:
        logger.error(f"ModelScope SDK安装失败: {e}")
        sys.exit(1)


def install_tts_deps():
    """安装TTS相关依赖"""
    logger.info("正在安装TTS相关依赖...")
    try:
        # 安装必要的TTS依赖
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", 
            "coqui-tts[zh]", "pyttsx3", "pydub>=0.25.1", 
            "librosa>=0.10.1", "numpy>=1.24.0", "soundfile"
        ])
        
        # 对于Windows用户，安装pywin32以支持pyttsx3
        try:
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", "pywin32"
            ])
            logger.info("pywin32安装成功，增强了Windows上的TTS支持")
        except subprocess.CalledProcessError:
            logger.warning("pywin32安装失败，这可能会影响pyttsx3在Windows上的使用")
        
        logger.info("TTS依赖安装成功")
    except subprocess.CalledProcessError as e:
        logger.error(f"TTS依赖安装失败: {e}")
        # 继续执行，但可能会影响后续使用
        logger.warning("继续执行，但TTS功能可能受限")


def download_tts_modelscope(model_name='damo/speech_sambert-hifigan_tts_zh-cn_16k'):
    """
    使用ModelScope下载TTS模型
    
    Args:
        model_name: ModelScope上的模型名称
    """
    logger.info(f"正在使用ModelScope下载TTS模型: {model_name}")
    ensure_directory(TTS_MODEL_DIR)
    
    try:
        # 导入ModelScope并下载模型
        download_script = f'''
import os
from modelscope import snapshot_download

# 设置模型存储路径
model_dir = r"{TTS_MODEL_DIR}"

# 下载模型
downloaded_dir = snapshot_download(
    '{model_name}',
    cache_dir=model_dir,
    revision='master'
)

print(f"TTS模型下载完成，存储在: {{downloaded_dir}}")
'''
        
        # 执行下载脚本
        subprocess.check_call([sys.executable, "-c", download_script])
        logger.info(f"TTS模型 {model_name} 下载成功")
        logger.info(f"模型存储位置: {TTS_MODEL_DIR}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"使用ModelScope下载TTS模型失败: {e}")
        return False


def update_tts_manager(model_path):
    """
    更新tts_manager.py文件，使其能够使用下载的模型
    """
    tts_file = PROJECT_ROOT / "multimodal" / "tts_manager.py"
    
    if not tts_file.exists():
        logger.warning(f"TTS管理器文件不存在: {tts_file}")
        return False
    
    try:
        with open(tts_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 更新模型路径配置
        if "MODEL_PATH" not in content:
            # 如果没有MODEL_PATH变量，则添加到文件中的TTSManager类定义后
            import re
            # 查找TTSManager类定义的位置
            class_match = re.search(r'class TTSManager\(\):', content)
            if class_match:
                pos = class_match.end()
                updated_content = (content[:pos] + 
                                 f"\n    # 本地模型路径\n    MODEL_PATH = r\"{model_path}\"\n\n" + 
                                 content[pos:])
            else:
                # 如果找不到类定义，就添加到文件开头
                header = f"# 默认TTS模型路径\nMODEL_PATH = r\"{model_path}\"\n\n"
                updated_content = header + content
        else:
            # 如果已有，则替换
            import re
            updated_content = re.sub(
                r'MODEL_PATH\s*=\s*[\'\"].*?[\'\"]',
                f"MODEL_PATH = r\"{model_path}\",
                content
            )
        
        # 写回文件
        with open(tts_file, 'w', encoding='utf-8') as f:
            f.write(updated_content)
        
        logger.info(f"已更新 {tts_file}，配置了模型路径")
        return True
    except Exception as e:
        logger.error(f"更新TTS管理器失败: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='使用ModelScope下载TTS模型')
    parser.add_argument('--model', default='damo/speech_sambert-hifigan_tts_zh-cn_16k',
                       help='ModelScope上的TTS模型名称 (默认: damo/speech_sambert-hifigan_tts_zh-cn_16k)')
    parser.add_argument('--no-install', action='store_true',
                       help='跳过依赖安装 (默认: 安装依赖)')
    parser.add_argument('--update-config', action='store_true',
                       help='更新TTS管理器配置 (默认: 不更新)')
    args = parser.parse_args()
    
    logger.info("开始下载TTS模型...")
    
    # 安装依赖
    if not args.no_install:
        install_modelscope()
        install_tts_deps()
    
    # 下载模型
    success = download_tts_modelscope(args.model)
    
    if success and args.update_config:
        # 使用下载的模型路径更新配置
        model_path = TTS_MODEL_DIR
        update_tts_manager(model_path)
    
    if success:
        logger.info("\n下载完成！")
        logger.info("您现在可以使用以下方式测试TTS功能:")
        logger.info("1. Coqui TTS (本地): 中文TTS模型，已下载")
        logger.info("2. pyttsx3 (本地): 使用系统语音引擎")
        logger.info(f"3. ModelScope TTS: 已下载到 {TTS_MODEL_DIR}")
    else:
        logger.error("下载失败，请检查网络连接或ModelScope访问权限")


if __name__ == "__main__":
    main()