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
        
        if not _chromadb_loaded:
            try:
                # Try to load chromadb, but don't interrupt program on failure
                try:
                    from chromadb import Client
                    from chromadb.config import Settings
                except ImportError:
                    logger.warning("chromadb not found, vector search functionality will be unavailable")
                    Client = None
                    Settings = None
                
                # Try to load TTS manager
                try:
                    from multimodal.tts_manager import get_tts_manager
                except ImportError:
                    logger.warning("TTS manager not found, speech synthesis functionality will be unavailable")
                    get_tts_manager = None
                
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
                    # Use chromadb new version API, supporting in-memory mode and persistent mode
                    if self._use_in_memory_db:
                        # In-memory mode - new API approach
                        self.client = Client()
                        logger.info("Vector database initialized successfully in memory mode")
                    else:
                        # Persistent mode - new API approach
                        persist_dir = "./chromadb"
                        os.makedirs(persist_dir, exist_ok=True)
                        self.client = Client(persist_dir)
                        logger.info(f"Vector database initialized successfully in persistent mode: {persist_dir}")
                    self.collection = self.client.get_or_create_collection(
                        "smallbot_kb",
                        metadata={"hnsw:space": "cosine"}  # Use cosine similarity, lower computational cost
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
            
            # Check cache
            cache_key = text if len(text) < 100 else hashlib.md5(text.encode()).hexdigest()
            if output_file is None and cache_key in self._tts_cache:
                cached_path = self._tts_cache[cache_key]
                if os.path.exists(cached_path):
                    logger.debug(f"TTS cache hit: {cache_key}")
                    return cached_path
            
            # Generate output file path
            if not output_file:
                file_id = hashlib.md5((text + str(time.time())[:8]).encode()).hexdigest()[:8]
                output_file = f"multimodal/voice/{file_id}.mp3"
            
            # Generate speech using TTS manager
            audio_path = self.tts_manager.generate_speech(text, output_file)
            
            # Validate result and cache
            if audio_path and os.path.exists(audio_path):
                logger.debug(f"TTS generated successfully: {audio_path}")
                # Update cache using LRU strategy
                if len(self._tts_cache) >= self.TTS_CACHE_SIZE:
                    # Remove earliest added item
                    self._tts_cache.pop(next(iter(self._tts_cache)))
                self._tts_cache[cache_key] = audio_path
                return audio_path
            else:
                logger.warning(f"TTS generation failed or file does not exist: {audio_path}")
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
