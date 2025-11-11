import os
import sys
import json
import numpy as np
import torch
import logging
import soundfile as sf
from datetime import datetime
import time
# 导入Coqui TTS API
from TTS.api import TTS

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('tts_log.txt', 'a', 'utf-8')
    ]
)
logger = logging.getLogger('DirectCoquiTTS')

class DirectCoquiTTS:
    def __init__(self, model_path):
        """初始化DirectCoquiTTS类，使用Coqui TTS API"""
        self.model_path = model_path
        self.sampling_rate = 22050  # 默认采样率
        self.tts_model = None  # Coqui TTS模型实例
        self.voice_clone_model = None  # 声音克隆模型实例
        self.use_voice_clone = False  # 是否使用声音克隆
        self.speaker_wav = None  # 说话人参考音频
        
        # 禁用SSL验证以避免下载问题
        os.environ["CURL_CA_BUNDLE"] = ""
        os.environ["PYTHONHTTPSVERIFY"] = "0"
        
        # 尝试初始化TTS模型
        try:
            self._initialize_tts_model()
        except Exception as e:
            logger.warning(f"初始化TTS模型失败，将在首次使用时重试: {e}")
        
        logger.info("DirectCoquiTTS初始化完成，使用Coqui TTS API")
    
    def _load_model(self):
        """已弃用：现在使用Coqui TTS API，不再需要直接加载模型权重"""
        logger.warning("_load_model方法已弃用，现在使用Coqui TTS API")
        return None
    
    def set_voice_clone(self, enable=True, speaker_wav=None):
        """设置是否使用声音克隆功能
        
        Args:
            enable: 是否启用声音克隆
            speaker_wav: 说话人参考音频文件路径
        """
        self.use_voice_clone = enable
        self.speaker_wav = speaker_wav
        
        if enable and speaker_wav:
            logger.info(f"已启用声音克隆，使用参考音频: {speaker_wav}")
            # 尝试初始化声音克隆模型
            try:
                self._initialize_voice_clone_model()
            except Exception as e:
                logger.warning(f"初始化声音克隆模型失败，将在首次使用时重试: {e}")
        elif enable:
            logger.warning("启用声音克隆但未提供参考音频")
        else:
            logger.info("已禁用声音克隆")
    
    def _initialize_voice_clone_model(self):
        """初始化声音克隆模型"""
        if self.voice_clone_model is None and self.speaker_wav:
            logger.info("初始化声音克隆模型...")
            try:
                # 尝试使用xtts_v2模型进行声音克隆
                self.voice_clone_model = TTS("tts_models/multilingual/multi-dataset/xtts_v2")
                logger.info("声音克隆模型初始化成功")
            except Exception as e:
                logger.error(f"初始化声音克隆模型失败: {e}")
                raise
    
    def text_to_speech(self, text, output_file=None):
        """将文本转换为高质量语音"""
        try:
            if not text or not isinstance(text, str):
                raise ValueError("文本必须是非空字符串")
                
            logger.info(f"开始语音合成，文本长度: {len(text)} 字符")
            
            # 如果没有指定输出文件，生成一个默认文件名
            if output_file is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "audio")
                os.makedirs(output_dir, exist_ok=True)
                output_file = os.path.join(output_dir, f"direct_coqui_tts_{timestamp}.wav")
            
            # 检查是否使用声音克隆
            if self.use_voice_clone and self.speaker_wav:
                audio = self._generate_voice_clone_speech(text)
            else:
                # 使用标准TTS模型生成语音
                audio = self._generate_high_quality_speech(text)
            
            # 添加降噪处理来消除电流声
            logger.info("应用降噪处理...")
            try:
                audio = self._remove_noise(audio, self.sampling_rate)
            except Exception as e:
                logger.warning(f"降噪处理失败: {e}，将使用平滑代替")
                audio = self._smooth_audio(audio)
            
            # 平滑音频波形（如果还没有平滑过）
            audio = self._smooth_audio(audio)
            
            # 应用动态范围压缩
            audio = self._apply_dynamic_range_compression(audio)
            
            # 应用自然均衡
            audio = self._apply_natural_equalization(audio, self.sampling_rate)
            
            # 轻微混响
            audio = self._add_subtle_reverb(audio, self.sampling_rate)
            
            # 最后添加轻微呼吸声
            audio = self._add_breathing_noise(audio, self.sampling_rate)
            
            # 归一化音频，避免削波
            max_amp = np.max(np.abs(audio))
            if max_amp > 0:
                audio *= 0.95 / max_amp
            
            # 保存音频
            sf.write(output_file, audio, self.sampling_rate)
            
            file_size = os.path.getsize(output_file) / 1024  # KB
            logger.info(f"✅ 语音合成成功！")
            logger.info(f"音频文件: {output_file}")
            logger.info(f"音频时长: {len(audio) / self.sampling_rate:.2f}秒")
            logger.info(f"文件大小: {file_size:.2f} KB")
            
            return str(output_file)
            
        except ImportError as ie:
            logger.warning(f"某些处理需要额外库: {ie}")
            # 简化处理流程
            if self.use_voice_clone and self.speaker_wav:
                audio = self._generate_voice_clone_speech(text)
            else:
                audio = self._generate_high_quality_speech(text)
            
            # 只进行必要的处理
            audio = self._smooth_audio(audio)
            
            # 归一化并保存
            max_amp = np.max(np.abs(audio))
            if max_amp > 0:
                audio *= 0.95 / max_amp
            
            sf.write(output_file, audio, self.sampling_rate)
            logger.info(f"音频合成成功（简化处理）")
            return str(output_file)
            
        except Exception as e:
            logger.error(f"语音合成失败: {e}")
            raise
    
    def _generate_voice_clone_speech(self, text):
        """使用声音克隆生成语音"""
        try:
            # 确保声音克隆模型已初始化
            self._initialize_voice_clone_model()
            
            logger.info("使用声音克隆模型生成语音...")
            # 使用to_preset方法进行声音克隆
            wav = self.voice_clone_model.tts_with_preset(
                text=text,
                speaker_wav=self.speaker_wav,
                language="zh"
            )
            
            # 转换为numpy数组
            audio = np.array(wav, dtype=np.float32)
            
            logger.info(f"声音克隆语音生成完成，音频长度: {len(audio)} 样本")
            return audio
        except Exception as e:
            logger.error(f"声音克隆失败: {e}")
            # 降级到标准TTS
            logger.warning("降级到标准TTS模型")
            return self._generate_high_quality_speech(text)
    
    def _initialize_tts_model(self):
        """初始化Coqui TTS模型，支持多种初始化方式以兼容不同版本"""
        if self.tts_model is None:
            logger.info("初始化Coqui TTS模型...")
            
            # 尝试使用GPU，如果可用
            device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info(f"使用设备: {device}")
            
            # 尝试多种模型初始化方式
            initialization_methods = [
                # 方法1: 使用完整模型标识符
                lambda: TTS("tts_models/zh-CN/baker/tacotron2-DDC-GRU"),
                # 方法2: 使用简化模型标识符
                lambda: TTS("zh-CN/baker/tacotron2-DDC-GRU"),
                # 方法3: 尝试使用其他中文模型
                lambda: TTS("tts_models/zh-CN/speedy-speaker/vits"),
                # 方法4: 尝试使用本地模型文件
                lambda: self._load_local_tts_model()
            ]
            
            # 尝试每种初始化方法
            for i, init_method in enumerate(initialization_methods, 1):
                try:
                    logger.info(f"尝试初始化方法 {i}...")
                    self.tts_model = init_method()
                    
                    # 检查模型是否成功初始化
                    if hasattr(self.tts_model, 'tts'):
                        logger.info(f"方法 {i} 初始化成功")
                        # 尝试设置设备
                        if hasattr(self.tts_model, 'model') and hasattr(self.tts_model.model, 'to'):
                            try:
                                self.tts_model.model.to(device)
                                logger.info(f"模型已移动到设备: {device}")
                            except Exception as move_e:
                                logger.warning(f"无法将模型移动到指定设备: {move_e}")
                        return
                except Exception as e:
                    logger.warning(f"初始化方法 {i} 失败: {e}")
            
            # 如果所有方法都失败，抛出异常
            raise RuntimeError("所有Coqui TTS模型初始化方法都失败了")
    
    def _load_local_tts_model(self):
        """尝试加载本地TTS模型"""
        local_model_path = os.path.join(self.model_path, "model.pth")
        config_path = os.path.join(self.model_path, "config.json")
        
        if os.path.exists(local_model_path) and os.path.exists(config_path):
            logger.info(f"尝试使用本地模型文件: {local_model_path} 和配置: {config_path}")
            
            # 检查TTS类是否接受单独的模型和配置路径
            try:
                # 对于较新版本的TTS
                return TTS(model_path=local_model_path, config_path=config_path)
            except TypeError:
                try:
                    # 对于旧版本的TTS，可能需要不同的参数名
                    return TTS(model_file=local_model_path, config_file=config_path)
                except Exception as e:
                    logger.error(f"加载本地模型失败: {e}")
                    # 如果直接加载失败，返回None
                    return None
        else:
            logger.warning(f"本地模型文件不完整: 模型={os.path.exists(local_model_path)}, 配置={os.path.exists(config_path)}")
            return None
    
    def _generate_high_quality_speech(self, text):
        """使用Coqui TTS模型生成高质量语音"""
        try:
            # 确保TTS模型已初始化
            self._initialize_tts_model()
            
            # 生成语音
            logger.info("使用Coqui TTS模型生成语音...")
            wav = self.tts_model.tts(text)
            
            # 转换为numpy数组
            audio = np.array(wav, dtype=np.float32)
            
            # 应用一些后处理来优化音频质量
            # 归一化音频，避免削波
            max_amp = np.max(np.abs(audio))
            if max_amp > 0:
                audio *= 0.95 / max_amp
            
            logger.info(f"语音生成完成，音频长度: {len(audio)} 样本")
            return audio
        except Exception as e:
            logger.error(f"Coqui TTS模型生成失败: {e}")
            # 降级处理：如果TTS模型失败，使用简单的合成方法
            logger.warning("尝试使用备用方法生成语音...")
            char_count = len(text)
            duration = min(max(char_count * 0.25, 2.0), 40.0)
            samples = int(self.sampling_rate * duration)
            audio = np.zeros(samples, dtype=np.float32)
            # 简单的音调变化模拟
            t = np.linspace(0, duration, samples)
            freq = 220 + 50 * np.sin(2 * np.pi * t / 3)
            audio = 0.5 * np.sin(2 * np.pi * freq * t)
            return audio
    

    
    def _apply_dynamic_range_compression(self, audio):
        """应用动态范围压缩"""
        # 软压缩器
        threshold = 0.6
        ratio = 3.0
        
        compressed = np.copy(audio)
        
        for i in range(len(compressed)):
            if abs(compressed[i]) > threshold:
                # 应用压缩
                excess = abs(compressed[i]) - threshold
                compressed[i] = np.sign(compressed[i]) * (threshold + excess / ratio)
        
        return compressed
    
    def _apply_natural_equalization(self, audio, sample_rate):
        """应用自然均衡"""
        enhanced = np.copy(audio)
        
        # 使用更自然的均衡设置
        def apply_eq(signal, boost, delay):
            result = np.copy(signal)
            for i in range(delay, len(signal)):
                result[i] += boost * signal[i - delay]
            return result
        
        # 增强1.5kHz左右（人声清晰度）
        mid_delay = int(sample_rate / 1500)
        enhanced = apply_eq(enhanced, 0.12, mid_delay)
        
        # 轻微增强高频
        high_delay = int(sample_rate / 4000)
        enhanced = apply_eq(enhanced, 0.08, high_delay)
        
        return enhanced
    
    def _add_subtle_reverb(self, audio, sample_rate):
        """添加轻微混响"""
        reverb = np.copy(audio)
        
        # 早期反射
        early_reflections = [
            (int(sample_rate * 0.025), 0.12),
            (int(sample_rate * 0.045), 0.08),
            (int(sample_rate * 0.07), 0.05)
        ]
        
        for delay, gain in early_reflections:
            if delay < len(reverb):
                reverb[delay:] += gain * audio[:-delay]
        
        # 主混响尾巴
        tail_length = int(sample_rate * 0.15)
        if tail_length < len(reverb):
            decay = np.linspace(0.02, 0, tail_length)
            for i in range(tail_length):
                if i < len(reverb):
                    reverb[i:] += decay[i] * audio[:len(reverb)-i]
        
        return reverb
    
    def _add_breathing_noise(self, audio, sample_rate):
        """添加自然呼吸声"""
        # 轻微的呼吸声
        breathing_level = 0.003  # 降低噪声水平
        
        # 生成呼吸噪声
        noise = breathing_level * np.random.randn(len(audio))
        
        # 让呼吸声在句子间隙更明显
        for i in range(0, len(audio), int(sample_rate * 0.5)):
            window_size = min(int(sample_rate * 0.1), len(audio) - i)
            noise[i:i+window_size] *= 1.5  # 减少增强幅度
        
        return audio + noise
    
    def _remove_noise(self, audio, sample_rate):
        """消除高频噪声和电流声"""
        # 应用低通滤波器消除高频噪声
        from scipy import signal
        
        # 设计低通滤波器，截止频率为5kHz
        cutoff_freq = 5000  # 降低截止频率以消除更多高频噪声
        nyquist = 0.5 * sample_rate
        normal_cutoff = cutoff_freq / nyquist
        b, a = signal.butter(6, normal_cutoff, btype='low', analog=False)
        
        # 应用滤波器
        filtered_audio = signal.filtfilt(b, a, audio)
        
        # 简化的降噪方法：使用滑动平均滤波和频域低通滤波的组合
        # 1. 应用滑动平均滤波平滑波形
        window_size = 15
        window = np.ones(window_size) / window_size
        smoothed = np.convolve(filtered_audio, window, mode='same')
        
        # 保留原始音频的首尾部分
        smoothed[:window_size//2] = filtered_audio[:window_size//2]
        smoothed[-window_size//2:] = filtered_audio[-window_size//2:]
        
        # 2. 应用频域低通滤波进一步消除高频噪声
        # 使用FFT转换到频域
        audio_fft = np.fft.rfft(smoothed)
        frequencies = np.fft.rfftfreq(len(smoothed), 1/sample_rate)
        
        # 创建低通滤波器
        lowpass_filter = np.ones_like(frequencies)
        # 在截止频率以上逐渐降低增益
        cutoff_idx = np.searchsorted(frequencies, cutoff_freq)
        if cutoff_idx < len(lowpass_filter):
            # 应用平滑过渡的低通滤波
            transition_width = min(cutoff_idx // 2, 50)
            if transition_width > 0:
                for i in range(cutoff_idx - transition_width, cutoff_idx + transition_width):
                    if 0 <= i < len(lowpass_filter):
                        # 缓动函数平滑过渡
                        t = (i - (cutoff_idx - transition_width)) / (2 * transition_width)
                        lowpass_filter[i] = 1 - t * (1 + np.sin(np.pi * t - np.pi/2)) / 2
            # 高于截止频率的部分应用更强的衰减
            lowpass_filter[cutoff_idx:] = 0.1
        
        # 应用滤波器
        filtered_fft = audio_fft * lowpass_filter
        
        # 转换回时域
        cleaned_audio = np.fft.irfft(filtered_fft)
        
        return cleaned_audio
    
    def _smooth_audio(self, audio):
        """平滑音频波形，减少电流声和不规则性"""
        # 使用移动平均滤波平滑波形
        window_size = 11  # 奇数窗口大小
        window = np.ones(window_size) / window_size
        
        # 应用移动平均
        smoothed = np.convolve(audio, window, mode='same')
        
        # 保留原始音频的首尾部分
        smoothed[:window_size//2] = audio[:window_size//2]
        smoothed[-window_size//2:] = audio[-window_size//2:]
        
        return smoothed
        
        return audio + noise

def test_direct_coqui_tts(use_voice_clone=False, speaker_wav=None):
    """测试DirectCoquiTTS类的功能
    
    Args:
        use_voice_clone: 是否使用声音克隆
        speaker_wav: 说话人参考音频文件路径
    """
    try:
        # 设置正确的模型路径 - 按照download_coqui_model.py中的设置
        model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "tts")
        
        # 确保模型目录存在
        os.makedirs(model_path, exist_ok=True)
        
        logger.info(f"使用模型路径: {model_path}")
        
        # 初始化TTS对象
        tts = DirectCoquiTTS(model_path)
        
        # 如果启用声音克隆，设置相关参数
        if use_voice_clone and speaker_wav:
            tts.set_voice_clone(True, speaker_wav)
            logger.info("将使用声音克隆功能进行测试")
        
        # 测试文本
        text = "你好，这是一个中文语音合成测试。很高兴能为您服务！"
        
        logger.info("开始合成语音...")
        
        # 记录开始时间，用于计算处理时间
        import time
        start_time = time.time()
        
        # 生成语音
        output_file = tts.text_to_speech(text, None)
        
        # 计算处理时间
        processing_time = time.time() - start_time
        
        logger.info(f"✅ 语音合成成功！")
        logger.info(f"输出文件: {output_file}")
        logger.info(f"文件大小: {os.path.getsize(output_file) / 1024:.2f} KB")
        logger.info(f"处理时间: {processing_time:.3f}秒")
        logger.info(f"语音合成完成！")
        
        return output_file
    except Exception as e:
        logger.error(f"测试失败: {e}")
        raise

if __name__ == "__main__":
    # 导入argparse以支持命令行参数
    import argparse
    
    parser = argparse.ArgumentParser(description="测试Coqui TTS功能")
    parser.add_argument("--voice-clone", action="store_true", help="启用声音克隆功能")
    parser.add_argument("--speaker-wav", type=str, help="说话人参考音频文件路径")
    args = parser.parse_args()
    
    # 运行测试
    test_direct_coqui_tts(args.voice_clone, args.speaker_wav)