#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P0-03 验证脚本: contract.py token 比较改用 hmac.compare_digest

验证项：
1. validate_internal_token 使用 hmac.compare_digest 而非 == 直接比较
2. 仍然保留"未配置 token 时放行"的行为
3. 输入为 None / 空 / 不等长 / 相同等场景下行为正确
4. 不存在残留的直接 == token 比较
"""
import sys
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = ROOT / "core" / "api" / "contract.py"

# 预先 stub config.integrated_config，避免触发项目重依赖链
_CONFIG_STUB_TOKEN = ""


def _stub_get_settings():
    return SimpleNamespace(security=SimpleNamespace(web_access_token=_CONFIG_STUB_TOKEN))


def _install_config_stub():
    config_pkg = ModuleType("config")
    config_pkg.__path__ = []  # type: ignore[attr-defined]
    integrated = ModuleType("config.integrated_config")
    integrated.get_settings = _stub_get_settings
    sys.modules["config"] = config_pkg
    sys.modules["config.integrated_config"] = integrated


_install_config_stub()


def load_module():
    """加载 contract.py，预先 stub 相对导入的 error_response 模块。"""
    import sys as _sys

    # 预先 stub core.api.error_response 模块（提供 ErrorCode 枚举）
    if "core.api.error_response" not in _sys.modules:
        from types import ModuleType, SimpleNamespace
        stub = ModuleType("core.api.error_response")
        # 提供一个简单的 ErrorCode 占位
        class _ErrorCodeStub:
            def __init__(self, value):
                self.value = value
        stub.ErrorCode = _ErrorCodeStub
        _sys.modules["core.api.error_response"] = stub

    # 同时确保 core.api 和 core 包存在
    for pkg_name in ("core", "core.api"):
        if pkg_name not in _sys.modules:
            _sys.modules[pkg_name] = type(pkg_name, (), {"__path__": []})

    # 加载 contract.py 但跳过其相对导入行（直接替换 import）
    content = CONTRACT_PATH.read_text(encoding="utf-8")
    # 把 `from .error_response import ErrorCode` 替换为从 stub 取
    patched = content.replace(
        "from .error_response import ErrorCode",
        "from core.api.error_response import ErrorCode  # noqa: E402",
    )

    spec = importlib.util.spec_from_file_location("contract_p0_03", CONTRACT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {CONTRACT_PATH}")
    module = importlib.util.module_from_spec(spec)

    # 使用 exec 加载 patched 源码，避免相对导入问题
    namespace = {"__name__": "contract_p0_03", "__file__": str(CONTRACT_PATH)}
    exec(compile(patched, str(CONTRACT_PATH), "exec"), namespace)
    return type("M", (), namespace)


def check_source_uses_hmac() -> list[str]:
    """检查源码层面是否使用 hmac.compare_digest。"""
    issues = []
    content = CONTRACT_PATH.read_text(encoding="utf-8")
    if "import hmac" not in content:
        issues.append("缺失 `import hmac`")
    if "hmac.compare_digest" not in content:
        issues.append("缺失 `hmac.compare_digest` 调用")
    # 禁止残留直接 == 比较 token
    # 允许出现在注释或字符串里，但禁止 x == required 这类实际比较
    for forbidden in ["x_internal_token == required", "provided == required"]:
        if forbidden in content:
            issues.append(f"残留直接比较: {forbidden}")
    return issues


def check_behavior(module) -> list[str]:
    """检查行为是否符合预期。"""
    issues = []

    import config.integrated_config as cfg_pkg

    original_get_settings = cfg_pkg.get_settings

    def _make_get_settings(token: str):
        def _impl():
            return SimpleNamespace(security=SimpleNamespace(web_access_token=token))
        return _impl

    try:
        # 场景1: 未配置 token（空字符串），任意输入都应放行
        cfg_pkg.get_settings = _make_get_settings("")
        if module.validate_internal_token(None) is not True:
            issues.append("[未配置token] None 输入应放行")
        if module.validate_internal_token("anything") is not True:
            issues.append("[未配置token] 非空输入应放行")

        # 场景2: 配置了 token，正确 token 应放行
        cfg_pkg.get_settings = _make_get_settings("secret-token-123")
        if module.validate_internal_token("secret-token-123") is not True:
            issues.append("[正确token] 应放行")

        # 场景3: 配置了 token，错误 token 应拒绝
        if module.validate_internal_token("wrong-token") is not False:
            issues.append("[错误token] 应拒绝")

        # 场景4: 配置了 token，None 应拒绝
        if module.validate_internal_token(None) is not False:
            issues.append("[None输入] 应拒绝")

        # 场景5: 配置了 token，空字符串应拒绝
        if module.validate_internal_token("") is not False:
            issues.append("[空字符串输入] 应拒绝")

        # 场景6: 大小写敏感
        if module.validate_internal_token("SECRET-TOKEN-123") is not False:
            issues.append("[大小写敏感] 应拒绝")

        # 场景7: 前后空格应被 strip
        if module.validate_internal_token("  secret-token-123  ") is not True:
            issues.append("[strip处理] 前后空格应被剥离并放行")

        # 场景8: 不等长 token 应快速拒绝（compare_digest 不抛异常）
        if module.validate_internal_token("short") is not False:
            issues.append("[不等长token] 应拒绝")

    finally:
        cfg_pkg.get_settings = original_get_settings

    return issues


def main() -> int:
    if not CONTRACT_PATH.exists():
        print(f"[ERROR] contract.py 不存在: {CONTRACT_PATH}")
        return 2

    all_issues: list[str] = []
    all_issues.extend(check_source_uses_hmac())

    try:
        module = load_module()
        all_issues.extend(check_behavior(module))
    except Exception as exc:
        all_issues.append(f"模块加载/行为测试失败: {exc}")

    if all_issues:
        print(f"[FAIL] 共发现 {len(all_issues)} 个问题:")
        for issue in all_issues:
            print(f"  - {issue}")
        return 1

    print("[OK] contract.py token 比较已改用 hmac.compare_digest，且行为符合预期")
    print("  - 使用常量时间比较防止时序侧信道攻击")
    print("  - 未配置 token 时放行（保留原行为）")
    print("  - 正确 token 放行 / 错误 token 拒绝 / None 拒绝 / 空字符串拒绝")
    print("  - strip 处理保留 / 大小写敏感 / 不等长 token 安全拒绝")
    return 0


if __name__ == "__main__":
    sys.exit(main())
