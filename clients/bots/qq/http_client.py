"""HTTP 客户端、健康检查与仿生延迟配置服务。

合并自 http_client.py + health_checker.py + bionic_profile_service.py，
统一管理所有 HTTP 通信和后端服务交互。
"""
import asyncio
import logging
import os
import socket
import time
from urllib.parse import urlparse

import aiohttp

from core.utils.async_locks import LazyAsyncLock


class HttpClient:
    """HTTP 客户端，封装 HTTP 会话管理和 API 请求。"""

    def __init__(self, base_url: str, access_token: str | None = None,
                 timeout: float = 30.0, logger: logging.Logger | None = None):
        self.base_url = str(base_url or "").rstrip("/")
        self.access_token = str(access_token or "").strip()
        self.timeout = float(timeout or 30.0)
        self.logger = logger or logging.getLogger("QQAdapter")
        self._session: aiohttp.ClientSession | None = None
        self._lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）

    async def get_session(self) -> aiohttp.ClientSession:
        async with self._lock:
            if self._session and not self._session.closed:
                return self._session
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
            return self._session

    async def request(self, method: str, path: str, json_body=None,
                      params=None, timeout_seconds: float | None = None) -> tuple[int, dict]:
        method = str(method or "GET").upper().strip()
        path = str(path or "").strip()
        if not path.startswith("/"):
            path = "/" + path
        url = self.base_url + path

        session = await self.get_session()
        try:
            headers = {}
            if self.access_token:
                headers["Authorization"] = f"Bearer {self.access_token}"
            kwargs: dict = {"json": json_body, "params": params, "headers": headers}
            if timeout_seconds is not None:
                kwargs["timeout"] = aiohttp.ClientTimeout(total=max(1.0, float(timeout_seconds)))

            async with session.request(method, url, **kwargs) as resp:
                status = resp.status
                ct = str(resp.headers.get("Content-Type") or "").lower()
                if "application/json" in ct:
                    return status, await resp.json(content_type=None)
                return status, {"text": await resp.text()}
        except Exception as e:
            msg = self._format_error(e)
            self.logger.warning(f"API请求异常: {method} {url} -> {msg} ({type(e).__name__})")
            return 0, {"error": msg, "details": {"error_type": type(e).__name__}}

    @staticmethod
    def _format_error(e: Exception) -> str:
        try:
            msg = str(e or "").strip()
        except Exception:
            msg = ""
        if not msg:
            msg = "请求超时" if isinstance(e, asyncio.TimeoutError) else type(e).__name__
        return msg

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None


class HealthChecker:
    """后端健康检查器。"""

    def __init__(self, http_client: HttpClient, logger: logging.Logger | None = None):
        self.http_client = http_client
        self.logger = logger or logging.getLogger("QQAdapter")

    async def preflight_check(self, *, config_file: str, napcat_ws_url: str,
                              xiaoyou_ws_url: str, xiaoyou_http_base_url: str) -> bool:
        self.logger.info(f"QQ Adapter config: {config_file} (exists={os.path.exists(config_file)})")
        self.logger.info(f"NapCat WS: {napcat_ws_url}")
        self.logger.info(f"Xiaoyou WS: {xiaoyou_ws_url}")
        self.logger.info(f"Xiaoyou HTTP: {xiaoyou_http_base_url}")
        if not str(xiaoyou_http_base_url or "").strip():
            return False
        if await self.check_backend_health():
            return True
        if await self.check_backend_tcp(xiaoyou_http_base_url, xiaoyou_ws_url):
            self.logger.info("Backend TCP probe OK，健康接口可能较慢、未就绪或路径不匹配")
            return True
        return False

    async def check_backend_health(self) -> bool:
        candidate_paths = ("/api/v1/health", "/health")
        for path in candidate_paths:
            try:
                status, data = await self.http_client.request("GET", path, timeout_seconds=2.0)
                if status != 200:
                    self.logger.warning(f"Backend health check not OK via {path}: {status}")
                    continue
                status_value = data.get("status") if isinstance(data, dict) else None
                self.logger.info(f"Backend health OK via {path} (status={status_value})")
                return True
            except Exception as e:
                self.logger.warning(f"Backend health check failed via {path}: {e}")
        return False

    async def check_backend_tcp(self, *urls: str) -> bool:
        checked_targets = set()
        for raw_url in urls:
            host, port = self._extract_host_port(raw_url)
            if not host or not port:
                continue
            target = (host, port)
            if target in checked_targets:
                continue
            checked_targets.add(target)
            ok = await asyncio.to_thread(self._probe_tcp_port, host, port, 1.0)
            if ok:
                self.logger.info(f"Backend TCP probe OK: {host}:{port}")
                return True
            self.logger.warning(f"Backend TCP probe failed: {host}:{port}")
        return False

    @staticmethod
    def _extract_host_port(raw_url: str) -> tuple[str, int]:
        try:
            parsed = urlparse(str(raw_url or "").strip())
        except Exception:
            return "", 0
        host = str(parsed.hostname or "").strip()
        if not host:
            return "", 0
        if parsed.port:
            return host, int(parsed.port)
        if parsed.scheme == "https" or parsed.scheme == "wss":
            return host, 443
        return host, 80

    @staticmethod
    def _probe_tcp_port(host: str, port: int, timeout_seconds: float) -> bool:
        try:
            with socket.create_connection((host, int(port)), timeout=max(0.2, float(timeout_seconds))):
                return True
        except Exception:
            return False


class BionicProfileService:
    """仿生延迟配置服务，带 TTL 缓存。"""

    def __init__(self, http_client: HttpClient, cfg, logger):
        self.http_client = http_client
        self.cfg = cfg
        self.logger = logger
        self._cache: dict = {}

    async def get_profile(self, session_id: str, force_refresh: bool = False) -> dict:
        if not self.cfg.qq_typing_delay_use_bionic_profile:
            return {}
        sid = str(session_id or "default_user").strip() or "default_user"
        now = time.time()
        ttl = max(30, int(self.cfg.qq_typing_delay_bionic_profile_ttl_seconds or 180))
        cache_item = self._cache.get(sid) or {}
        cached = cache_item.get("profile")
        if not force_refresh and cached and float(cache_item.get("expire_ts") or 0) > now:
            return cached

        status, data = await self.http_client.request(
            "GET", "/api/v1/diary/bionic-delay/profile",
            params={"session_id": sid, "refresh": "true" if force_refresh else "false"},
            timeout_seconds=4.0,
        )
        if status != 200 or not isinstance(data, dict) or not bool(data.get("success", False)):
            return cached or {}
        payload = data.get("data")
        profile = payload.get("profile") if isinstance(payload, dict) else None
        if not isinstance(profile, dict):
            return cached or {}
        self._cache[sid] = {"profile": profile, "expire_ts": now + ttl}
        return profile
