#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ASR模型下载脚本 - 使用ModelScope下载语音识别模型

此脚本用于下载ASR（自动语音识别）模型，支持：
1. 使用ModelScope下载Paraformer模型
2. 安装必要的依赖
3. 更新STT连接器配置
4. 提供命令行参数控制下载行为
"""

import os
import sys
import argparse
import subprocess
import json
from pathlib import Path
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('asr_download.log', encoding='utf-8')
    ]
)
logger = logging.getLogger('asr_downloader')

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.absolute()

# 模型默认保存路径
DEFAULT_MODEL_DIR = PROJECT_ROOT / "models" / "asr"

# 默认模型ID
DEFAULT_MODEL_ID = "iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch"

def ensure_directory(directory):
    """确保目录存在"""
    directory = Path(directory)
    if not directory.exists():
        try:
            directory.mkdir(parents=True, exist_ok=True)
            logger.info(f"创建目录: {directory}")
            return True
        except Exception as e:
            logger.error(f"创建目录失败: {directory}, 错误: {e}")
            return False
    return True

def install_dependencies(skip_deps=False):
    """安装必要的依赖"""
    if skip_deps:
        logger.info("跳过依赖安装")
        return True
    
    try:
        # 安装modelscope
        logger.info("安装modelscope...")
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "modelscope", "--upgrade"
        ])
        
        # 安装其他必要的ASR依赖
        logger.info("安装ASR必要依赖...")
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", 
            "numpy", "pydub", "librosa", "soundfile"
        ])
        
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"安装依赖失败: {e}")
        return False

def download_model(model_id, model_dir, force_download=False):
    """使用ModelScope下载模型"""
    ensure_directory(model_dir)
    model_dir = Path(model_dir)
    
    # 检查模型是否已存在
    model_exists = (model_dir / ".lock").exists()
    if model_exists and not force_download:
        logger.info(f"模型已存在，跳过下载: {model_dir}")
        return model_dir
    
    try:
        logger.info(f"开始下载模型: {model_id} 到 {model_dir}")
        from modelscope import snapshot_download
        
        # 使用snapshot_download下载模型
        model_path = snapshot_download(
            model_id=model_id,
            cache_dir=str(model_dir)
        )
        
        logger.info(f"模型下载完成: {model_path}")
        return model_path
    except ImportError as e:
        logger.error(f"导入modelscope失败: {e}")
        return None
    except Exception as e:
        logger.error(f"下载模型失败: {e}")
        return None

def update_stt_connector_config(model_path):
    """更新STT连接器配置文件"""
    stt_connector_path = PROJECT_ROOT / "multimodal" / "stt_connector.py"
    
    if not stt_connector_path.exists():
        logger.warning(f"STT连接器文件不存在: {stt_connector_path}")
        return False
    
    try:
        # 读取文件内容
        with open(stt_connector_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 更新模型路径配置
        import re
        # 匹配DEFAULT_MODEL_PATH行并替换
        new_content = re.sub(
            r'DEFAULT_MODEL_PATH\s*=\s*r?["\'].*?["\']',
            f"DEFAULT_MODEL_PATH = r\"{model_path}\",",
            content
        )
        
        # 更新模型类型为paraformer
        new_content = re.sub(
            r'ASR_MODEL_TYPE\s*=\s*["\'].*?["\']',
            'ASR_MODEL_TYPE = "paraformer"',
            new_content
        )
        
        # 如果没有找到这些配置，添加到文件开头
        if new_content == content:
            new_content = f"""
# ASR模型配置
DEFAULT_MODEL_PATH = r"{model_path}"
ASR_MODEL_TYPE = "paraformer"

""" + content
        
        # 写回文件
        with open(stt_connector_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        logger.info(f"已更新STT连接器配置: {stt_connector_path}")
        return True
    except Exception as e:
        logger.error(f"更新STT连接器配置失败: {e}")
        return False

def update_multimodal_requirements():
    """更新multimodal_requirements.txt文件，添加语音处理依赖"""
    requirements_path = PROJECT_ROOT / "multimodal_requirements.txt"
    
    if not requirements_path.exists():
        logger.warning(f"requirements文件不存在: {requirements_path}")
        # 创建新文件
        with open(requirements_path, 'w', encoding='utf-8') as f:
            f.write("# ASR/TTS 依赖\n")
    
    try:
        # 读取当前依赖
        with open(requirements_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 需要添加的依赖
        voice_deps = [
            'modelscope>=1.8.0',
            'numpy>=1.20.0',
            'pydub>=0.25.1',
            'librosa>=0.9.1',
            'soundfile>=0.10.3.post1'
        ]
        
        # 添加缺失的依赖
        updated = False
        for dep in voice_deps:
            if dep.split('>=')[0].strip() not in content:
                content += f"\n{dep}"
                updated = True
        
        if updated:
            with open(requirements_path, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"已更新multimodal_requirements.txt")
        else:
            logger.info("multimodal_requirements.txt已经包含所有必要的依赖")
        
        return True
    except Exception as e:
        logger.error(f"更新requirements文件失败: {e}")
        return False

def create_asr_config(model_path):
    """创建ASR配置文件"""
    config_dir = PROJECT_ROOT / "config"
    ensure_directory(config_dir)
    config_path = config_dir / "asr_config.json"
    
    config = {
        "model_path": str(model_path),
        "model_type": "paraformer",
        "sample_rate": 16000,
        "language": "zh-CN",
        "enable_vad": True,
        "enable_punctuation": True,
        "use_gpu": True
    }
    
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        logger.info(f"已创建ASR配置文件: {config_path}")
        return True
    except Exception as e:
        logger.error(f"创建ASR配置文件失败: {e}")
        return False

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='ASR模型下载工具')
    parser.add_argument('--model-id', default=DEFAULT_MODEL_ID,
                        help=f'要下载的ModelScope模型ID (默认: {DEFAULT_MODEL_ID})')
    parser.add_argument('--model-dir', default=DEFAULT_MODEL_DIR,
                        help=f'模型保存目录 (默认: {DEFAULT_MODEL_DIR})')
    parser.add_argument('--force-download', action='store_true',
                        help='强制重新下载模型')
    parser.add_argument('--skip-deps', action='store_true',
                        help='跳过依赖安装')
    parser.add_argument('--update-config', action='store_true',
                        help='更新STT连接器配置')
    parser.add_argument('--update-requirements', action='store_true',
                        help='更新multimodal_requirements.txt')
    
    args = parser.parse_args()
    
    # 确保项目根目录存在
    if not PROJECT_ROOT.exists():
        logger.error(f"项目根目录不存在: {PROJECT_ROOT}")
        return 1
    
    # 安装依赖
    if not install_dependencies(args.skip_deps):
        logger.warning("依赖安装失败，尝试继续")
    
    # 下载模型
    model_path = download_model(args.model_id, args.model_dir, args.force_download)
    if not model_path:
        logger.error("模型下载失败")
        return 1
    
    # 更新配置
    if args.update_config:
        update_stt_connector_config(model_path)
        create_asr_config(model_path)
    
    # 更新requirements
    if args.update_requirements:
        update_multimodal_requirements()
    
    logger.info("ASR模型下载和配置完成！")
    print(f"\n🎉 成功完成ASR模型的下载和配置！")
    print(f"📁 模型路径: {model_path}")
    if args.update_config:
        print(f"⚙️  已更新STT连接器配置")
    if args.update_requirements:
        print(f"📋 已更新multimodal_requirements.txt")
    print(f"\n下一步：")
    print(f"1. 确保STT连接器支持Paraformer模型")
    print(f"2. 运行服务测试语音识别功能")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())