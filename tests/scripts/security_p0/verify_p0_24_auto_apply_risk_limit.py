#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
P0-24 验证脚本：限制 auto_apply 为低风险补丁

验证目标：
  1. core/services/auto_heal/heal_service.py 新增 _AUTO_APPLY_BLOCKED_PREFIXES
  2. 新增 _AUTO_APPLY_ALLOWED_SEVERITIES（仅 LOW/MEDIUM）
  3. 新增 _can_auto_apply(anomaly, patch) 方法实现三层风险限制
  4. _process_anomaly 中调用 _can_auto_apply，被阻止则改为人工审批

验证方法：
  - AST 分析：检查常量、方法定义、调用关系
  - 源码扫描：检查关键字符串与日志
  - 单元测试：构造 anomaly+patch 实例，验证各种风险组合下 _can_auto_apply 的返回值
"""

import ast
import sys
import time
import uuid
from pathlib import Path
from typing import List

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# 辅助：读取源码与 AST
# ---------------------------------------------------------------------------
def _read_source(rel_path: str) -> str:
    return (_PROJECT_ROOT / rel_path).read_text(encoding="utf-8")


def _parse_ast(rel_path: str) -> ast.Module:
    return ast.parse(_read_source(rel_path))


# ---------------------------------------------------------------------------
# 检查 1：模块级常量存在
# ---------------------------------------------------------------------------
def check_module_constants() -> List[str]:
    issues: List[str] = []
    rel = "core/services/auto_heal/heal_service.py"
    try:
        tree = _parse_ast(rel)
    except Exception as e:
        issues.append(f"[{rel}] AST 解析失败: {e}")
        return issues

    found_blocked = False
    found_severities = False
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_AUTO_APPLY_BLOCKED_PREFIXES":
                    found_blocked = True
                if isinstance(target, ast.Name) and target.id == "_AUTO_APPLY_ALLOWED_SEVERITIES":
                    found_severities = True

    if not found_blocked:
        issues.append(f"[{rel}] 未找到 _AUTO_APPLY_BLOCKED_PREFIXES 常量")
    if not found_severities:
        issues.append(f"[{rel}] 未找到 _AUTO_APPLY_ALLOWED_SEVERITIES 常量")

    return issues


# ---------------------------------------------------------------------------
# 检查 2：_can_auto_apply 方法定义与三层检查逻辑
# ---------------------------------------------------------------------------
def check_can_auto_apply_method() -> List[str]:
    issues: List[str] = []
    rel = "core/services/auto_heal/heal_service.py"
    try:
        tree = _parse_ast(rel)
    except Exception as e:
        issues.append(f"[{rel}] AST 解析失败: {e}")
        return issues

    # 找到 AutoHealService 类
    cls_node = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "AutoHealService":
            cls_node = node
            break
    if cls_node is None:
        issues.append(f"[{rel}] 未找到 AutoHealService 类")
        return issues

    # 找到 _can_auto_apply 方法
    method_node = None
    for sub in cls_node.body:
        if isinstance(sub, ast.FunctionDef) and sub.name == "_can_auto_apply":
            method_node = sub
            break
    if method_node is None:
        issues.append(f"[{rel}] 未找到 _can_auto_apply 方法")
        return issues

    # 检查方法体是否引用了三个关键判断
    src = _read_source(rel)
    method_src = ast.get_source_segment(src, method_node) or ""

    if "_AUTO_APPLY_ALLOWED_SEVERITIES" not in method_src:
        issues.append(f"[{rel}] _can_auto_apply 未引用 _AUTO_APPLY_ALLOWED_SEVERITIES")
    if "_AUTO_APPLY_BLOCKED_PREFIXES" not in method_src:
        issues.append(f"[{rel}] _can_auto_apply 未引用 _AUTO_APPLY_BLOCKED_PREFIXES")
    if "is_protected_file" not in method_src:
        issues.append(f"[{rel}] _can_auto_apply 未调用 is_protected_file（缺少第三层检查）")

    # 检查参数签名
    args = method_node.args
    if len(args.args) != 3:  # self, anomaly, patch
        issues.append(
            f"[{rel}] _can_auto_apply 参数数量不对: 期望 3 (self, anomaly, patch)，"
            f"实际 {len(args.args)}"
        )

    return issues


# ---------------------------------------------------------------------------
# 检查 3：_process_anomaly 中调用 _can_auto_apply
# ---------------------------------------------------------------------------
def check_process_anomaly_uses_can_auto_apply() -> List[str]:
    issues: List[str] = []
    rel = "core/services/auto_heal/heal_service.py"
    src = _read_source(rel)

    if "_can_auto_apply" not in src:
        issues.append(f"[{rel}] 源码中未出现 _can_auto_apply 调用")
        return issues

    # 检查 _process_anomaly 方法中是否同时出现 _can_auto_apply 与 _notify_patch_ready
    # 这是"被风险阻止则改为人工审批"的关键证据
    try:
        tree = _parse_ast(rel)
    except Exception as e:
        issues.append(f"[{rel}] AST 解析失败: {e}")
        return issues

    cls_node = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "AutoHealService":
            cls_node = node
            break
    if cls_node is None:
        issues.append(f"[{rel}] 未找到 AutoHealService 类")
        return issues

    process_node = None
    for sub in cls_node.body:
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name == "_process_anomaly":
            process_node = sub
            break
    if process_node is None:
        issues.append(f"[{rel}] 未找到 _process_anomaly 方法")
        return issues

    process_src = ast.get_source_segment(src, process_node) or ""
    if "_can_auto_apply" not in process_src:
        issues.append(f"[{rel}] _process_anomaly 未调用 _can_auto_apply")
    if "_notify_patch_ready" not in process_src:
        issues.append(f"[{rel}] _process_anomaly 未调用 _notify_patch_ready（缺少人工审批回退路径）")

    # 检查日志：风险被阻止时应有 warning 日志
    if "auto_apply 已启用但补丁被风险限制阻止" not in process_src:
        issues.append(f"[{rel}] _process_anomaly 缺少风险阻止的 warning 日志")

    return issues


# ---------------------------------------------------------------------------
# 检查 4：单元测试 _can_auto_apply 的行为
# ---------------------------------------------------------------------------
def check_can_auto_apply_behavior() -> List[str]:
    """构造 anomaly + patch 实例，验证 _can_auto_apply 在各种风险组合下的返回值"""
    issues: List[str] = []

    try:
        from core.services.auto_heal.heal_service import (
            AutoHealService,
            _AUTO_APPLY_BLOCKED_PREFIXES,
            _AUTO_APPLY_ALLOWED_SEVERITIES,
        )
        from core.services.auto_heal.models import (
            AnomalyEvent,
            AnomalyType,
            Patch,
        )
        from core.contracts.states import AnomalySeverity
    except Exception as e:
        issues.append(f"导入 AutoHealService 失败: {e}")
        return issues

    # 验证常量内容
    if AnomalySeverity.HIGH in _AUTO_APPLY_ALLOWED_SEVERITIES:
        issues.append("HIGH 严重程度不应在允许列表中")
    if AnomalySeverity.CRITICAL in _AUTO_APPLY_ALLOWED_SEVERITIES:
        issues.append("CRITICAL 严重程度不应在允许列表中")
    if AnomalySeverity.LOW not in _AUTO_APPLY_ALLOWED_SEVERITIES:
        issues.append("LOW 严重程度应在允许列表中")
    if AnomalySeverity.MEDIUM not in _AUTO_APPLY_ALLOWED_SEVERITIES:
        issues.append("MEDIUM 严重程度应在允许列表中")

    if not _AUTO_APPLY_BLOCKED_PREFIXES:
        issues.append("_AUTO_APPLY_BLOCKED_PREFIXES 不应为空")
    if "routers/" not in _AUTO_APPLY_BLOCKED_PREFIXES:
        issues.append("routers/ 应在黑名单中")
    if "config/" not in _AUTO_APPLY_BLOCKED_PREFIXES:
        issues.append("config/ 应在黑名单中")

    # 构造 service 实例（不调用 initialize，避免触发后台任务）
    service = AutoHealService()

    def _make_anomaly(severity: AnomalySeverity) -> AnomalyEvent:
        return AnomalyEvent(
            id=f"test-{uuid.uuid4().hex[:6]}",
            anomaly_type=AnomalyType.ERROR_BURST,
            title="test anomaly",
            description="",
            severity=severity,
            detected_at=time.time(),
            metric_name="test_metric",
            metric_value=1.0,
            auto_fixable=True,
        )

    def _make_patch(file_path: str) -> Patch:
        return Patch(
            id=f"patch-{uuid.uuid4().hex[:6]}",
            anomaly_id="",
            file_path=file_path,
            original_code="",
            patched_code="",
            diff="",
            description="",
        )

    # 测试用例：(severity, file_path, expected)
    test_cases = [
        # 1. LOW 严重程度 + 普通业务文件 → 允许
        (AnomalySeverity.LOW, "core/tools/study/english/vocab_helper.py", True),
        # 2. MEDIUM 严重程度 + 普通业务文件 → 允许
        (AnomalySeverity.MEDIUM, "core/services/study/helper.py", True),
        # 3. HIGH 严重程度 + 普通业务文件 → 拒绝（严重程度过高）
        (AnomalySeverity.HIGH, "core/tools/study/english/vocab_helper.py", False),
        # 4. CRITICAL 严重程度 + 普通业务文件 → 拒绝
        (AnomalySeverity.CRITICAL, "core/tools/study/english/vocab_helper.py", False),
        # 5. LOW 严重程度 + routers/ 路径 → 拒绝（黑名单）
        (AnomalySeverity.LOW, "routers/admin/auto_heal.py", False),
        # 6. LOW 严重程度 + config/ 路径 → 拒绝（黑名单）
        (AnomalySeverity.LOW, "config/integrated_config.py", False),
        # 7. LOW 严重程度 + auto_heal 自身 → 拒绝（黑名单 + 受保护文件双重）
        (AnomalySeverity.LOW, "core/services/auto_heal/heal_service.py", False),
        # 8. LOW 严重程度 + logger.py → 拒绝（受保护文件）
        (AnomalySeverity.LOW, "core/utils/logger.py", False),
        # 9. LOW 严重程度 + log_sanitizer → 拒绝（黑名单）
        (AnomalySeverity.LOW, "core/utils/log_sanitizer.py", False),
        # 10. MEDIUM 严重程度 + WebSocket 路径 → 拒绝（黑名单）
        (AnomalySeverity.MEDIUM, "core/interfaces/websocket/manager.py", False),
        # 11. Windows 风格路径 + routers/ → 拒绝（路径归一化）
        (AnomalySeverity.LOW, "routers\\admin\\auto_heal.py", False),
        # 12. 空文件路径 → 允许（无路径限制，仅看严重程度）
        (AnomalySeverity.LOW, "", True),
    ]

    for idx, (sev, fpath, expected) in enumerate(test_cases, start=1):
        anomaly = _make_anomaly(sev)
        patch = _make_patch(fpath)
        try:
            actual = service._can_auto_apply(anomaly, patch)
        except Exception as e:
            issues.append(f"用例 {idx} 抛出异常: {e} (severity={sev.value}, file={fpath})")
            continue
        if actual != expected:
            issues.append(
                f"用例 {idx} 失败: severity={sev.value}, file={fpath}, "
                f"期望={expected}, 实际={actual}"
            )

    return issues


# ---------------------------------------------------------------------------
# 检查 5：模块导入测试
# ---------------------------------------------------------------------------
def check_imports() -> List[str]:
    issues: List[str] = []
    try:
        import importlib
        import core.services.auto_heal.heal_service as hs
        importlib.reload(hs)
        if not hasattr(hs, "_AUTO_APPLY_BLOCKED_PREFIXES"):
            issues.append("缺少 _AUTO_APPLY_BLOCKED_PREFIXES")
        if not hasattr(hs, "_AUTO_APPLY_ALLOWED_SEVERITIES"):
            issues.append("缺少 _AUTO_APPLY_ALLOWED_SEVERITIES")
        if not hasattr(hs.AutoHealService, "_can_auto_apply"):
            issues.append("AutoHealService 缺少 _can_auto_apply 方法")
    except Exception as e:
        issues.append(f"导入 heal_service 失败: {e}")
    return issues


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def main() -> int:
    print("=" * 70)
    print("P0-24 验证：限制 auto_apply 为低风险补丁")
    print("=" * 70)

    all_issues = []

    print("\n[1/5] 检查模块级常量定义 ...")
    issues = check_module_constants()
    all_issues.extend(issues)
    print(f"  -> {'PASS' if not issues else 'FAIL'} ({len(issues)} 个问题)")

    print("\n[2/5] 检查 _can_auto_apply 方法定义与三层检查逻辑 ...")
    issues = check_can_auto_apply_method()
    all_issues.extend(issues)
    print(f"  -> {'PASS' if not issues else 'FAIL'} ({len(issues)} 个问题)")

    print("\n[3/5] 检查 _process_anomaly 调用 _can_auto_apply ...")
    issues = check_process_anomaly_uses_can_auto_apply()
    all_issues.extend(issues)
    print(f"  -> {'PASS' if not issues else 'FAIL'} ({len(issues)} 个问题)")

    print("\n[4/5] 单元测试 _can_auto_apply 行为（12 个用例）...")
    issues = check_can_auto_apply_behavior()
    all_issues.extend(issues)
    print(f"  -> {'PASS' if not issues else 'FAIL'} ({len(issues)} 个问题)")

    print("\n[5/5] 模块导入测试 ...")
    issues = check_imports()
    all_issues.extend(issues)
    print(f"  -> {'PASS' if not issues else 'FAIL'} ({len(issues)} 个问题)")

    print("\n" + "=" * 70)
    if not all_issues:
        print("✅ 全部检查通过！P0-24 修复验证成功。")
        return 0
    else:
        print(f"❌ 共发现 {len(all_issues)} 个问题：")
        for msg in all_issues:
            print(f"  - {msg}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
