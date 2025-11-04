import json, os, hashlib, logging, time
from functools import wraps
import asyncio
import inspect
from threading import Lock
from collections import OrderedDict
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Lazy imports to reduce memory usage at startup
# These modules will be dynamically imported when needed

# =======================================================
# 1. High-performance Cache Decorator (Optimized Version)
# =======================================================

class CacheManager:
    def __init__(self, max_size=100, ttl=3600):
        self.cache = OrderedDict()  # Use OrderedDict for LRU caching
        self.lock = Lock()
        self.max_size = max_size  # Maximum number of cache items
        self.ttl = ttl  # Cache expiration time (seconds)
    
    def get(self, key):
        with self.lock:
            if key in self.cache:
                value, timestamp = self.cache[key]
                # Check if expired
                if time.time() - timestamp < self.ttl:
                    # Update access order (LRU)
                    self.cache.move_to_end(key)
                    return value
                else:
                    # Delete expired item
                    del self.cache[key]
            return None
    
    def set(self, key, value):
        with self.lock:
            # If cache is full, remove least recently used item
            if len(self.cache) >= self.max_size and key not in self.cache:
                self.cache.popitem(last=False)
            # Store value and timestamp
            self.cache[key] = (value, time.time())
    
    def clear(self):
        with self.lock:
            self.cache.clear()

# Create global cache manager instance
cache_manager = CacheManager(max_size=50, ttl=1800)  # Reduced cache size and expiration time to save memory


def cache_result(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            # Cache key generation optimized for low-config computers
            # Only use first few parameters and subset of keyword arguments to generate key
            serializable_args = []
            for i, arg in enumerate(args[:3]):  # Only use first 3 parameters
                if hasattr(arg, 'get_history') and callable(arg.get_history):
                    # Safely handle MemoryManager objects
                    try:
                        serializable_args.append(str(arg.get_history()[:10]))  # Only take first 10 items of history
                    except Exception:
                        serializable_args.append(str(type(arg)))
                elif inspect.iscoroutine(arg) or inspect.isawaitable(arg) or callable(arg):
                    # Don't serialize functions, coroutines, or callable objects
                    serializable_args.append(str(type(arg)))
                else:
                    try:
                        # Try to convert argument to JSON serializable form
                        json.dumps(arg)
                        serializable_args.append(arg)
                    except (TypeError, OverflowError):
                        # For non-serializable objects, use type name
                        serializable_args.append(str(type(arg)))
            
            # Only use first 3 keyword arguments
            limited_kwargs = dict(list(kwargs.items())[:3])
            
            # Generate cache key
            key_parts = [func.__name__, str(serializable_args), str(limited_kwargs)]
            key = hashlib.md5(''.join(key_parts).encode()).hexdigest()
            
            # Try to get result from cache
            cached_result = cache_manager.get(key)
            if cached_result is not None:
                logger.debug(f"Cache hit: {func.__name__}")
                return cached_result
            
            # Execute function
            if inspect.iscoroutinefunction(func):
                res = await func(*args, **kwargs)
            else:
                # For synchronous functions, use thread pool
                res = await asyncio.to_thread(func, *args, **kwargs)
            
            # Only cache serializable results of moderate size
            try:
                if res is not None and sys.getsizeof(res) < 500000:  # Less than 500KB
                    cache_manager.set(key, res)
                    logger.debug(f"Cache updated: {func.__name__}")
            except Exception as cache_error:
                logger.warning(f"Cache storage failed: {cache_error}")
            
            return res
        except Exception as e:
            logger.error(f"Cache decorator error: {e}", exc_info=True)
            # Even if cache handling fails, try to execute the original function
            if inspect.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)
    return wrapper

# =======================================================
# 2. Optimized TTS Logic
# =======================================================
# Lazy imports to reduce startup time
vector_search = None
vector_lock = Lock()

async def init_vector_search():
    """Asynchronously initialize vector_search instance"""
    global vector_search
    with vector_lock:
        if vector_search is None:
            try:
                # Dynamic import to reduce startup time
                from .vector_search import VectorSearch
                vector_search = await asyncio.to_thread(VectorSearch)
                logger.info("VectorSearch instance initialized successfully")
            except Exception as e:
                logger.error(f"VectorSearch initialization failed: {e}")
                raise
    return vector_search

async def tts_generate(text: str):
    """Generate speech using vector module's TTS functionality (optimized version)"""
    try:
        # Parameter validation
        if not text or not isinstance(text, str):
            logger.warning("Invalid TTS input")
            return None
        
        # Text length limit to prevent processing overly long text
        if len(text) > 500:
            text = text[:500]
            logger.warning("TTS text too long, truncated")
        
        # Ensure vector_search instance is initialized
        vs = await init_vector_search()
        
        # Use asyncio's thread pool executor to avoid blocking event loop
        audio_path = await asyncio.to_thread(vs.text_to_speech, text)
        
        # Validate result
        if audio_path and os.path.exists(audio_path):
            logger.debug(f"TTS generated successfully: {audio_path}")
            return audio_path
        else:
            logger.warning("TTS generation failed, returned path is invalid")
            return None
    except Exception as e:
        logger.error(f"TTS error: {e}", exc_info=True)
        return None

# =======================================================
# 3. Optimized Utility Functions
# =======================================================

# Lazy imports for jieba and SnowNLP
_jieba_loaded = False
_snownlp_loaded = False
_psutil_loaded = False

def load_jieba():
    global _jieba_loaded
    if not _jieba_loaded:
        try:
            import jieba.analyse
            _jieba_loaded = True
            logger.info("Jieba library loaded successfully")
        except ImportError:
            logger.error("Failed to load Jieba library")
            raise

def load_snownlp():
    global _snownlp_loaded
    if not _snownlp_loaded:
        try:
            from snownlp import SnowNLP
            _snownlp_loaded = True
            logger.info("SnowNLP library loaded successfully")
        except ImportError:
            logger.error("Failed to load SnowNLP library")
            raise

def load_psutil():
    global _psutil_loaded
    if not _psutil_loaded:
        try:
            import psutil
            _psutil_loaded = True
            logger.info("psutil library loaded successfully")
        except ImportError:
            logger.error("Failed to load psutil library")
            raise

def extract_keywords(text, topK=3):
    """Optimized keyword extraction function"""
    try:
        if not text or not isinstance(text, str):
            return []
        
        # Dynamically load jieba
        load_jieba()
        import jieba.analyse
        
        # Text length limit
        if len(text) > 1000:
            text = text[:1000]
        
        # Extract keywords
        return jieba.analyse.extract_tags(text, topK=topK)
    except Exception as e:
        logger.error(f"Keyword extraction failed: {e}")
        return []
# 
def analyze_emotion(text):
    """Optimized emotion analysis function"""
    try:
        if not text or not isinstance(text, str):
            return None
        
        # Dynamically load SnowNLP
        load_snownlp()
        from snownlp import SnowNLP
        
        # Text length limit
        if len(text) > 500:
            text = text[:500]
        
        # Analyze emotion
        s = SnowNLP(text)
        return round(s.sentiments, 4)
    except Exception as e:
        logger.error(f"Emotion analysis failed: {e}")
        return None
# 
def get_system_info():
    """Optimized system information retrieval function"""
    try:
        # Dynamically load psutil
        load_psutil()
        import psutil
        
        # Use more efficient way to get system information
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Get CPU and memory information only when needed
        try:
            cpu = psutil.cpu_percent(interval=0.1)  # Use shorter sampling interval
            mem = psutil.virtual_memory().percent
            return f"[System Info: Time {now}, CPU {cpu}%, Memory {mem}%]"
        except:
            # If resource usage can't be obtained, only return time
            return f"[System Info: Time {now}]"
    except Exception as e:
        logger.error(f"Failed to get system information: {e}")
        # Return minimal system information
        return f"[System Info: Time {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"

# Ensure no unnecessary dependencies are imported
import sys

# Resource cleanup function
def cleanup_utils():
    """Clean up resources used by utility functions"""
    try:
        # Clear cache
        cache_manager.clear()
        logger.info("Utility function cache cleared")
    except Exception as e:
        logger.error(f"Failed to clean up utility function resources: {e}")