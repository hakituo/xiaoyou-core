#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模型切换与会话级模型锁同步回归测试。

背景：
- 移动端 WebSocket 连接上的 forced_model_preference 优先级最高（会话级锁定）；
- 全局切换模型（POST /models/switch）后若不同步该锁，旧锁定会把切换盖回旧模型；
- HybridLLMModule.reload() 若只读配置文件的 default_chat_model，
  会把 /models/switch 刚写入 settings.model.llm.model 的运行时模型盖回默认值。
"""

import asyncio
from types import SimpleNamespace


def _make_settings(provider: str = "deepseek", model: str = "deepseek-v4-pro"):
    return SimpleNamespace(
        model=SimpleNamespace(
            llm=SimpleNamespace(provider=provider, model=model),
            text_path="",
            persona_model_map={},
            llm_preload_on_startup=False,
        )
    )


class _FakeLLMModule:
    def __init__(self):
        self.reloaded = False
        self.unloaded = False

    async def unload_model(self):
        self.unloaded = True

    async def reload(self):
        self.reloaded = True


class _FakeWs:
    """可哈希的假 WebSocket 连接对象。"""

    def __init__(self, pref=None):
        if pref is not None:
            self.forced_model_preference = pref


class _FakeWsManager:
    def __init__(self, connections):
        self.connections = connections
        self.broadcasts = []

    async def broadcast(self, data):
        self.broadcasts.append(data)


def test_hybrid_llm_reload_prefers_runtime_switched_model(monkeypatch):
    """reload 应优先使用运行时已切换的模型，而不是配置文件默认值。"""
    import config.integrated_config as integrated_config
    import config.model_config as model_config
    from core.llm import HybridLLMModule

    settings = _make_settings()
    monkeypatch.setattr(integrated_config, "get_settings", lambda: settings)
    monkeypatch.setattr(
        model_config,
        "get_default_chat_model",
        lambda *args, **kwargs: "cloud:deepseek:ling:deepseek-v4-flash",
    )

    module = HybridLLMModule(
        local_module=None,
        cloud_module=SimpleNamespace(),
        preload_local=False,
        default_provider="deepseek",
    )
    asyncio.run(module.reload())

    assert module.default_provider == "deepseek"
    assert module.default_model_name == "deepseek-v4-pro"


def test_switch_model_syncs_session_locks_and_broadcasts(monkeypatch):
    """/models/switch 成功后应同步所有带会话锁的连接并广播 model_update。"""
    import core.core_engine.model_manager as model_manager_module
    import core.llm as llm_package
    import core.interfaces.websocket.websocket_manager as wsm_module
    import routers.v1.models as models_router

    pro_entry = SimpleNamespace(
        model_path="cloud:deepseek:rushuang:deepseek-v4-pro"
    )
    fake_model_manager = SimpleNamespace(
        _models={"deepseek-v4-pro": pro_entry}
    )
    fake_llm = _FakeLLMModule()

    # 连接 A：带旧的会话级锁（flash），应被同步为 pro
    ws_locked = _FakeWs(
        pref="cloud:deepseek:rushuang:deepseek-v4-flash"
    )
    # 连接 B：无会话锁，不应被新增锁
    ws_unlocked = _FakeWs()
    fake_ws_manager = _FakeWsManager(
        {ws_locked: SimpleNamespace(), ws_unlocked: SimpleNamespace()}
    )

    monkeypatch.setattr(
        models_router, "get_settings", lambda: _make_settings()
    )
    monkeypatch.setattr(
        model_manager_module, "get_model_manager", lambda: fake_model_manager
    )
    monkeypatch.setattr(llm_package, "get_llm_module", lambda: fake_llm)
    monkeypatch.setattr(
        wsm_module, "get_websocket_manager", lambda: fake_ws_manager
    )

    request = models_router.SwitchModelRequest(
        model_name="deepseek-v4-pro", provider="deepseek"
    )
    result = asyncio.run(models_router.switch_model(request))

    assert result["success"] is True
    assert fake_llm.reloaded is True
    assert fake_llm.unloaded is True

    # 旧锁被同步为目标模型完整路由
    assert (
        ws_locked.forced_model_preference
        == "cloud:deepseek:rushuang:deepseek-v4-pro"
    )
    # 无锁连接不会被追加锁
    assert not hasattr(ws_unlocked, "forced_model_preference")

    # 广播 model_update，让客户端同步 UI
    assert fake_ws_manager.broadcasts
    update = fake_ws_manager.broadcasts[0]
    assert update["type"] == "model_update"
    assert update["data"]["provider"] == "deepseek"
    assert update["data"]["model"] == "deepseek-v4-pro"
    assert (
        update["data"]["path"] == "cloud:deepseek:rushuang:deepseek-v4-pro"
    )
