import json
import os
import sys
import asyncio
import time
import threading

class MemoryManager:
    def __init__(self, max_length=10, user_id="default", auto_save_interval=300):
        """
        优化的内存管理器，降低默认max_length以减少内存占用，并添加自动保存功能
        
        Args:
            max_length: 历史记录最大条数
            user_id: 用户ID，用于保存/加载历史记录
            auto_save_interval: 自动保存间隔（秒），0表示禁用自动保存
        """
        self.history = []
        self.max_length = max_length
        self.user_id = user_id
        self.history_dir = "history"
        self.auto_save_interval = auto_save_interval
        self.last_modified_time = time.time()
        self.lock = threading.Lock()  # 添加线程锁以确保线程安全
        
        # 确保历史记录目录存在
        try:
            os.makedirs(self.history_dir, exist_ok=True)
        except Exception as e:
            print(f"创建历史目录失败: {e}")
        
        # 启动自动保存线程
        if auto_save_interval > 0:
            self.auto_save_thread = threading.Thread(target=self._auto_save_loop, daemon=True)
            self.auto_save_thread.start()

    def add_message(self, role, content, is_important=False):
        """
        添加一条对话记录，支持标记重要消息
        
        Args:
            role: 消息角色（user/assistant/system）
            content: 消息内容
            is_important: 是否为重要消息（重要消息更难被移除）
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
            
            # 限制历史记录长度，智能移除策略
            self._trim_history()
            
            return message
    
    def _trim_history(self):
        """智能修剪历史记录，优先保留重要消息"""
        if len(self.history) > self.max_length:
            # 区分重要和非重要消息
            important_messages = [msg for msg in self.history if msg.get('is_important', False)]
            normal_messages = [msg for msg in self.history if not msg.get('is_important', False)]
            
            # 计算可以保留的非重要消息数量
            max_normal = max(0, self.max_length - len(important_messages))
            
            # 保留最新的非重要消息
            if max_normal < len(normal_messages):
                normal_messages = normal_messages[-max_normal:]
            
            # 重新组合历史记录
            self.history = important_messages + normal_messages
            
            # 如果还是超过限制，按时间戳排序并保留最新的
            if len(self.history) > self.max_length:
                self.history.sort(key=lambda x: x['timestamp'], reverse=True)
                self.history = self.history[:self.max_length]
                # 恢复时间顺序
                self.history.sort(key=lambda x: x['timestamp'])

    def get_history(self):
        """返回当前历史对话，优化内存使用"""
        with self.lock:
            # 只返回LLM需要的字段，减少内存占用
            simplified_history = []
            for msg in self.history:
                simplified_history.append({
                    "role": msg["role"], 
                    "content": msg["content"]
                })
            return simplified_history.copy()

    def clear(self):
        """手动清空历史"""
        with self.lock:
            self.history.clear()
            self.last_modified_time = time.time()
            return "历史记录已清空"
    
    def save_history(self):
        """保存历史记录到文件，使用压缩格式减少文件大小"""
        try:
            file_path = os.path.join(self.history_dir, f"{self.user_id}.json")
            
            # 序列化时处理可能的编码问题
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
            
            # 使用紧凑格式保存，减少文件大小
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(safe_history, f, ensure_ascii=False, separators=(',', ':'))
            
            return f"历史记录已保存到 {file_path}（{os.path.getsize(file_path)} 字节）"
        except Exception as e:
            error_msg = f"保存历史记录失败: {str(e)}"
            print(error_msg)
            return error_msg
    
    def load_history(self):
        """从文件加载历史记录"""
        try:
            file_path = os.path.join(self.history_dir, f"{self.user_id}.json")
            if os.path.exists(file_path):
                # 异步加载大文件，避免阻塞
                with open(file_path, 'r', encoding='utf-8') as f:
                    loaded_history = json.load(f)
                
                with self.lock:
                    self.history = loaded_history
                    self.last_modified_time = time.time()
                
                # 确保加载后历史记录符合最大长度限制
                self._trim_history()
                
                return f"已加载保存的历史记录 ({len(self.history)} 条)"
            else:
                return "未找到保存的历史记录"
        except json.JSONDecodeError:
            return "历史记录文件格式错误，无法加载"
        except Exception as e:
            error_msg = f"加载历史记录失败: {str(e)}"
            print(error_msg)
            return error_msg
    
    def set_max_length(self, max_length):
        """设置历史记录最大长度，添加合理的边界检查"""
        try:
            if 1 <= max_length <= 100:  # 添加合理范围限制
                with self.lock:
                    self.max_length = max_length
                    # 如果当前历史超过新限制，智能截断
                    self._trim_history()
                return f"历史记录最大长度已设置为 {max_length}"
            else:
                return "最大长度必须在1-100之间"
        except Exception as e:
            return f"设置最大长度失败: {str(e)}"
    
    def get_stats(self):
        """获取内存统计信息，包含更多详细指标"""
        with self.lock:
            # 估算内存使用
            try:
                # 使用sys.getsizeof估算对象大小
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
                # 如果内存计算失败，返回基本信息
                return {
                    "current_length": len(self.history),
                    "max_length": self.max_length,
                    "user_id": self.user_id
                }
    
    def _auto_save_loop(self):
        """自动保存循环线程"""
        while True:
            try:
                time.sleep(self.auto_save_interval)
                # 只有在有修改且不是空历史时才保存
                if self.history and (time.time() - self.last_modified_time > 60):  # 至少1分钟未保存才执行
                    self.save_history()
                    print(f"[{time.ctime()}] 自动保存 {self.user_id} 的历史记录")
            except Exception as e:
                print(f"自动保存失败: {e}")
    
    async def async_save_history(self):
        """异步保存历史记录，避免阻塞事件循环"""
        return await asyncio.to_thread(self.save_history)
    
    async def async_load_history(self):
        """异步加载历史记录，避免阻塞事件循环"""
        return await asyncio.to_thread(self.load_history)
