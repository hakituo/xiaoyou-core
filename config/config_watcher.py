"""
配置热重载功能实现
监控配置文件变化，实现动态配置更新
"""
import os
import time
import threading
import logging
from typing import Dict, List, Callable, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent, FileDeletedEvent
from config.integrated_config import get_settings, AppSettings, _settings_instance
# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('config_watcher')
class ConfigChangedHandler(FileSystemEventHandler):
    """配置文件变化事件处理器"""
    def __init__(self, config_manager, watch_extensions=None):
        self.config_manager = config_manager
        # 默认监控的配置文件扩展名
        self.watch_extensions = watch_extensions or ['.py', '.json', '.yaml', '.yml']
class ConfigManager:
    """
    配置管理器，支持配置热重载
    特性：
    - 监控配置文件变化
    - 配置自动重新加载
    - 配置变更回调通知
    - 防抖动机制避免频繁重载
    """
    def __init__(self):
        self.observer = None
        self.event_handler = None
        self.watched_directories = set()
        self.callbacks = []
        self.last_reload_time = 0
        self.reload_lock = threading.RLock()  # 重入锁保护配置重载
        self.debounce_timer = None
        self.debounce_time = 1.0  # 防抖动时间（秒）
        # 默认监控的配置目录
        self.config_directories = []
        self._setup_default_directories()
    def _setup_default_directories(self):
        """设置默认监控的配置目录"""
        # 获取项目根目录
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir)
        # 默认监控的目录
        default_dirs = [
            os.path.join(project_root, 'config'),
            os.path.join(project_root, 'configs'),  # 兼容性目录
            os.path.join(project_root, 'src', 'config')
        ]
        # 只添加存在的目录
        for dir_path in default_dirs:
            if os.path.exists(dir_path) and os.path.isdir(dir_path):
                self.config_directories.append(dir_path)
                logger.info(f"添加默认监控目录: {dir_path}")
    def _watch_directory(self, dir_path: str):
        """添加单个目录到监控列表"""
        if dir_path not in self.watched_directories:
            self.observer.schedule(self.event_handler, dir_path, recursive=True)
            self.watched_directories.add(dir_path)
            logger.info(f"开始监控目录: {dir_path}")
    def _schedule_reload(self):
        """调度配置重载（带防抖动）"""
        if self.debounce_timer:
            self.debounce_timer.cancel()
        self.debounce_timer = threading.Timer(self.debounce_time, self.reload_config)
        self.debounce_timer.daemon = True
        self.debounce_timer.start()
    def _notify_callbacks(self, old_settings: AppSettings, new_settings: AppSettings):
        """通知所有注册的回调函数配置已变更"""
        for callback in self.callbacks:
            try:
                callback(old_settings, new_settings)
            except Exception as e:
                logger.error(f"配置变更回调执行失败: {e}")
    
    def register_callback(self, callback: Callable[[AppSettings, AppSettings], None]):
        """
        注册配置变更回调函数
        Args:
            callback: 回调函数，接收旧配置和新配置作为参数
        """
        if callback not in self.callbacks:
            self.callbacks.append(callback)
            logger.info(f"已注册配置变更回调: {callback.__name__}")
# 全局配置管理器实例
_config_manager_instance = None
def get_config_manager() -> ConfigManager:
    """
    获取全局配置管理器实例
    Returns:
        ConfigManager: 配置管理器实例
    """
    global _config_manager_instance
    if _config_manager_instance is None:
        _config_manager_instance = ConfigManager()
    return _config_manager_instance
# 配置变更装饰器
def on_config_change(func):
    """
    配置变更装饰器，用于标记配置变更时需要调用的函数
    使用方法:
    @on_config_change
    def handle_config_change(old_settings, new_settings):
        # 处理配置变更
        pass
    """
    config_manager = get_config_manager()
    config_manager.register_callback(func)
    return func
# 示例：配置变更处理器示例
@on_config_change
# 应用示例
def example_usage():
    """配置管理器使用示例"""
    # 1. 启动配置监控
    config_manager = get_config_manager()
    config_manager.start_watching()
    # 2. 获取当前配置
    settings = get_settings()
    print(f"初始配置 - 服务器端口: {settings.server.port}")
    # 3. 注册自定义回调
    def custom_callback(old_settings, new_settings):
        print(f"自定义回调: 配置已更新")
        print(f"新的日志级别: {new_settings.log.level}")
    config_manager.register_callback(custom_callback)
    try:
        # 4. 等待配置变更
        print("正在监控配置文件变化，按Ctrl+C退出...")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        # 5. 清理
        config_manager.unregister_callback(custom_callback)
        config_manager.stop_watching()
        print("配置监控已停止")
if __name__ == "__main__":
    example_usage()