#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
使用ModelScope下载Whisper模型脚本
此脚本使用阿里ModelScope SDK下载高质量的Whisper模型
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


def install_whisper_deps():
    """安装Whisper相关依赖"""
    logger.info("正在安装Whisper相关依赖...")
    try:
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", 
            "openai-whisper", "pydub>=0.25.1", "librosa>=0.10.1", 
            "numpy>=1.24.0", "soundfile", "ffmpeg-python"
        ])
        logger.info("Whisper依赖安装成功")
    except subprocess.CalledProcessError as e:
        logger.error(f"Whisper依赖安装失败: {e}")
        # 继续执行，但可能会影响后续使用
        logger.warning("继续执行，但Whisper功能可能受限")


def download_whisper_modelscope(model_name='AI-ModelScope/whisper-large-v3'):
    """
    使用ModelScope下载Whisper模型
    
    Args:
        model_name: ModelScope上的模型名称
    """
    logger.info(f"正在使用ModelScope下载模型: {model_name}")
    ensure_directory(WHISPER_MODEL_DIR)
    
    try:
        # 导入ModelScope并下载模型
        download_script = f'''
import os
from modelscope import snapshot_download

# 设置模型存储路径
model_dir = r"{WHISPER_MODEL_DIR}"

# 下载模型
downloaded_dir = snapshot_download(
    '{model_name}',
    cache_dir=model_dir,
    revision='master'
)

print(f"模型下载完成，存储在: {{downloaded_dir}}")
'''
        
        # 执行下载脚本
        subprocess.check_call([sys.executable, "-c", download_script])
        logger.info(f"模型 {model_name} 下载成功")
        logger.info(f"模型存储位置: {WHISPER_MODEL_DIR}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"使用ModelScope下载模型失败: {e}")
        return False


def update_stt_connector(model_path):
    """
    更新stt_connector.py文件，使其能够使用下载的模型
    """
    stt_file = PROJECT_ROOT / "multimodal" / "stt_connector.py"
    
    if not stt_file.exists():
        logger.warning(f"STT连接器文件不存在: {stt_file}")
        return False
    
    try:
        with open(stt_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 更新模型路径配置
        if "DEFAULT_MODEL_PATH" not in content:
            # 如果没有DEFAULT_MODEL_PATH变量，则添加到文件开头
            header = f"# 默认模型路径\nDEFAULT_MODEL_PATH = r\"{model_path}\"\n\n"
            updated_content = header + content
        else:
            # 如果已有，则替换
            import re
            updated_content = re.sub(
                r'DEFAULT_MODEL_PATH\s*=\s*[\'"]{1}.*?[\'"]{1}',
                f"DEFAULT_MODEL_PATH = r\"{model_path}\"",
                content
            )
        
        # 写回文件
        with open(stt_file, 'w', encoding='utf-8') as f:
            f.write(updated_content)
        
        logger.info(f"已更新 {stt_file}，配置了模型路径")
        return True
    except Exception as e:
        logger.error(f"更新STT连接器失败: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='使用ModelScope下载Whisper模型')
    parser.add_argument('--model', default='AI-ModelScope/whisper-large-v3',
                       help='ModelScope上的模型名称 (默认: AI-ModelScope/whisper-large-v3)')
    parser.add_argument('--no-install', action='store_true',
                       help='跳过依赖安装 (默认: 安装依赖)')
    parser.add_argument('--update-config', action='store_true',
                       help='更新STT连接器配置 (默认: 不更新)')
    args = parser.parse_args()
    
    logger.info("开始下载Whisper模型...")
    
    # 安装依赖
    if not args.no_install:
        install_modelscope()
        install_whisper_deps()
    
    # 下载模型
    success = download_whisper_modelscope(args.model)
    
    if success and args.update_config:
        # 尝试找到下载的模型目录
        model_path = WHISPER_MODEL_DIR
        update_stt_connector(model_path)
    
    if success:
        logger.info("\n下载完成！您可以使用以下命令来测试Whisper模型:")
        logger.info(f"python -c \"import whisper; model = whisper.load_model(r'{WHISPER_MODEL_DIR}'); print('模型加载成功！')\"")
    else:
        logger.error("下载失败，请检查网络连接或ModelScope访问权限")


if __name__ == "__main__":
    main()