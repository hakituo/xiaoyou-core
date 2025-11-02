import asyncio
import os
import traceback

from core.utils import get_system_info, analyze_emotion, extract_keywords, cache_result
from memory.memory_manager import MemoryManager
from memory.long_term_db import retrieve_long_term_memory, save_long_term_memory
from core.models.qianwen_model import QianwenModel as LLMModel 


# =======================================================
# 1. 初始化模型实例
# =======================================================
model = LLMModel()

# 自定义AI人设配置
# 你可以修改下面的内容来更改AI的角色设定
CUSTOM_PERSONALITY = ""
# 取消下面一行的注释并修改内容来自定义AI人设
# CUSTOM_PERSONALITY = "你是一个专业的技术顾问，擅长解决编程问题..."

# 如果设置了自定义人设，则应用它
if CUSTOM_PERSONALITY:
    model.set_personality(CUSTOM_PERSONALITY) 


# =======================================================
# 2. 优化的命令系统（使用字典映射提高性能）
# =======================================================
class CommandHandler:
    """优化的命令处理系统，使用字典映射代替if-elif链以提高性能"""
    
    def __init__(self):
        # 命令映射字典，键为命令名，值为处理函数
        self.commands = {
            'clear': self._handle_clear,
            'save': self._handle_save,
            'load': self._handle_load,
            'memory': self._handle_memory,
            'setmemory': self._handle_setmemory,
            'system': self._handle_system,
            'help': self._handle_help,
        }
        
        # 预编译帮助文本，避免重复生成
        self._help_text = (
            "可用命令:\n"
            + "/clear - 清空历史记录\n"
            + "/save - 保存历史记录到文件\n"
            + "/load - 从文件加载历史记录\n"
            + "/memory - 查看当前内存状态\n"
            + "/setmemory [数字] - 设置历史记录最大长度\n"
            + "/system - 查看系统信息\n"
            + "/help - 显示此帮助信息"
        )
    
    def handle(self, text, memory: MemoryManager):
        """
        处理用户输入的命令
        
        Args:
            text: 用户输入的文本
            memory: 内存管理器实例
        
        Returns:
            tuple: (is_command, response_text)
        """
        if not text.startswith('/'):
            return False, ""
        
        try:
            command_parts = text[1:].strip().split(' ', 1)
            command = command_parts[0].lower()
            args = command_parts[1] if len(command_parts) > 1 else ""
            
            # 使用字典查找命令处理函数，比if-elif链更高效
            if command in self.commands:
                return True, self.commands[command](memory, args)
            
            return True, f"未知命令: {command}，使用 /help 查看可用命令"
        except Exception as e:
            return True, f"命令执行出错: {str(e)}"
    
    def _handle_clear(self, memory, args):
        return memory.clear()
    
    def _handle_save(self, memory, args):
        return memory.save_history()
    
    def _handle_load(self, memory, args):
        return memory.load_history()
    
    def _handle_memory(self, memory, args):
        stats = memory.get_stats()
        return f"内存状态: 当前历史 {stats['current_length']}/{stats['max_length']} 条消息"
    
    def _handle_setmemory(self, memory, args):
        try:
            max_len = int(args)
            # 添加边界检查，防止设置过小或过大的值
            if max_len < 1 or max_len > 100:
                return "请设置1-100之间的有效数字"
            return memory.set_max_length(max_len)
        except ValueError:
            return "请输入有效的数字作为最大历史记录长度"
    
    def _handle_system(self, memory, args):
        # 直接在当前线程中执行，因为这是同步命令处理
        try:
            return get_system_info()
        except Exception as e:
            print(f"获取系统信息错误: {str(e)}")
            return "获取系统信息失败"

    
    def _handle_help(self, memory, args):
        return self._help_text

# 创建命令处理器实例
command_handler = CommandHandler()

# 兼容旧接口的函数
def handle_command(text, memory: MemoryManager):
    """处理命令的同步接口，确保在同步上下文中正确执行"""
    try:
        # 直接调用命令处理器的handle方法
        return command_handler.handle(text, memory)
    except Exception as e:
        print(f"命令处理错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return False, f"命令处理出错: {str(e)}"

# 添加异步版本的命令处理器，用于异步上下文
async def handle_command_async(text, memory: MemoryManager):
    """异步版本的命令处理，适用于异步上下文"""
    # 在单独线程中执行命令处理，避免阻塞事件循环
    is_command, response = await asyncio.to_thread(handle_command, text, memory)
    return is_command, response


# =======================================================
# 3. 优化的LLM查询函数 (最终修正：async + asyncio.to_thread + 错误处理)
# =======================================================
def _assemble_user_content(text, keywords, system_info, emotion):
    """优化的用户内容组装函数，减少字符串连接操作"""
    keywords_str = "、".join(keywords) if keywords else "无"
    # 使用格式化字符串而非多次拼接
    return f"长期记忆: {system_info} | 用户情绪: {emotion} | 用户说: {text} (关键词:{keywords_str})"

async def query_model(text, memory: MemoryManager):
    """
    优化的LLM主查询逻辑，使用asyncio.to_thread包装阻塞函数，
    增强错误处理，优化内存使用和并发处理。
    """
    
    # 首先检查是否为命令 (使用异步版本的命令处理器)
    is_command, command_response = await handle_command_async(text, memory)
    if is_command:
        return command_response
    
    try:
        # 1. 顺序执行同步工具调用，避免协程问题
        try:
            # 使用to_thread确保在单独线程中执行
            keywords = await asyncio.to_thread(extract_keywords, text)
            system_info = await asyncio.to_thread(get_system_info)
            emotion = await asyncio.to_thread(analyze_emotion, text)
        except Exception as e:
            print(f"工具调用错误: {str(e)}")
            # 设置默认值，确保即使工具调用失败也能继续
            keywords = []
            system_info = "系统信息获取失败"
            emotion = None
        
        # 2. 优化的长期记忆检索 (添加错误处理)
        long_mem = ""
        try:
            long_mem = await asyncio.to_thread(retrieve_long_term_memory, keywords)
        except Exception as e:
            # 记录错误但不影响主要流程
            print(f"长期记忆检索错误: {str(e)}")
        
        # 3. 组装最终历史记录 (直接在当前线程执行，避免协程问题)
        try:
            keywords_str = "、".join(keywords) if isinstance(keywords, (list, tuple)) else str(keywords)
            user_content = f"长期记忆: {system_info} | 用户情绪: {emotion} | 用户说: {text} (关键词:{keywords_str})"
        except Exception as e:
            print(f"组装内容错误: {str(e)}")
            user_content = f"用户说: {text}"
        
        history = memory.get_history() + [{"role": "user", "content": user_content}]
        
        # 4. 调用LLM (添加错误处理和回退)
        try:
            reply_text = await asyncio.to_thread(model.generate, history)
            
            # 5. 异步保存长期记忆，不阻塞主流程
            # 创建后台任务保存，不等待其完成
            try:
                asyncio.create_task(
                    asyncio.to_thread(save_long_term_memory, text, keywords_str)
                )
            except Exception as e:
                print(f"保存长期记忆时出错: {str(e)}")
            
            return reply_text
        except Exception as e:
            error_msg = f"AI生成出错: {str(e)}"
            print(traceback.format_exc())  # 详细日志用于调试
            return f"抱歉，我暂时无法生成回复，请稍后再试。{error_msg}"
    
    except Exception as e:
        # 捕获所有异常，确保系统稳定运行
        error_msg = f"处理请求时出错: {str(e)}"
        print(traceback.format_exc())  # 详细日志用于调试
        return f"系统处理出错: {error_msg}，请重试。"

# 添加一个简单的异步任务管理器来限制并发任务数量
class AsyncTaskManager:
    def __init__(self, max_concurrent_tasks=3):
        self.semaphore = asyncio.Semaphore(max_concurrent_tasks)
    
    async def run_task(self, coro):
        """运行任务并限制并发数量"""
        async with self.semaphore:
            # 确保正确等待协程完成
            try:
                return await coro
            except Exception as e:
                print(f"任务执行错误: {str(e)}")
                import traceback
                traceback.print_exc()
                return f"系统错误: {str(e)}"

# 创建全局任务管理器实例
task_manager = AsyncTaskManager(max_concurrent_tasks=3)