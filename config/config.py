# 项目配置文件

class Config:
    # 基础配置
    SERVER_PORT = 7860  # 服务端口
    
    # WebSocket配置
    WS_PORT = 6790  # WebSocket服务端口
    WS_HEARTBEAT_INTERVAL = 30  # 心跳间隔（秒）
    WS_TIMEOUT = 60  # 超时时间（秒）
    MAX_CONNECTIONS = 10  # 最大连接数
    
    # 日志配置
    LOG_LEVEL = "INFO"  # 日志级别：DEBUG, INFO, WARNING, ERROR, CRITICAL
    LOG_FILE = "flask_app.log"  # 日志文件名
    
    # 性能配置
    MAX_REQUESTS_PER_MINUTE = 60  # 每分钟最大请求数
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 最大内容长度（16MB）
    
    # 对话历史配置
    DEFAULT_HISTORY_LENGTH = 10  # 默认历史记录长度
    MAX_HISTORY_LENGTH = 50  # 最大历史记录长度
    
    # 内存管理配置
    MEMORY_PRUNING_THRESHOLD = 0.3  # 重要性阈值，低于此值的记忆会被优先修剪
    LONG_TERM_MEMORY_DB = "long_term_memory.db"  # 长期记忆数据库文件
    
    # 模型配置
    DEFAULT_MODEL = "qwen3-max-2025-09-23"
    MODEL_PATH = "./models/"  # 本地模型路径
    
    # 语音配置
    VOICE_ENABLED = True
    DEFAULT_VOICE_ENGINE = "local"  # 使用本地语音引擎
    DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"  # 默认语音
    DEFAULT_VOICE_SPEED = 1.0  # 默认语速
    
    # 缓存配置
    CACHE_SIZE = 1000  # LRU缓存大小
    CACHE_TTL = 3600  # 缓存过期时间（秒）
    
    # API Keys
    QIANWEN_API_KEY = "sk-315b05704dc4420591c9b8afe29bd0b0"  # 通义千问API密钥
    
    # Model Configuration
    DEFAULT_MODEL = "qwen3-max-2025-09-23"
    
    # 日志配置
    LOG_LEVEL = "INFO"  # "DEBUG", "INFO", "WARNING", "ERROR"
    LOG_FILE = "xiaoyou_core.log"
    
    # 资源限制
    MAX_TEXT_LENGTH = 4096  # 最大文本长度
    MAX_REQUESTS_PER_MINUTE = 60  # 每分钟最大请求数
    
    # 文件系统路径
    HISTORY_DIR = "./history/"  # 历史记录目录
    STATIC_DIR = "./static/"  # 静态资源目录
    TEMPLATES_DIR = "./templates/"  # 模板目录
    
    # 跨域配置
    CORS_ENABLED = True  # 是否启用CORS
    ALLOWED_ORIGINS = ["*"]  # 允许的来源，生产环境应该限制为特定域名

class DevelopmentConfig(Config):
    DEBUG_MODE = True
    LOG_LEVEL = "DEBUG"
    DEFAULT_HISTORY_LENGTH = 20

class ProductionConfig(Config):
    DEBUG_MODE = False
    LOG_LEVEL = "WARNING"
    CORS_ENABLED = True

class TestingConfig(Config):
    TESTING = True
    DEBUG_MODE = True
    LOG_LEVEL = "DEBUG"
    MAX_CONNECTIONS = 2

config_by_name = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': Config
}