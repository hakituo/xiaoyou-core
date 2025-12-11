#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import time
import logging
import hashlib
import asyncio
import numpy as np
import soundfile as sf
from threading import Lock
from core.voice.tts_engine import TTSManager as NewTTSManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class TTSManager:
    # Use models/tts directory for TTS output
    DEFAULT_SPEED = 1.0
    TEMP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "models", "tts")
    
    def __init__(self):
        self._lock = Lock()
        self._initialized = False
        self._tts_cache = {}  # Simple cache for TTS results
        self._cache_size = 30  # Limit cache size
        
        # Cache cleanup interval
        self.cache_clean_interval = 3600  # 1 hour
        self.last_cache_clean = time.time()
        
        # New TTS Engine instance
        self.new_engine = NewTTSManager()
        
        # Ensure voice directory exists
        if os.path.exists(self.TEMP_DIR) and not os.path.isdir(self.TEMP_DIR):
            os.remove(self.TEMP_DIR)
        os.makedirs(self.TEMP_DIR, exist_ok=True)
    
    def _initialize(self):
        """Initialize TTS engine (wrapper around new engine)"""
        with self._lock:
            if self._initialized:
                return True
            
            try:
                # Run async initialization synchronously
                asyncio.run(self.new_engine.initialize())
                self._initialized = True
                return True
            except Exception as e:
                logger.error(f"Failed to initialize TTS engine: {e}")
                return False

    def _generate_cache_key(self, text, speed=None, emotion=None):
        """Generate cache key for TTS request"""
        key_parts = [text, "gpt_sovits"]
        if speed:
            key_parts.append(str(speed))
        if emotion:
            key_parts.append(str(emotion))
        return hashlib.md5("|".join(key_parts).encode()).hexdigest()

    def _check_and_clean_cache(self):
        """Check and clean expired cache"""
        current_time = time.time()
        if current_time - self.last_cache_clean > self.cache_clean_interval:
            with self._lock:
                expired_keys = []
                for key, entry in self._tts_cache.items():
                    if current_time - entry['timestamp'] > self.cache_clean_interval:
                        expired_keys.append(key)
                        if os.path.exists(entry['file_path']):
                            try:
                                os.remove(entry['file_path'])
                            except Exception as e:
                                logger.warning(f"Failed to remove expired cache file: {e}")
                
                for key in expired_keys:
                    del self._tts_cache[key]
                
                self.last_cache_clean = current_time

    def text_to_speech(self, text, speed=None, emotion=None):
        """
        Convert text to speech
        
        Args:
            text: Text to convert
            speed: Speech speed (default 1.0)
            emotion: Emotion parameter (optional)
        
        Returns:
            Path to generated audio file
        """
        if not text:
            raise ValueError("TTS requires non-empty text input")
        
        if not self._initialize():
            raise RuntimeError("TTS engine initialization failed")
        
        self._check_and_clean_cache()
        
        cache_key = self._generate_cache_key(text, speed, emotion)
        
        with self._lock:
            if cache_key in self._tts_cache:
                cached_file = self._tts_cache[cache_key]['file_path']
                if os.path.exists(cached_file):
                    logger.info(f"Using cached audio file: {cached_file}")
                    self._tts_cache[cache_key]['timestamp'] = time.time()
                    return cached_file
        
        filename = f"tts_{cache_key}.wav"
        filepath = os.path.join(self.TEMP_DIR, filename)
        
        try:
            logger.info(f"Generating audio for text: {text[:50]}...")
            
            # Call new engine (async) synchronously
            # Note: nesting asyncio.run might fail if already in a loop.
            # But since this is likely called from a thread or sync context, it might be fine.
            # If called from async context, this will fail.
            # We should check if event loop exists.
            
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # If we are in an async loop, we can't use run_until_complete easily without nesting
                    # But for now assuming sync context as per original usage
                     logger.warning("Running sync text_to_speech inside async loop - this might block or fail")
                     # This is tricky. Ideally callers should use async.
                     # For now, we'll try to use the loop.
                     future = asyncio.run_coroutine_threadsafe(
                         self.new_engine.synthesize(text, speed=speed if speed else 1.0),
                         loop
                     )
                     audio_data = future.result()
                else:
                    audio_data = loop.run_until_complete(
                        self.new_engine.synthesize(text, speed=speed if speed else 1.0)
                    )
            except RuntimeError:
                # No event loop
                audio_data = asyncio.run(
                    self.new_engine.synthesize(text, speed=speed if speed else 1.0)
                )

            # Save to file
            if audio_data is not None and len(audio_data) > 0:
                sf.write(filepath, audio_data, 32000) # Assuming 32k for GPT-SoVITS
                
                with self._lock:
                    self._tts_cache[cache_key] = {
                        'file_path': filepath,
                        'timestamp': time.time()
                    }
                return filepath
            else:
                raise RuntimeError("Generated audio data is empty")
                
        except Exception as e:
            logger.error(f"TTS generation failed: {e}")
            raise RuntimeError(f"Speech synthesis failed: {str(e)}") from e

    def clear_cache(self):
        """Clear TTS cache"""
        with self._lock:
            for entry in self._tts_cache.values():
                if 'file_path' in entry and os.path.exists(entry['file_path']):
                    try:
                        os.remove(entry['file_path'])
                    except:
                        pass
            self._tts_cache.clear()
            logger.info("TTS cache cleared")

    def close(self):
        """Clean up resources"""
        self.clear_cache()
        # new_engine doesn't need explicit sync close usually, but if it did:
        # asyncio.run(self.new_engine.shutdown())
        self._initialized = False

# Singleton instance
_tts_manager_instance = None
_tts_manager_lock = Lock()

def get_tts_manager():
    """Get singleton TTS manager instance"""
    global _tts_manager_instance
    with _tts_manager_lock:
        if _tts_manager_instance is None:
            _tts_manager_instance = TTSManager()
    return _tts_manager_instance

def cleanup_tts():
    """Clean up TTS resources"""
    global _tts_manager_instance
    with _tts_manager_lock:
        if _tts_manager_instance:
            _tts_manager_instance.close()
            _tts_manager_instance = None
