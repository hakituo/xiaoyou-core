import os
import logging
import threading
import time
import asyncio
import hashlib
from functools import lru_cache

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Edge TTS support
edge_tts = None
edge_tts_voice = "zh-CN-XiaoyiNeural"  # Specify the default voice role

# Lazy import to reduce startup time
pyttsx3 = None

class TTSManager:
    # Low-spec computer optimization parameters
    MAX_TEXT_LENGTH = 300       # Limit the maximum length of processed text
    MIN_RATE = 100              # Minimum speech rate
    MAX_RATE = 250              # Maximum speech rate
    PLAYBACK_CACHE_SIZE = 20    # Playback cache size
    MAX_RETRY_COUNT = 2         # Maximum retry count
    RETRY_DELAY_MS = 500        # Retry delay (milliseconds)
    
    # TTS engine types
    ENGINE_PYTTSX3 = "pyttsx3"
    ENGINE_EDGE_TTS = "edge_tts"
    
    def __init__(self):
        self.engine = None
        self._lock = threading.RLock()  # Reentrant lock for thread safety
        self._initialized = False
        self._playback_thread = None
        self._is_playing = False
        self._config = {
            'rate': 130,           # Lower speech rate for better quality and naturalness
            'volume': 1.0,         # Default volume
            'language': 'chinese',  # Default language
            'engine': self.ENGINE_EDGE_TTS  # Using Edge TTS engine
        }
        # Simple playback cache
        self._playback_cache = {}
        
        # Lazy initialization, engine will be created on first use
        logger.info("TTSManager created, engine will be initialized on first use")
    
    def _load_pyttsx3(self):
        """Dynamically load pyttsx3 library"""
        global pyttsx3
        if pyttsx3 is None:
            try:
                import pyttsx3
                logger.info("pyttsx3 library loaded successfully")
            except ImportError:
                logger.error("pyttsx3 library not installed, TTS functionality unavailable")
                return False
        return pyttsx3 is not None
    
    def _load_edge_tts(self):
        """Dynamically load Edge TTS library"""
        global edge_tts
        if edge_tts is None:
            try:
                import edge_tts
                logger.info("Edge TTS library loaded successfully")
            except ImportError:
                logger.error("Edge TTS library not installed, trying pyttsx3 as fallback")
                return False
        return edge_tts is not None
    
    def _initialize_engine(self):
        """Initialize TTS engine"""
        with self._lock:
            if self._initialized:
                return True
            
            # Check engine type to use
            if self._config['engine'] == self.ENGINE_EDGE_TTS:
                # Try to use Edge TTS
                if self._load_edge_tts():
                    self._initialized = True
                    logger.info(f"Edge TTS engine initialized successfully, using voice: {edge_tts_voice}")
                    return True
                else:
                    # Fall back to pyttsx3 if failed
                    logger.warning("Edge TTS initialization failed, falling back to pyttsx3")
                    self._config['engine'] = self.ENGINE_PYTTSX3
            
            # Use pyttsx3 as fallback
            if not self._load_pyttsx3():
                return False
            
            # Try to initialize pyttsx3 engine
            try:
                self.engine = pyttsx3.init(driverName=None, debug=False)
                
                # Apply configuration
                self.set_rate(self._config['rate'])
                self.set_volume(self._config['volume'])
                self.set_voice_language(self._config['language'])
                
                # Set event callbacks
                self.engine.connect('started-utterance', self._on_utterance_start)
                self.engine.connect('finished-utterance', self._on_utterance_end)
                
                self._initialized = True
                logger.info("pyttsx3 TTS engine initialized successfully")
                return True
            except Exception as e:
                logger.error(f"TTS engine initialization failed: {e}", exc_info=True)
                self.engine = None
                return False
    
    def _on_utterance_start(self, name, location, length):
        """Speech start playback callback"""
        self._is_playing = True
        logger.debug(f"Speech started playing: {name}")
    
    def _on_utterance_end(self, name, completed):
        """Speech end playback callback"""
        self._is_playing = False
        status = "successful" if completed else "interrupted"
        logger.debug(f"Speech playback ended: {name}, status: {status}")
    
    def set_voice_language(self, language='chinese'):
        """Set voice language (optimized version)"""
        if not self.engine and not self._initialize_engine():
            return False
        
        try:
            voices = self.engine.getProperty('voices')
            if not voices:
                logger.warning("No available voices found in system")
                return False
            
            # Try to find Chinese voice first, enhanced matching logic
            target_voice = None
            preferred_voice_indices = []
            
            for i, voice in enumerate(voices):
                voice_id = voice.id.lower() if voice.id else ''
                voice_name = voice.name.lower() if voice.name else ''
                voice_info = f"{voice_id} {voice_name}"
                
                # Stricter Chinese voice matching rules
                if ('china' in voice_info and 'female' in voice_info) or \
                   ('chinese' in voice_info and 'female' in voice_info):
                    # Prefer female Chinese voice, usually more natural
                    preferred_voice_indices.insert(0, i)  # Put at the front
                elif 'china' in voice_info or \
                     'chinese' in voice_info or \
                     'zh' in voice_info or \
                     'chinese' in voice_info.lower() or \
                     'mandarin' in voice_info.lower():
                    preferred_voice_indices.append(i)
            
            # Select the best voice
            if preferred_voice_indices:
                # Use the first matching voice
                best_voice = voices[preferred_voice_indices[0]]
                self.engine.setProperty('voice', best_voice.id)
                self._config['language'] = language
                logger.info(f"Voice set to: {best_voice.id}")
                return True
            else:
                # If no specific Chinese voice found, try to select a more natural-sounding voice
                # Usually index 0 is system default, but sometimes index 1 or 2 might be better
                best_voice_index = 0
                if len(voices) > 1:
                    # Try to select the second voice, which might be more natural on some systems
                    best_voice_index = 1
                
                self.engine.setProperty('voice', voices[best_voice_index].id)
                logger.warning(f"No specific {language} language voice found, using fallback voice: {voices[best_voice_index].id}")
                return True
        except Exception as e:
            logger.error(f"Failed to set voice language: {e}")
            return False
    
    def set_rate(self, rate):
        """Set speech rate (optimized version)"""
        # Limit speech rate range
        safe_rate = max(self.MIN_RATE, min(self.MAX_RATE, rate))
        
        if not self.engine and not self._initialize_engine():
            # If engine not initialized, save configuration first
            self._config['rate'] = safe_rate
            return False
        
        try:
            self.engine.setProperty('rate', safe_rate)
            self._config['rate'] = safe_rate
            logger.debug(f"Speech rate set to: {safe_rate}")
            return True
        except Exception as e:
            logger.error(f"Failed to set speech rate: {e}")
            return False
    
    def set_volume(self, volume):
        """Set volume (optimized version)"""
        # Limit volume range
        safe_volume = max(0.0, min(1.0, volume))
        
        if not self.engine and not self._initialize_engine():
            # If engine not initialized, save configuration first
            self._config['volume'] = safe_volume
            return False
        
        try:
            self.engine.setProperty('volume', safe_volume)
            self._config['volume'] = safe_volume
            logger.debug(f"Volume set to: {safe_volume}")
            return True
        except Exception as e:
            logger.error(f"Failed to set volume: {e}")
            return False
    
    def _clean_text(self, text):
        """Clean and validate text"""
        if not text or not isinstance(text, str):
            return None
        
        # Remove excess whitespace
        cleaned = ' '.join(text.split())
        
        # Limit text length
        if len(cleaned) > self.MAX_TEXT_LENGTH:
            logger.warning(f"TTS text too long, truncated to {self.MAX_TEXT_LENGTH} characters")
            cleaned = cleaned[:self.MAX_TEXT_LENGTH]
        
        return cleaned
    
    def speak(self, text):
        """Play text as speech (optimized version)"""
        # Clean and validate text
        cleaned_text = self._clean_text(text)
        if not cleaned_text:
            logger.warning("Invalid TTS input text")
            return False
        
        # Initialize engine
        if not self.engine and not self._initialize_engine():
            return False
        
        # Try to use cached speech file
        cache_key = hashlib.md5(cleaned_text.encode()).hexdigest()
        if cache_key in self._playback_cache:
            cached_file = self._playback_cache[cache_key]
            if os.path.exists(cached_file):
                # Logic to play cached file with system player could be added here
                logger.debug(f"Using cached speech file: {cached_file}")
        
        # Execute speech playback with retry support
        retries = 0
        while retries <= self.MAX_RETRY_COUNT:
            try:
                with self._lock:
                    self.engine.say(cleaned_text)
                    self.engine.runAndWait()
                logger.info(f"Speech playback successful: {len(cleaned_text)} characters")
                return True
            except Exception as e:
                retries += 1
                if retries > self.MAX_RETRY_COUNT:
                    logger.error(f"Speech playback failed (retried {self.MAX_RETRY_COUNT} times): {e}", exc_info=True)
                    # Try to reinitialize engine
                    self._initialized = False
                    return False
                logger.warning(f"Speech playback failed, retrying in {retries} seconds: {e}")
                time.sleep(self.RETRY_DELAY_MS / 1000.0)
    
    def save_to_file(self, text, filename):
        """Save text as audio file (optimized version)"""
        # Clean and validate text
        cleaned_text = self._clean_text(text)
        if not cleaned_text:
            logger.warning("Invalid TTS input text")
            return None
        
        # Initialize engine
        if not self.engine and not self._initialize_engine():
            return None
        
        # Validate and ensure file path is valid
        if not filename:
            logger.warning("Invalid audio file path")
            return None
        
        try:
            # Ensure directory exists
            dir_path = os.path.dirname(os.path.abspath(filename))
            os.makedirs(dir_path, exist_ok=True)
            
            # Execute file save with retry support
            retries = 0
            while retries <= self.MAX_RETRY_COUNT:
                try:
                    with self._lock:
                        self.engine.save_to_file(cleaned_text, filename)
                        self.engine.runAndWait()
                    
                    # Verify file was successfully created
                    if os.path.exists(filename) and os.path.getsize(filename) > 0:
                        # Update cache
                        cache_key = hashlib.md5(cleaned_text.encode()).hexdigest()
                        # Maintain cache size limit
                        if len(self._playback_cache) >= self.PLAYBACK_CACHE_SIZE:
                            # Remove oldest item
                            self._playback_cache.pop(next(iter(self._playback_cache)))
                        self._playback_cache[cache_key] = filename
                        
                        logger.info(f"Speech file saved successfully: {filename} ({os.path.getsize(filename)} bytes)")
                        return filename
                    else:
                        raise Exception("Created file is empty or does not exist")
                except Exception as e:
                    retries += 1
                    if retries > self.MAX_RETRY_COUNT:
                        logger.error(f"Failed to save speech file (retried {self.MAX_RETRY_COUNT} times): {e}")
                        return None
                    logger.warning(f"Failed to save speech file, retrying in {self.RETRY_DELAY_MS}ms: {e}")
                    time.sleep(self.RETRY_DELAY_MS / 1000.0)
        except Exception as e:
            logger.error(f"Error occurred while saving speech file: {e}", exc_info=True)
            return None
    
    def generate_speech(self, text, output_file):
        """Generate speech and save to specified file (method called by Vector module)"""
        # Ensure engine is initialized
        self._initialize_engine()
        
        # Check if using Edge TTS engine
        if self._config['engine'] == self.ENGINE_EDGE_TTS and edge_tts:
            # For Edge TTS, use async method but run in sync environment
            try:
                import asyncio
                # Check if already in event loop
                try:
                    loop = asyncio.get_running_loop()
                    # If already in event loop, use run_coroutine_threadsafe
                    future = asyncio.run_coroutine_threadsafe(
                        self._save_with_edge_tts(text, output_file),
                        loop
                    )
                    return future.result(timeout=10)  # Set timeout
                except RuntimeError:
                    # If not in event loop, create new event loop
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        return loop.run_until_complete(
                            self._save_with_edge_tts(text, output_file)
                        )
                    finally:
                        loop.close()
            except Exception as e:
                logger.error(f"Edge TTS sync call failed: {e}")
                # Fall back to pyttsx3 on failure
                return self.save_to_file(text, output_file)
        else:
            # Use pyttsx3 as fallback
            return self.save_to_file(text, output_file)
    
    async def speak_async(self, text):
        """Async text-to-speech playback (optimized version)"""
        # Use thread pool to execute sync operations, avoid blocking event loop
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None,  # Use default thread pool
                self.speak,
                text
            )
        except Exception as e:
            logger.error(f"Async speech playback failed: {e}")
            return False
    
    async def save_to_file_async(self, text, filename):
        """Async save audio file (optimized version)"""
        # Clean and validate text
        cleaned_text = self._clean_text(text)
        if not cleaned_text:
            logger.warning("Invalid TTS input text")
            return None
        
        # Validate and ensure file path is valid
        if not filename:
            logger.warning("Invalid audio file path")
            return None
        
        # Ensure directory exists
        dir_path = os.path.dirname(os.path.abspath(filename))
        os.makedirs(dir_path, exist_ok=True)
        
        # Initialize engine
        if not self._initialize_engine():
            return None
        
        # Check if using Edge TTS engine
        if self._config['engine'] == self.ENGINE_EDGE_TTS and edge_tts:
            return await self._save_with_edge_tts(cleaned_text, filename)
        
        # Use pyttsx3 as fallback
        # Use thread pool to execute sync operations, avoid blocking event loop
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None,  # Use default thread pool
                self.save_to_file,
                cleaned_text,
                filename
            )
        except Exception as e:
            logger.error(f"Async save speech file failed: {e}")
            return None
    
    async def _save_with_edge_tts(self, text, filename):
        """Save audio file using Edge TTS"""
        try:
            # Create Edge TTS communicator
            communicate = edge_tts.Communicate(text, voice=edge_tts_voice)
            
            # Save audio file
            with open(filename, "wb") as file:
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        file.write(chunk["data"])
            
            # Verify file was successfully created
            if os.path.exists(filename) and os.path.getsize(filename) > 0:
                # Update cache
                cache_key = hashlib.md5(text.encode()).hexdigest()
                # Maintain cache size limit
                if len(self._playback_cache) >= self.PLAYBACK_CACHE_SIZE:
                    # Remove oldest item
                    self._playback_cache.pop(next(iter(self._playback_cache)))
                self._playback_cache[cache_key] = filename
                
                logger.info(f"Edge TTS speech file saved successfully: {filename} ({os.path.getsize(filename)} bytes)")
                return filename
            else:
                raise Exception("Created file is empty or does not exist")
        except Exception as e:
            logger.error(f"Edge TTS save failed: {e}", exc_info=True)
            return None
    
    def is_playing(self):
        """Check if speech is currently playing"""
        return self._is_playing
    
    def stop(self):
        """Stop current speech playback"""
        try:
            with self._lock:
                if self.engine:
                    self.engine.stop()
                    self._is_playing = False
                    logger.info("Speech playback stopped")
                    return True
        except Exception as e:
            logger.error(f"Failed to stop speech playback: {e}")
        return False
    
    def clear_cache(self):
        """Clear cache to free resources"""
        try:
            self._playback_cache.clear()
            logger.info("TTS cache cleared")
            return True
        except Exception as e:
            logger.error(f"Failed to clear TTS cache: {e}")
            return False
    
    def close(self):
        """Close TTS engine and release resources"""
        try:
            # Stop current playback
            self.stop()
            
            # Clear cache
            self.clear_cache()
            
            # Close engine
            if self.engine:
                try:
                    self.engine.endLoop()
                except:
                    pass  # Ignore method that might not exist
                
                try:
                    self.engine = None
                except:
                    pass
            
            self._initialized = False
            logger.info("TTS engine closed")
            return True
        except Exception as e:
            logger.error(f"Failed to close TTS engine: {e}")
            return False
    
    def __del__(self):
        """Destructor, ensure resource release"""
        try:
            self.close()
        except:
            pass  # Avoid exceptions in destructor

# Global singleton instance
_tts_manager_instance = None
_tts_manager_lock = threading.RLock()

def get_tts_manager():
    """Get TTS manager singleton (thread-safe version)"""
    global _tts_manager_instance
    with _tts_manager_lock:
        if _tts_manager_instance is None:
            _tts_manager_instance = TTSManager()
        return _tts_manager_instance

def cleanup_tts():
    """Clean up TTS resources"""
    global _tts_manager_instance
    with _tts_manager_lock:
        if _tts_manager_instance is not None:
            _tts_manager_instance.close()
            _tts_manager_instance = None
            logger.info("TTS resources cleaned up")

# Test code
if __name__ == "__main__":
    try:
        tts = get_tts_manager()
        tts.speak("Hello, this is a voice function test of the AI assistant")
    finally:
        # Ensure resources are cleaned up after testing
        cleanup_tts()
    tts.save_to_file("This is a saved voice file test", "test_output.mp3")