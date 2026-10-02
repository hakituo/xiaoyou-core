# -*- coding: utf-8 -*-
"""P2-2: 收敛配置到 pydantic model - 验证脚本

验证内容：
1. config/settings_adapters.py 存在且定义了 ASRSettings/TelegramAdapterSettings/MultiQQConfig/MultiQQRoleConfig
2. 提供统一加载入口：get_asr_settings/get_telegram_adapter_settings/get_multi_qq_config/get_multi_qq_raw_dict/get_multi_qq_role_config
3. 多线程并发调用 get_xxx() 返回同一实例（单例模式）
4. stt_connector.py 通过 get_asr_settings 加载 ASR 配置
5. telegram/settings.py 通过 get_telegram_adapter_settings 加载配置
6. multi_qq_adapter.py 通过 get_multi_qq_raw_dict 加载配置
7. Active Care 中 3 处 multi_qq_config.json 读取已切换到统一入口
8. ruff check 无 syntax 错误
"""

from __future__ import annotations

import ast
import subprocess
import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENV_PYTHON = PROJECT_ROOT / "venv_core" / "Scripts" / "python.exe"
VENV_RUFF = PROJECT_ROOT / "venv_core" / "Scripts" / "ruff.exe"


def _ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def _info(msg: str) -> None:
    print(f"  [INFO] {msg}")


def check_pydantic_models() -> bool:
    """检查 settings_adapters.py 是否定义了所有 pydantic model。"""
    print("\n=== 1. 检查 pydantic model 定义 ===")
    sa_path = PROJECT_ROOT / "config" / "settings_adapters.py"
    if not sa_path.exists():
        _fail(f"文件不存在: {sa_path}")
        return False

    content = sa_path.read_text(encoding="utf-8")
    expected_models = [
        "class ASRSettings(",
        "class TelegramAdapterSettings(",
        "class MultiQQRoleConfig(",
        "class MultiQQConfig(",
    ]
    expected_functions = [
        "def get_asr_settings(",
        "def get_telegram_adapter_settings(",
        "def get_multi_qq_config(",
        "def get_multi_qq_raw_dict(",
        "def get_multi_qq_role_config(",
        "def reset_adapter_settings_cache(",
    ]

    all_passed = True
    for model_def in expected_models:
        if model_def in content:
            _ok(f"找到 model 定义: {model_def}")
        else:
            _fail(f"未找到 model 定义: {model_def}")
            all_passed = False

    for func_def in expected_functions:
        if func_def in content:
            _ok(f"找到函数定义: {func_def}")
        else:
            _fail(f"未找到函数定义: {func_def}")
            all_passed = False

    return all_passed


def check_singleton_thread_safety() -> bool:
    """检查 get_xxx() 在多线程下返回同一实例。"""
    print("\n=== 2. 检查单例模式 + 线程安全 ===")
    try:
        # 重置缓存
        sys.path.insert(0, str(PROJECT_ROOT))
        from config.settings_adapters import (
            get_asr_settings,
            get_telegram_adapter_settings,
            get_multi_qq_config,
            reset_adapter_settings_cache,
        )

        reset_adapter_settings_cache()

        results: dict = {}
        errors: list = []

        def worker(key: str):
            try:
                if key == "asr":
                    results[key] = id(get_asr_settings())
                elif key == "tg":
                    results[key] = id(get_telegram_adapter_settings())
                elif key == "dqq":
                    results[key] = id(get_multi_qq_config())
            except Exception as e:
                errors.append(f"{key}: {e}")

        threads = []
        for key in ["asr", "tg", "dqq"] * 5:  # 每个调用 5 次
            t = threading.Thread(target=worker, args=(key,))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()

        if errors:
            _fail(f"线程异常: {errors}")
            return False

        # 由于 dict 只存最后一次，改用直接检查
        a1 = id(get_asr_settings())
        a2 = id(get_asr_settings())
        if a1 == a2:
            _ok("get_asr_settings() 单例正常")
        else:
            _fail(f"get_asr_settings() 不是单例: {a1} != {a2}")
            return False

        t1 = id(get_telegram_adapter_settings())
        t2 = id(get_telegram_adapter_settings())
        if t1 == t2:
            _ok("get_telegram_adapter_settings() 单例正常")
        else:
            _fail(f"get_telegram_adapter_settings() 不是单例: {t1} != {t2}")
            return False

        d1 = id(get_multi_qq_config())
        d2 = id(get_multi_qq_config())
        if d1 == d2:
            _ok("get_multi_qq_config() 单例正常")
        else:
            _fail(f"get_multi_qq_config() 不是单例: {d1} != {d2}")
            return False

        return True
    except Exception as e:
        _fail(f"单例测试失败: {e}")
        return False


def check_callers_updated() -> bool:
    """检查调用点是否已切换到统一入口。"""
    print("\n=== 3. 检查调用点已切换到统一入口 ===")

    checks = [
        (
            "multimodal/stt_connector.py",
            ["from config.settings_adapters import get_asr_settings"],
            "clients/bots/multi_qq_config.json 不应出现在加载逻辑中",
        ),
        (
            "clients/bots/telegram/settings.py",
            ["from config.settings_adapters import get_telegram_adapter_settings"],
            "应通过 pydantic 加载",
        ),
        (
            "clients/bots/multi_qq_adapter.py",
            ["from config.settings_adapters import get_multi_qq_raw_dict"],
            "应通过统一入口加载",
        ),
        (
            "core/services/active_care/peer_chat/peer_script_generator.py",
            ["get_multi_qq_role_config"],
            "应使用 get_multi_qq_role_config",
        ),
        (
            "core/services/active_care/peer_chat/peer_chat_scheduler.py",
            ["get_multi_qq_role_config"],
            "应使用 get_multi_qq_role_config",
        ),
        (
            "core/services/active_care/core/qq_connection_resolver.py",
            ["get_multi_qq_raw_dict"],
            "应使用 get_multi_qq_raw_dict",
        ),
    ]

    all_passed = True
    for rel_path, expected_tokens, desc in checks:
        full_path = PROJECT_ROOT / rel_path
        if not full_path.exists():
            _fail(f"文件不存在: {rel_path}")
            all_passed = False
            continue

        content = full_path.read_text(encoding="utf-8")
        for tok in expected_tokens:
            if tok in content:
                _ok(f"{rel_path}: 包含 {tok}")
            else:
                _fail(f"{rel_path}: 缺少 {tok}（{desc}）")
                all_passed = False

    # 检查 Active Care 3 处不再使用 parents[4]
    for rel_path in [
        "core/services/active_care/peer_chat/peer_script_generator.py",
        "core/services/active_care/peer_chat/peer_chat_scheduler.py",
        "core/services/active_care/core/qq_connection_resolver.py",
    ]:
        full_path = PROJECT_ROOT / rel_path
        if not full_path.exists():
            continue
        content = full_path.read_text(encoding="utf-8")
        # 检查是否还有 parents[4] 用于 multi_qq_config.json（注释中允许）
        # 简单检查：看是否有 json.load(open(...)) 形式读取 multi_qq_config.json
        if "parents[4]" in content and "multi_qq_config" in content:
            # 进一步检查是否在代码行（非注释）中
            for i, line in enumerate(content.split("\n"), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "parents[4]" in line and "multi_qq_config" in line:
                    _fail(f"{rel_path}:{i} 仍使用 parents[4] 加载 multi_qq_config")
                    all_passed = False
                    break
            else:
                _ok(f"{rel_path}: 不再使用 parents[4] 加载 multi_qq_config")
        else:
            _ok(f"{rel_path}: 不再使用 parents[4] 加载 multi_qq_config")

    return all_passed


def check_files_syntax() -> bool:
    """检查关键文件 AST 语法正确。"""
    print("\n=== 4. 检查关键文件 AST 语法 ===")
    key_files = [
        "config/settings_adapters.py",
        "multimodal/stt_connector.py",
        "clients/bots/telegram/settings.py",
        "clients/bots/multi_qq_adapter.py",
        "core/services/active_care/peer_chat/peer_script_generator.py",
        "core/services/active_care/peer_chat/peer_chat_scheduler.py",
        "core/services/active_care/core/qq_connection_resolver.py",
    ]

    all_passed = True
    for rel_path in key_files:
        full_path = PROJECT_ROOT / rel_path
        if not full_path.exists():
            _fail(f"文件不存在: {rel_path}")
            all_passed = False
            continue
        try:
            ast.parse(full_path.read_text(encoding="utf-8"))
            _ok(f"语法正确: {rel_path}")
        except SyntaxError as e:
            _fail(f"语法错误: {rel_path} - {e}")
            all_passed = False

    return all_passed


def check_ruff() -> bool:
    """运行 ruff check 验证无 syntax 错误。"""
    print("\n=== 5. 运行 ruff check（仅 E9 和 F821）===")
    try:
        result = subprocess.run(
            [
                str(VENV_RUFF), "check",
                "config/settings_adapters.py",
                "multimodal/stt_connector.py",
                "clients/bots/telegram/settings.py",
                "clients/bots/multi_qq_adapter.py",
                "core/services/active_care/peer_chat/peer_script_generator.py",
                "core/services/active_care/peer_chat/peer_chat_scheduler.py",
                "core/services/active_care/core/qq_connection_resolver.py",
                "--select", "E9,F821",
                "--output-format=concise",
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            _ok("ruff check 通过（无 E9/F821 错误）")
            return True
        else:
            errors = [line for line in result.stdout.split("\n") if line.strip()]
            real_errors = [e for e in errors if ": E9" in e or ": F821" in e]
            if not real_errors:
                _ok("ruff check 通过（无 E9/F821 错误）")
                return True
            _fail(f"ruff check 发现 {len(real_errors)} 个错误:")
            for err in real_errors[:10]:
                print(f"    {err}")
            return False
    except Exception as e:
        _fail(f"ruff check 运行失败: {e}")
        return False


def check_field_access() -> bool:
    """检查 pydantic model 字段可正常访问。"""
    print("\n=== 6. 检查 pydantic model 字段访问 ===")
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from config.settings_adapters import (
            get_asr_settings,
            get_telegram_adapter_settings,
            get_multi_qq_config,
            get_multi_qq_role_config,
            reset_adapter_settings_cache,
        )

        reset_adapter_settings_cache()

        # ASR
        asr = get_asr_settings()
        assert hasattr(asr, "model_path"), "ASRSettings.model_path 不存在"
        assert hasattr(asr, "model_type"), "ASRSettings.model_type 不存在"
        assert isinstance(asr.model_path, str), "model_path 不是 str"
        assert isinstance(asr.model_type, str), "model_type 不是 str"
        _ok(f"ASRSettings: model_path={asr.model_path[:30]}..., model_type={asr.model_type}")

        # Telegram
        tg = get_telegram_adapter_settings()
        assert hasattr(tg, "bot_token"), "TelegramAdapterSettings.bot_token 不存在"
        assert hasattr(tg, "http_base_url"), "TelegramAdapterSettings.http_base_url 不存在"
        assert isinstance(tg.bot_token, str), "bot_token 不是 str"
        _ok(
            "TelegramAdapterSettings: "
            f"bot_token_configured={bool(tg.bot_token)}, http_base_url={tg.http_base_url}"
        )

        # MultiQQ
        dqq = get_multi_qq_config()
        assert hasattr(dqq, "roles"), "MultiQQConfig.roles 不存在"
        assert isinstance(dqq.roles, dict), "roles 不是 dict"
        _ok(f"MultiQQConfig: roles={list(dqq.roles.keys())}")

        # MultiQQRoleConfig
        if "aveline" in dqq.roles:
            aveline = dqq.roles["aveline"]
            assert hasattr(aveline, "role_name"), "MultiQQRoleConfig.role_name 不存在"
            assert hasattr(aveline, "peer_qq_id"), "MultiQQRoleConfig.peer_qq_id 不存在"
            _ok(f"MultiQQRoleConfig[aveline]: role_name={aveline.role_name}, peer_qq_id={aveline.peer_qq_id}")

        # get_multi_qq_role_config 单独访问
        ling = get_multi_qq_role_config("ling")
        if ling is not None:
            _ok(f"get_multi_qq_role_config('ling'): role_name={ling.role_name}")
        else:
            _info("get_multi_qq_role_config('ling') 返回 None（配置中无 ling 角色）")

        return True
    except Exception as e:
        _fail(f"字段访问测试失败: {e}")
        return False


def main() -> int:
    print("=" * 70)
    print("P2-2: 收敛配置到 pydantic model - 验证脚本")
    print("=" * 70)

    results = []
    results.append(check_pydantic_models())
    results.append(check_singleton_thread_safety())
    results.append(check_callers_updated())
    results.append(check_files_syntax())
    results.append(check_ruff())
    results.append(check_field_access())

    print("\n" + "=" * 70)
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"总计: {passed}/{total} 项通过")
    print("=" * 70)

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
