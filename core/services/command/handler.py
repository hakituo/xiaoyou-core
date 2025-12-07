import asyncio
from typing import Dict, Any, Tuple
from memory.memory_manager import MemoryManager

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
    
    def handle(self, text: str, memory: MemoryManager) -> Tuple[bool, str]:
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
            # Add boundary checks to prevent setting non-positive values
            if max_len < 1:
                return "Please set a valid positive number"
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
