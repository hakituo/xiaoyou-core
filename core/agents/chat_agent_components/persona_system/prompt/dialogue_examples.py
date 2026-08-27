"""对话示例选择（公开仓库占位版）。

说明：私有版本基于真实对话语料做示例检索与风格抽取；公开仓库不含
语料数据，仅保留接口签名占位，保证导入链完整。
"""

from typing import Any, List


def get_dialogue_examples(*args: Any, **kwargs: Any) -> str:
    """获取对话示例注入文本（占位：公开仓库无语料，返回空串）。"""
    return ""


def tokenize_for_example_rank(text: str) -> List[str]:
    """示例排序用分词（占位实现：按空白切分）。"""
    return str(text or "").split()


def has_real_chat_corpus(*args: Any, **kwargs: Any) -> bool:
    """是否存在真实对话语料（占位：恒为 False）。"""
    return False


def select_real_chat_examples(*args: Any, **kwargs: Any) -> List[Any]:
    """选取真实对话示例（占位：返回空列表）。"""
    return []


def _load_real_chat_cache(*args: Any, **kwargs: Any) -> Any:
    """加载真实对话缓存（占位：返回空字典）。"""
    return {}


def _select_examples(*args: Any, **kwargs: Any) -> List[Any]:
    """内部示例选择（占位：返回空列表）。"""
    return []


def _get_style_retriever(*args: Any, **kwargs: Any) -> Any:
    """获取风格检索器（占位：返回 None）。"""
    return None
