import os
import logging
import hashlib
import threading
import time
from functools import lru_cache

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 延迟导入以减少启动时间
_chromadb_loaded = False
Client = None
Settings = None
get_tts_manager = None

class VectorSearch:
    # 低配置电脑优化设置
    MAX_QUERY_LENGTH = 1000  # 限制查询文本长度
    TTS_CACHE_SIZE = 30      # TTS缓存大小
    DB_CACHE_SIZE = 50       # 数据库查询缓存大小
    
    def __init__(self, use_in_memory_db=True):
        self._lock = threading.RLock()  # 可重入锁确保线程安全
        self._initialized = False
        self.client = None
        self.collection = None
        self.tts_manager = None
        self._tts_cache = {}  # TTS结果缓存
        self._use_in_memory_db = use_in_memory_db  # 使用内存数据库减少磁盘I/O
        
        # 初始化必要组件
        try:
            self._initialize_components()
        except Exception as e:
            logger.error(f"VectorSearch初始化失败: {e}", exc_info=True)
            # 即使初始化失败，也要确保对象可用，后续操作会尝试重新初始化
    
    def _load_dependencies(self):
        """动态加载依赖项"""
        global _chromadb_loaded, Client, Settings, get_tts_manager
        
        if not _chromadb_loaded:
            try:
                # 尝试加载chromadb，但失败时不中断程序
                try:
                    from chromadb import Client
                    from chromadb.config import Settings
                except ImportError:
                    logger.warning("未找到chromadb，向量搜索功能将不可用")
                    Client = None
                    Settings = None
                
                # 尝试加载TTS管理器
                try:
                    from voice.tts_manager import get_tts_manager
                except ImportError:
                    logger.warning("未找到TTS管理器，语音合成功能将不可用")
                    get_tts_manager = None
                
                _chromadb_loaded = True
            except Exception as e:
                logger.error(f"加载依赖项失败: {e}")
    
    def _initialize_components(self):
        """初始化组件"""
        with self._lock:
            if self._initialized:
                return
            
            # 加载依赖项
            self._load_dependencies()
            
            # 初始化数据库客户端（如果可用）
            if Client and Settings:
                try:
                    # 使用chromadb新版本API，支持内存模式和持久化模式
                    if self._use_in_memory_db:
                        # 内存模式 - 新API方式
                        self.client = Client()
                        logger.info("向量数据库使用内存模式初始化成功")
                    else:
                        # 持久化模式 - 新API方式
                        persist_dir = "./chromadb"
                        os.makedirs(persist_dir, exist_ok=True)
                        self.client = Client(persist_dir)
                        logger.info(f"向量数据库使用持久化模式初始化成功: {persist_dir}")
                    self.collection = self.client.get_or_create_collection(
                        "smallbot_kb",
                        metadata={"hnsw:space": "cosine"}  # 使用cosine相似度，计算成本较低
                    )
                    logger.info("向量数据库初始化成功")
                except Exception as e:
                    logger.error(f"向量数据库初始化失败: {e}")
                    self.client = None
                    self.collection = None
            
            # 初始化TTS管理器（如果可用）
            if get_tts_manager:
                try:
                    self.tts_manager = get_tts_manager()
                    logger.info("TTS管理器初始化成功")
                except Exception as e:
                    logger.error(f"TTS管理器初始化失败: {e}")
                    self.tts_manager = None
            
            # 确保voice目录存在
            try:
                os.makedirs("voice", exist_ok=True)
                logger.info("Voice目录准备就绪")
            except Exception as e:
                logger.error(f"创建voice目录失败: {e}")
            
            self._initialized = True
    
    def _ensure_initialized(self):
        """确保组件已初始化"""
        if not self._initialized:
            self._initialize_components()
    
    def add_document(self, doc_id, text, metadata=None):
        """添加文档到向量数据库（优化版）"""
        try:
            self._ensure_initialized()
            
            if not self.collection:
                logger.warning("向量数据库未初始化，无法添加文档")
                return False
            
            # 文本长度限制
            if len(text) > 2000:
                logger.warning(f"文档过长，已截断: {doc_id}")
                text = text[:2000]
            
            self.collection.add(
                documents=[text], 
                ids=[doc_id], 
                metadatas=[metadata or {}]
            )
            logger.debug(f"文档添加成功: {doc_id}")
            return True
        except Exception as e:
            logger.error(f"添加文档失败: {doc_id} - {e}")
            return False
    
    @lru_cache(maxsize=DB_CACHE_SIZE)
    def query(self, text, top_k=3):
        """查询向量数据库（优化版）"""
        try:
            self._ensure_initialized()
            
            if not self.collection:
                logger.warning("向量数据库未初始化，返回空结果")
                return []
            
            # 文本长度限制
            if len(text) > self.MAX_QUERY_LENGTH:
                logger.warning("查询文本过长，已截断")
                text = text[:self.MAX_QUERY_LENGTH]
            
            # 优化查询参数
            results = self.collection.query(
                query_texts=[text], 
                n_results=min(top_k, 5)  # 限制最大结果数
            )
            
            # 清理缓存（如果结果太多）
            if hasattr(self.query, 'cache_info'):
                cache_info = self.query.cache_info()
                if cache_info.currsize > self.DB_CACHE_SIZE * 0.8:
                    # 当缓存接近上限时，清除一部分
                    self.query.cache_clear()
                    logger.info("向量查询缓存已清理")
            
            return results["documents"][0] if results and results["documents"] else []
        except Exception as e:
            logger.error(f"向量查询失败: {e}")
            return []
    
    def text_to_speech(self, text, output_file=None):
        """将文本转换为语音（优化版）"""
        try:
            self._ensure_initialized()
            
            if not self.tts_manager:
                logger.warning("TTS管理器未初始化，无法生成语音")
                return None
            
            # 参数验证
            if not text or not isinstance(text, str):
                logger.warning("无效的TTS输入文本")
                return None
            
            # 文本长度限制
            if len(text) > 500:
                logger.warning("TTS文本过长，已截断")
                text = text[:500]
            
            # 检查缓存
            cache_key = text if len(text) < 100 else hashlib.md5(text.encode()).hexdigest()
            if output_file is None and cache_key in self._tts_cache:
                cached_path = self._tts_cache[cache_key]
                if os.path.exists(cached_path):
                    logger.debug(f"TTS缓存命中: {cache_key}")
                    return cached_path
            
            # 生成输出文件路径
            if not output_file:
                file_id = hashlib.md5((text + str(time.time())[:8]).encode()).hexdigest()[:8]
                output_file = f"voice/{file_id}.mp3"
            
            # 使用TTS管理器生成语音
            audio_path = self.tts_manager.generate_speech(text, output_file)
            
            # 验证结果并缓存
            if audio_path and os.path.exists(audio_path):
                logger.debug(f"TTS生成成功: {audio_path}")
                # 更新缓存，使用LRU策略
                if len(self._tts_cache) >= self.TTS_CACHE_SIZE:
                    # 删除最早添加的项
                    self._tts_cache.pop(next(iter(self._tts_cache)))
                self._tts_cache[cache_key] = audio_path
                return audio_path
            else:
                logger.warning(f"TTS生成失败或文件不存在: {audio_path}")
                return None
        except Exception as e:
            logger.error(f"TTS处理失败: {e}", exc_info=True)
            return None
    
    def speak_text(self, text):
        """直接播放文本的语音（优化版）"""
        try:
            self._ensure_initialized()
            
            if not self.tts_manager:
                logger.warning("TTS管理器未初始化，无法播放语音")
                return False
            
            # 参数验证和限制
            if not text or not isinstance(text, str):
                logger.warning("无效的语音播放文本")
                return False
            
            # 文本长度限制
            if len(text) > 300:
                logger.warning("播放文本过长，已截断")
                text = text[:300]
            
            # 异步播放以避免阻塞
            self.tts_manager.speak(text)
            logger.debug("语音播放请求已发送")
            return True
        except Exception as e:
            logger.error(f"语音播放失败: {e}")
            return False
    
    def clear_cache(self):
        """清理缓存以释放内存"""
        try:
            # 清理TTS缓存
            self._tts_cache.clear()
            
            # 清理查询缓存
            if hasattr(self.query, 'cache_clear'):
                self.query.cache_clear()
            
            logger.info("VectorSearch缓存已清理")
            return True
        except Exception as e:
            logger.error(f"清理缓存失败: {e}")
            return False
    
    def close(self):
        """关闭资源"""
        try:
            # 清理缓存
            self.clear_cache()
            
            # 关闭客户端（如果支持）
            if hasattr(self.client, 'close'):
                self.client.close()
            
            # 关闭TTS管理器（如果有close方法）
            if hasattr(self.tts_manager, 'close'):
                self.tts_manager.close()
            
            self._initialized = False
            logger.info("VectorSearch资源已释放")
        except Exception as e:
            logger.error(f"关闭VectorSearch资源失败: {e}")
    
    def __del__(self):
        """析构函数，确保资源释放"""
        try:
            self.close()
        except:
            pass  # 避免析构函数中抛出异常
