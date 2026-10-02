"""验证 errors_20260909.json 中四类问题的修复契约。"""

from __future__ import annotations

import ast
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    from core.llm.openai_compat.client import _is_sensitive_input_rejection

    runtime_source = (PROJECT_ROOT / "memory/core/runtime_ops.py").read_text(encoding="utf-8")
    manager_source = (PROJECT_ROOT / "memory/weighted_memory_manager.py").read_text(
        encoding="utf-8"
    )
    extractor_source = (PROJECT_ROOT / "core/character/people/extractor.py").read_text(
        encoding="utf-8"
    )
    response_source = (
        PROJECT_ROOT / "core/services/active_care/core/response_generator.py"
    ).read_text(encoding="utf-8")

    assert "_save_pending_during_load = True" in runtime_source
    assert "if self._save_pending_during_load:" in manager_source
    reclassify_pos = manager_source.index("self.reclassify_all_memories()")
    loaded_pos = manager_source.index("self._data_loaded_event.set()", reclassify_pos)
    assert reclassify_pos < loaded_pos
    print("[PASS] 后台记忆加载完成前保存请求只排队，完成后统一触发")

    executor_source = (
        PROJECT_ROOT / "core/services/active_care/core/executor.py"
    ).read_text(encoding="utf-8")
    executor_tree = ast.parse(executor_source)
    executor_class = next(
        node
        for node in executor_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ActiveCareExecutor"
    )
    method = next(
        node
        for node in executor_class.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "generate_peer_script"
    )
    expected_parameters = {
        "proactive_assignment_mode",
        "aveline_state",
        "ling_state",
        "role_states",
    }
    parameters = {arg.arg for arg in (*method.args.args, *method.args.kwonlyargs)}
    forwarded = {
        keyword.arg
        for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "generate_peer_script"
        for keyword in node.keywords
        if keyword.arg is not None
    }
    assert expected_parameters <= parameters
    assert expected_parameters <= forwarded
    print("[PASS] 主动关怀分工协商参数已穿过 ActiveCareExecutor 门面")

    assert _is_sensitive_input_rejection(422, "input new_sensitive (1026)")
    # 不可重试状态码已收敛到 error_handling.NON_RETRYABLE_STATUS（client.py 只消费判定结果）
    assert "NON_RETRYABLE_STATUS = (401, 402, 403, 422)" in (
        PROJECT_ROOT / "core/llm/openai_compat/error_handling.py"
    ).read_text(encoding="utf-8")
    assert 'if chunk.get("non_retryable"):' in extractor_source
    assert "logger.warning(" in extractor_source
    assert "Active Care generation rejected by upstream" in response_source
    print("[PASS] 422 敏感输入拒绝被标记为不可重试，业务层安全停止")

    persona_path = PROJECT_ROOT / "core/character/configs/core_ling.json"
    if persona_path.exists():
        persona = json.loads(persona_path.read_text(encoding="utf-8"))
        assert persona["identity"]["name"] == "Ling"
        print("[PASS] 本机 core_ling.json 当前为完整且可解析的人设文件")
    else:
        assert "core_ling.json" in (
            PROJECT_ROOT / ".gitignore"
        ).read_text(encoding="utf-8")
        print("[PASS] clean checkout 未包含私有人设文件，CI 不以其存在为前提")

    print("结果: 4/4 类错误修复契约通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
