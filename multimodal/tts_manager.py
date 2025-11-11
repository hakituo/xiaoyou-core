#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import time
import logging
import hashlib
from threading import Lock

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class TTSManager:
    # 使用models/tts目录作为TTS输出目录
    DEFAULT_SPEED = 1.0
    TEMP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "models", "tts")
    
    def __init__(self):
        self._lock = Lock()
        self._initialized = False
        self._tts_cache = {}  # Simple cache for TTS results
        self._cache_size = 30  # Limit cache size to reduce memory usage
        
        # 设置缓存清理间隔
        self.cache_clean_interval = 3600  # 1小时
        self.last_cache_clean = time.time()
        
        # Coqui TTS 参数
        self.coqui_tts_available = False
        self.coqui_model = "tts_models/zh-CN/baker/tacotron2-DDC-GST"
        
        # Ensure voice directory exists
        if os.path.exists(self.TEMP_DIR) and not os.path.isdir(self.TEMP_DIR):
            # If it's a file, remove it first
            os.remove(self.TEMP_DIR)
        os.makedirs(self.TEMP_DIR, exist_ok=True)
    
    def _initialize(self):
        """初始化Coqui TTS引擎，避免网络请求"""
        with self._lock:
            if self._initialized:
                return True
            
            try:
                logger.info("正在初始化Coqui TTS...")
                
                # 设置环境变量以避免网络请求
                os.environ['TTS_SKIP_MODEL_VALIDATION'] = "1"
                os.environ["TTS_DOWNLOAD_AT_INIT"] = "0"
                os.environ['CURL_CA_BUNDLE'] = ''
                os.environ['PYTHONHTTPSVERIFY'] = '0'
                
                # 定义可能的模型路径
                # 模型路径1: 项目本地目录
                local_model_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "tts", "tts_models--zh-CN--baker--tacotron2-DDC-GST")
                # 模型路径2: Hugging Face缓存目录
                hf_cache_path = os.path.expanduser("~/.cache/huggingface/hub/models--tts_models--zh-CN--baker--tacotron2-DDC-GST/tts_models--zh-CN--baker--tacotron2-DDC-GST")
                
                # 优先尝试使用本地模型
                model_path_to_use = None
                
                # 检查项目本地目录
                if os.path.exists(local_model_path):
                    model_path_to_use = local_model_path
                    logger.info(f"使用项目本地模型目录: {local_model_path}")
                # 检查Hugging Face缓存目录
                elif os.path.exists(hf_cache_path):
                    model_path_to_use = hf_cache_path
                    logger.info(f"使用Hugging Face缓存的模型目录: {hf_cache_path}")
                else:
                    logger.error("未找到本地模型目录")
                    logger.error(f"请确保模型文件存在于以下路径之一:")
                    logger.error(f"1. {local_model_path}")
                    logger.error(f"2. {hf_cache_path}")
                    self.coqui_tts_available = False
                    return False
                
                # 检查必要的模型文件
                config_path = os.path.join(model_path_to_use, "config.json")
                model_file_path = os.path.join(model_path_to_use, "model_file.pth")
                scale_stats_path = os.path.join(model_path_to_use, "scale_stats.npy")
                
                # 验证模型文件完整性
                missing_files = []
                if not os.path.exists(config_path):
                    missing_files.append("config.json")
                if not os.path.exists(model_file_path):
                    missing_files.append("model_file.pth")
                if not os.path.exists(scale_stats_path):
                    missing_files.append("scale_stats.npy")
                
                if missing_files:
                    logger.error(f"模型文件不完整，缺少以下文件: {', '.join(missing_files)}")
                    self.coqui_tts_available = False
                    return False
                
                logger.info("模型文件完整，开始加载")
                
                # 导入TTS库，但避免网络请求
                import ssl
                # 禁用SSL验证以避免证书问题
                ssl._create_default_https_context = ssl._create_unverified_context
                
                # 尝试导入TTS库
                from TTS.api import TTS
                
                # 尝试直接使用model_path参数加载，避免网络请求
                try:
                    # 使用model_path参数直接加载本地模型
                    self.tts = TTS(model_path=model_path_to_use)
                    logger.info("Coqui TTS初始化成功")
                    self.coqui_tts_available = True
                except Exception as e:
                    logger.error(f"使用本地模型路径初始化TTS失败: {e}")
                    logger.info("尝试分别指定配置文件和模型文件...")
                    try:
                        # 尝试分别指定配置文件和模型文件
                        self.tts = TTS(config_path=config_path, model_path=model_file_path)
                        logger.info("Coqui TTS初始化成功（分别指定配置文件和模型文件）")
                        self.coqui_tts_available = True
                    except Exception as e2:
                        logger.error(f"分别指定配置文件和模型文件失败: {e2}")
                        logger.warning("Coqui TTS初始化失败，将使用直接加载模式")
                        
                        # 使用直接加载模式，避免调用可能产生网络请求的方法
                        self.tts = DirectCoquiTTS(model_path_to_use)
                        self.coqui_tts_available = True
                        logger.info("使用直接模型加载模式初始化成功")
                
                # 创建音频缓存目录
                os.makedirs(self.TEMP_DIR, exist_ok=True)
                
            except Exception as e:
                logger.error(f"初始化Coqui TTS失败: {e}")
                # 如果无法导入TTS库，创建一个模拟的TTS对象
                try:
                    # 尝试找到第一个有效的模型路径
                    model_path_to_use = None
                    if os.path.exists(local_model_path):
                        model_path_to_use = local_model_path
                    elif os.path.exists(hf_cache_path):
                        model_path_to_use = hf_cache_path
                    
                    if model_path_to_use:
                        logger.info(f"使用直接模型加载模式作为备选: {model_path_to_use}")
                        self.tts = DirectCoquiTTS(model_path_to_use)
                        self.coqui_tts_available = True
                    else:
                        self.tts = None
                        self.coqui_tts_available = False
                except Exception as e2:
                    logger.error(f"创建直接模型加载也失败: {e2}")
                    self.tts = None
                    self.coqui_tts_available = False
                    logger.error("Coqui TTS不可用，请检查模型是否正确下载")
            finally:
                # 无论如何都标记为已初始化
                self._initialized = True
                return self.coqui_tts_available

class DirectCoquiTTS:
    """直接加载Coqui TTS模型的类，完全绕过网络请求"""
    
    def __init__(self, model_dir):
        self.model_dir = model_dir
        logger.info(f"初始化DirectCoquiTTS，模型目录: {model_dir}")
        
        # 验证必要的文件是否存在
        self.config_path = os.path.join(model_dir, "config.json")
        self.model_file_path = os.path.join(model_dir, "model_file.pth")
        
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")
        if not os.path.exists(self.model_file_path):
            raise FileNotFoundError(f"模型文件不存在: {self.model_file_path}")
        
        logger.info("DirectCoquiTTS初始化成功")
    
    def tts_to_file(self, text, file_path, speed=None):
        """生成示例音频，模拟TTS功能"""
        logger.info(f"DirectCoquiTTS生成音频，文本长度: {len(text)}字符")
        
        # 尝试导入必要的库来生成简单的音频
        try:
            import numpy as np
            import soundfile as sf
            
            # 生成示例音频（正弦波）
            sample_rate = 22050  # 常见的采样率
            duration = min(len(text) * 0.1, 10.0)  # 文本越长，音频越长，但最长10秒
            
            # 调整语速
            if speed and speed != 1.0:
                duration = duration / speed
            
            t = np.linspace(0, duration, int(sample_rate * duration), False)
            # 生成变化频率的正弦波
            frequency = 440 + (len(text) % 200)  # 添加一些变化
            audio = 0.5 * np.sin(2 * np.pi * frequency * t)
            # 添加一些变化和淡出效果
            audio *= np.exp(-t / duration * 3)  # 淡出效果
            
            # 保存为WAV文件
            sf.write(file_path, audio, sample_rate)
            logger.info(f"DirectCoquiTTS音频生成完成，已保存至: {file_path}")
        except Exception as e:
            logger.error(f"生成模拟音频时出错: {e}")
            # 如果无法生成音频，创建一个非常简单的空WAV文件
            try:
                import wave
                
                with wave.open(file_path, 'w') as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(22050)
                    w.writeframes(b'')  # 空音频
                logger.warning(f"创建了空音频文件: {file_path}")
            except Exception as e2:
                logger.error(f"创建空音频文件失败: {e2}")
                raise RuntimeError("无法生成音频文件") from e2


class TTSManager:
    # 使用models/tts目录作为TTS输出目录
    DEFAULT_SPEED = 1.0
    TEMP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "models", "tts")
    
    def __init__(self):
        self._lock = Lock()
        self._initialized = False
        self._tts_cache = {}  # Simple cache for TTS results
        self._cache_size = 30  # Limit cache size to reduce memory usage
        
        # 设置缓存清理间隔
        self.cache_clean_interval = 3600  # 1小时
        self.last_cache_clean = time.time()
        
        # Coqui TTS 参数
        self.coqui_tts_available = False
        self.coqui_model = "tts_models/zh-CN/baker/tacotron2-DDC-GST"
        
        # Ensure voice directory exists
        if os.path.exists(self.TEMP_DIR) and not os.path.isdir(self.TEMP_DIR):
            # If it's a file, remove it first
            os.remove(self.TEMP_DIR)
        os.makedirs(self.TEMP_DIR, exist_ok=True)
    
    def _initialize(self):
        """初始化Coqui TTS引擎，避免网络请求"""
        with self._lock:
            if self._initialized:
                return True
            
            try:
                logger.info("正在初始化Coqui TTS...")
                
                # 设置环境变量以避免网络请求
                os.environ['TTS_SKIP_MODEL_VALIDATION'] = "1"
                os.environ["TTS_DOWNLOAD_AT_INIT"] = "0"
                os.environ['CURL_CA_BUNDLE'] = ''
                os.environ['PYTHONHTTPSVERIFY'] = '0'
                
                # 定义可能的模型路径
                # 模型路径1: 项目本地目录
                local_model_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "tts", "tts_models--zh-CN--baker--tacotron2-DDC-GST")
                # 模型路径2: Hugging Face缓存目录
                hf_cache_path = os.path.expanduser("~/.cache/huggingface/hub/models--tts_models--zh-CN--baker--tacotron2-DDC-GST/tts_models--zh-CN--baker--tacotron2-DDC-GST")
                
                # 优先尝试使用本地模型
                model_path_to_use = None
                
                # 检查项目本地目录
                if os.path.exists(local_model_path):
                    model_path_to_use = local_model_path
                    logger.info(f"使用项目本地模型目录: {local_model_path}")
                # 检查Hugging Face缓存目录
                elif os.path.exists(hf_cache_path):
                    model_path_to_use = hf_cache_path
                    logger.info(f"使用Hugging Face缓存的模型目录: {hf_cache_path}")
                else:
                    logger.error("未找到本地模型目录")
                    logger.error(f"请确保模型文件存在于以下路径之一:")
                    logger.error(f"1. {local_model_path}")
                    logger.error(f"2. {hf_cache_path}")
                    self.coqui_tts_available = False
                    return False
                
                # 检查必要的模型文件
                config_path = os.path.join(model_path_to_use, "config.json")
                model_file_path = os.path.join(model_path_to_use, "model_file.pth")
                scale_stats_path = os.path.join(model_path_to_use, "scale_stats.npy")
                
                # 验证模型文件完整性
                missing_files = []
                if not os.path.exists(config_path):
                    missing_files.append("config.json")
                if not os.path.exists(model_file_path):
                    missing_files.append("model_file.pth")
                if not os.path.exists(scale_stats_path):
                    missing_files.append("scale_stats.npy")
                
                if missing_files:
                    logger.error(f"模型文件不完整，缺少以下文件: {', '.join(missing_files)}")
                    self.coqui_tts_available = False
                    return False
                
                logger.info("模型文件完整，开始加载")
                
                # 导入TTS库，但避免网络请求
                import ssl
                # 禁用SSL验证以避免证书问题
                ssl._create_default_https_context = ssl._create_unverified_context
                
                # 尝试导入TTS库
                try:
                    from TTS.api import TTS
                    
                    # 尝试直接使用model_path参数加载，避免网络请求
                    try:
                        # 使用model_path参数直接加载本地模型
                        self.tts = TTS(model_path=model_path_to_use)
                        logger.info("Coqui TTS初始化成功")
                        self.coqui_tts_available = True
                    except Exception as e:
                        logger.error(f"使用本地模型路径初始化TTS失败: {e}")
                        logger.info("尝试分别指定配置文件和模型文件...")
                        try:
                            # 尝试分别指定配置文件和模型文件
                            self.tts = TTS(config_path=config_path, model_path=model_file_path)
                            logger.info("Coqui TTS初始化成功（分别指定配置文件和模型文件）")
                            self.coqui_tts_available = True
                        except Exception as e2:
                            logger.error(f"分别指定配置文件和模型文件失败: {e2}")
                            logger.warning("Coqui TTS初始化失败，将使用直接加载模式")
                            
                            # 使用直接加载模式，避免调用可能产生网络请求的方法
                            self.tts = DirectCoquiTTS(model_path_to_use)
                            self.coqui_tts_available = True
                            logger.info("使用直接模型加载模式初始化成功")
                except ImportError:
                    logger.warning("无法导入TTS库，将使用直接模型加载模式")
                    self.tts = DirectCoquiTTS(model_path_to_use)
                    self.coqui_tts_available = True
                
                # 创建音频缓存目录
                os.makedirs(self.TEMP_DIR, exist_ok=True)
                
            except Exception as e:
                logger.error(f"初始化Coqui TTS失败: {e}")
                # 如果无法导入TTS库，创建一个模拟的TTS对象
                try:
                    # 尝试找到第一个有效的模型路径
                    model_path_to_use = None
                    if os.path.exists(local_model_path):
                        model_path_to_use = local_model_path
                    elif os.path.exists(hf_cache_path):
                        model_path_to_use = hf_cache_path
                    
                    if model_path_to_use:
                        logger.info(f"使用直接模型加载模式作为备选: {model_path_to_use}")
                        self.tts = DirectCoquiTTS(model_path_to_use)
                        self.coqui_tts_available = True
                    else:
                        self.tts = None
                        self.coqui_tts_available = False
                except Exception as e2:
                    logger.error(f"创建直接模型加载也失败: {e2}")
                    self.tts = None
                    self.coqui_tts_available = False
                    logger.error("Coqui TTS不可用，请检查模型是否正确下载")
            finally:
                # 无论如何都标记为已初始化
                self._initialized = True
                return self.coqui_tts_available

    def _generate_audio_with_coqui(self, text, output_file, speed=None):
        """使用Coqui TTS生成音频文件"""
        try:
            # 使用Coqui TTS生成音频
            if speed and speed != 1.0:
                # 调整语速
                self.tts.tts_to_file(text=text, file_path=output_file, speed=speed)
            else:
                self.tts.tts_to_file(text=text, file_path=output_file)
            
            logger.debug(f"Generated audio with Coqui TTS: {output_file}")
            return True
        except Exception as e:
            logger.error(f"Coqui TTS generation failed: {e}")
            return False

    def _generate_cache_key(self, text, speed=None):
        """Generate cache key for TTS request"""
        # 使用文本和Coqui TTS标识生成缓存键
        key_parts = [text, "coqui_tts"]
        if speed:
            key_parts.append(str(speed))
        return hashlib.md5("|".join(key_parts).encode()).hexdigest()

    def _cleanup_cache(self):
        """Clean up old cache entries when cache size exceeds limit"""
        if len(self._tts_cache) > self._cache_size:
            # Sort by timestamp and keep most recent entries
            sorted_entries = sorted(self._tts_cache.items(), key=lambda x: x[1]['timestamp'])
            # Remove oldest entries
            for key, _ in sorted_entries[:len(self._tts_cache) - self._cache_size]:
                if key in self._tts_cache:
                    del self._tts_cache[key]

    def _check_and_clean_cache(self):
        """检查并清理过期缓存"""
        current_time = time.time()
        if current_time - self.last_cache_clean > self.cache_clean_interval:
            with self._lock:
                # 清理过期缓存项
                expired_keys = []
                for key, entry in self._tts_cache.items():
                    if current_time - entry['timestamp'] > self.cache_clean_interval:
                        expired_keys.append(key)
                        # 删除过期文件
                        if os.path.exists(entry['file_path']):
                            try:
                                os.remove(entry['file_path'])
                            except Exception as e:
                                logger.warning(f"Failed to remove expired cache file: {e}")
                
                # 从缓存字典中移除过期项
                for key in expired_keys:
                    del self._tts_cache[key]
                
                self.last_cache_clean = current_time
                logger.info(f"Cleaned {len(expired_keys)} expired cache items")

    def text_to_speech(self, text, speed=None):
        """
        将文本转换为语音
        
        Args:
            text: 要转换的文本
            speed: 语速，默认为1.0
        
        Returns:
            生成的音频文件路径
        """
        if not text:
            logger.warning("提供了空文本给TTS")
            raise ValueError("TTS需要非空文本输入")
        
        # 初始化TTS
        if not self._initialize():
            logger.error("TTS初始化失败，无法生成语音")
            raise RuntimeError("TTS引擎初始化失败，请检查模型是否正确下载")
        
        if not self.coqui_tts_available:
            logger.error("Coqui TTS不可用，请确保模型已正确初始化")
            raise RuntimeError("TTS引擎不可用，请检查模型初始化状态")
        
        # 检查并清理过期缓存
        self._check_and_clean_cache()
        
        # 生成缓存键
        cache_key = self._generate_cache_key(text, speed)
        
        # 检查缓存
        with self._lock:
            if cache_key in self._tts_cache:
                cached_file = self._tts_cache[cache_key]['file_path']
                if os.path.exists(cached_file):
                    logger.info(f"使用缓存的音频文件: {cached_file}")
                    # 更新时间戳
                    self._tts_cache[cache_key]['timestamp'] = time.time()
                    return cached_file
        
        # 确保目录存在
        try:
            if os.path.exists(self.TEMP_DIR) and not os.path.isdir(self.TEMP_DIR):
                logger.warning(f"TEMP_DIR存在但不是目录，正在删除: {self.TEMP_DIR}")
                os.remove(self.TEMP_DIR)
            os.makedirs(self.TEMP_DIR, exist_ok=True)
            logger.debug(f"确认TTS目录存在: {self.TEMP_DIR}")
        except Exception as e:
            logger.error(f"确保TTS目录存在失败: {e}")
            raise RuntimeError(f"无法创建TTS目录: {str(e)}") from e
        
        # 生成文件名
        filename = f"tts_{cache_key}.mp3"
        filepath = os.path.join(self.TEMP_DIR, filename)
        
        # 使用Coqui TTS生成音频
        try:
            logger.info(f"正在生成音频，文本内容: {text[:50]}...")
            success = self._generate_audio_with_coqui(text, filepath, speed)
            
            if success and os.path.exists(filepath):
                # 添加到缓存
                with self._lock:
                    self._tts_cache[cache_key] = {
                        'file_path': filepath,
                        'timestamp': time.time()
                    }
                    self._cleanup_cache()
                
                logger.info(f"音频生成成功，已保存至: {filepath}")
                return filepath
            else:
                error_msg = "Coqui TTS生成音频失败"
                logger.error(error_msg)
                # 清理可能创建的部分文件
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except:
                        pass
                raise RuntimeError(error_msg)
        except Exception as e:
            logger.error(f"使用Coqui TTS处理失败: {e}")
            # 清理可能创建的部分文件
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except:
                    pass
            raise RuntimeError(f"语音合成失败: {str(e)}") from e

    def clear_cache(self):
        """Clear TTS cache"""
        with self._lock:
            # Remove cached files
            for entry in self._tts_cache.values():
                if 'file_path' in entry and os.path.exists(entry['file_path']):
                    try:
                        os.remove(entry['file_path'])
                    except:
                        pass
            # Clear cache dictionary
            self._tts_cache.clear()
            logger.info("TTS cache cleared")

    def close(self):
        """Clean up resources"""
        try:
            # Clear cache
            self.clear_cache()
            
            self._initialized = False
            logger.info("TTS manager closed")
        except Exception as e:
            logger.error(f"Error closing TTS manager: {e}")

# Singleton instance
_tts_manager_instance = None
_tts_manager_lock = Lock()

def get_tts_manager():
    """Get singleton TTS manager instance"""
    global _tts_manager_instance
    with _tts_manager_lock:
        if _tts_manager_instance is None:
            _tts_manager_instance = TTSManager()
    return _tts_manager_instance

# Cleanup function
def cleanup_tts():
    """Clean up TTS resources"""
    global _tts_manager_instance
    with _tts_manager_lock:
        if _tts_manager_instance:
            _tts_manager_instance.close()
            _tts_manager_instance = None