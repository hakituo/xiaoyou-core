import asyncio
import os
import logging
from memory.memory_manager import MemoryManager
# 导入我们新创建的文本推理模块
from core.text_infer import load_model, generate_response
from PIL import Image
import numpy as np
import io
import base64

# Configure logger
logger = logging.getLogger(__name__)


# =======================================================
# 1. Initialize Model Instance
# =======================================================
# 预先加载模型以提高首次响应速度
try:
    load_model()
except Exception:
    pass

# Custom AI Personality Configuration
CUSTOM_PERSONALITY = ""


# =======================================================
# 2. Command System
# =======================================================
class CommandHandler:
    """Command processing system using dictionary mapping for efficient command handling"""
    
    def __init__(self):
        # Command mapping dictionary
        self.commands = {
            'clear': self._handle_clear,
            'save': self._handle_save,
            'load': self._handle_load,
            'memory': self._handle_memory,
            'setmemory': self._handle_setmemory,
            'system': self._handle_system,
            'help': self._handle_help,
        }
        
        # Precompile help text
        self._help_text = "\n".join([
            "Available commands:",
            "/clear - Clear history",
            "/save - Save history to file",
            "/load - Load history from file",
            "/memory - View current memory status",
            "/setmemory [number] - Set maximum history length",
            "/system - View system information",
            "/help - Show this help information"
        ])
    
    def handle(self, text, memory: MemoryManager):
        """
        Process commands from user input
        
        Args:
            text: User input text
            memory: Memory manager instance
        
        Returns:
            tuple: (is_command, response_text)
        """
        if not text.startswith('/'):
            return False, ""
        
        command_parts = text[1:].strip().split(' ', 1)
        command = command_parts[0].lower()
        args = command_parts[1] if len(command_parts) > 1 else ""
        
        if command in self.commands:
            return True, self.commands[command](memory, args)
        
        return True, f"Unknown command: {command}, use /help to see available commands"
    
    def _handle_clear(self, memory, args):
        return memory.clear()
    
    def _handle_save(self, memory, args):
        return memory.save_history()
    
    def _handle_load(self, memory, args):
        return memory.load_history()
    
    def _handle_memory(self, memory, args):
        stats = memory.get_stats()
        return f"Memory status: Current history {stats['current_length']}/{stats['max_length']} messages"
    
    def _handle_setmemory(self, memory, args):
        try:
            max_len = int(args)
            # Add boundary checks to prevent setting too small or too large values
            if max_len < 1 or max_len > 100:
                return "Please set a valid number between 1-100"
            return memory.set_max_length(max_len)
        except ValueError:
            return "Please enter a valid number for the maximum history length"
    
    def _handle_system(self, memory, args):
        """Handle system information command"""
        import sys
        return f"System Information:\nPython: {sys.version}\nMemory status: {memory.get_stats()}\n"

    
    def _handle_help(self, memory, args):
        return self._help_text

# Create command handler instance
command_handler = CommandHandler()

# Function compatible with old interface
def handle_command(text, memory: MemoryManager):
    """Process user commands synchronously"""
    return command_handler.handle(text, memory)

async def handle_command_async(text, memory: MemoryManager):
    """Process user commands asynchronously"""
    # For simplicity, we'll just call the synchronous version
    return await asyncio.to_thread(handle_command, text, memory)


# =======================================================
# 3. Optimized LLM Query Function (Final Revision: async + asyncio.to_thread + Error Handling)
# =======================================================


def _process_image_file(file_path):
    """
    Process image file for analysis
    
    Args:
        file_path: Path to the image file
    
    Returns:
        str: Base64 encoded image data
    """
    try:
        # Check if file exists
        if not os.path.exists(file_path):
            logger.error(f"Image file not found: {file_path}")
            return None
        
        # Open and process the image
        with open(file_path, 'rb') as f:
            image_data = f.read()
            
        # Encode image to base64
        encoded_image = base64.b64encode(image_data).decode('utf-8')
        return encoded_image
    except Exception as e:
        logger.error(f"Error processing image file: {e}")
        return None

def _is_image_query(text):
    """
    Check if the query contains image-related keywords
    
    Args:
        text: User input text
    
    Returns:
        bool: True if contains image keywords
    """
    image_keywords = ['图片', '图像', '照片', '分析', '描述', '显示', '内容', '识别', '是什么']
    return any(keyword in text for keyword in image_keywords)

async def query_model(text, memory: MemoryManager):
    """
    Main query function to process user input and generate response
    
    Args:
        text: User input text
        memory: Memory manager instance
    
    Returns:
        str: Generated response
    """
    # First check if it's a command
    is_command, command_response = await handle_command_async(text, memory)
    if is_command:
        return command_response
    
    # Add user message to history
    user_content = f"User says: {text}"
    
    # Create history
    history = memory.get_history()
    
    # Check if we need to handle image-related content
    if _is_image_query(text):
        # Look for recent file uploads in history that might contain image paths
        image_paths = []
        for msg in reversed(history):
            if msg.get('role') == 'user' and 'image' in msg.get('content', '').lower():
                # Extract potential image path from message content
                if 'file_path' in msg.get('content', ''):
                    # This is a placeholder - in a real implementation, you would extract the actual path
                    image_paths.append("/path/to/recent/image.jpg")
                break
        
        # If we found image paths, process the first one
        if image_paths:
            encoded_image = _process_image_file(image_paths[0])
            if encoded_image:
                # Add multimodal prompt to user content
                user_content += "\n[Image analysis request]"
                logger.info("Processing image analysis request")
    
    # Add the current user message to history
    history = history + [{"role": "user", "content": user_content}]
    
    # Generate response
    try:
        # For image analysis, we'll add a special prompt to guide the model
        if _is_image_query(text):
            # Prepend system message for image analysis
            system_prompt = {"role": "system", "content": "You are an AI assistant that can analyze images. Please provide a detailed description of the image content, including objects, text, colors, and overall scene. Then address the user's specific question about the image."}
            history_with_system = [system_prompt] + history
            reply_text = await asyncio.to_thread(generate_response, history_with_system)
        else:
            # Standard text generation
            reply_text = await asyncio.to_thread(generate_response, history)
        
        return reply_text
    except Exception as e:
        logger.error(f"Error generating response: {e}")
        return "抱歉，我暂时无法生成响应。请稍后再试。"