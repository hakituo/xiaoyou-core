import os, logging, time
import asyncio
from threading import Lock
from multimodal.tts_manager import get_tts_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Text-to-Speech Generation Function

class TTSTaskManager:
    def __init__(self):
        self.task_lock = Lock()
        self.current_tasks = set()
        self.max_concurrent_tasks = 1  # Limit to 1 concurrent TTS task
    
    def add_task(self, task_id):
        with self.task_lock:
            # Wait if we've reached the maximum concurrent tasks
            while len(self.current_tasks) >= self.max_concurrent_tasks:
                time.sleep(0.1)
            self.current_tasks.add(task_id)
    
    def remove_task(self, task_id):
        with self.task_lock:
            if task_id in self.current_tasks:
                self.current_tasks.remove(task_id)

# Global TTS task manager instance
_tts_task_manager = TTSTaskManager()


async def tts_generate(text, output_path="output.wav", voice="default", speed=1.0):
    """
    Generate speech from text using the specified voice and speed.
    
    Args:
        text: Text to convert to speech
        output_path: Path to save the output audio file
        voice: Voice to use ("default" for system default)
        speed: Speech speed multiplier (0.5 to 2.0)
        
    Returns:
        bool: True if successful, False otherwise
    """
    # Import hashlib only when needed
    import hashlib
    
    task_id = f"tts_{hashlib.md5(text.encode()).hexdigest()[:8]}"
    
    try:
        # Add task to the manager to limit concurrency
        _tts_task_manager.add_task(task_id)
        
        # 修复目录和文件路径处理
        abs_output_path = os.path.abspath(output_path)
        output_dir = os.path.dirname(abs_output_path)
        
        # 确保目录存在 - 使用exist_ok=True避免目录已存在时的错误
        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        
        # 如果文件已存在，先删除
        if os.path.exists(abs_output_path):
            try:
                os.remove(abs_output_path)
                logger.info(f"Removed existing file: {abs_output_path}")
            except Exception as e:
                logger.warning(f"Failed to remove existing file: {e}")
        
        # Use asyncio.to_thread to avoid blocking the event loop
        result = await asyncio.to_thread(
            _tts_generate_sync,
            text, abs_output_path, voice, speed
        )
        
        return result
    except Exception as e:
        logger.error(f"TTS generation failed: {e}")
        return False
    finally:
        # Always remove the task from the manager
        _tts_task_manager.remove_task(task_id)


def _tts_generate_sync(text, output_path, voice, speed):
    """
    Synchronous implementation of TTS generation using multimodal TTSManager.
    """
    try:
        # Validate input
        if not text or not isinstance(text, str):
            logger.warning("Invalid text input for TTS")
            return False
        
        # 确保output_path是绝对路径
        abs_output_path = os.path.abspath(output_path)
        output_dir = os.path.dirname(abs_output_path)
        
        # 彻底清理：检查并删除可能存在的同名目录
        if os.path.exists(abs_output_path) and os.path.isdir(abs_output_path):
            logger.warning(f"Output path exists but is a directory, removing: {abs_output_path}")
            import shutil
            shutil.rmtree(abs_output_path)
        
        # 确保输出目录存在
        if os.path.exists(output_dir) and not os.path.isdir(output_dir):
            logger.warning(f"Output directory exists but is not a directory, removing: {output_dir}")
            os.remove(output_dir)
        os.makedirs(output_dir, exist_ok=True)
        logger.debug(f"Ensured output directory exists: {output_dir}")
        
        # 检查并删除已存在的文件
        if os.path.exists(abs_output_path):
            try:
                os.remove(abs_output_path)
                logger.debug(f"Removed existing output file: {abs_output_path}")
            except Exception as e:
                logger.error(f"Failed to remove existing output file: {e}")
                return False
        
        # Get the TTS manager instance
        tts_manager = get_tts_manager()
        
        # Use TTS manager to generate speech with local engines only
        logger.info(f"Generating local TTS for text: {text[:50]}...")
        generated_file = tts_manager.text_to_speech(text, voice=voice, speed=speed, use_local=True)
        
        # 增强的错误检查
        if not generated_file:
            logger.error("TTS manager failed to generate speech (returned None)")
            return False
        
        # 确保generated_file是文件而不是目录
        if not os.path.isfile(generated_file):
            if os.path.isdir(generated_file):
                logger.error(f"Generated path is a directory, not a file: {generated_file}")
            else:
                logger.error(f"Generated file does not exist or is not a file: {generated_file}")
            return False
        
        logger.debug(f"Successfully generated TTS file: {generated_file}")
        
        # 如果TTS管理器生成的文件与请求的输出路径不同，复制它
        if generated_file != abs_output_path:
            import shutil
            try:
                # 再次确保目标目录存在
                os.makedirs(output_dir, exist_ok=True)
                # 复制文件
                shutil.copy2(generated_file, abs_output_path)
                logger.info(f"Copied TTS file to: {abs_output_path}")
            except Exception as copy_error:
                logger.error(f"Failed to copy TTS file: {copy_error}", exc_info=True)
                return False
        
        logger.info(f"TTS generated successfully: {abs_output_path}")
        return True
        
    except Exception as e:
        logger.error(f"TTS generation error using TTS manager: {e}", exc_info=True)
        return False