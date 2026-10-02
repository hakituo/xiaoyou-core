"""验证 executor.py 与 peer_script_generator.py 解耦是否成功。

校验点：
1. 6 个新子模块可独立 import 且类存在：
   - core/overlap_guard.py        OverlapGuard
   - core/morning_pending.py      MorningPendingInjector
   - postprocess/send_content_corrector.py  SendContentCorrector
   - peer_chat/peer_config_loader.py        PeerConfigLoader
   - peer_chat/peer_context.py              PeerContextGatherer
   - peer_chat/peer_script_llm.py           PeerScriptLLMGenerator
2. executor 委托链路：_check_overlap_guard -> _overlap_guard.check；
   _last_trigger_ts_by_persona 与 overlap_guard 共享同一 dict。
3. PeerScriptGenerator 委托链路：_load_peer_config / _gather_peer_context /
   _generate_script_llm 分别委托到对应子模块。
4. 关键私有方法保留（外部 evaluate_ling_peer_chat.py 依赖）。

全部通过返回 0，否则非 0。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "venv_core" / "Lib" / "site-packages"))

FAILURES: list[str] = []


def _fail(msg: str) -> None:
    FAILURES.append(msg)
    sys.stderr.write(f"FAIL: {msg}\n")
    sys.stderr.flush()


def check_new_modules() -> None:
    """1. 新子模块可 import 且类存在"""
    cases = [
        ("core/services/active_care/core/overlap_guard.py", "OverlapGuard"),
        ("core/services/active_care/core/morning_pending.py", "MorningPendingInjector"),
        ("core/services/active_care/postprocess/send_content_corrector.py", "SendContentCorrector"),
        ("core/services/active_care/peer_chat/peer_config_loader.py", "PeerConfigLoader"),
        ("core/services/active_care/peer_chat/peer_context.py", "PeerContextGatherer"),
        ("core/services/active_care/peer_chat/peer_script_llm.py", "PeerScriptLLMGenerator"),
    ]
    for module_path, cls_name in cases:
        rel = Path(module_path).with_suffix("")
        dotted = ".".join(rel.parts)
        try:
            mod = __import__(dotted, fromlist=[cls_name])
            if not hasattr(mod, cls_name):
                _fail(f"{dotted} 缺少类 {cls_name}")
        except Exception as e:  # noqa: BLE001
            _fail(f"导入 {dotted} 失败: {e}")


def check_executor_delegation() -> None:
    """2. executor 委托链路与共享数据字典"""
    try:
        from core.services.active_care.core.executor import ActiveCareExecutor

        storage = mock.MagicMock()
        context = mock.MagicMock()
        exec_ = ActiveCareExecutor(context, storage)

        # _check_overlap_guard 委托到 _overlap_guard.check
        with mock.patch.object(exec_._overlap_guard, "check", return_value=True) as m:
            result = exec_._check_overlap_guard("startup", 100.0, "persona_x")
            if result is not True:
                _fail("executor._check_overlap_guard 未委托给 OverlapGuard.check")
            else:
                m.assert_called_once_with("startup", 100.0, "persona_x")

        # _last_trigger_ts_by_persona 共享同一 dict（外部 service/delayed_task 兼容）
        if exec_._last_trigger_ts_by_persona is not exec_._overlap_guard._last_trigger_ts_by_persona:
            _fail("executor._last_trigger_ts_by_persona 与 overlap_guard 未共享字典")

        # 新子模块已挂载
        for attr in ("_overlap_guard", "_morning_pending", "_content_corrector"):
            if not hasattr(exec_, attr):
                _fail(f"executor 缺少子模块属性 {attr}")
    except Exception as e:  # noqa: BLE001
        _fail(f"executor 委托校验异常: {e}")


def check_peer_generator_delegation() -> None:
    """3. PeerScriptGenerator 委托链路"""
    try:
        from core.services.active_care.peer_chat.peer_script_generator import (
            PeerScriptGenerator,
        )

        host = SimpleNamespace(
            settings=mock.MagicMock(),
            context=mock.MagicMock(),
            _extract_text_from_llm_response=lambda raw: raw,
        )
        gen = PeerScriptGenerator(host)

        # 子模块已挂载
        for attr in ("_config_loader", "_context_gatherer", "_script_llm"):
            if not hasattr(gen, attr):
                _fail(f"PeerScriptGenerator 缺少子模块属性 {attr}")

        # _load_peer_config -> _config_loader.load
        with mock.patch.object(gen._config_loader, "load", return_value={"k": 1}) as m:
            cfg = gen._load_peer_config("role_a", "role_b")
            if cfg != {"k": 1}:
                _fail("_load_peer_config 未委托给 PeerConfigLoader.load")
            else:
                m.assert_called_once_with("role_a", "role_b")

        # _gather_peer_context -> _context_gatherer.gather
        async def fake_gather(role_id, peer_role_id, cfg):
            return {"ctx": True}

        with mock.patch.object(gen._context_gatherer, "gather", side_effect=fake_gather) as m:
            ctx = asyncio.get_event_loop().run_until_complete(
                gen._gather_peer_context("role_a", "role_b", {"k": 1})
            )
            if ctx != {"ctx": True}:
                _fail("_gather_peer_context 未委托给 PeerContextGatherer.gather")
            else:
                m.assert_called_once_with("role_a", "role_b", {"k": 1})

        # _generate_script_llm -> _script_llm.generate
        async def fake_generate(**kwargs):
            return [{"role": kwargs["role_id"], "content": "hi"}]

        with mock.patch.object(gen._script_llm, "generate", side_effect=fake_generate) as m:
            script = asyncio.get_event_loop().run_until_complete(
                gen._generate_script_llm(role_id="role_a", peer_role_id="role_b")
            )
            if script != [{"role": "role_a", "content": "hi"}]:
                _fail("_generate_script_llm 未委托给 PeerScriptLLMGenerator.generate")
            else:
                m.assert_called_once()

        # 兼容入口：record_raw_text 写回 _last_raw_text
        gen.record_raw_text("SOME_RAW")
        if gen._last_raw_text != "SOME_RAW":
            _fail("record_raw_text 未写回 _last_raw_text")
    except Exception as e:  # noqa: BLE001
        _fail(f"PeerScriptGenerator 委托校验异常: {e}")


def main() -> int:
    check_new_modules()
    check_executor_delegation()
    check_peer_generator_delegation()

    if FAILURES:
        sys.stderr.write(f"\n共 {len(FAILURES)} 处失败。\n")
        sys.stderr.flush()
        return 1
    sys.stderr.write("解耦验证全部通过。\n")
    sys.stderr.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())