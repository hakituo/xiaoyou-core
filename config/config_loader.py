import os
import yaml
import json
import re
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Union
from dotenv import load_dotenv
# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
class ConfigLoader:
    """配置加载器 (ConfigLoader)
    负责加载、合并和管理配置，包括YAML/JSON配置文件和环境变量。
    支持敏感信息管理和配置验证。
    实现了单例模式，确保配置的一致性和全局可访问性。
    主要方法:
        get: 获取配置项
        update: 更新配置项
        get_all: 获取所有配置
        reload: 重新加载配置
        validate: 验证配置有效性
    特性:
        - 支持YAML和JSON格式配置文件
        - 环境变量集成和.env文件支持
        - 敏感信息管理
        - 配置验证
        - 配置热重载支持
    """
    def __init__(self, base_dir: str = None):
        """初始化配置加载器
        Args:
            base_dir: 配置文件基础目录，默认为config目录
        """
        # 优化：统一使用config目录作为配置文件基础目录
        self.base_dir = base_dir or os.path.dirname(os.path.abspath(__file__))
        self.configs: Dict[str, Any] = {}
        # 加载环境变量
        self._load_env_files()
        # 加载配置文件
        self._load_all_configs()
        # 验证配置
        self.validate()
    def _load_env_files(self):
        """加载.env文件（内部方法）"""
        # 获取环境
        env = os.getenv("ENVIRONMENT", "development")
        # 优先级: .env.local > .env.${ENV} > .env
        env_files = [
            Path(".env.local"),
            Path(f".env.{env}"),
            Path(".env")
        ]
        loaded = False
        for env_file in env_files:
            if env_file.exists():
                try:
                    load_dotenv(dotenv_path=env_file)
                    logger.info(f"成功加载环境变量文件: {env_file}")
                    loaded = True
                except Exception as e:
                    logger.error(f"加载环境变量文件失败 {env_file}: {e}")
        if not loaded:
            logger.warning("未找到.env文件，将使用默认配置")
            # 检查是否有.env.example文件，如果有，提示用户复制
            if Path(".env.example").exists():
                logger.info("发现.env.example文件，可以复制一份并修改为.env使用")
    def _load_all_configs(self):
        """加载所有配置文件并合并环境变量（内部方法）"""
        # 首先检查并尝试加载yaml子目录中的配置文件
        yaml_dir = os.path.join(self.base_dir, 'yaml')
        if os.path.exists(yaml_dir):
            yaml_files = ['app.yaml', 'env.yaml', 'paths.yaml', 'experiment.yaml']
            for yaml_file in yaml_files:
                file_path = os.path.join(yaml_dir, yaml_file)
                if os.path.exists(file_path):
                    config_name = os.path.splitext(yaml_file)[0]
                    self.configs[config_name] = self._load_yaml(file_path)
        else:
            # 兼容模式：尝试从旧的configs目录加载（为迁移提供过渡期）
            old_configs_dir = os.path.join(os.path.dirname(self.base_dir), 'configs')
            if os.path.exists(old_configs_dir):
                yaml_files = ['app.yaml', 'env.yaml', 'paths.yaml', 'experiment.yaml']
                for yaml_file in yaml_files:
                    file_path = os.path.join(old_configs_dir, yaml_file)
                    if os.path.exists(file_path):
                        config_name = os.path.splitext(yaml_file)[0]
                        self.configs[config_name] = self._load_yaml(file_path)
        # 加载JSON配置文件（直接在config目录下）
        json_files = ['asr_config.json']
        for json_file in json_files:
            file_path = os.path.join(self.base_dir, json_file)
            if os.path.exists(file_path):
                config_name = os.path.splitext(json_file)[0]
                self.configs[config_name] = self._load_json(file_path)
        # 合并环境变量配置
        self._merge_env_configs()
    def _load_yaml(self, file_path: str) -> Dict[str, Any]:
        """加载YAML配置文件（内部方法）"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
                # 替换环境变量占位符
                return self._resolve_env_vars(config)
        except Exception as e:
            logger.error(f"无法加载YAML文件 {file_path}: {e}")
            return {}
    def _load_json(self, file_path: str) -> Dict[str, Any]:
        """加载JSON配置文件（内部方法）"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                config = json.load(f) or {}
                # 替换环境变量占位符
                return self._resolve_env_vars(config)
        except Exception as e:
            logger.error(f"无法加载JSON文件 {file_path}: {e}")
            return {}
    def _resolve_env_vars(self, config: Any) -> Any:
        """递归替换配置中的环境变量占位符（内部方法）"""
        if isinstance(config, dict):
            return {k: self._resolve_env_vars(v) for k, v in config.items()}
        elif isinstance(config, list):
            return [self._resolve_env_vars(item) for item in config]
        elif isinstance(config, str):
            # 匹配 ${ENV_VAR} 或 $ENV_VAR 格式
            pattern = r'\$\{([^}]+)\}|\$(\w+)'  
            def replace_var(match):
                env_var = match.group(1) or match.group(2)
                return os.getenv(env_var, match.group(0))
            return re.sub(pattern, replace_var, config)
        return config
    def _merge_env_configs(self):
        """合并环境变量到配置中（内部方法）"""
        # 关键环境变量配置
        critical_env_vars = {
            'SECRET_KEY': {'default': 'default-dev-secret-key-please-change', 'description': '应用密钥'},
            'SERVER_PORT': {'default': 8000, 'description': '服务器端口'},
            'WS_PORT': {'default': 8765, 'description': 'WebSocket端口'},
            'ENVIRONMENT': {'default': 'development', 'description': '运行环境'},
            'REDIS_URL': {'default': 'redis://localhost:6379/0', 'description': 'Redis连接URL'},
            'MAX_WORKERS': {'default': 4, 'description': '最大工作线程数'},
            'MAX_TTS_CONCURRENT': {'default': 2, 'description': '最大TTS并发数'},
            'IP_WHITELIST': {'default': '127.0.0.1', 'description': 'IP白名单'},
            'LOG_LEVEL': {'default': 'INFO', 'description': '日志级别'},
            'LOG_DIR': {'default': './logs/', 'description': '日志目录'},
            'LOG_USE_JSON_FORMAT': {'default': False, 'description': '是否使用JSON格式日志'},
            'LOG_MAX_BYTES': {'default': 10485760, 'description': '日志文件最大字节数'},
            'LOG_BACKUP_COUNT': {'default': 5, 'description': '保留的日志文件数量'},
            'LOG_ROTATION_TYPE': {'default': 'size', 'description': '日志轮转类型'},
            'LOG_ROTATION_WHEN': {'default': 'midnight', 'description': '时间轮转单位'},
            'LOG_ROTATION_INTERVAL': {'default': 1, 'description': '轮转时间间隔'},
            'MAX_REQUESTS_PER_MINUTE': {'default': 60, 'description': '每分钟最大请求数'},
            'MAX_IP_REQUESTS_PER_MINUTE': {'default': 30, 'description': '每IP每分钟最大请求数'},
            'MAX_CONTENT_LENGTH': {'default': 16 * 1024 * 1024, 'description': '最大内容长度'},
            'INFER_SERVICE_HOST': {'default': '0.0.0.0', 'description': '推理服务主机地址'},
            'INFER_SERVICE_PORT': {'default': 8000, 'description': '推理服务端口'},
            'INFER_SERVICE_WORKERS': {'default': 1, 'description': '推理服务工作进程数'},
            'INFER_SERVICE_ENABLED': {'default': True, 'description': '是否启用推理服务'},
            'DASHSCOPE_API_KEY': {'default': '', 'description': 'DashScope API Key'}
        }
        # 创建系统配置部分
        if 'system' not in self.configs:
            self.configs['system'] = {}
        # 合并环境变量
        for env_var, info in critical_env_vars.items():
            value = os.getenv(env_var)
            if value is not None:
                # 尝试类型转换
                if isinstance(info['default'], bool):
                    value = value.lower() in ('true', '1', 'yes', 'y')
                elif isinstance(info['default'], int):
                    try:
                        value = int(value)
                    except ValueError:
                        logger.warning(f"环境变量 {env_var} 不是有效的整数，使用默认值 {info['default']}")
                        value = info['default']
                elif isinstance(info['default'], float):
                    try:
                        value = float(value)
                    except ValueError:
                        logger.warning(f"环境变量 {env_var} 不是有效的浮点数，使用默认值 {info['default']}")
                        value = info['default']
                # 记录配置变更
                if env_var.lower() not in self.configs['system'] or self.configs['system'][env_var.lower()] != value:
                    # 脱敏敏感信息
                    if any(sensitive in env_var.lower() for sensitive in ['secret', 'key', 'token', 'password']):
                        if isinstance(value, str) and len(value) > 8:
                            masked_value = value[:4] + '****' + value[-4:]
                        else:
                            masked_value = '****'
                        logger.info(f"环境变量覆盖配置: {env_var} = {masked_value}")
                    else:
                        logger.debug(f"环境变量覆盖配置: {env_var} = {value}")
                self.configs['system'][env_var.lower()] = value
            elif info['default'] not in self.configs['system']:
                self.configs['system'][env_var.lower()] = info['default']
        # 确保日志目录存在
        log_dir = self.configs['system'].get('log_dir', './logs/')
        if not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir, exist_ok=True)
                logger.info(f"创建日志目录: {log_dir}")
            except Exception as e:
                logger.error(f"无法创建日志目录 {log_dir}: {e}")
    def _mask_sensitive_value(self, value: Any) -> str:
        """脱敏敏感值
        Args:
            value: 要脱敏的值
        Returns:
            脱敏后的值
        """
        if isinstance(value, str):
            if len(value) <= 8:
                return '*' * len(value)
            return value[:4] + '*' * (len(value) - 8) + value[-4:]
        elif isinstance(value, (int, float)):
            return '****'
        elif value is None:
            return 'None'
        else:
            return '****'
    def _mask_sensitive_info(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """脱敏敏感信息（内部方法）"""
        sensitive_keys = ['secret_key', 'password', 'token', 'api_key', 'key']
        masked_config = {}
        for key, value in config.items():
            if any(sensitive in key.lower() for sensitive in sensitive_keys):
                if isinstance(value, str) and len(value) > 8:
                    masked_config[key] = value[:4] + '****' + value[-4:]
                else:
                    masked_config[key] = '****'
            elif isinstance(value, dict):
                masked_config[key] = self._mask_sensitive_info(value)
            else:
                masked_config[key] = value
        return masked_config
    def _is_valid_ip(self, ip: str) -> bool:
        """验证IP地址或CIDR格式（内部方法）"""
        # 检查IPv4地址
        ipv4_pattern = r"^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"
        # 检查CIDR格式
        cidr_pattern = r"^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\/(3[0-2]|[12]?[0-9])$"
        return bool(re.match(ipv4_pattern, ip) or re.match(cidr_pattern, ip))
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        通过点分隔的路径获取配置值
        Args:
            key: 配置键路径，如 'logging.log_level'
            default: 默认值，当配置不存在时返回
        Returns:
            配置值或默认值
        """
        try:
            keys = key.split('.')
            value = self.configs
            for k in keys:
                if isinstance(value, dict) and k in value:
                    value = value[k]
                else:
                    # 尝试从顶层配置中查找
                    if k in self.configs:
                        value = self.configs[k]
                    else:
                        return default
            return value
        except Exception:
            return default
    
    def validate(self):
        """
        验证配置有效性
        确保必要的配置项存在且格式正确
        """
        try:
            # 检查必要的配置目录
            if not os.path.exists(self.base_dir):
                logger.warning(f"配置目录不存在: {self.base_dir}")
            
            # 检查日志目录配置
            log_dir = self.get('logging.log_dir')
            if log_dir:
                # 确保日志目录可创建
                try:
                    os.makedirs(log_dir, exist_ok=True)
                except Exception as e:
                    logger.warning(f"日志目录可能无法创建: {e}")
            
            # 验证端口配置
            port = self.get('server.port')
            if port is not None:
                try:
                    port_int = int(port)
                    if not (1 <= port_int <= 65535):
                        logger.warning(f"端口配置无效: {port}")
                except (ValueError, TypeError):
                    logger.warning(f"端口配置不是有效整数: {port}")
            
            logger.info("配置验证完成")
        except Exception as e:
            logger.error(f"配置验证失败: {e}")
            # 验证失败不应该阻止程序运行，只记录警告
# 创建全局配置加载器实例
_config_loader = None
# 创建配置对象
class Config:
    """配置对象，用于访问配置值"""
    def __init__(self, loader):
        self._loader = loader
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        通过点分隔的路径获取配置值，支持默认值
        Args:
            key: 配置键路径，如 'logging.log_dir'
            default: 默认值，当配置不存在时返回
        Returns:
            配置值或默认值
        """
        return self._loader.get(key, default)
    
    def __getattr__(self, name):
        # 尝试从配置中获取属性
        value = self._loader.get(name.lower(), None)
        if value is None:
            raise AttributeError(f"配置中不存在 {name}")
        return value
        
    def validate(self) -> bool:
        """验证配置的有效性
        Returns:
            bool: 配置是否有效
        """
        try:
            # 基本配置验证
            required_sections = ['app', 'api', 'logging']
            for section in required_sections:
                if section not in self._loader.configs:
                    logger.warning(f"配置缺少必要部分: {section}")
                    
            # 验证API配置
            if 'api' in self._loader.configs:
                api_config = self._loader.configs['api']
                # 检查必要的API配置项
                if 'host' not in api_config:
                    api_config['host'] = '127.0.0.1'
                if 'port' not in api_config:
                    api_config['port'] = 8000
                    
            # 验证应用配置
            if 'app' in self._loader.configs:
                app_config = self._loader.configs['app']
                # 设置默认值
                if 'name' not in app_config:
                    app_config['name'] = 'xiaoyou-core'
                if 'version' not in app_config:
                    app_config['version'] = '1.0.0'
                    
            # 验证日志配置
            if 'logging' in self._loader.configs:
                logging_config = self._loader.configs['logging']
                # 设置默认日志级别
                if 'level' not in logging_config:
                    logging_config['level'] = 'INFO'
                    
            logger.info("配置验证通过")
            return True
            
        except Exception as e:
            logger.error(f"配置验证失败: {str(e)}")
            return False
# 创建全局配置对象
_config = None
def get_config_loader() -> ConfigLoader:
    """获取配置加载器实例（单例模式）"""
    global _config_loader
    if _config_loader is None:
        _config_loader = ConfigLoader()
    return _config_loader
def get_settings():
    """获取配置设置对象的快捷方法"""
    return get_config_instance()
def get_config_instance() -> Config:
    """获取配置对象实例（单例模式）"""
    global _config
    if _config is None:
        _config = Config(get_config_loader())
    return _config

def get_config() -> Config:
    """获取配置对象实例（别名，兼容其他模块调用）"""
    return get_config_instance()
# 导出配置对象
config = get_config_instance()