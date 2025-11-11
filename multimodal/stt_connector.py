# STT 异步连接：支持本地Whisper和Paraformer模型进行语音识别
import os
import sys
import logging
import asyncio
import torch
import json
from typing import Dict, Any, Optional, Union
import tempfile
import shutil
from transformers import WhisperProcessor, WhisperForConditionalGeneration
from pydub import AudioSegment
import numpy as np

# ASR模型配置
DEFAULT_MODEL_PATH = r"D:\AI\xiaoyou-core\models\asr\iic\speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
ASR_MODEL_TYPE = "paraformer"  # whisper 或 paraformer

# 尝试从配置文件加载
config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "asr_config.json")
if os.path.exists(config_path):
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            DEFAULT_MODEL_PATH = config.get("model_path", DEFAULT_MODEL_PATH)
            ASR_MODEL_TYPE = config.get("model_type", ASR_MODEL_TYPE)
    except Exception as e:
        logging.warning(f"加载ASR配置文件失败: {e}")

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class STTConnector:
    """本地STT连接器，支持Whisper和Paraformer模型进行语音识别"""
    
    def __init__(self, model_type: str = None, model_path: str = None):
        # 从环境变量获取配置
        self.temp_audio_dir = os.getenv("TEMP_AUDIO_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_audio"))
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        # 使用传入的参数或默认配置
        self.model_type = model_type or os.getenv("ASR_MODEL_TYPE", ASR_MODEL_TYPE)
        self.model_path = model_path or os.getenv("ASR_MODEL_PATH", DEFAULT_MODEL_PATH)
        self.processor = None
        self.model = None
        self.modelscope_model = None  # 用于Paraformer模型
        
        # 确保临时音频目录存在
        os.makedirs(self.temp_audio_dir, exist_ok=True)
        
        # 初始化模型
        self._load_model()
    
    def _load_model(self):
        """根据模型类型加载相应的模型"""
        try:
            if self.model_type.lower() == "whisper":
                # 加载Whisper模型
                logger.info(f"正在加载Whisper模型: {self.model_path}")
                self.processor = WhisperProcessor.from_pretrained(self.model_path)
                self.model = WhisperForConditionalGeneration.from_pretrained(self.model_path)
                self.model.to(self.device)
                logger.info("Whisper模型加载成功")
            elif self.model_type.lower() == "paraformer":
                # 加载Paraformer模型
                logger.info(f"正在加载Paraformer模型: {self.model_path}")
                self._load_paraformer_model()
            else:
                logger.error(f"不支持的模型类型: {self.model_type}")
                # 默认尝试加载Whisper
                self.model_type = "whisper"
                self._load_model()
        except Exception as e:
            logger.error(f"加载模型失败: {str(e)}")
            # 如果加载失败，稍后将尝试使用默认模型
            self.processor = None
            self.model = None
            self.modelscope_model = None
    
    def _load_paraformer_model(self):
        """加载Paraformer模型"""
        try:
            # 尝试导入modelscope相关模块
            from modelscope.pipelines import pipeline
            from modelscope.utils.constant import Tasks
            
            logger.info(f"使用ModelScope加载Paraformer模型: {self.model_path}")
            # 创建语音识别pipeline
            self.modelscope_model = pipeline(
                task=Tasks.auto_speech_recognition,
                model=self.model_path,
                device=self.device
            )
            logger.info("Paraformer模型加载成功")
        except ImportError as e:
            logger.error(f"导入modelscope失败: {e}")
            logger.info("尝试安装modelscope...")
            try:
                import subprocess
                subprocess.check_call([sys.executable, "-m", "pip", "install", "modelscope"])
                # 重新导入
                from modelscope.pipelines import pipeline
                from modelscope.utils.constant import Tasks
                
                self.modelscope_model = pipeline(
                    task=Tasks.auto_speech_recognition,
                    model=self.model_path,
                    device=self.device
                )
                logger.info("Paraformer模型加载成功")
            except Exception as e2:
                logger.error(f"安装和加载modelscope失败: {e2}")
                raise
    
    async def close(self):
        """清理资源"""
        if self.model_type.lower() == "whisper" and self.model:
            # 释放Whisper模型内存
            del self.model
            self.model = None
            self.processor = None
            torch.cuda.empty_cache() if torch.cuda.is_available() else None
            logger.info("Whisper模型已卸载")
        elif self.model_type.lower() == "paraformer" and self.modelscope_model:
            # 释放Paraformer模型内存
            del self.modelscope_model
            self.modelscope_model = None
            torch.cuda.empty_cache() if torch.cuda.is_available() else None
            logger.info("Paraformer模型已卸载")
        
        # 清理临时文件
        if os.path.exists(self.temp_audio_dir):
            try:
                shutil.rmtree(self.temp_audio_dir)
                logger.info(f"已清理临时音频目录: {self.temp_audio_dir}")
            except Exception as e:
                logger.warning(f"清理临时目录失败: {e}")
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.close()
    
    async def _ensure_model_loaded(self):
        """确保模型已加载"""
        if self.model_type.lower() == "whisper":
            # Whisper模型的加载逻辑
            if not self.model or not self.processor:
                await asyncio.to_thread(self._load_model)
                if not self.model or not self.processor:
                    try:
                        logger.info("尝试使用默认Whisper模型")
                        await asyncio.to_thread(
                            lambda: (
                                setattr(self, 'processor', WhisperProcessor.from_pretrained("openai/whisper-small")),
                                setattr(self, 'model', WhisperForConditionalGeneration.from_pretrained("openai/whisper-small")),
                                self.model.to(self.device)
                            )
                        )
                        logger.info("默认Whisper模型加载成功")
                    except Exception as e:
                        logger.error(f"加载默认模型失败: {str(e)}")
                        raise Exception("无法加载语音识别模型")
        elif self.model_type.lower() == "paraformer":
            # Paraformer模型的加载逻辑
            if not self.modelscope_model:
                await asyncio.to_thread(self._load_paraformer_model)
                if not self.modelscope_model:
                    raise Exception("无法加载Paraformer语音识别模型")
    
    def _transcribe_audio_with_whisper(self, audio_path: str, language: str):
        """使用Whisper模型转录音频"""
        try:
            # 加载音频文件
            audio = AudioSegment.from_file(audio_path)
            # 转换为16kHz采样率
            audio = audio.set_frame_rate(16000)
            audio = audio.set_channels(1)
            
            # 转换为numpy数组
            samples = np.array(audio.get_array_of_samples())
            
            # 预处理音频
            input_features = self.processor(
                samples, 
                sampling_rate=16000, 
                return_tensors="pt"
            ).input_features
            
            input_features = input_features.to(self.device)
            
            # 设置生成参数
            generate_kwargs = {}
            if language != "auto":
                # 如果指定了语言，设置语言代码
                generate_kwargs["language"] = language
            
            # 生成转录结果
            predicted_ids = self.model.generate(input_features, **generate_kwargs)
            
            # 解码结果
            transcription = self.processor.batch_decode(
                predicted_ids, 
                skip_special_tokens=True
            )[0]
            
            return {
                "text": transcription,
                "confidence": 0.9,  # Whisper不直接提供置信度
                "detected_language": language if language != "auto" else "unknown"
            }
            
        except Exception as e:
            logger.error(f"转录音频失败: {str(e)}")
            raise
    

    
    async def transcribe_audio_file(
        self,
        audio_file_path: str,
        language: str = "auto",
        max_duration: int = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        异步转录音频文件
        
        Args:
            audio_file_path: 音频文件路径
            language: 语言代码，默认为auto自动检测
            max_duration: 最大音频长度（秒），超过将被截断
            **kwargs: 额外参数
            
        Returns:
            包含转录结果的字典
        """
        # 确保模型已加载
        await self._ensure_model_loaded()
        
        # 使用asyncio.to_thread隔离文件存在检查，避免阻塞事件循环
        file_exists = await asyncio.to_thread(os.path.exists, audio_file_path)
        if not file_exists:
            raise FileNotFoundError(f"音频文件不存在: {audio_file_path}")
        
        # 加载音频文件
        audio = await asyncio.to_thread(AudioSegment.from_file, audio_file_path)
        
        # 如果指定了最大时长，截断音频
        if max_duration:
            audio = audio[:max_duration * 1000]  # 转换为毫秒
            
            # 保存截断后的音频到临时文件
            temp_file_path = os.path.join(self.temp_audio_dir, "temp_audio.wav")
            os.makedirs(self.temp_audio_dir, exist_ok=True)
            await asyncio.to_thread(audio.export, temp_file_path, format="wav")
            audio_file_path = temp_file_path
        
        try:
            # 根据模型类型选择转录方法
            if self.model_type.lower() == "whisper":
                # 使用Whisper模型转录
                result = await asyncio.to_thread(
                    self._transcribe_audio_with_whisper, audio_file_path, language
                )
                
                return {
                    "text": result.get("text", ""),
                    "confidence": result.get("confidence", 0.0),
                    "language": result.get("detected_language", language),
                    "speakers": [],  # 本地版本暂不支持说话人分离
                    "audio_path": audio_file_path,
                    "success": True,
                    "model": "Whisper"
                }
            elif self.model_type.lower() == "paraformer":
                # 使用Paraformer模型转录
                result = await asyncio.to_thread(
                    self._transcribe_audio_with_paraformer, audio_file_path
                )
                
                return {
                    "text": result,
                    "confidence": 0.9,  # Paraformer的默认置信度
                    "language": "zh-CN",  # Paraformer主要针对中文
                    "speakers": [],
                    "audio_path": audio_file_path,
                    "success": True,
                    "model": "Paraformer"
                }
            else:
                raise ValueError(f"不支持的模型类型: {self.model_type}")
        except Exception as e:
            logger.error(f"转录失败: {str(e)}")
            raise Exception(f"音频转录失败: {str(e)}")
    
    def _transcribe_audio_with_paraformer(self, audio_path: str):
        """使用Paraformer模型转录音频"""
        try:
            logger.info(f"使用Paraformer转录音频: {audio_path}")
            
            # 检查文件格式，如果不是wav可能需要转换
            if not audio_path.lower().endswith('.wav'):
                # 转换为wav格式
                temp_wav = os.path.join(self.temp_audio_dir, "temp_paraformer.wav")
                audio = AudioSegment.from_file(audio_path)
                audio = audio.set_frame_rate(16000)
                audio = audio.set_channels(1)
                audio.export(temp_wav, format="wav")
                audio_path = temp_wav
            
            # 使用modelscope的pipeline进行识别
            result = self.modelscope_model(audio_path)
            
            # 不同版本的modelscope可能返回格式不同
            if isinstance(result, dict):
                text = result.get('text', '')
            else:
                text = str(result)
            
            logger.info(f"Paraformer转录结果: {text[:50]}..." if len(text) > 50 else text)
            return text
        except Exception as e:
            logger.error(f"Paraformer转录失败: {str(e)}")
            raise
    
    async def transcribe_audio_data(
        self,
        audio_data: bytes,
        format: str = "wav",
        language: str = "auto",
        max_duration: int = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        转录音频数据（内存中的音频）- 使用asyncio.to_thread隔离文件操作
        
        Args:
            audio_data: 音频二进制数据
            format: 音频格式（如wav, mp3等）
            language: 语言代码，默认自动检测
            max_duration: 最大音频长度（秒），超过将被截断
            **kwargs: 额外参数
            
        Returns:
            包含转录文本和元数据的字典
        """
        # 创建临时文件
        temp_file_path = None
        try:
            # 生成临时文件名
            temp_filename = f"temp_{hash(audio_data)}_{asyncio.get_event_loop().time()}.{format}"
            temp_file_path = os.path.join(self.temp_audio_dir, temp_filename)
            
            # 使用asyncio.to_thread隔离文件写入操作
            await asyncio.to_thread(
                lambda: open(temp_file_path, 'wb').write(audio_data)
            )
            
            # 调用文件转录方法
            return await self.transcribe_audio_file(
                temp_file_path, 
                language=language, 
                max_duration=max_duration,
                **kwargs
            )
            
        finally:
            # 清理临时文件 - 使用asyncio.to_thread隔离文件删除操作
            if temp_file_path:
                file_exists = await asyncio.to_thread(os.path.exists, temp_file_path)
                if file_exists:
                    try:
                        await asyncio.to_thread(os.remove, temp_file_path)
                    except Exception as e:
                        logger.warning(f"无法删除临时音频文件: {str(e)}")
    
    async def batch_transcribe(
        self,
        audio_files: list[str],
        language: str = "auto",
        concurrency_limit: int = 3
    ) -> list[Dict[str, Any]]:
        """
        批量转录多个音频文件
        
        Args:
            audio_files: 音频文件路径列表
            language: 语言代码
            concurrency_limit: 并发限制
            
        Returns:
            转录结果列表
        """
        semaphore = asyncio.Semaphore(concurrency_limit)
        
        async def _transcribe_file(file_path):
            async with semaphore:
                try:
                    result = await self.transcribe_audio_file(file_path, language)
                    return {"success": True, "result": result, "file": file_path}
                except Exception as e:
                    logger.error(f"转录文件失败 {file_path}: {str(e)}")
                    return {"success": False, "error": str(e), "file": file_path}
        
        tasks = [_transcribe_file(file) for file in audio_files]
        return await asyncio.gather(*tasks)
    
    async def get_supported_languages(self) -> list[str]:
        """
        获取支持的语言列表
        
        Returns:
            支持的语言代码列表
        """
        if self.model_type.lower() == "whisper":
            # Whisper支持99种语言，返回最常用的几种
            return [
                "zh-CN", "zh-TW", "en-US", "en-GB", "ja", "ko", 
                "fr", "de", "es", "it", "pt", "ru", "auto"
            ]
        elif self.model_type.lower() == "paraformer":
            # Paraformer主要支持中文
            return ["zh-CN"]
    
    async def health_check(self) -> bool:
        """
        检查STT模型是否可用
        
        Returns:
            模型是否可用
        """
        try:
            # 尝试确保模型已加载
            await self._ensure_model_loaded()
            if self.model_type.lower() == "whisper":
                return self.model is not None and self.processor is not None
            elif self.model_type.lower() == "paraformer":
                return self.modelscope_model is not None
            return False
        except:
            return False
    
    def estimate_transcription_time(self, audio_file_path: str) -> float:
        """
        估算转录时间（基于文件大小）
        
        Args:
            audio_file_path: 音频文件路径
            
        Returns:
            估算的秒数
        """
        try:
            file_size = os.path.getsize(audio_file_path) / (1024 * 1024)  # MB
            # 简单估算：每MB音频约需要2秒处理时间
            return max(1.0, file_size * 2)
        except:
            return 5.0  # 默认返回5秒
    
    async def estimate_transcription_time_async(self, audio_file_path: str) -> float:
        """
        异步版本的转录时间估算
        
        Args:
            audio_file_path: 音频文件路径
            
        Returns:
            估算的秒数
        """
        # 使用asyncio.to_thread隔离文件大小获取操作
        try:
            file_size = await asyncio.to_thread(
                lambda: os.path.getsize(audio_file_path) / (1024 * 1024)
            )
            return max(1.0, file_size * 2)
        except:
            return 5.0  # 默认返回5秒

# 创建全局STT连接器实例
stt_connector = None

def get_stt_connector() -> STTConnector:
    """
    获取STT连接器实例（单例模式）
    
    Returns:
        STTConnector实例
    """
    global stt_connector
    if stt_connector is None:
        stt_connector = STTConnector()
    return stt_connector

async def initialize_stt_connector():
    """
    初始化STT连接器
    """
    connector = get_stt_connector()
    # 验证连接
    is_healthy = await connector.health_check()
    if is_healthy:
        logger.info("STT连接器初始化成功")
    else:
        logger.warning("STT服务可能不可用，将在需要时重试")
    return connector

async def shutdown_stt_connector():
    """
    关闭STT连接器
    """
    global stt_connector
    if stt_connector:
        await stt_connector.close()
        stt_connector = None
        logger.info("STT连接器已关闭")

# 示例使用
async def example_usage():
    """示例使用方法"""
    async with STTConnector() as connector:
        try:
            # 健康检查
            is_healthy = await connector.health_check()
            print(f"STT服务状态: {'健康' if is_healthy else '不健康'}")
            
            # 获取支持的语言
            languages = await connector.get_supported_languages()
            print(f"支持的语言: {languages}")
            
            # 注意：实际使用时需要提供真实的音频文件路径
            # result = await connector.transcribe_audio_file(
            #     "path/to/audio.wav",
            #     language="zh-CN"
            # )
            # print(f"转录结果: {result['text']}")
            
        except Exception as e:
            print(f"错误: {str(e)}")

if __name__ == "__main__":
    asyncio.run(example_usage())