"""验证 peer_chat 日志与 active_care 日志分离

检查项：
1. 所有 peer_chat 相关模块的 logger 应写入 peer_chat.log
2. 不再使用 ACTIVE_CARE_EXECUTOR / NEGOTIATION_PARSER / PROACTIVE_PARSER logger
3. 不再使用 active_care_schedule.log 作为 peer_chat 的输出目标
4. 实际触发一次日志写入，确认 peer_chat.log 文件被创建
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# 项目根目录加入 sys.path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def _read_source(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def check_logger_config(rel_path: str, forbidden_substrings: list[str], required_substring: str) -> None:
    """检查文件源码中的 logger 配置是否符合预期"""
    src = _read_source(rel_path)
    assert required_substring in src, (
        f"[FAIL] {rel_path} 未找到预期配置: {required_substring}"
    )
    for bad in forbidden_substrings:
        assert bad not in src, (
            f"[FAIL] {rel_path} 仍包含禁止字符串: {bad}"
        )


def main() -> int:
    # 1. peer_chat 模块全部使用 peer_chat.log
    targets = [
        # (相对路径, 禁止字符串列表, 必须包含的字符串)
        ("clients/bots/qq/peer_chat.py",
         ["logging.getLogger(__name__)"],
         'get_module_logger("PEER_CHAT", "peer_chat.log")'),
        ("core/services/active_care/peer_chat/peer_script_generator.py",
         [],
         'get_module_logger("PEER_CHAT", "peer_chat.log")'),
        ("core/services/active_care/peer_chat/peer_script_dispatch.py",
         ['get_logger("ACTIVE_CARE_EXECUTOR")'],
         'get_module_logger("PEER_CHAT", "peer_chat.log")'),
        ("core/services/active_care/peer_chat/peer_script_hooks.py",
         ['get_logger("ACTIVE_CARE_EXECUTOR")'],
         'get_module_logger("PEER_CHAT", "peer_chat.log")'),
        ("core/services/active_care/peer_chat/negotiation_parser.py",
         ['get_logger("NEGOTIATION_PARSER")'],
         'get_module_logger("PEER_CHAT", "peer_chat.log")'),
        ("core/services/active_care/peer_chat/proactive_assignment_parser.py",
         ['get_logger("PROACTIVE_PARSER")'],
         'get_module_logger("PEER_CHAT", "peer_chat.log")'),
        ("core/services/active_care/peer_chat/peer_chat_scheduler.py",
         ['"active_care_schedule.log"'],
         'get_module_logger("PEER_CHAT_SCHEDULER", "peer_chat.log")'),
        ("core/services/character_daily/engine_peer_chat_support.py",
         ['"active_care_schedule.log"'],
         'get_module_logger("PEER_CHAT", "peer_chat.log")'),
        ("core/services/character_daily/peer_chat_gate.py",
         ['"active_care_schedule.log"'],
         'get_module_logger("PEER_CHAT", "peer_chat.log")'),
    ]
    for rel, bad_list, good in targets:
        check_logger_config(rel, bad_list, good)
    print(f"[OK] {len(targets)} 个 peer_chat 相关文件 logger 配置正确")

    # 2. 实际触发日志写入，确认 peer_chat.log 被创建
    # 临时改变工作目录到临时目录，避免污染项目 logs
    tmp = tempfile.mkdtemp()
    try:
        os.chdir(tmp)
        # 重新导入以触发 handler 初始化（handler 懒加载）
        from core.utils.logger import get_module_logger
        test_logger = get_module_logger("PEER_CHAT", "peer_chat.log")
        test_logger.info("verify_peer_chat_log_separation: 测试写入")

        # 等待队列监听器写出（队列异步）
        import time
        for _ in range(20):
            candidates = list(Path(tmp).rglob("peer_chat.log"))
            if candidates:
                break
            time.sleep(0.3)

        candidates = list(Path(tmp).rglob("peer_chat.log"))
        assert candidates, "[FAIL] peer_chat.log 文件未被创建"
        content = candidates[0].read_text(encoding="utf-8", errors="ignore")
        assert "verify_peer_chat_log_separation" in content, (
            f"[FAIL] peer_chat.log 中未找到测试日志: {content}"
        )
        print(f"[OK] peer_chat.log 文件已创建并写入成功: {candidates[0]}")
    finally:
        # 关闭 handler 释放文件锁，再尝试清理临时目录
        try:
            for h in list(test_logger.handlers):
                h.close()
                test_logger.removeHandler(h)
        except Exception:
            pass
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    # 3. 全局确认：peer_chat 目录下所有 .py 不再含 active_care_schedule.log
    peer_chat_dir = ROOT / "core" / "services" / "active_care" / "peer_chat"
    leaked: list[str] = []
    for py in peer_chat_dir.rglob("*.py"):
        txt = py.read_text(encoding="utf-8")
        if "active_care_schedule.log" in txt:
            leaked.append(str(py.relative_to(ROOT)))
    assert not leaked, f"[FAIL] peer_chat 目录仍存在 active_care_schedule.log 引用: {leaked}"
    print("[OK] peer_chat 目录已彻底脱离 active_care_schedule.log")

    print("\n所有验证通过 ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
