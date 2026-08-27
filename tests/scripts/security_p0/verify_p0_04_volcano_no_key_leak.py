#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P0-04 验证脚本: volcano_tts_engine.py API key 日志泄漏修复

验证项：
1. 不再在日志中输出 api_key 任何片段（包括 api_key[:8]、api_key 直接打印）
2. 不再在日志中输出 appid / access_token / secret 等敏感凭证
3. 保留合成流程必要逻辑（_resolve_voice、headers x-api-key 等）
4. 动态加载模块，捕获实际执行 logger.info 时的输出，确保不泄漏 api_key
"""
import sys
import io
import logging
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
ENGINE_PATH = ROOT / "core" / "voice" / "engines" / "volcano_tts_engine.py"


def _install_stubs():
    """预存根依赖，避免触发项目重依赖链。"""
    # config 包
    if "config" not in sys.modules:
        config_pkg = ModuleType("config")
        config_pkg.__path__ = []  # type: ignore[attr-defined]
        sys.modules["config"] = config_pkg
    if "config.integrated_config" not in sys.modules:
        integrated = ModuleType("config.integrated_config")
        integrated.get_settings = lambda: SimpleNamespace()
        sys.modules["config.integrated_config"] = integrated

    # core.utils.logger - 提供 get_logger 与 get_module_logger 两个名字
    if "core.utils.logger" not in sys.modules:
        for pkg_name in ("core", "core.utils"):
            if pkg_name not in sys.modules:
                pkg = ModuleType(pkg_name)
                pkg.__path__ = []  # type: ignore[attr-defined]
                sys.modules[pkg_name] = pkg
        logger_mod = ModuleType("core.utils.logger")

        def _get_logger(name, log_file=None):
            return logging.getLogger(name)

        def _get_module_logger(name, log_file=None):
            return logging.getLogger(name)

        logger_mod.get_logger = _get_logger
        logger_mod.get_module_logger = _get_module_logger
        sys.modules["core.utils.logger"] = logger_mod

    # core.voice.engines.base - 提供 TTSEngine 父类
    if "core.voice.engines.base" not in sys.modules:
        for pkg_name in ("core", "core.voice", "core.voice.engines"):
            if pkg_name not in sys.modules:
                pkg = ModuleType(pkg_name)
                pkg.__path__ = []  # type: ignore[attr-defined]
                sys.modules[pkg_name] = pkg
        base_mod = ModuleType("core.voice.engines.base")

        class _TTSEngineBase:
            """模拟 TTSEngine 父类。"""
            async def synthesize(self, text, **kwargs):
                return await self.synthesize_bytes(text, **kwargs)

            def _decode_mp3(self, audio_bytes):
                return audio_bytes

        base_mod.TTSEngine = _TTSEngineBase
        sys.modules["core.voice.engines.base"] = base_mod

    # stub aiohttp - 防止实际发起网络请求，避免事件循环关闭时的噪音
    if "aiohttp" not in sys.modules:
        aiohttp_stub = ModuleType("aiohttp")

        class _StubClientSession:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, *args, **kwargs):
                class _Resp:
                    status = 500
                    async def json(self):
                        return {"code": 9999, "message": "stub-no-network"}
                    async def __aenter__(self):
                        return self
                    async def __aexit__(self, *args):
                        return False
                return _Resp()

            async def close(self):
                pass

        aiohttp_stub.ClientSession = _StubClientSession
        sys.modules["aiohttp"] = aiohttp_stub

    # stub numpy（避免引入重依赖）
    if "numpy" not in sys.modules:
        np_stub = ModuleType("numpy")
        np_stub.array = lambda *args, **kwargs: None
        np_stub.float32 = "float32"

        class _ndarray:
            pass

        np_stub.ndarray = _ndarray
        sys.modules["numpy"] = np_stub


def load_module():
    """加载 volcano_tts_engine.py 模块。"""
    _install_stubs()

    content = ENGINE_PATH.read_text(encoding="utf-8")
    spec = importlib.util.spec_from_file_location("volcano_tts_p0_04", ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {ENGINE_PATH}")
    module = importlib.util.module_from_spec(spec)

    namespace = {"__name__": "volcano_tts_p0_04", "__file__": str(ENGINE_PATH)}
    exec(compile(content, str(ENGINE_PATH), "exec"), namespace)
    return namespace


def check_source_no_leak() -> list[str]:
    """检查源码层面不再泄漏 api_key。"""
    issues = []
    content = ENGINE_PATH.read_text(encoding="utf-8")
    # 禁止 api_key[:n] 这种切片输出
    for forbidden in [
        "api_key[:",
        "secret[:",
        "access_token[:",
        "token[:",
        "f\"...{api_key}",
        "f'...{api_key}",
        "logger.info(f\"Volcano TTS synthesize: voice_name={voice_name}, voice_id={voice_id}, api_key=",
    ]:
        if forbidden in content:
            issues.append(f"残留敏感信息泄漏模式: {forbidden!r}")

    # 检查所有 logger.xxx 调用，禁止出现 {api_key} {secret} {access_token} {token} 等插值
    import re
    pattern = re.compile(
        r"logger\.\w+\([^)]*\{[^}]*(api_key|secret|access_token|app_secret|api_secret)[^}]*\}[^)]*\)",
        re.IGNORECASE,
    )
    matches = pattern.findall(content)
    if matches:
        issues.append(f"logger 调用中发现敏感变量插值: {matches}")

    return issues


def check_logic_preserved(content: str) -> list[str]:
    """检查关键功能逻辑保留。"""
    issues = []
    if "_resolve_voice" not in content:
        issues.append("缺失 _resolve_voice 方法")
    if "x-api-key" not in content:
        issues.append("缺失 x-api-key header 设置")
    if "async def synthesize_bytes" not in content:
        issues.append("缺失 async def synthesize_bytes 方法")
    return issues


def check_runtime_no_leak(module) -> list[str]:
    """动态捕获日志输出，确保实际合成时不会泄漏 api_key。"""
    issues = []

    # 构造一个测试用 engine 实例
    VolcanoTTSClient = module.get("VolcanoTTSClient") or module.get("VolcanoTTSEngine")
    if VolcanoTTSClient is None:
        # 尝试找到模块中所有以 Volcano 开头的类
        for k, v in module.items():
            if isinstance(v, type) and "Volcano" in k:
                VolcanoTTSClient = v
                break

    if VolcanoTTSClient is None:
        issues.append("未找到 Volcano TTS 客户端类")
        return issues

    # 准备日志捕获
    test_logger = logging.getLogger("VOLCANO_TTS_TEST")
    test_logger.setLevel(logging.DEBUG)
    log_capture = io.StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setLevel(logging.DEBUG)
    test_logger.addHandler(handler)

    # 替换模块内的 logger
    module["logger"] = test_logger

    try:
        # 用一个明显的假 api_key 创建实例
        try:
            client = VolcanoTTSClient(
                api_key="AKID_supersecret_dontleak_1234567890",
                appid="test_appid",
                model="test_voice",
            )
        except TypeError:
            # 兼容不同构造签名
            client = VolcanoTTSClient(
                api_key="AKID_supersecret_dontleak_1234567890",
                appid="test_appid",
            )

        # 触发 _resolve_voice（不实际发送网络请求）
        try:
            if hasattr(client, "_resolve_voice"):
                api_key, appid, voice_id = client._resolve_voice("test_voice")
                # 强制触发 synthesize_bytes 的日志路径（会失败但不影响日志检查）
                try:
                    import asyncio
                    asyncio.run(client.synthesize_bytes("hello", voice="test_voice"))
                except Exception:
                    pass
        except Exception:
            pass

        log_content = log_capture.getvalue()
        # 检查日志中是否出现 api_key 任何片段（前8字符是关键标志）
        sensitive_markers = [
            "AKID_supersecret",
            "supersecret_dontleak",
            "dontleak_1234567890",
            "AKID_supersecret_dontleak_1234567890",
        ]
        for marker in sensitive_markers:
            if marker in log_content:
                issues.append(f"运行时日志泄漏 api_key 片段: {marker!r}")

        # 同时禁止 api_key[:8] 这类截断形式
        if "api_key=AKID" in log_content or "api_key=AK" in log_content:
            issues.append("运行时日志中包含 api_key 前缀")

    finally:
        test_logger.removeHandler(handler)

    return issues


def main() -> int:
    if not ENGINE_PATH.exists():
        print(f"[ERROR] volcano_tts_engine.py 不存在: {ENGINE_PATH}")
        return 2

    all_issues: list[str] = []
    all_issues.extend(check_source_no_leak())

    content = ENGINE_PATH.read_text(encoding="utf-8")
    all_issues.extend(check_logic_preserved(content))

    try:
        module = load_module()
        all_issues.extend(check_runtime_no_leak(module))
    except Exception as exc:
        all_issues.append(f"模块加载/运行时测试失败: {exc}")

    if all_issues:
        print(f"[FAIL] 共发现 {len(all_issues)} 个问题:")
        for issue in all_issues:
            print(f"  - {issue}")
        return 1

    print("[OK] volcano_tts_engine.py API key 日志泄漏已修复")
    print("  - 不再输出 api_key[:8] 等片段")
    print("  - 不再在 logger 中插值 api_key / secret / access_token")
    print("  - 保留 _resolve_voice / x-api-key header / synthesize_bytes 核心逻辑")
    return 0


if __name__ == "__main__":
    sys.exit(main())
