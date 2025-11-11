import json
import os
import sys
import asyncio
import time
import threading
import logging

# Configure logger
logger = logging.getLogger(__name__)

class MemoryManager:
    def __init__(self, max_length=10, user_id="default", auto_save_interval=300):
        """
        Optimized memory manager that reduces default max_length to decrease memory usage and adds auto-save functionality
        
        Args:
            max_length: Maximum number of history records
            user_id: User ID for saving/loading history
            auto_save_interval: Auto-save interval in seconds, 0 means disable auto-save
        """
        self.history = []
        self.max_length = max_length
        self.user_id = user_id
        self.history_dir = "history"
        self.auto_save_interval = auto_save_interval
        self.last_modified_time = time.time()
        self.lock = threading.Lock()  # Add thread lock to ensure thread safety
        
        # Ensure history directory exists
        try:
            os.makedirs(self.history_dir, exist_ok=True)
        except Exception as e:
            print(f"Failed to create history directory: {e}")
        
        # Start auto-save thread
        if auto_save_interval > 0:
            self.auto_save_thread = threading.Thread(target=self._auto_save_loop, daemon=True)
            self.auto_save_thread.start()

    def add_message(self, role, content, is_important=False):
        """
        Add a conversation record, with support for marking important messages
        
        Args:
            role: Message role (user/assistant/system)
            content: Message content
            is_important: Whether it's an important message (important messages are harder to remove)
        """
        with self.lock:
            message = {
                "role": role, 
                "content": content,
                "timestamp": time.time(),
                "is_important": is_important
            }
            
            self.history.append(message)
            self.last_modified_time = time.time()
            
            # Limit history length with intelligent removal strategy
            self._trim_history()
            
            return message
    
    def _trim_history(self):
        """Intelligently trim history using LRU strategy with importance weighting"""
        if len(self.history) > self.max_length:
            # Calculate importance score for each message
            # Score = base_importance * (recency_factor + importance_boost)
            now = time.time()
            for msg in self.history:
                # Base score starts with timestamp for recency
                recency_factor = 1.0
                if len(self.history) > 1:
                    # Normalize timestamp to 0-1 range
                    oldest_time = min(self.history, key=lambda x: x['timestamp'])['timestamp']
                    newest_time = max(self.history, key=lambda x: x['timestamp'])['timestamp']
                    time_range = newest_time - oldest_time if newest_time > oldest_time else 1
                    recency_factor = (msg['timestamp'] - oldest_time) / time_range
                
                # Add importance boost for important messages
                importance_boost = 2.0 if msg.get('is_important', False) else 0.0
                
                # Calculate final score
                msg['_score'] = recency_factor + importance_boost
            
            # Sort by score in descending order (highest first)
            self.history.sort(key=lambda x: x.get('_score', 0), reverse=True)
            
            # Keep top messages up to max_length
            self.history = self.history[:self.max_length]
            
            # Remove temporary score field
            for msg in self.history:
                if '_score' in msg:
                    del msg['_score']
            
            # Restore chronological order
            self.history.sort(key=lambda x: x['timestamp'])
            
            # Log trimming action
            logger.debug(f"History trimmed to {len(self.history)} messages (max: {self.max_length})")

    def get_history(self):
        """Return current conversation history, optimized for memory usage"""
        with self.lock:
            # Only return fields needed by LLM to reduce memory usage
            simplified_history = []
            for msg in self.history:
                simplified_history.append({
                    "role": msg["role"], 
                    "content": msg["content"]
                })
            return simplified_history.copy()

    def clear(self):
        """Manually clear history"""
        with self.lock:
            self.history.clear()
            self.last_modified_time = time.time()
            return "History cleared"
    
    def save_history(self):
        """Save history to file, using compressed format to reduce file size"""
        try:
            file_path = os.path.join(self.history_dir, f"{self.user_id}.json")
            
            # Handle potential encoding issues during serialization
            def safe_serialize(obj):
                if isinstance(obj, dict):
                    return {str(k): safe_serialize(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [safe_serialize(item) for item in obj]
                elif isinstance(obj, (str, int, float, bool, type(None))):
                    return obj
                else:
                    return str(obj)
            
            with self.lock:
                safe_history = safe_serialize(self.history)
            
            # Save using compact format to reduce file size
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(safe_history, f, ensure_ascii=False, separators=(',', ':'))
            
            return f"History saved to {file_path} ({os.path.getsize(file_path)} bytes)"
        except Exception as e:
            error_msg = f"Failed to save history: {str(e)}"
            print(error_msg)
            return error_msg
    
    def load_history(self):
        """Load history from file"""
        try:
            file_path = os.path.join(self.history_dir, f"{self.user_id}.json")
            if os.path.exists(file_path):
                # Async loading for large files to avoid blocking
                with open(file_path, 'r', encoding='utf-8') as f:
                    loaded_history = json.load(f)
                
                with self.lock:
                    self.history = loaded_history
                    self.last_modified_time = time.time()
                
                # Ensure loaded history complies with maximum length limit
                self._trim_history()
                
                return f"Loaded saved history ({len(self.history)} entries)"
            else:
                return "No saved history found"
        except json.JSONDecodeError:
            return "History file format error, cannot load"
        except Exception as e:
            error_msg = f"Failed to load history: {str(e)}"
            print(error_msg)
            return error_msg
    
    def set_max_length(self, max_length):
        """Set maximum history length with reasonable boundary checks"""
        try:
            if 1 <= max_length <= 100:  # Add reasonable range limit
                with self.lock:
                    self.max_length = max_length
                    # If current history exceeds new limit, intelligently truncate
                    self._trim_history()
                return f"Maximum history length set to {max_length}"
            else:
                return "Maximum length must be between 1-100"
        except Exception as e:
            return f"Failed to set maximum length: {str(e)}"
    
    def get_stats(self):
        """Get memory statistics with more detailed metrics"""
        with self.lock:
            # Estimate memory usage
            try:
                # Estimate object size using sys.getsizeof
                history_size = sys.getsizeof(self.history)
                for item in self.history:
                    history_size += sys.getsizeof(item)
                    for key, value in item.items():
                        history_size += sys.getsizeof(key)
                        history_size += sys.getsizeof(value)
                
                return {
                    "current_length": len(self.history),
                    "max_length": self.max_length,
                    "user_id": self.user_id,
                    "memory_usage_bytes": history_size,
                    "memory_usage_mb": round(history_size / (1024 * 1024), 2),
                    "important_messages": sum(1 for msg in self.history if msg.get('is_important', False)),
                    "last_modified_time": time.ctime(self.last_modified_time)
                }
            except Exception:
                # If memory calculation fails, return basic information
                return {
                    "current_length": len(self.history),
                    "max_length": self.max_length,
                    "user_id": self.user_id
                }
    
    def _auto_save_loop(self):
        """Auto-save loop thread"""
        while True:
            try:
                time.sleep(self.auto_save_interval)
                # Only save if there are modifications and history is not empty
                if self.history and (time.time() - self.last_modified_time > 60):  # Execute only if not saved for at least 1 minute
                    self.save_history()
                    print(f"[{time.ctime()}] Auto-saved history for {self.user_id}")
            except Exception as e:
                print(f"Auto-save failed: {e}")
    
    async def async_save_history(self):
        """Asynchronously save history to avoid blocking event loop"""
        return await asyncio.to_thread(self.save_history)
    
    async def async_load_history(self):
        """Asynchronously load history to avoid blocking event loop"""
        return await asyncio.to_thread(self.load_history)
