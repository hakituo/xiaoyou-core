"""
API调用监控模块（兼容层）

所有逻辑已迁移到 core.llm.llm_logger，此文件保留为向后兼容的代理。
"""

from core.llm.llm_logger import get_api_call_count, log_api_call

__all__ = ["get_api_call_count", "log_api_call"]
