import json, os, hashlib, logging, time
from functools import wraps
import asyncio
import inspect
from threading import Lock
from collections import OrderedDict
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 延迟导入以减少启动时的内存占用
# 这些模块将在需要时动态导入

# =======================================================
# 1. 高性能缓存装饰器 (优化版)
# =======================================================
class CacheManager:
    def __init__(self, max_size=100, ttl=3600):
        self.cache = OrderedDict()  # 使用OrderedDict以便LRU缓存
        self.lock = Lock()
        self.max_size = max_size  # 最大缓存项数
        self.ttl = ttl  # 缓存过期时间（秒）
    
    def get(self, key):
        with self.lock:
            if key in self.cache:
                value, timestamp = self.cache[key]
                # 检查是否过期
                if time.time() - timestamp < self.ttl:
                    # 更新访问顺序（LRU）
                    self.cache.move_to_end(key)
                    return value
                else:
                    # 删除过期项
                    del self.cache[key]
            return None
    
    def set(self, key, value):
        with self.lock:
            # 如果缓存已满，删除最少使用的项
            if len(self.cache) >= self.max_size and key not in self.cache:
                self.cache.popitem(last=False)
            # 存储值和时间戳
            self.cache[key] = (value, time.time())
    
    def clear(self):
        with self.lock:
            self.cache.clear()

# 创建全局缓存管理器实例
cache_manager = CacheManager(max_size=50, ttl=1800)  # 减少缓存大小和过期时间以节省内存

def cache_result(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            # 为低配置电脑优化的缓存键生成
            # 只使用前几个参数和关键字参数的子集来生成键
            serializable_args = []
            for i, arg in enumerate(args[:3]):  # 只使用前3个参数
                if hasattr(arg, 'get_history') and callable(arg.get_history):
                    # 安全地处理MemoryManager对象
                    try:
                        serializable_args.append(str(arg.get_history()[:10]))  # 只取历史记录的前10条
                    except Exception:
                        serializable_args.append(str(type(arg)))
                elif inspect.iscoroutine(arg) or inspect.isawaitable(arg) or callable(arg):
                    # 不序列化函数、协程或可调用对象
                    serializable_args.append(str(type(arg)))
                else:
                    try:
                        # 尝试将参数转换为JSON可序列化的形式
                        json.dumps(arg)
                        serializable_args.append(arg)
                    except (TypeError, OverflowError):
                        # 对于不可序列化的对象，使用类型名称
                        serializable_args.append(str(type(arg)))
            
            # 只使用关键字参数的前3个
            limited_kwargs = dict(list(kwargs.items())[:3])
            
            # 生成缓存键
            key_parts = [func.__name__, str(serializable_args), str(limited_kwargs)]
            key = hashlib.md5(''.join(key_parts).encode()).hexdigest()
            
            # 尝试从缓存获取结果
            cached_result = cache_manager.get(key)
            if cached_result is not None:
                logger.debug(f"缓存命中: {func.__name__}")
                return cached_result
            
            # 执行函数
            if inspect.iscoroutinefunction(func):
                res = await func(*args, **kwargs)
            else:
                # 对于同步函数，使用线程池执行
                res = await asyncio.to_thread(func, *args, **kwargs)
            
            # 只缓存可序列化且大小适中的结果
            try:
                if res is not None and sys.getsizeof(res) < 500000:  # 小于500KB
                    cache_manager.set(key, res)
                    logger.debug(f"缓存更新: {func.__name__}")
            except Exception as cache_error:
                logger.warning(f"缓存存储失败: {cache_error}")
            
            return res
        except Exception as e:
            logger.error(f"缓存装饰器错误: {e}", exc_info=True)
            # 即使缓存处理失败，也要尝试执行原函数
            if inspect.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)
    return wrapper

# =======================================================
# 2. 优化的TTS逻辑
# =======================================================
# 延迟导入以减少启动时间
vector_search = None
vector_lock = Lock()

async def init_vector_search():
    """异步初始化vector_search实例"""
    global vector_search
    with vector_lock:
        if vector_search is None:
            try:
                # 动态导入以减少启动时间
                from .vector_search import VectorSearch
                vector_search = await asyncio.to_thread(VectorSearch)
                logger.info("VectorSearch实例初始化成功")
            except Exception as e:
                logger.error(f"VectorSearch初始化失败: {e}")
                raise
    return vector_search

async def tts_generate(text: str):
    """使用vector模块的TTS功能生成语音（优化版）"""
    try:
        # 参数验证
        if not text or not isinstance(text, str):
            logger.warning("TTS输入无效")
            return None
        
        # 文本长度限制，防止处理过长文本
        if len(text) > 500:
            text = text[:500]
            logger.warning("TTS文本过长，已截断")
        
        # 确保vector_search实例已初始化
        vs = await init_vector_search()
        
        # 使用asyncio的线程池执行器来避免阻塞事件循环
        audio_path = await asyncio.to_thread(vs.text_to_speech, text)
        
        # 验证结果
        if audio_path and os.path.exists(audio_path):
            logger.debug(f"TTS生成成功: {audio_path}")
            return audio_path
        else:
            logger.warning("TTS生成失败，返回路径无效")
            return None
    except Exception as e:
        logger.error(f"TTS错误: {e}", exc_info=True)
        return None

# =======================================================
# 3. 优化的工具函数
# =======================================================

# 延迟导入jieba和SnowNLP
_jieba_loaded = False
_snownlp_loaded = False
_psutil_loaded = False

def load_jieba():
    global _jieba_loaded
    if not _jieba_loaded:
        try:
            import jieba.analyse
            _jieba_loaded = True
            logger.info("Jieba库加载成功")
        except ImportError:
            logger.error("Jieba库加载失败")
            raise

def load_snownlp():
    global _snownlp_loaded
    if not _snownlp_loaded:
        try:
            from snownlp import SnowNLP
            _snownlp_loaded = True
            logger.info("SnowNLP库加载成功")
        except ImportError:
            logger.error("SnowNLP库加载失败")
            raise

def load_psutil():
    global _psutil_loaded
    if not _psutil_loaded:
        try:
            import psutil
            _psutil_loaded = True
            logger.info("psutil库加载成功")
        except ImportError:
            logger.error("psutil库加载失败")
            raise

def extract_keywords(text, topK=3):
    """优化的关键词提取函数"""
    try:
        if not text or not isinstance(text, str):
            return []
        
        # 动态加载jieba
        load_jieba()
        import jieba.analyse
        
        # 文本长度限制
        if len(text) > 1000:
            text = text[:1000]
        
        # 提取关键词
        return jieba.analyse.extract_tags(text, topK=topK)
    except Exception as e:
        logger.error(f"关键词提取失败: {e}")
        return []

def analyze_emotion(text):
    """优化的情绪分析函数"""
    try:
        if not text or not isinstance(text, str):
            return None
        
        # 动态加载SnowNLP
        load_snownlp()
        from snownlp import SnowNLP
        
        # 文本长度限制
        if len(text) > 500:
            text = text[:500]
        
        # 分析情绪
        s = SnowNLP(text)
        return round(s.sentiments, 4)
    except Exception as e:
        logger.error(f"情绪分析失败: {e}")
        return None

def get_system_info():
    """优化的系统信息获取函数"""
    try:
        # 动态加载psutil
        load_psutil()
        import psutil
        
        # 使用更高效的方式获取系统信息
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 仅在需要时获取CPU和内存信息
        try:
            cpu = psutil.cpu_percent(interval=0.1)  # 使用较短的采样间隔
            mem = psutil.virtual_memory().percent
            return f"[系统信息: 时间 {now}, CPU {cpu}%, 内存 {mem}%]"
        except:
            # 如果无法获取资源使用情况，只返回时间
            return f"[系统信息: 时间 {now}]"
    except Exception as e:
        logger.error(f"获取系统信息失败: {e}")
        # 返回最小化的系统信息
        return f"[系统信息: 时间 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"

# 确保在导入时不会引入不必要的依赖
import sys

# 资源清理函数
def cleanup_utils():
    """清理工具函数使用的资源"""
    try:
        # 清除缓存
        cache_manager.clear()
        logger.info("工具函数缓存已清理")
    except Exception as e:
        logger.error(f"清理工具函数资源失败: {e}")