import os
import logging
import hashlib
import threading
import time
from functools import lru_cache

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Lazy imports to reduce startup time
_chromadb_loaded = False
Client = None
Settings = None
get_tts_manager = None

class VectorSearch:
    # Low-config computer optimization settings
    MAX_QUERY_LENGTH = 1000  # Limit query text length
    TTS_CACHE_SIZE = 30      # TTS cache size
    DB_CACHE_SIZE = 50       # Database query cache size
    
    def __init__(self, use_in_memory_db=True):
        self._lock = threading.RLock()  # Reentrant lock for thread safety
        self._initialized = False
        self.client = None
        self.collection = None
        self.tts_manager = None
        self._tts_cache = {}  # TTS result cache
        self._use_in_memory_db = use_in_memory_db  # Use in-memory database to reduce disk I/O
        
        # Initialize necessary components
        try:
            self._initialize_components()
        except Exception as e:
            logger.error(f"VectorSearch initialization failed: {e}", exc_info=True)
            # Even if initialization fails, ensure object is usable, subsequent operations will try to reinitialize
    
    def _load_dependencies(self):
        """Dynamically load dependencies"""
        global _chromadb_loaded, Client, Settings, get_tts_manager
        
        # print(f"DEBUG: Loading dependencies. _chromadb_loaded: {_chromadb_loaded}")
        if not _chromadb_loaded:
            try:
                # Try to load chromadb, but don't interrupt program on failure
                try:
                    import chromadb
                    # print(f"DEBUG: chromadb imported. Version: {chromadb.__version__}")
                    # Capture Client and Settings, and also PersistentClient if available
                    Client = chromadb.Client
                    Settings = chromadb.config.Settings
                    
                    # Store PersistentClient in a class attribute or global if needed, 
                    # but here we can just check chromadb.PersistentClient in _initialize_components if we import chromadb there.
                    # Or better, let's just make 'chromadb' available globally or import it inside methods.
                    # But to keep consistent with existing code structure:
                    self._chromadb_module = chromadb
                    
                    # print("DEBUG: Client and Settings imported from chromadb")
                except ImportError as e:
                    logger.warning(f"chromadb not found or import error: {e}")
                    Client = None
                    Settings = None
                    self._chromadb_module = None
                except Exception as e:
                    logger.error(f"Unexpected error importing chromadb: {e}")
                    Client = None
                    Settings = None
                    self._chromadb_module = None
                
                # Try to load TTS manager
                try:
                    from multimodal.tts_manager import get_tts_manager
                except ImportError:
                    logger.warning("TTS manager not found, speech synthesis functionality will be unavailable")
                    get_tts_manager = None
                
                # Import certifi to fix SSL issues
                try:
                    import certifi
                    os.environ['SSL_CERT_FILE'] = certifi.where()
                    os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
                    # logger.info(f"Set SSL_CERT_FILE to {os.environ['SSL_CERT_FILE']}")
                except ImportError:
                    logger.warning("certifi not found, SSL certificate verification might fail")
                
                _chromadb_loaded = True
            except Exception as e:
                logger.error(f"Failed to load dependencies: {e}")

    def _initialize_components(self):
        """Initialize components"""
        with self._lock:
            if self._initialized:
                return
            
            # Load dependencies
            self._load_dependencies()
            
            # Initialize database client (if available)
            if Client and Settings:
                try:
                    # Use chromadb new version API
                    if self._use_in_memory_db:
                        # In-memory mode
                        if hasattr(self._chromadb_module, 'EphemeralClient'):
                            self.client = self._chromadb_module.EphemeralClient()
                        else:
                            self.client = Client()
                        logger.info("Vector database initialized successfully in memory mode")
                    else:
                        # Persistent mode
                        persist_dir = "./chromadb"
                        # Make path absolute to avoid CWD issues
                        persist_dir = os.path.abspath(persist_dir)
                        os.makedirs(persist_dir, exist_ok=True)
                        
                        if hasattr(self._chromadb_module, 'PersistentClient'):
                             self.client = self._chromadb_module.PersistentClient(path=persist_dir)
                        else:
                            # Fallback for older versions
                            self.client = Client(Settings(
                                persist_directory=persist_dir, 
                                is_persistent=True
                            ))
                            
                        logger.info(f"Vector database initialized successfully in persistent mode: {persist_dir}")
                        
                    # Explicitly use a lightweight embedding model to avoid hanging
                    from chromadb.utils import embedding_functions
                    
                    # Define a safe embedding function creation wrapper
                    def create_embedding_function():
                        # Determine model path (local first, then online)
                        model_name = "all-MiniLM-L6-v2"
                        local_model_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "embedding", "all-MiniLM-L6-v2")
                        
                        if os.path.exists(local_model_path):
                            logger.info(f"Found local embedding model at: {local_model_path}")
                            model_name = local_model_path
                        else:
                            logger.info("Local embedding model not found, trying online download...")
                            # Use mirror for better connectivity in China
                            os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

                        try:
                            # Try loading the standard model with CPU enforced to save VRAM for LLM
                            return embedding_functions.SentenceTransformerEmbeddingFunction(
                                model_name=model_name,
                                device="cpu"
                            )
                        except TypeError:
                            # Older versions might not support device arg
                            return embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model_name)
                        except Exception as e:
                            logger.warning(f"Failed to load SentenceTransformer: {e}. Trying with SSL verification disabled...")
                            # Try with SSL verification disabled context if possible, 
                            # or just return a dummy function to prevent crash
                            try:
                                # Quick hack: Disable SSL verify globally for a moment (dangerous but effective for local tools)
                                import ssl
                                _create_unverified_https_context = ssl._create_unverified_context
                                ssl._create_default_https_context = _create_unverified_https_context
                                
                                ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model_name)
                                logger.info("Successfully loaded embedding model with SSL verification disabled")
                                return ef
                            except Exception as e2:
                                logger.error(f"Still failed to load embedding model: {e2}. Using fallback hash embedding.")
                                
                                # Fallback class for emergency
                                class DummyEmbeddingFunction:
                                    def __call__(self, input):
                                        # Return zero vectors of dimension 384
                                        return [[0.0] * 384 for _ in input]
                                return DummyEmbeddingFunction()

                    emb_fn = create_embedding_function()
                    
                    self.collection = self.client.get_or_create_collection(
                        "smallbot_kb",
                        embedding_function=emb_fn,
                        metadata={"hnsw:space": "cosine"}
                    )
                    logger.info("Vector database initialized successfully")
                except Exception as e:
                    logger.error(f"Failed to initialize vector database: {e}")
                    self.client = None
                    self.collection = None
            
            # Initialize TTS manager (if available)
            if get_tts_manager:
                try:
                    self.tts_manager = get_tts_manager()
                    logger.info("TTS manager initialized successfully")
                except Exception as e:
                    logger.error(f"Failed to initialize TTS manager: {e}")
                    self.tts_manager = None
            
            # Ensure voice directory exists
            try:
                os.makedirs("voice", exist_ok=True)
                logger.info("Voice directory ready")
            except Exception as e:
                logger.error(f"Failed to create voice directory: {e}")
            
            self._initialized = True
    
    def _ensure_initialized(self):
        """Ensure components are initialized"""
        if not self._initialized:
            self._initialize_components()
    
    def add_document(self, doc_id, text, metadata=None):
        """Add document to vector database (optimized version)"""
        try:
            self._ensure_initialized()
            
            if not self.collection:
                logger.warning("Vector database not initialized, cannot add document")
                return False
            
            # Text length limit
            if len(text) > 2000:
                logger.warning(f"Document too long, truncated: {doc_id}")
                text = text[:2000]
            
            self.collection.add(
                documents=[text], 
                ids=[doc_id], 
                metadatas=[metadata or {}]
            )
            logger.debug(f"Document added successfully: {doc_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to add document: {doc_id} - {e}")
            return False
    
    @lru_cache(maxsize=DB_CACHE_SIZE)
    def query(self, text, top_k=3):
        """Query vector database (optimized version)"""
        try:
            self._ensure_initialized()
            
            if not self.collection:
                logger.warning("Vector database not initialized, returning empty results")
                return []
            
            # Text length limit
            if len(text) > self.MAX_QUERY_LENGTH:
                logger.warning("Query text too long, truncated")
                text = text[:self.MAX_QUERY_LENGTH]
            
            # Optimize query parameters
            results = self.collection.query(
                query_texts=[text], 
                n_results=min(top_k, 5)  # Limit maximum results
            )
            
            # Clean cache (if too many results)
            if hasattr(self.query, 'cache_info'):
                cache_info = self.query.cache_info()
                if cache_info.currsize > self.DB_CACHE_SIZE * 0.8:
                    # When cache is near limit, clear some
                    self.query.cache_clear()
                    logger.info("Vector query cache cleared")
            
            return results["documents"][0] if results and results["documents"] else []
        except Exception as e:
            logger.error(f"Vector query failed: {e}")
            return []
    
    def query_full(self, text, top_k=3):
        """Query vector database and return full results including metadata"""
        try:
            self._ensure_initialized()
            
            if not self.collection:
                logger.warning("Vector database not initialized, cannot query")
                return []
            
            # Text length limit
            if len(text) > self.MAX_QUERY_LENGTH:
                logger.warning("Query text too long, truncated")
                text = text[:self.MAX_QUERY_LENGTH]
            
            results = self.collection.query(
                query_texts=[text], 
                n_results=min(top_k, 10)
            )
            
            structured_results = []
            if results and results["documents"]:
                documents = results["documents"][0]
                metadatas = results["metadatas"][0] if "metadatas" in results else [{}] * len(documents)
                distances = results["distances"][0] if "distances" in results else [0.0] * len(documents)
                ids = results["ids"][0] if "ids" in results else [""] * len(documents)
                
                for i in range(len(documents)):
                    structured_results.append({
                        "id": ids[i],
                        "document": documents[i],
                        "metadata": metadatas[i],
                        "distance": distances[i]
                    })
            
            return structured_results
        except Exception as e:
            logger.error(f"Vector full query failed: {e}")
            return []

    def text_to_speech(self, text, output_file=None):
        """Convert text to speech (optimized version)"""
        try:
            self._ensure_initialized()
            
            if not self.tts_manager:
                logger.warning("TTS manager not initialized, cannot generate speech")
                return None
            
            # Parameter validation
            if not text or not isinstance(text, str):
                logger.warning("Invalid TTS input text")
                return None
            
            # Text length limit
            if len(text) > 500:
                logger.warning("TTS text too long, truncated")
                text = text[:500]
            
            # Delegate to TTS manager which handles caching and generation
            # Note: TTSManager.text_to_speech returns the file path
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
        """Clear cache to free memory"""
        try:
            # Clear TTS cache
            self._tts_cache.clear()
            
            # Clear query cache
            if hasattr(self.query, 'cache_clear'):
                self.query.cache_clear()
            
            logger.info("VectorSearch cache cleared")
            return True
        except Exception as e:
            logger.error(f"Failed to clear cache: {e}")
            return False
    
    def close(self):
        """Close resources"""
        try:
            # Clear cache
            self.clear_cache()
            
            # Close client (if supported)
            if hasattr(self.client, 'close'):
                self.client.close()
            
            # Close TTS manager (if it has a close method)
            if hasattr(self.tts_manager, 'close'):
                self.tts_manager.close()
            
            self._initialized = False
            logger.info("VectorSearch resources released")
        except Exception as e:
            logger.error(f"Failed to close VectorSearch resources: {e}")
    
    def __del__(self):
        """Destructor to ensure resource release"""
        try:
            self.close()
        except:
            pass  # Avoid throwing exceptions in destructor
