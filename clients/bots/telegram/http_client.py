"""Telegram 适配器 HTTP 客户端。

参照 QQ 适配器的 HttpClient 设计，复用 HTTP 会话、统一错误处理。
负责与后端 REST API 通信（健康检查、视觉、语音识别等）。
"""
import asyncio
import logging
import socket
from urllib.parse import urlparse

import aiohttp

from core.utils.async_locks import LazyAsyncLock


class HttpClient:
    """HTTP 客户端，封装 HTTP 会话管理和 API 请求。"""

    def __init__(self, base_url: str, access_token: str | None = None,
                 timeout: float = 60.0, logger: logging.Logger | None = None):
        self.base_url = str(base_url or "").rstrip("/")
        self.access_token = str(access_token or "").strip()
        self.timeout = float(timeout or 60.0)
        self.logger = logger or logging.getLogger("TelegramAdapter")
        self._session: aiohttp.ClientSession | None = None
        self._lock = LazyAsyncLock()

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

    async def download_file(self, url: str, timeout_seconds: float = 30.0) -> bytes:
        """下载文件（Telegram 文件 URL）。"""
        session = await self.get_session()
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout_seconds)) as resp:
                if resp.status == 200:
                    return await resp.read()
                self.logger.warning(f"下载文件失败: {url} -> HTTP {resp.status}")
                return b""
        except Exception as e:
            self.logger.warning(f"下载文件异常: {url} -> {e}")
            return b""

    async def upload_file(self, path: str, file_data: bytes, filename: str = "audio.ogg",
                          fields: dict | None = None, timeout_seconds: float = 60.0) -> tuple[int, dict]:
        """上传文件到后端（multipart/form-data）。"""
        url = self.base_url + (path if path.startswith("/") else "/" + path)
        session = await self.get_session()
        try:
            headers = {}
            if self.access_token:
                headers["Authorization"] = f"Bearer {self.access_token}"

            form = aiohttp.FormData()
            form.add_field("file", file_data, filename=filename, content_type="application/octet-stream")
            if fields:
                for k, v in fields.items():
                    form.add_field(k, str(v))

            async with session.post(url, data=form, headers=headers,
                                    timeout=aiohttp.ClientTimeout(total=timeout_seconds)) as resp:
                status = resp.status
                ct = str(resp.headers.get("Content-Type") or "").lower()
                if "application/json" in ct:
                    return status, await resp.json(content_type=None)
                return status, {"text": await resp.text()}
        except Exception as e:
            msg = self._format_error(e)
            self.logger.warning(f"上传文件异常: {url} -> {msg}")
            return 0, {"error": msg}

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
        self.logger = logger or logging.getLogger("TelegramAdapter")

    async def prelight_check(self, http_base_url: str, ws_url: str) -> bool:
        self.logger.info(f"Telegram Adapter HTTP: {http_base_url}")
        self.logger.info(f"Telegram Adapter WS: {ws_url}")
        if not str(http_base_url or "").strip():
            return False
        if await self._check_health():
            return True
        if await self._check_tcp(ws_url, http_base_url):
            self.logger.info("后端 TCP 探测成功，健康接口可能尚未就绪")
            return True
        return False

    async def _check_health(self) -> bool:
        for path in ("/api/v1/health", "/health"):
            try:
                status, data = await self.http_client.request("GET", path, timeout_seconds=2.0)
                if status == 200:
                    self.logger.info(f"后端健康检查通过: {path}")
                    return True
                self.logger.warning(f"后端健康检查失败: {path} -> HTTP {status}")
            except Exception as e:
                self.logger.warning(f"后端健康检查异常: {path} -> {e}")
        return False

    async def _check_tcp(self, *urls: str) -> bool:
        checked = set()
        for raw_url in urls:
            host, port = self._extract_host_port(raw_url)
            if not host or not port or (host, port) in checked:
                continue
            checked.add((host, port))
            ok = await asyncio.to_thread(self._probe_tcp, host, port, 1.0)
            if ok:
                self.logger.info(f"后端 TCP 探测成功: {host}:{port}")
                return True
            self.logger.warning(f"后端 TCP 探测失败: {host}:{port}")
        return False

    @staticmethod
    def _extract_host_port(raw_url: str) -> tuple[str, int]:
        try:
            p = urlparse(str(raw_url or "").strip())
        except Exception:
            return "", 0
        host = str(p.hostname or "").strip()
        if not host:
            return "", 0
        if p.port:
            return host, int(p.port)
        if p.scheme in ("https", "wss"):
            return host, 443
        return host, 80

    @staticmethod
    def _probe_tcp(host: str, port: int, timeout: float) -> bool:
        try:
            with socket.create_connection((host, int(port)), timeout=max(0.2, float(timeout))):
                return True
        except Exception:
            return False
