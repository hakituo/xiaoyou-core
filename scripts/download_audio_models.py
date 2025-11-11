#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
下载语音处理模型脚本
此脚本用于下载STT（语音转文本）和TTS（文本转语音）所需的模型
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
WHISPER_MODEL_DIR = MODELS_DIR / "whisper"
TTS_MODEL_DIR = MODELS_DIR / "tts"


def ensure_directory(directory):
    """确保目录存在"""
    directory.mkdir(parents=True, exist_ok=True)
    logger.info(f"确保目录存在: {directory}")


def install_dependencies():
    """安装必要的依赖"""
    logger.info("正在安装语音处理所需的依赖...")
    try:
        # 安装Whisper相关依赖
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", 
            "openai-whisper", "pydub>=0.25.1", "librosa>=0.10.1", 
            "numpy>=1.24.0", "soundfile", "ffmpeg-python"
        ])
        logger.info("依赖安装成功")
    except subprocess.CalledProcessError as e:
        logger.error(f"依赖安装失败: {e}")
        sys.exit(1)


def download_whisper_model(model_size="base"):
    """
    下载Whisper模型
    model_size: 模型大小，可选值: tiny, base, small, medium, large
    """
    logger.info(f"正在下载Whisper模型: {model_size}")
    ensure_directory(WHISPER_MODEL_DIR)
    
    try:
        # 使用whisper命令行工具下载模型
        subprocess.check_call([
            sys.executable, "-c", 
            f"import whisper; whisper.load_model('{model_size}', download_root='{WHISPER_MODEL_DIR}')"
        ])
        logger.info(f"Whisper模型 {model_size} 下载成功")
    except subprocess.CalledProcessError as e:
        logger.error(f"Whisper模型下载失败: {e}")
        # 如果直接下载失败，尝试使用transformers下载
        logger.info("尝试使用transformers下载Whisper模型...")
        try:
            subprocess.check_call([
                sys.executable, "-c",
                f"from transformers import WhisperModel; \
                model = WhisperModel.from_pretrained('openai/whisper-{model_size}', \
                cache_dir='{WHISPER_MODEL_DIR}')"
            ])
            logger.info(f"通过transformers成功下载Whisper模型 {model_size}")
        except subprocess.CalledProcessError as e:
            logger.error(f"通过transformers下载Whisper模型也失败: {e}")


def download_tts_model(model_name="tts-1"):
    """
    配置Coqui TTS模型
    """
    logger.info(f"配置TTS模型: {model_name}")
    ensure_directory(TTS_MODEL_DIR)
    
    try:
        # 安装coqui-tts及其中文支持
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", 
            "coqui-tts[zh]"
        ])
        
        logger.info("Coqui TTS库安装完成")
        logger.info("注意: 中文模型将在首次使用时下载或可通过专用脚本下载")
    except subprocess.CalledProcessError as e:
        logger.error(f"Coqui TTS库安装失败: {e}")


def download_mozilla_tts_model():
    """
    配置Coqui TTS支持（保留向后兼容性）
    """
    logger.info("正在配置Coqui TTS支持...")
    
    try:
        # 安装coqui-tts库
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "coqui-tts[zh]"
        ])
        logger.info("Coqui TTS库安装成功")
    except subprocess.CalledProcessError as e:
        logger.error(f"Coqui TTS库安装失败: {e}")


def update_requirements_file():
    """
    更新multimodal_requirements.txt文件，添加语音处理依赖
    """
    req_file = PROJECT_ROOT / "multimodal_requirements.txt"
    
    try:
        with open(req_file, 'r', encoding='utf-8') as f:
            content = f.readlines()
        
        # 查找语音处理部分并取消注释
        updated = False
        for i, line in enumerate(content):
            if line.strip().startswith('# 语音处理'):
                # 取消注释接下来的依赖行
                j = i + 1
                while j < len(content) and content[j].strip().startswith('# '):
                    content[j] = content[j][2:].strip() + '\n'
                    updated = True
                    j += 1
                break
        
        # 如果没有找到语音处理部分，添加它
        if not updated:
            voice_deps = [
                '\n# 语音处理\n',
                'pydub>=0.25.1\n',
                'librosa>=0.10.1\n',
                'numpy>=1.24.0\n',
                'openai-whisper\n',
                'coqui-tts[zh]\n',
                'soundfile\n',
                'ffmpeg-python\n'
            ]
            content.extend(voice_deps)
            updated = True
        
        # 写回文件
        if updated:
            with open(req_file, 'w', encoding='utf-8') as f:
                f.writelines(content)
            logger.info(f"已更新 {req_file}，添加了语音处理依赖")
    except Exception as e:
        logger.error(f"更新requirements文件失败: {e}")


def main():
    parser = argparse.ArgumentParser(description='下载和配置语音处理模型')
    parser.add_argument('--whisper-size', default='base', 
                       choices=['tiny', 'base', 'small', 'medium', 'large'],
                       help='Whisper模型大小 (默认: base)')
    parser.add_argument('--install-deps', action='store_true', 
                       help='安装所有依赖 (默认: 不安装)')
    parser.add_argument('--mozilla-tts', action='store_true', 
                       help='安装Mozilla TTS支持 (默认: 不安装)')
    args = parser.parse_args()
    
    logger.info("开始配置语音处理模型...")
    
    # 安装依赖
    if args.install_deps:
        install_dependencies()
    
    # 更新requirements文件
    update_requirements_file()
    
    # 下载Whisper模型
    download_whisper_model(args.whisper_size)
    
    # 配置TTS
    download_tts_model()
    
    # 可选：安装Mozilla TTS
    if args.mozilla_tts:
        download_mozilla_tts_model()
    
    logger.info("语音处理模型配置完成!")
    logger.info(f"Whisper模型存储在: {WHISPER_MODEL_DIR}")
    logger.info(f"TTS配置存储在: {TTS_MODEL_DIR}")


if __name__ == "__main__":
    main()