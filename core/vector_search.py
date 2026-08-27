from core.utils.logger import get_logger
import os
import logging
import threading
import time
from functools import lru_cache
from config.integrated_config import get_settings

# 配置日志
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = get_logger(__name__)

# 延迟导入以减少启动时间
_chromadb_loaded = False
_chromadb_module = None
Client = None
Settings = None
PersistentClient = None
EphemeralClient = None
get_tts_manager = None


class VectorSearch:
    # 低配电脑优化设置
    MAX_QUERY_LENGTH = 1000  # 限制查询文本长度
    DB_CACHE_SIZE = 20  # 数据库查询缓存大小（从50减少）

    def __init__(self, use_in_memory_db=False, collection_name: str = "default"):
        self._lock = threading.RLock()  # 可重入锁，保证线程安全
        self._initialized = False
        self._chromadb_module = None
        self.client = None
        self.collection = None
        self.tts_manager = None
        self._tts_cache = {}  # TTS结果缓存
        self._use_in_memory_db = (
            use_in_memory_db  # 使用内存数据库以减少磁盘I/O
        )
        self.collection_name = collection_name or "default"
        self.settings = get_settings()
        self.max_document_length = getattr(
            self.settings.vector_search, "max_document_length", 2000
        )
        self.max_query_length = getattr(
            self.settings.vector_search, "max_query_length", self.MAX_QUERY_LENGTH
        )
        self.tts_text_max_length = getattr(
            self.settings.vector_search, "tts_text_max_length", 500
        )
        self.truncate_log_interval_seconds = getattr(
            self.settings.vector_search,
            "truncate_log_interval_seconds",
            60.0,
        )
        self._truncate_counts = {"document": 0, "query": 0, "tts": 0}
        self._truncate_last_ids = {"document": None, "query": None, "tts": None}
        self._last_truncate_log_ts = 0.0

        # 初始化必要组件
        try:
            self._initialize_components()
        except Exception as e:
            logger.error(f"VectorSearch initialization failed: {e}", exc_info=True)
            # 即使初始化失败，也确保对象可用，后续操作会尝试重新初始化

    def _load_dependencies(self):
        """动态加载依赖"""
        global \
            _chromadb_loaded, \
            _chromadb_module, \
            Client, \
            Settings, \
            PersistentClient, \
            EphemeralClient, \
            get_tts_manager

        # print(f"DEBUG: Loading dependencies. _chromadb_loaded: {_chromadb_loaded}")
        if not _chromadb_loaded:
            try:
                try:
                    project_root = os.path.dirname(
                        os.path.dirname(os.path.abspath(__file__))
                    )
                    shadow_dir = os.path.join(project_root, "chromadb")
                    if os.path.isdir(shadow_dir) and not os.path.exists(
                        os.path.join(shadow_dir, "__init__.py")
                    ):
                        migrated_root = os.path.join(project_root, "data")
                        os.makedirs(migrated_root, exist_ok=True)
                        target_dir = os.path.join(migrated_root, "chromadb_store")

                        if not os.path.exists(target_dir):
                            os.rename(shadow_dir, target_dir)
                            logger.warning(
                                "检测到项目根目录存在 chromadb 数据目录，会遮蔽 pip 安装的 chromadb 包；已自动迁移到: %s",
                                os.path.abspath(target_dir),
                            )
                        else:
                            legacy_dir = os.path.join(
                                migrated_root,
                                f"chromadb_legacy_{int(__import__('time').time())}",
                            )
                            os.rename(shadow_dir, legacy_dir)
                            logger.warning(
                                "检测到项目根目录存在 chromadb 数据目录，会遮蔽 pip 安装的 chromadb 包；"
                                "由于目标目录已存在，已迁移到: %s",
                                os.path.abspath(legacy_dir),
                            )
                except Exception as e:
                    logger.warning(
                        "检测/迁移 chromadb 数据目录失败（可能导致 chromadb 包被遮蔽）: %s",
                        e,
                    )

                # 尝试加载chromadb，但失败时不中断程序
                try:
                    import chromadb

                    # print(f"DEBUG: chromadb imported. Version: {chromadb.__version__}")
                    # Chroma 新版本可能已移除 chromadb.Client，仅保留 PersistentClient/EphemeralClient
                    Client = getattr(chromadb, "Client", None)
                    PersistentClient = getattr(chromadb, "PersistentClient", None)
                    EphemeralClient = getattr(chromadb, "EphemeralClient", None)

                    try:
                        from chromadb.config import Settings as _Settings

                        Settings = _Settings
                    except Exception:
                        Settings = getattr(
                            getattr(chromadb, "config", None), "Settings", None
                        )

                    # 将 PersistentClient 存储为类属性或全局变量，
                    # 但这里我们只需在 _initialize_components 中检查 chromadb.PersistentClient 即可。
                    # 或者更好的方式是让 'chromadb' 全局可用或在方法内导入。
                    # 但为了与现有代码结构保持一致：
                    _chromadb_module = chromadb
                    self._chromadb_module = chromadb

                    if not (
                        PersistentClient
                        or EphemeralClient
                        or (Client and Settings)
                        or Client
                    ):
                        logger.error(
                            "已导入 chromadb，但未找到可用的 Client API。"
                            "这通常表示 chromadb 安装不完整或被同名目录遮蔽。"
                            "建议执行：python -m pip install -U chromadb"
                        )
                        _chromadb_module = None
                        self._chromadb_module = None
                        Client = None
                        Settings = None
                        PersistentClient = None
                        EphemeralClient = None

                    spec = getattr(chromadb, "__spec__", None)
                    if (
                        getattr(spec, "origin", None) is None
                        and getattr(spec, "submodule_search_locations", None) is not None
                    ):
                        try:
                            locations = list(
                                chromadb.__spec__.submodule_search_locations
                            )
                        except Exception:
                            locations = []
                        if any(
                            os.path.abspath(p).lower().endswith(os.sep + "chromadb")
                            and os.path.abspath(p)
                            .lower()
                            .startswith(os.path.abspath(os.getcwd()).lower())
                            for p in locations
                        ):
                            logger.error(
                                "当前导入到的是项目目录下的 chromadb（数据目录/命名空间包），不是 pip 安装的 chromadb 包。"
                                "请确保项目根目录不要存在名为 chromadb 的目录（会导致向量库不可用）。"
                            )
                            _chromadb_module = None
                            self._chromadb_module = None
                            Client = None
                            Settings = None
                            PersistentClient = None
                            EphemeralClient = None

                    # print("DEBUG: Client and Settings imported from chromadb")
                except ImportError as e:
                    logger.warning(f"chromadb not found or import error: {e}")
                    Client = None
                    Settings = None
                    PersistentClient = None
                    EphemeralClient = None
                    self._chromadb_module = None
                except Exception as e:
                    logger.error(f"Unexpected error importing chromadb: {e}")
                    Client = None
                    Settings = None
                    PersistentClient = None
                    EphemeralClient = None
                    self._chromadb_module = None

                # 尝试加载TTS管理器
                try:
                    from multimodal.tts_manager import get_tts_manager
                except ImportError:
                    logger.warning(
                        "TTS manager not found, speech synthesis functionality will be unavailable"
                    )
                    get_tts_manager = None

                # 导入certifi以修复SSL问题
                try:
                    import certifi

                    os.environ["SSL_CERT_FILE"] = certifi.where()
                    os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
                    # logger.info(f"Set SSL_CERT_FILE to {os.environ['SSL_CERT_FILE']}")
                except ImportError:
                    logger.warning(
                        "certifi not found, SSL certificate verification might fail"
                    )

                _chromadb_loaded = True
            except Exception as e:
                logger.error(f"Failed to load dependencies: {e}")
        else:
            self._chromadb_module = _chromadb_module

    def _initialize_components(self):
        """初始化组件"""
        with self._lock:
            if self._initialized:
                return

            # 加载依赖
            self._load_dependencies()

            # 初始化数据库客户端（如果可用）
            if self._chromadb_module:
                try:
                    # 使用chromadb新版本API
                    if self._use_in_memory_db:
                        # 内存模式
                        if EphemeralClient:
                            self.client = EphemeralClient()
                        elif Client:
                            self.client = Client()
                        else:
                            raise RuntimeError(
                                "chromadb 可用但未找到可用的 Client/EphemeralClient"
                            )
                        logger.info(
                            "Vector database initialized successfully in memory mode"
                        )
                    else:
                        # 持久化模式
                        project_root = os.path.dirname(
                            os.path.dirname(os.path.abspath(__file__))
                        )
                        persist_dir = os.path.join(
                            project_root, "data", "chromadb_store"
                        )
                        persist_dir = os.path.abspath(persist_dir)
                        os.makedirs(persist_dir, exist_ok=True)

                        if PersistentClient:
                            self.client = PersistentClient(path=persist_dir)
                        elif Client and Settings:
                            self.client = Client(
                                Settings(
                                    persist_directory=persist_dir,
                                    is_persistent=True,
                                )
                            )
                        elif Client:
                            logger.warning(
                                "chromadb 缺少 Settings/PersistentClient，已退化为非持久化 Client()；"
                                "向量库将不会落盘。建议升级 chromadb。"
                            )
                            self.client = Client()
                        else:
                            raise RuntimeError(
                                "chromadb 可用但未找到可用的 PersistentClient/Client+Settings"
                            )

                        logger.info(
                            f"Vector database initialized successfully in persistent mode: {persist_dir}"
                        )

                    # 显式使用轻量级嵌入模型以避免挂起
                    # [优化] 使用共享嵌入生成器以节省内存
                    try:
                        from memory.embedding_generator import embedding_generator

                        class SharedEmbeddingFunction:
                            def name(self):
                                return "sentence_transformer"

                            def __call__(self, input: list) -> list:
                                return self.embed_documents(input)

                            def embed_documents(self, texts: list) -> list:
                                if not isinstance(texts, list):
                                    texts = [texts]
                                embeddings = (
                                    embedding_generator.generate_embeddings_batch(texts)
                                )
                                return [emb.tolist() for emb in embeddings]

                            def embed_query(self, input: str) -> list:
                                text = (
                                    input[0]
                                    if isinstance(input, list) and input
                                    else str(input)
                                )
                                embeddings = (
                                    embedding_generator.generate_embeddings_batch(
                                        [text]
                                    )
                                )
                                return [embeddings[0].tolist()]

                        emb_fn = SharedEmbeddingFunction()
                        logger.info(
                            "Using shared embedding generator from memory module"
                        )
                    except ImportError:
                        logger.warning(
                            "Could not import shared embedding generator, falling back to local instance"
                        )
                        from chromadb.utils import embedding_functions

                        # 定义安全的嵌入函数创建包装器
                        def create_embedding_function():
                            # 确定模型路径（本地优先，其次在线），与统一生成器保持一致使用 bge-small-zh-v1.5
                            model_name = "bge-small-zh-v1.5"
                            project_root = os.path.dirname(
                                os.path.dirname(os.path.abspath(__file__))
                            )
                            local_model_path = os.path.join(
                                project_root,
                                "models",
                                "BERT",
                                "bge-small-zh-v1.5",
                            )

                            if os.path.exists(local_model_path):
                                logger.info(f"使用本地嵌入模型: {local_model_path}")
                                model_name = local_model_path
                                try:
                                    return embedding_functions.SentenceTransformerEmbeddingFunction(
                                        model_name=model_name,
                                        device="cpu",
                                        local_files_only=True,
                                    )
                                except Exception as e:
                                    logger.warning(
                                        f"本地加载失败，尝试非 local_files_only 模式: {e}"
                                    )

                            # 如果本地不存在，或者加载失败，则不再尝试联网下载，避免启动挂起
                            logger.warning(
                                "本地模型不可用，为保证系统启动速度，跳过联网下载。"
                            )
                            logger.warning(
                                "请手动运行 python scripts/download_embedding_model.py 下载模型。"
                            )

                            # 紧急情况的备用类
                            # 维度对齐统一生成器的默认模型（bge-small-zh-v1.5，512 维）
                            class DummyEmbeddingFunction:
                                def __call__(self, input):
                                    # 返回 512 维的零向量
                                    return [[0.0] * 512 for _ in input]

                            return DummyEmbeddingFunction()

                        emb_fn = create_embedding_function()

                    self.collection = self.client.get_or_create_collection(
                        self.collection_name,
                        embedding_function=emb_fn,
                        metadata={"hnsw:space": "cosine"},
                    )
                    logger.info("Vector database initialized successfully")
                except Exception as e:
                    logger.error(f"Failed to initialize vector database: {e}")
                    self.client = None
                    self.collection = None

            # 初始化TTS管理器（如果可用）
            if get_tts_manager:
                try:
                    self.tts_manager = get_tts_manager()
                    logger.info("TTS manager initialized successfully")
                except Exception as e:
                    logger.error(f"Failed to initialize TTS manager: {e}")
                    self.tts_manager = None

            self._initialized = True

    def _ensure_initialized(self):
        """确保组件已初始化"""
        if not self._initialized:
            self._initialize_components()

    def _record_truncate(self, kind, identifier=None):
        self._truncate_counts[kind] = self._truncate_counts.get(kind, 0) + 1
        if identifier:
            self._truncate_last_ids[kind] = identifier
        self._maybe_log_truncate_summary()

    def _maybe_log_truncate_summary(self):
        total = sum(self._truncate_counts.values())
        if total <= 0:
            return
        interval = float(self.truncate_log_interval_seconds or 0)
        now = time.monotonic()
        if (
            interval > 0
            and self._last_truncate_log_ts
            and (now - self._last_truncate_log_ts) < interval
        ):
            return
        parts = []
        for key in ("document", "query", "tts"):
            count = self._truncate_counts.get(key, 0)
            if count:
                part = f"{key}={count}"
                last_id = self._truncate_last_ids.get(key)
                if last_id:
                    part += f"(last={last_id})"
                parts.append(part)
        if parts:
            summary = ", ".join(parts)
            logger.warning(f"VectorSearch 截断汇总: {summary}")
        self._truncate_counts = {"document": 0, "query": 0, "tts": 0}
        self._last_truncate_log_ts = now

    def add_document(self, doc_id, text, metadata=None):
        """向向量数据库添加文档（优化版本）"""
        try:
            self._ensure_initialized()

            if not self.collection:
                logger.warning("Vector database not initialized, cannot add document")
                return False

            # 文本长度限制
            if len(text) > self.max_document_length:
                self._record_truncate("document", doc_id)
                text = text[: self.max_document_length]

            self.collection.add(
                documents=[text], ids=[doc_id], metadatas=[metadata or {}]
            )
            logger.debug(f"Document added successfully: {doc_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to add document: {doc_id} - {e}")
            return False

    @lru_cache(maxsize=DB_CACHE_SIZE)
    def query(self, text, top_k=3):
        """查询向量数据库（优化版本）"""
        try:
            self._ensure_initialized()

            if not self.collection:
                logger.warning(
                    "Vector database not initialized, returning empty results"
                )
                return []

            # 文本长度限制
            if len(text) > self.max_query_length:
                self._record_truncate("query")
                text = text[: self.max_query_length]

            # 优化查询参数
            results = self.collection.query(
                query_texts=[text],
                n_results=min(top_k, 5),  # 限制最大结果数
            )

            # 清理缓存（如果结果过多）
            if hasattr(self.query, "cache_info"):
                cache_info = self.query.cache_info()
                if cache_info.currsize > self.DB_CACHE_SIZE * 0.8:
                    # 当缓存接近限制时，清理部分
                    self.query.cache_clear()
                    logger.info("Vector query cache cleared")

            return results["documents"][0] if results and results["documents"] else []
        except Exception as e:
            logger.error(f"Vector query failed: {e}")
            return []

    def text_to_speech(self, text, output_file=None):
        """将文本转换为语音（优化版本）"""
        try:
            self._ensure_initialized()

            if not self.tts_manager:
                logger.warning("TTS manager not initialized, cannot generate speech")
                return None

            # 参数验证
            if not text or not isinstance(text, str):
                logger.warning("Invalid TTS input text")
                return None

            # 文本长度限制
            if len(text) > self.tts_text_max_length:
                self._record_truncate("tts")
                text = text[: self.tts_text_max_length]

            # 委托给TTS管理器处理缓存和生成
            # 注意：TTSManager.text_to_speech返回文件路径
            audio_path = self.tts_manager.text_to_speech(text)

            if audio_path and os.path.exists(audio_path):
                logger.debug(f"TTS generated successfully: {audio_path}")
                return audio_path
            else:
                logger.warning(f"TTS generation failed: {audio_path}")
                return None

        except Exception as e:
            logger.error(f"TTS processing failed: {e}", exc_info=True)
            return None

    # def speak_text(self, text):
    #     """Directly play text as speech (optimized version)"""
    #     try:
    #         self._ensure_initialized()
    #
    #         if not self.tts_manager:
    #             logger.warning("TTS manager not initialized, cannot play speech")
    #             return False
    #
    #         # Parameter validation and limitations
    #         if not text or not isinstance(text, str):
    #             logger.warning("Invalid speech playback text")
    #             return False
    #
    #         # Text length limit
    #         if len(text) > 300:
    #             logger.warning("Playback text too long, truncated")
    #             text = text[:300]
    #
    #         # Async playback to avoid blocking
    #         self.tts_manager.speak(text)
    #         logger.debug("Speech playback request sent")
    #         return True
    #     except Exception as e:
    #         logger.error(f"Speech playback failed: {e}")
    #         return False

    def clear_cache(self):
        """清理缓存以释放内存"""
        try:
            # 清理TTS缓存
            self._tts_cache.clear()

            # 清理查询缓存
            if hasattr(self.query, "cache_clear"):
                self.query.cache_clear()

            logger.info("VectorSearch cache cleared")
            return True
        except Exception as e:
            logger.error(f"Failed to clear cache: {e}")
            return False

    def close(self):
        """关闭资源"""
        try:
            # 清理缓存
            self.clear_cache()

            # 关闭客户端（如果支持）
            if hasattr(self.client, "close"):
                self.client.close()

            # 关闭TTS管理器（如果有close方法）
            if hasattr(self.tts_manager, "close"):
                self.tts_manager.close()

            self._initialized = False
            logger.info("VectorSearch resources released")
        except Exception as e:
            logger.error(f"Failed to close VectorSearch resources: {e}")

    def __del__(self):
        """析构函数，确保资源释放"""
        try:
            self.close()
        except Exception:
            pass  # 避免在析构函数中抛出异常
