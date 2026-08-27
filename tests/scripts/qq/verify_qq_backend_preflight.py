#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 QQ adapter 后端探活的路径与 TCP 兜底逻辑。"""

from __future__ import annotations

import asyncio
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from clients.bots.qq.http_client import HealthChecker


class _FakeHttpClient:
    def __init__(self, responses: dict[str, tuple[int, dict]]):
        self.responses = responses
        self.requests: list[str] = []

    async def request(self, method, path, json_body=None, params=None, timeout_seconds=None):
        self.requests.append(path)
        return self.responses.get(path, (404, {"error": "not found"}))


class _FakeLogger:
    def __init__(self):
        self.messages: list[tuple[str, str]] = []

    def info(self, message: str):
        self.messages.append(("info", message))

    def warning(self, message: str):
        self.messages.append(("warning", message))


async def main() -> int:
    logger = _FakeLogger()
    client = _FakeHttpClient(
        {
            "/api/v1/health": (0, {"error": "timeout"}),
            "/health": (404, {"error": "not found"}),
        }
    )
    checker = HealthChecker(client, logger=logger)
    checker._probe_tcp_port = lambda host, port, timeout: host == "127.0.0.1" and port == 8000

    ok = await checker.preflight_check(
        config_file="d:/AI/xiaoyou-core/clients/bots/config/config.json",
        napcat_ws_url="ws://127.0.0.1:3001",
        xiaoyou_ws_url="ws://127.0.0.1:8000/api/v1/ws",
        xiaoyou_http_base_url="http://127.0.0.1:8000",
    )

    print("=== QQ 后端探活验证 ===")
    print(f"探活结果: {ok}")
    print(f"尝试过的健康路径: {client.requests}")

    if client.requests[:2] != ["/api/v1/health", "/health"]:
        print("验证失败：健康检查路径顺序不正确。")
        return 1
    if not ok:
        print("验证失败：TCP 兜底探测未生效。")
        return 1

    print("验证通过：优先检查 /api/v1/health，失败后可回退并使用 TCP 探测兜底。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
