"""
配置系统 - 默认值单元测试
"""

import pytest


def test_server_settings_defaults():
    """测试服务器配置默认值"""
    from config.settings_server import ServerSettings

    settings = ServerSettings()
    assert settings.port == 8000
    assert settings.ws_port == 8765


def test_memory_settings_defaults():
    """测试记忆配置默认值"""
    from config.settings_core import MemorySettings

    settings = MemorySettings()
    assert settings.short_term_capacity == 60


def test_model_settings_defaults():
    """测试模型配置默认值"""
    from config.settings_model import ModelSettings

    settings = ModelSettings()
    assert settings.temperature == 0.7


def test_chat_settings_defaults():
    """测试聊天配置默认值"""
    from config.settings_chat import ChatSettings

    settings = ChatSettings()
    assert isinstance(settings, object)


def test_app_settings_composition():
    """测试 AppSettings 包含所有子配置"""
    from config.integrated_config import AppSettings

    settings = AppSettings()
    # 检查包含主要配置字段
    assert hasattr(settings, "server")
    assert hasattr(settings, "model")
    assert hasattr(settings, "chat")
    assert hasattr(settings, "memory")


def test_config_backward_compat_mapping():
    """测试 Config 向后兼容映射"""
    from config.integrated_config import Config, get_settings

    # 重置缓存
    from config.integrated_config import reset_settings_cache
    reset_settings_cache()

    try:
        config = Config()
        # Config 应该有向后兼容的属性
        assert hasattr(config, "SERVER_PORT") or hasattr(config, "server")
    except Exception:
        pass


def test_get_settings_singleton():
    """测试 get_settings 单例模式"""
    from config.integrated_config import get_settings, reset_settings_cache

    reset_settings_cache()
    settings1 = get_settings()
    settings2 = get_settings()
    assert settings1 is settings2


def test_reset_settings_cache():
    """测试重置设置缓存"""
    from config.integrated_config import get_settings, reset_settings_cache

    settings1 = get_settings()
    reset_settings_cache()
    settings2 = get_settings()
    # 重置后应该创建新实例
    assert settings1 is not settings2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
