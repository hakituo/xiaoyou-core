# -*- coding: utf-8 -*-
"""OpenAI 兼容层的 cloud 模型路径解析回归测试。

被测函数：``routers.openai_compat._extract_cloud_model_id``

背景：模型路径存在两种格式，解析时必须都支持——

- 传统格式（3 段）：``cloud:<provider>:<model>`` → ``<model>``
- 多 API key 格式（4 段及以上）：``cloud:<provider>:<key_alias>:<model>`` → 从第 4 段起整段作为模型名

历史坑：早期实现用 ``split(":", 2)``，会把 ``qqbot1`` 当成模型名的前缀，
导致 ``cloud:deepseek:qqbot1:deepseek-v4-pro`` 解析出错误的模型名。
本测试直接锁定该函数行为，避免后续改动再次退化。

替代说明：原 ``tests/scripts/test_model_path_fix.py`` 只是把解析逻辑复制到测试里自证，
既没有引用被测代码也没有断言，已删除。
"""
from __future__ import annotations

import pytest

from routers.openai_compat import _extract_cloud_model_id


@pytest.mark.parametrize(
    ("model_path", "expected_model_id"),
    [
        # 传统格式（3 段）
        ("cloud:deepseek:deepseek-v4-pro", "deepseek-v4-pro"),
        ("cloud:deepseek:deepseek-v4-flash", "deepseek-v4-flash"),
        (
            "cloud:siliconflow:Qwen/Qwen3-VL-235B-A22B-Thinking",
            "Qwen/Qwen3-VL-235B-A22B-Thinking",
        ),
        # 多 API key 格式（4 段）
        ("cloud:deepseek:qqbot1:deepseek-v4-pro", "deepseek-v4-pro"),
        ("cloud:deepseek:qqbot2:deepseek-v4-flash", "deepseek-v4-flash"),
        # 模型名本身含冒号：必须完整保留，不能只取最后一段
        ("cloud:someprovider:some:model", "model"),
        (
            "cloud:provider:key_alias:family:variant:thinking",
            "family:variant:thinking",
        ),
    ],
)
def test_extract_cloud_model_id_supported_formats(model_path: str, expected_model_id: str):
    """3 段与 4 段以上的路径都要提取出正确的模型名。"""
    assert _extract_cloud_model_id(model_path) == expected_model_id


@pytest.mark.parametrize(
    ("model_path", "expected"),
    [
        ("", ""),
        ("cloud:deepseek", "cloud:deepseek"),  # 段数不足，原样返回
        ("cloud:", "cloud:"),
        ("gpt-4o", "gpt-4o"),  # 非 cloud: 前缀，原样返回
    ],
)
def test_extract_cloud_model_id_fallback_keeps_input(model_path: str, expected: str):
    """不满足解析条件时原样返回：不抛异常、不截断。"""
    assert _extract_cloud_model_id(model_path) == expected


def test_extract_cloud_model_id_tolerates_none():
    """入参为 None 时按空串处理（端点可能直接透传可选字段）。"""
    assert _extract_cloud_model_id(None) == ""
