#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 客户端公共 session 管理

- LLMSessionMixin：常驻 session 的创建 / 关闭与基础状态报告
- request_session：按「本次请求的 api_key 是否等于客户端默认 key」决定
  复用常驻 session 还是建临时 session，流式与非流式走同一条路径
"""

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, Optional

import aiohttp

from core.contracts import ModuleInitState


def create_session(
    api_key: Optional[str],
    timeout: Any,
    proxy: Optional[str] = None,
) -> aiohttp.ClientSession:
    """统一构造 aiohttp session：主 / VL / 临时 session 共用同一套头与超时"""
    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        proxy=proxy,
    )


class LLMSessionMixin:
    """LLM 客户端公共 session 管理和状态报告混入类"""

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = create_session(
                self.api_key, self.timeout, getattr(self, "proxy", None)
            )
        return self.session

    async def _close_session(self):
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None
        if self._vision_session and self._vision_session.closed is False:
            await self._vision_session.close()
            self._vision_session = None

    async def shutdown(self):
        await self._close_session()

    def _build_base_status(self, provider: str = "", **extra) -> Dict[str, Any]:
        init_state = (
            ModuleInitState.INITIALIZED
            if bool(self.initialized)
            else ModuleInitState.NOT_INITIALIZED
        )
        status = {
            "status": init_state.value,
            "init_state": init_state.value,
            "api_key_configured": bool(self.api_key),
            "session_active": self.session is not None and not self.session.closed,
            "model": self.default_model,
        }
        if provider:
            status["provider"] = provider
        if getattr(self, "base_url", None):
            status["base_url"] = self.base_url
        status.update(extra)
        return status


@asynccontextmanager
async def request_session(
    client: Any,
    api_key: Optional[str] = None,
) -> AsyncIterator[aiohttp.ClientSession]:
    """取得本次请求使用的 session。

    api_key 为空或等于 client.api_key 时复用常驻 session：aiohttp 连接池会自行
    丢弃坏连接并在下次请求时重建，关闭整个 session 会丢掉 TCP/TLS，徒增 200-800ms。

    动态 key（与 client.api_key 不同）时建临时 session，请求结束后关闭——
    常驻 session 的 Authorization 头是建 session 时定死的，不能拿来发别的 key。
    """
    if api_key and api_key != getattr(client, "api_key", None):
        session = create_session(
            api_key,
            getattr(client, "timeout", 180),
            getattr(client, "proxy", None),
        )
        try:
            yield session
        finally:
            if not session.closed:
                await session.close()
    else:
        yield await client._get_session()
