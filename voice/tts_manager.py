import os
import logging
import threading
import time
import asyncio
import hashlib
from functools import lru_cache

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Edge TTS支持
edge_tts = None
edge_tts_voice = "zh-CN-XiaoyiNeural"  # 指定语音角色

# 延迟导入以减少启动时间
pyttsx3 = None

class TTSManager:
    # 低配置电脑优化参数
    MAX_TEXT_LENGTH = 300       # 限制处理文本长度
    MIN_RATE = 100              # 最低语速
    MAX_RATE = 250              # 最高语速
    PLAYBACK_CACHE_SIZE = 20    # 播放缓存大小
    MAX_RETRY_COUNT = 2         # 最大重试次数
    RETRY_DELAY_MS = 500        # 重试延迟(毫秒)
    
    # TTS引擎类型
    ENGINE_PYTTSX3 = "pyttsx3"
    ENGINE_EDGE_TTS = "edge_tts"
    
    def __init__(self):
        self.engine = None
        self._lock = threading.RLock()  # 可重入锁确保线程安全
        self._initialized = False
        self._playback_thread = None
        self._is_playing = False
        self._config = {
            'rate': 130,           # 降低语速以提高语音质量和自然度
            'volume': 1.0,         # 默认音量
            'language': 'chinese',  # 默认语言
            'engine': self.ENGINE_EDGE_TTS  # 使用Edge TTS引擎
        }
        # 简单的播放缓存
        self._playback_cache = {}
        
        # 延迟初始化，不立即创建引擎
        logger.info("TTSManager已创建，引擎将在首次使用时初始化")
    
    def _load_pyttsx3(self):
        """动态加载pyttsx3库"""
        global pyttsx3
        if pyttsx3 is None:
            try:
                import pyttsx3
                logger.info("pyttsx3库加载成功")
            except ImportError:
                logger.error("pyttsx3库未安装，TTS功能不可用")
                return False
        return pyttsx3 is not None
    
    def _load_edge_tts(self):
        """动态加载Edge TTS库"""
        global edge_tts
        if edge_tts is None:
            try:
                import edge_tts
                logger.info("Edge TTS库加载成功")
            except ImportError:
                logger.error("Edge TTS库未安装，尝试使用pyttsx3作为备选")
                return False
        return edge_tts is not None
    
    def _initialize_engine(self):
        """初始化TTS引擎"""
        with self._lock:
            if self._initialized:
                return True
            
            # 检查使用的引擎类型
            if self._config['engine'] == self.ENGINE_EDGE_TTS:
                # 尝试使用Edge TTS
                if self._load_edge_tts():
                    self._initialized = True
                    logger.info(f"Edge TTS引擎初始化成功，使用语音: {edge_tts_voice}")
                    return True
                else:
                    # 失败后回退到pyttsx3
                    logger.warning("Edge TTS初始化失败，回退到pyttsx3")
                    self._config['engine'] = self.ENGINE_PYTTSX3
            
            # 使用pyttsx3作为备选
            if not self._load_pyttsx3():
                return False
            
            # 尝试初始化pyttsx3引擎
            try:
                self.engine = pyttsx3.init(driverName=None, debug=False)
                
                # 应用配置
                self.set_rate(self._config['rate'])
                self.set_volume(self._config['volume'])
                self.set_voice_language(self._config['language'])
                
                # 设置事件回调
                self.engine.connect('started-utterance', self._on_utterance_start)
                self.engine.connect('finished-utterance', self._on_utterance_end)
                
                self._initialized = True
                logger.info("pyttsx3 TTS引擎初始化成功")
                return True
            except Exception as e:
                logger.error(f"TTS引擎初始化失败: {e}", exc_info=True)
                self.engine = None
                return False
    
    def _on_utterance_start(self, name, location, length):
        """语音开始播放回调"""
        self._is_playing = True
        logger.debug(f"语音开始播放: {name}")
    
    def _on_utterance_end(self, name, completed):
        """语音结束播放回调"""
        self._is_playing = False
        status = "成功" if completed else "中断"
        logger.debug(f"语音播放结束: {name}, 状态: {status}")
    
    def set_voice_language(self, language='chinese'):
        """设置语音语言（优化版）"""
        if not self.engine and not self._initialize_engine():
            return False
        
        try:
            voices = self.engine.getProperty('voices')
            if not voices:
                logger.warning("系统中未找到可用的语音")
                return False
            
            # 优先尝试找到中文语音，增强匹配逻辑
            target_voice = None
            preferred_voice_indices = []
            
            for i, voice in enumerate(voices):
                voice_id = voice.id.lower() if voice.id else ''
                voice_name = voice.name.lower() if voice.name else ''
                voice_info = f"{voice_id} {voice_name}"
                
                # 更严格的中文语音匹配规则
                if ('china' in voice_info and 'female' in voice_info) or \
                   ('chinese' in voice_info and 'female' in voice_info):
                    # 优先选择女性中文语音，通常更自然
                    preferred_voice_indices.insert(0, i)  # 放在最前面
                elif 'china' in voice_info or \
                     'chinese' in voice_info or \
                     'zh' in voice_info or \
                     '中文' in voice_info or \
                     '普通话' in voice_info:
                    preferred_voice_indices.append(i)
            
            # 选择最佳语音
            if preferred_voice_indices:
                # 使用第一个匹配的语音
                best_voice = voices[preferred_voice_indices[0]]
                self.engine.setProperty('voice', best_voice.id)
                self._config['language'] = language
                logger.info(f"语音设置为: {best_voice.id}")
                return True
            else:
                # 如果没有找到专门的中文语音，尝试选择听起来更自然的语音
                # 通常第0个是系统默认，但有些系统上第1或第2个可能更好
                best_voice_index = 0
                if len(voices) > 1:
                    # 尝试选择第二个语音，有些系统上第二个是更自然的
                    best_voice_index = 1
                
                self.engine.setProperty('voice', voices[best_voice_index].id)
                logger.warning(f"未找到专门的{language}语言语音，使用备用语音: {voices[best_voice_index].id}")
                return True
        except Exception as e:
            logger.error(f"设置语音语言失败: {e}")
            return False
    
    def set_rate(self, rate):
        """设置语速（优化版）"""
        # 限制语速范围
        safe_rate = max(self.MIN_RATE, min(self.MAX_RATE, rate))
        
        if not self.engine and not self._initialize_engine():
            # 如果引擎未初始化，先保存配置
            self._config['rate'] = safe_rate
            return False
        
        try:
            self.engine.setProperty('rate', safe_rate)
            self._config['rate'] = safe_rate
            logger.debug(f"语速设置为: {safe_rate}")
            return True
        except Exception as e:
            logger.error(f"设置语速失败: {e}")
            return False
    
    def set_volume(self, volume):
        """设置音量（优化版）"""
        # 限制音量范围
        safe_volume = max(0.0, min(1.0, volume))
        
        if not self.engine and not self._initialize_engine():
            # 如果引擎未初始化，先保存配置
            self._config['volume'] = safe_volume
            return False
        
        try:
            self.engine.setProperty('volume', safe_volume)
            self._config['volume'] = safe_volume
            logger.debug(f"音量设置为: {safe_volume}")
            return True
        except Exception as e:
            logger.error(f"设置音量失败: {e}")
            return False
    
    def _clean_text(self, text):
        """清理并验证文本"""
        if not text or not isinstance(text, str):
            return None
        
        # 去除多余空白字符
        cleaned = ' '.join(text.split())
        
        # 限制文本长度
        if len(cleaned) > self.MAX_TEXT_LENGTH:
            logger.warning(f"TTS文本过长，已截断至{self.MAX_TEXT_LENGTH}字符")
            cleaned = cleaned[:self.MAX_TEXT_LENGTH]
        
        return cleaned
    
    def speak(self, text):
        """播放文本语音（优化版）"""
        # 清理并验证文本
        cleaned_text = self._clean_text(text)
        if not cleaned_text:
            logger.warning("无效的TTS输入文本")
            return False
        
        # 初始化引擎
        if not self.engine and not self._initialize_engine():
            return False
        
        # 尝试使用缓存的语音文件
        cache_key = hashlib.md5(cleaned_text.encode()).hexdigest()
        if cache_key in self._playback_cache:
            cached_file = self._playback_cache[cache_key]
            if os.path.exists(cached_file):
                # 这里可以添加使用系统播放器播放缓存文件的逻辑
                logger.debug(f"使用缓存的语音文件: {cached_file}")
        
        # 执行语音播放，支持重试
        retries = 0
        while retries <= self.MAX_RETRY_COUNT:
            try:
                with self._lock:
                    self.engine.say(cleaned_text)
                    self.engine.runAndWait()
                logger.info(f"语音播放成功: {len(cleaned_text)}字符")
                return True
            except Exception as e:
                retries += 1
                if retries > self.MAX_RETRY_COUNT:
                    logger.error(f"语音播放失败(已重试{self.MAX_RETRY_COUNT}次): {e}", exc_info=True)
                    # 尝试重新初始化引擎
                    self._initialized = False
                    return False
                logger.warning(f"语音播放失败，{retries}秒后重试: {e}")
                time.sleep(self.RETRY_DELAY_MS / 1000.0)
    
    def save_to_file(self, text, filename):
        """将文本保存为音频文件（优化版）"""
        # 清理并验证文本
        cleaned_text = self._clean_text(text)
        if not cleaned_text:
            logger.warning("无效的TTS输入文本")
            return None
        
        # 初始化引擎
        if not self.engine and not self._initialize_engine():
            return None
        
        # 验证并确保文件路径有效
        if not filename:
            logger.warning("无效的音频文件路径")
            return None
        
        try:
            # 确保目录存在
            dir_path = os.path.dirname(os.path.abspath(filename))
            os.makedirs(dir_path, exist_ok=True)
            
            # 执行文件保存，支持重试
            retries = 0
            while retries <= self.MAX_RETRY_COUNT:
                try:
                    with self._lock:
                        self.engine.save_to_file(cleaned_text, filename)
                        self.engine.runAndWait()
                    
                    # 验证文件是否成功创建
                    if os.path.exists(filename) and os.path.getsize(filename) > 0:
                        # 更新缓存
                        cache_key = hashlib.md5(cleaned_text.encode()).hexdigest()
                        # 保持缓存大小限制
                        if len(self._playback_cache) >= self.PLAYBACK_CACHE_SIZE:
                            # 删除最早添加的项
                            self._playback_cache.pop(next(iter(self._playback_cache)))
                        self._playback_cache[cache_key] = filename
                        
                        logger.info(f"语音文件保存成功: {filename} ({os.path.getsize(filename)}字节)")
                        return filename
                    else:
                        raise Exception("创建的文件为空或不存在")
                except Exception as e:
                    retries += 1
                    if retries > self.MAX_RETRY_COUNT:
                        logger.error(f"保存语音文件失败(已重试{self.MAX_RETRY_COUNT}次): {e}")
                        return None
                    logger.warning(f"保存语音文件失败，{self.RETRY_DELAY_MS}毫秒后重试: {e}")
                    time.sleep(self.RETRY_DELAY_MS / 1000.0)
        except Exception as e:
            logger.error(f"保存语音文件过程中发生错误: {e}", exc_info=True)
            return None
    
    def generate_speech(self, text, output_file):
        """生成语音并保存到指定文件（Vector模块调用的方法）"""
        # 确保引擎已初始化
        self._initialize_engine()
        
        # 检查是否使用Edge TTS引擎
        if self._config['engine'] == self.ENGINE_EDGE_TTS and edge_tts:
            # 对于Edge TTS，使用异步方法但在同步环境中运行
            try:
                import asyncio
                # 检查当前是否已经在事件循环中
                try:
                    loop = asyncio.get_running_loop()
                    # 如果已经在事件循环中，使用run_coroutine_threadsafe
                    future = asyncio.run_coroutine_threadsafe(
                        self._save_with_edge_tts(text, output_file),
                        loop
                    )
                    return future.result(timeout=10)  # 设置超时时间
                except RuntimeError:
                    # 如果不在事件循环中，创建新的事件循环
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        return loop.run_until_complete(
                            self._save_with_edge_tts(text, output_file)
                        )
                    finally:
                        loop.close()
            except Exception as e:
                logger.error(f"Edge TTS同步调用失败: {e}")
                # 失败时回退到pyttsx3
                return self.save_to_file(text, output_file)
        else:
            # 使用pyttsx3作为备选
            return self.save_to_file(text, output_file)
    
    async def speak_async(self, text):
        """异步播放文本语音（优化版）"""
        # 使用线程池执行同步操作，避免阻塞事件循环
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None,  # 使用默认线程池
                self.speak,
                text
            )
        except Exception as e:
            logger.error(f"异步语音播放失败: {e}")
            return False
    
    async def save_to_file_async(self, text, filename):
        """异步保存音频文件（优化版）"""
        # 清理并验证文本
        cleaned_text = self._clean_text(text)
        if not cleaned_text:
            logger.warning("无效的TTS输入文本")
            return None
        
        # 验证并确保文件路径有效
        if not filename:
            logger.warning("无效的音频文件路径")
            return None
        
        # 确保目录存在
        dir_path = os.path.dirname(os.path.abspath(filename))
        os.makedirs(dir_path, exist_ok=True)
        
        # 初始化引擎
        if not self._initialize_engine():
            return None
        
        # 检查是否使用Edge TTS
        if self._config['engine'] == self.ENGINE_EDGE_TTS and edge_tts:
            return await self._save_with_edge_tts(cleaned_text, filename)
        
        # 使用pyttsx3作为备选
        # 使用线程池执行同步操作，避免阻塞事件循环
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None,  # 使用默认线程池
                self.save_to_file,
                cleaned_text,
                filename
            )
        except Exception as e:
            logger.error(f"异步保存语音文件失败: {e}")
            return None
    
    async def _save_with_edge_tts(self, text, filename):
        """使用Edge TTS保存音频文件"""
        try:
            # 创建Edge TTS通信器
            communicate = edge_tts.Communicate(text, voice=edge_tts_voice)
            
            # 保存音频文件
            with open(filename, "wb") as file:
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        file.write(chunk["data"])
            
            # 验证文件是否成功创建
            if os.path.exists(filename) and os.path.getsize(filename) > 0:
                # 更新缓存
                cache_key = hashlib.md5(text.encode()).hexdigest()
                # 保持缓存大小限制
                if len(self._playback_cache) >= self.PLAYBACK_CACHE_SIZE:
                    # 删除最早添加的项
                    self._playback_cache.pop(next(iter(self._playback_cache)))
                self._playback_cache[cache_key] = filename
                
                logger.info(f"Edge TTS语音文件保存成功: {filename} ({os.path.getsize(filename)}字节)")
                return filename
            else:
                raise Exception("创建的文件为空或不存在")
        except Exception as e:
            logger.error(f"Edge TTS保存失败: {e}", exc_info=True)
            return None
    
    def is_playing(self):
        """检查是否正在播放语音"""
        return self._is_playing
    
    def stop(self):
        """停止当前语音播放"""
        try:
            with self._lock:
                if self.engine:
                    self.engine.stop()
                    self._is_playing = False
                    logger.info("语音播放已停止")
                    return True
        except Exception as e:
            logger.error(f"停止语音播放失败: {e}")
        return False
    
    def clear_cache(self):
        """清理缓存以释放资源"""
        try:
            self._playback_cache.clear()
            logger.info("TTS缓存已清理")
            return True
        except Exception as e:
            logger.error(f"清理TTS缓存失败: {e}")
            return False
    
    def close(self):
        """关闭TTS引擎并释放资源"""
        try:
            # 停止当前播放
            self.stop()
            
            # 清理缓存
            self.clear_cache()
            
            # 关闭引擎
            if self.engine:
                try:
                    self.engine.endLoop()
                except:
                    pass  # 忽略可能不存在的方法
                
                try:
                    self.engine = None
                except:
                    pass
            
            self._initialized = False
            logger.info("TTS引擎已关闭")
            return True
        except Exception as e:
            logger.error(f"关闭TTS引擎失败: {e}")
            return False
    
    def __del__(self):
        """析构函数，确保资源释放"""
        try:
            self.close()
        except:
            pass  # 避免析构函数中抛出异常

# 全局单例实例
_tts_manager_instance = None
_tts_manager_lock = threading.RLock()

def get_tts_manager():
    """获取TTS管理器单例（线程安全版）"""
    global _tts_manager_instance
    with _tts_manager_lock:
        if _tts_manager_instance is None:
            _tts_manager_instance = TTSManager()
        return _tts_manager_instance

def cleanup_tts():
    """清理TTS资源"""
    global _tts_manager_instance
    with _tts_manager_lock:
        if _tts_manager_instance is not None:
            _tts_manager_instance.close()
            _tts_manager_instance = None
            logger.info("TTS资源已清理")

# 测试代码
if __name__ == "__main__":
    try:
        tts = get_tts_manager()
        tts.speak("你好，这是AI助手的语音功能测试")
    finally:
        # 确保测试结束后清理资源
        cleanup_tts()
    tts.save_to_file("这是保存的语音文件测试", "test_output.mp3")