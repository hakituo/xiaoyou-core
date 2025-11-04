import asyncio
import os
import traceback

from core.utils import get_system_info, analyze_emotion, extract_keywords, cache_result
from memory.memory_manager import MemoryManager
from memory.long_term_db import retrieve_long_term_memory, save_long_term_memory
from core.models.qianwen_model import QianwenModel as LLMModel 


# =======================================================
# 1. Initialize Model Instance
# =======================================================
model = LLMModel()

# Custom AI Personality Configuration
# You can modify the following content to change the AI's role setting
CUSTOM_PERSONALITY = ""
# Uncomment the line below and modify the content to customize the AI personality
# CUSTOM_PERSONALITY = "You are a professional technical advisor, skilled at solving programming problems..."

# Apply custom personality if set
if CUSTOM_PERSONALITY:
    model.set_personality(CUSTOM_PERSONALITY) 


# =======================================================
# 2. Optimized Command System (Using Dictionary Mapping for Better Performance)
# =======================================================
class CommandHandler:
    """Optimized command processing system that uses dictionary mapping instead of if-elif chains for better performance"""
    
    def __init__(self):
        # Command mapping dictionary, keys are command names, values are handler functions
        self.commands = {
            'clear': self._handle_clear,
            'save': self._handle_save,
            'load': self._handle_load,
            'memory': self._handle_memory,
            'setmemory': self._handle_setmemory,
            'system': self._handle_system,
            'help': self._handle_help,
        }
        
        # Precompile help text to avoid repeated generation
        self._help_text = (
            "Available commands:\n"
            + "/clear - Clear history\n"
            + "/save - Save history to file\n"
            + "/load - Load history from file\n"
            + "/memory - View current memory status\n"
            + "/setmemory [number] - Set maximum history length\n"
            + "/system - View system information\n"
            + "/help - Show this help information"
        )
    
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
        
        try:
            command_parts = text[1:].strip().split(' ', 1)
            command = command_parts[0].lower()
            args = command_parts[1] if len(command_parts) > 1 else ""
            
            # Use dictionary lookup for command handler functions, more efficient than if-elif chains
            if command in self.commands:
                return True, self.commands[command](memory, args)
            
            return True, f"Unknown command: {command}, use /help to see available commands"
        except Exception as e:
            return True, f"Command execution error: {str(e)}"
    
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
        # Execute directly in the current thread since this is synchronous command processing
        try:
            return get_system_info()
        except Exception as e:
            print(f"Error getting system info: {str(e)}")
            return "Failed to get system information"

    
    def _handle_help(self, memory, args):
        return self._help_text

# Create command handler instance
command_handler = CommandHandler()

# Function compatible with old interface
def handle_command(text, memory: MemoryManager):
    """Synchronous interface for command processing, ensuring correct execution in synchronous contexts"""
    try:
        # Directly call the command handler's handle method
        return command_handler.handle(text, memory)
    except Exception as e:
        print(f"Command processing error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False, f"Command processing error: {str(e)}"

# Add async version of command processor for async context
async def handle_command_async(text, memory: MemoryManager):
    """Asynchronous version of command processing for async contexts"""
    # Execute command processing in a separate thread to avoid blocking the event loop
    is_command, response = await asyncio.to_thread(handle_command, text, memory)
    return is_command, response


# =======================================================
# 3. Optimized LLM Query Function (Final Revision: async + asyncio.to_thread + Error Handling)
# =======================================================


async def query_model(text, memory: MemoryManager):
    """
    Optimized LLM main query logic, using asyncio.to_thread to wrap blocking functions,
    enhanced error handling, optimized memory usage and concurrent processing.
    """
    
    # First check if it's a command (using asynchronous command handler)
    is_command, command_response = await handle_command_async(text, memory)
    if is_command:
        return command_response
    
    try:
        # 1. Sequentially execute synchronous tool calls to avoid coroutine issues
        try:
            # Use to_thread to ensure execution in a separate thread
            keywords = await asyncio.to_thread(extract_keywords, text)
            system_info = await asyncio.to_thread(get_system_info)
            emotion = await asyncio.to_thread(analyze_emotion, text)
        except Exception as e:
            print(f"Tool call error: {str(e)}")
            # Set default values to ensure continuation even if tool calls fail
            keywords = []
            system_info = "System information retrieval failed"
            emotion = None
        
        # 2. Optimized long-term memory retrieval (with error handling)
        long_mem = ""
        try:
            long_mem = await asyncio.to_thread(retrieve_long_term_memory, keywords)
        except Exception as e:
            # Log the error but don't affect the main process
            print(f"Long-term memory retrieval error: {str(e)}")
        
        # 3. Assemble final history (execute directly in current thread to avoid coroutine issues)
        try:
            keywords_str = ", ".join(keywords) if isinstance(keywords, (list, tuple)) else str(keywords)
            user_content = f"Long-term memory: {system_info} | User emotion: {emotion} | User says: {text} (Keywords:{keywords_str})"
        except Exception as e:
            print(f"Content assembly error: {str(e)}")
            user_content = f"User says: {text}"
        
        history = memory.get_history() + [{"role": "user", "content": user_content}]
        
        # 4. Call LLM (with error handling and fallback)
        try:
            reply_text = await asyncio.to_thread(model.generate, history)
            
            # 5. Asynchronously save long-term memory without blocking the main process
            # Create a background task for saving, without waiting for it to complete
            try:
                asyncio.create_task(
                    asyncio.to_thread(save_long_term_memory, text, keywords_str)
                )
            except Exception as e:
                print(f"Error saving long-term memory: {str(e)}")
            
            return reply_text
        except Exception as e:
            error_msg = f"AI generation error: {str(e)}"
            print(traceback.format_exc())  # Detailed log for debugging
            return f"Sorry, I'm temporarily unable to generate a response. Please try again later. {error_msg}"
    
    except Exception as e:
        # Catch all exceptions to ensure system stability
        error_msg = f"Error processing request: {str(e)}"
        print(traceback.format_exc())  # Detailed log for debugging
        return f"System processing error: {error_msg}, please try again."

# Add a simple asynchronous task manager to limit the number of concurrent tasks
class AsyncTaskManager:
    def __init__(self, max_concurrent_tasks=3):
        self.semaphore = asyncio.Semaphore(max_concurrent_tasks)
    
    async def run_task(self, coro):
        """Run task and limit concurrent count"""
        async with self.semaphore:
            # Ensure correct waiting for coroutine completion
            try:
                return await coro
            except Exception as e:
                print(f"Task execution error: {str(e)}")
                import traceback
                traceback.print_exc()
                return f"System error: {str(e)}"

# Create global task manager instance
task_manager = AsyncTaskManager(max_concurrent_tasks=3)