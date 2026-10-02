"""守卫「普通聊天 -> TeachingOrchestrator」这条主 runtime 线。

这个缺口一旦复发，症状是**学习系统静默失灵**：普通聊天里的提问、没听懂、
自称掌握都不会落库，而界面上看不出任何异常——只有知识点永远停在 unknown。

生产主对话走的是流式（stream_chat），非流式是另一条入口。
两条都必须接 observe_learning_message，否则等于半个系统不工作。
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 两条入口各自调用 observe_learning_message 的位置
WIRED_SITES = (
    PROJECT_ROOT / "core/agents/chat_agent_components/handler.py",
    PROJECT_ROOT
    / "core/agents/chat_agent_components/streaming_pipeline/preparation.py",
)


def _calls_observe(path: Path) -> bool:
    """用 AST 检查源码里是否真的把 observe_learning_message 用起来了。

    不用字符串匹配：注释或文档里出现同名不该算接通。
    同时要覆盖「作为传参被调用」的写法——实际调用形式是
    ``await asyncio.to_thread(observe_learning_message, message)``，
    函数名出现在 args 里而不是 func 上。
    """
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if getattr(func, "id", None) == "observe_learning_message":
            return True
        if getattr(func, "attr", None) == "observe_learning_message":
            return True
        for arg in node.args:
            if isinstance(arg, ast.Name) and arg.id == "observe_learning_message":
                return True
    return False


@pytest.mark.parametrize("path", WIRED_SITES, ids=lambda p: p.name)
def test_chat_entry_observes_learning(path: Path):
    assert path.exists(), f"入口文件不存在，链路可能已被重构: {path}"
    assert _calls_observe(path), (
        f"{path.name} 没有调用 observe_learning_message。"
        "普通聊天的学习证据不会进入学习系统，且不会报错——症状是学习状态静默失灵。"
    )


def test_both_streaming_and_blocking_paths_are_wired():
    """流式和阻塞两条入口都要接，只接一条等于只覆盖一半场景。"""
    assert len(WIRED_SITES) == 2
    assert all(_calls_observe(p) for p in WIRED_SITES)


def test_observe_delegates_to_orchestrator():
    """确认入口最终走到 TeachingOrchestrator，而不是空壳。"""
    from core.agents.chat_agent_components.study import observe_learning_message

    source = inspect.getsource(observe_learning_message)
    assert "TeachingOrchestrator" in source or "observe_message" in source
