"""memory/core/async_persistence.py 单元测试。

该模块只是 ``core.utils.atomic_io`` 的异步薄封装（保留用于向后兼容）。
因此测试分两层：
1. **委托契约**：参数必须原样透传（尤其是默认 encoding="utf-8"），用假函数记录调用；
2. **真实往返**：不 mock，走真实 atomic_io 落盘再读回，证明这条委托链真的能工作。
"""

from __future__ import annotations

import asyncio
import json

from memory.core import async_persistence


class TestDumpDelegation:
    """async_safe_json_dump 的参数透传。"""

    def test_delegates_all_positional_args(self, monkeypatch):
        calls = []

        async def _fake_dump(data, file_path, encoding):
            calls.append((data, file_path, encoding))

        monkeypatch.setattr(async_persistence, "_async_safe_json_dump", _fake_dump)
        asyncio.run(async_persistence.async_safe_json_dump({"a": 1}, "x.json", "gbk"))
        assert calls == [({"a": 1}, "x.json", "gbk")]

    def test_default_encoding_is_utf8(self, monkeypatch):
        calls = []

        async def _fake_dump(data, file_path, encoding):
            calls.append(encoding)

        monkeypatch.setattr(async_persistence, "_async_safe_json_dump", _fake_dump)
        asyncio.run(async_persistence.async_safe_json_dump({"a": 1}, "x.json"))
        assert calls == ["utf-8"]

    def test_accepts_path_object(self, monkeypatch, tmp_path):
        calls = []

        async def _fake_dump(data, file_path, encoding):
            calls.append(file_path)

        monkeypatch.setattr(async_persistence, "_async_safe_json_dump", _fake_dump)
        target = tmp_path / "p.json"
        asyncio.run(async_persistence.async_safe_json_dump([], target))
        assert calls == [target]

    def test_returns_none(self, monkeypatch):
        async def _fake_dump(data, file_path, encoding):
            return "ignored"

        monkeypatch.setattr(async_persistence, "_async_safe_json_dump", _fake_dump)
        assert asyncio.run(async_persistence.async_safe_json_dump({}, "x.json")) is None


class TestLoadDelegation:
    """async_safe_json_load 的参数透传与返回值透传。"""

    def test_delegates_all_args_and_returns_value(self, monkeypatch):
        calls = []

        async def _fake_load(file_path, encoding, default):
            calls.append((file_path, encoding, default))
            return {"k": "v"}

        monkeypatch.setattr(async_persistence, "_async_safe_json_load", _fake_load)
        result = asyncio.run(async_persistence.async_safe_json_load("x.json"))
        assert result == {"k": "v"}
        assert calls == [("x.json", "utf-8", None)]

    def test_passes_custom_encoding_and_default(self, monkeypatch):
        calls = []

        async def _fake_load(file_path, encoding, default):
            calls.append((encoding, default))
            return default

        monkeypatch.setattr(async_persistence, "_async_safe_json_load", _fake_load)
        sentinel = {"fallback": True}
        result = asyncio.run(
            async_persistence.async_safe_json_load("x.json", "gbk", sentinel)
        )
        assert result is sentinel
        assert calls == [("gbk", sentinel)]


class TestRealRoundTrip:
    """不 mock：走真实 atomic_io，验证委托链路端到端可用。"""

    def test_dump_then_load(self, tmp_path):
        path = tmp_path / "data.json"
        payload = {"角色": "Ye", "n": 3, "list": [1, 2]}
        asyncio.run(async_persistence.async_safe_json_dump(payload, path))
        assert json.loads(path.read_text(encoding="utf-8")) == payload
        assert asyncio.run(async_persistence.async_safe_json_load(path)) == payload

    def test_dump_creates_missing_parent_dirs(self, tmp_path):
        path = tmp_path / "nested" / "deeper" / "data.json"
        asyncio.run(async_persistence.async_safe_json_dump({"ok": True}, path))
        assert path.exists()
        assert asyncio.run(async_persistence.async_safe_json_load(path)) == {"ok": True}

    def test_load_missing_file_returns_default(self, tmp_path):
        missing = tmp_path / "does_not_exist.json"
        assert (
            asyncio.run(
                async_persistence.async_safe_json_load(
                    missing, default={"fallback": True}
                )
            )
            == {"fallback": True}
        )

    def test_load_missing_file_without_default_returns_none(self, tmp_path):
        missing = tmp_path / "does_not_exist.json"
        assert asyncio.run(async_persistence.async_safe_json_load(missing)) is None

    def test_load_corrupt_file_returns_default(self, tmp_path):
        broken = tmp_path / "broken.json"
        broken.write_text("{not valid json", encoding="utf-8")
        assert (
            asyncio.run(
                async_persistence.async_safe_json_load(broken, default="fallback")
            )
            == "fallback"
        )

    def test_dump_overwrites_existing_file(self, tmp_path):
        path = tmp_path / "data.json"
        asyncio.run(async_persistence.async_safe_json_dump({"v": 1}, path))
        asyncio.run(async_persistence.async_safe_json_dump({"v": 2}, path))
        assert asyncio.run(async_persistence.async_safe_json_load(path)) == {"v": 2}
