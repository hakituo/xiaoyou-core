import os
import numpy as np
import soundfile as sf
import matplotlib.pyplot as plt
import logging
import sys

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger('AudioAnalyzer')

class AudioAnalyzer:
    """音频分析工具，用于检查生成的音频文件"""
    
    def analyze_file(self, file_path):
        """分析单个音频文件"""
        try:
            if not os.path.exists(file_path):
                logger.error(f"❌ 文件不存在: {file_path}")
                return False
            
            logger.info(f"🔍 分析文件: {file_path}")
            
            # 读取音频文件
            audio, sample_rate = sf.read(file_path)
            
            # 基本信息
            logger.info(f"📊 采样率: {sample_rate} Hz")
            logger.info(f"⏱️  时长: {len(audio) / sample_rate:.3f} 秒")
            logger.info(f"📈 样本数: {len(audio)}")
            
            # 振幅分析
            max_amp = np.max(np.abs(audio))
            rms_amp = np.sqrt(np.mean(audio**2))
            logger.info(f"🔊 最大振幅: {max_amp:.6f}")
            logger.info(f"📊 RMS振幅: {rms_amp:.6f}")
            
            # 检查是否有声音（非静音）
            if max_amp < 0.001:
                logger.warning(f"🔇 警告: 音频几乎是静音，最大振幅仅为 {max_amp:.6f}")
            else:
                logger.info(f"✅ 音频包含有效声音，最大振幅为 {max_amp:.6f}")
            
            # 频率分析（简单版本）
            self._analyze_frequency_content(audio, sample_rate)
            
            # 生成简单的波形图像
            self._generate_waveform_plot(audio, sample_rate, file_path)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 分析失败: {e}")
            return False
    
    def _analyze_frequency_content(self, audio, sample_rate):
        """简单的频率内容分析"""
        try:
            # 使用FFT进行频率分析
            n = len(audio)
            fft_result = np.fft.fft(audio)
            frequencies = np.fft.fftfreq(n, 1/sample_rate)
            magnitudes = np.abs(fft_result[:n//2])
            frequencies = frequencies[:n//2]
            
            # 找到主要频率
            if len(magnitudes) > 0:
                peak_freq_idx = np.argmax(magnitudes)
                peak_freq = frequencies[peak_freq_idx]
                peak_mag = magnitudes[peak_freq_idx]
                
                logger.info(f"🎵 主要频率: {peak_freq:.1f} Hz")
                logger.info(f"📊 主要频率强度: {peak_mag:.2f}")
                
                # 检查频率范围
                if 20 <= peak_freq <= 20000:
                    logger.info(f"✅ 主要频率在人耳可听范围内 (20-20000 Hz)")
                else:
                    logger.warning(f"⚠️  主要频率不在人耳可听范围内: {peak_freq:.1f} Hz")
        except Exception as e:
            logger.error(f"❌ 频率分析失败: {e}")
    
    def _generate_waveform_plot(self, audio, sample_rate, file_path):
        """生成波形图像文件"""
        try:
            # 创建图像目录
            image_dir = os.path.join('output', 'audio', 'waveforms')
            os.makedirs(image_dir, exist_ok=True)
            
            # 生成图像文件名
            base_name = os.path.basename(file_path)
            image_name = os.path.splitext(base_name)[0] + '_waveform.png'
            image_path = os.path.join(image_dir, image_name)
            
            # 创建波形图
            plt.figure(figsize=(10, 4))
            plt.plot(audio[:min(len(audio), sample_rate//2)])  # 只显示前500ms
            plt.title(f'波形图 - {base_name}')
            plt.xlabel('样本')
            plt.ylabel('振幅')
            plt.grid(True)
            plt.savefig(image_path)
            plt.close()
            
            logger.info(f"📊 波形图已保存: {image_path}")
        except Exception as e:
            logger.error(f"❌ 生成波形图失败: {e}")
    
    def analyze_directory(self, directory):
        """分析目录中的所有WAV文件"""
        if not os.path.exists(directory):
            logger.error(f"❌ 目录不存在: {directory}")
            return
        
        logger.info(f"📂 分析目录: {directory}")
        
        # 获取所有WAV文件
        wav_files = [f for f in os.listdir(directory) if f.lower().endswith('.wav')]
        
        if not wav_files:
            logger.warning(f"⚠️  目录中没有找到WAV文件")
            return
        
        logger.info(f"📋 找到 {len(wav_files)} 个WAV文件")
        
        # 分析每个文件
        success_count = 0
        for wav_file in wav_files:
            file_path = os.path.join(directory, wav_file)
            logger.info(f"\n{'='*50}")
            if self.analyze_file(file_path):
                success_count += 1
        
        logger.info(f"\n{'='*50}")
        logger.info(f"📊 分析完成: 成功 {success_count}/{len(wav_files)}")

def main():
    """主函数"""
    analyzer = AudioAnalyzer()
    
    # 优先分析real_tts目录中的文件
    real_tts_dir = os.path.join('output', 'audio', 'real_tts')
    if os.path.exists(real_tts_dir):
        logger.info(f"\n{'='*60}")
        logger.info(f"🎯 正在分析 real_tts 目录...")
        analyzer.analyze_directory(real_tts_dir)
    else:
        logger.warning(f"⚠️ real_tts 目录不存在: {real_tts_dir}")
    
    # 分析basic_tts目录中的文件
    basic_tts_dir = os.path.join('output', 'audio', 'basic_tts')
    if os.path.exists(basic_tts_dir):
        logger.info(f"\n{'='*60}")
        logger.info(f"🎯 正在分析 basic_tts 目录...")
        analyzer.analyze_directory(basic_tts_dir)
    else:
        logger.warning(f"⚠️ basic_tts 目录不存在: {basic_tts_dir}")
    
    # 也分析之前生成的其他音频文件
    audio_dir = os.path.join('output', 'audio')
    if os.path.exists(audio_dir):
        logger.info(f"\n{'='*60}")
        logger.info(f"📂 分析其他可能的音频文件...")
        
        # 检查根目录下的WAV文件
        root_wav_files = [f for f in os.listdir(audio_dir) if f.lower().endswith('.wav')]
        for wav_file in root_wav_files:
            file_path = os.path.join(audio_dir, wav_file)
            logger.info(f"\n{'='*50}")
            analyzer.analyze_file(file_path)

if __name__ == "__main__":
    main()