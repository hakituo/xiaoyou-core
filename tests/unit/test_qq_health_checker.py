#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QQ adapter 后端探活回归测试。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from clients.bots.qq.http_client import HealthChecker


class _FakeHttpClient:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    async def request(self, method, path, json_body=None, params=None, timeout_seconds=None):
        self.requests.append((method, path, timeout_seconds))
        return self.responses.get(path, (404, {"error": "not found"}))


class _FakeLogger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def warning(self, message):
        self.messages.append(("warning", message))


class TestQQHealthChecker(unittest.IsolatedAsyncioTestCase):
    async def test_prefers_api_v1_health(self):
        client = _FakeHttpClient(
            {
                "/api/v1/health": (200, {"status": "ok"}),
            }
        )
        checker = HealthChecker(client, logger=_FakeLogger())

        ok = await checker.check_backend_health()

        self.assertTrue(ok)
        self.assertEqual(client.requests[0][1], "/api/v1/health")

    async def test_falls_back_to_legacy_health_path(self):
        client = _FakeHttpClient(
            {
                "/api/v1/health": (404, {"error": "not found"}),
                "/health": (200, {"status": "ok"}),
            }
        )
        checker = HealthChecker(client, logger=_FakeLogger())

        ok = await checker.check_backend_health()

        self.assertTrue(ok)
        self.assertEqual(
            [path for _method, path, _timeout in client.requests],
            ["/api/v1/health", "/health"],
        )

    async def test_preflight_uses_tcp_probe_when_health_endpoint_fails(self):
        client = _FakeHttpClient(
            {
                "/api/v1/health": (0, {"error": "timeout"}),
                "/health": (404, {"error": "not found"}),
            }
        )
        logger = _FakeLogger()
        checker = HealthChecker(client, logger=logger)
        checker._probe_tcp_port = lambda host, port, timeout: host == "127.0.0.1" and port == 8000

        ok = await checker.preflight_check(
            config_file="d:/AI/xiaoyou-core/clients/bots/config/config.json",
            napcat_ws_url="ws://127.0.0.1:3001",
            xiaoyou_ws_url="ws://127.0.0.1:8000/api/v1/ws",
            xiaoyou_http_base_url="http://127.0.0.1:8000",
        )

        self.assertTrue(ok)
        self.assertTrue(
            any("TCP probe OK" in msg for _level, msg in logger.messages),
            "健康接口失败后应记录 TCP 探测成功日志",
        )


if __name__ == "__main__":
    unittest.main()
