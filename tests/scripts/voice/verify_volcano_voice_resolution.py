"""验证火山 TTS 的音色解析与资源 ID 修复。

线上问题（用户回传日志）：
    Volcano TTS synthesize: voice_name=None, voice_id=None, ...
      _resolve_voice: voice_name=None, key_cfg={}
    Volcano TTS 请求失败: 403 | {"code":3001,"message":"[resource_id=] requested resource not granted"}

两个根因：
1. 调用方显式传了 voice=None，而 `kwargs.get("voice", default)` 在 key 存在时**不会**回退默认值，
   于是拿着 None 去查 voice_map，最终把无效的 voice_type 发出去；配置值被写成字符串
   "None"/"null" 也会踩同一个坑。
2. 火山新版 API 必须携带资源 ID（header X-Api-Resource-Id），payload/header 都没有时
   服务端直接 403 code 3001 `[resource_id=] requested resource not granted`。

本脚本校验修复后的行为，防止回归。

运行：d:\\AI\\xiaoyou-core\\venv_core\\Scripts\\python.exe tests/scripts/voice/verify_volcano_voice_resolution.py
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core.voice.engines.volcano_tts_engine import (  # noqa: E402
    DEFAULT_RESOURCE_ID,
    DEFAULT_VOICE,
    VolcanoTTSEngine,
    _sanitize_voice_value,
)

ENGINE_SOURCE = (
    PROJECT_ROOT / "core/voice/engines/volcano_tts_engine.py"
).read_text(encoding="utf-8")

REAL_VOICE = "S_HbG6m9272"
VOICE_MAP = {"Aveline": REAL_VOICE, "Ling": "S_LvHb6zN62"}


def _check(condition: bool, msg: str) -> tuple[bool, str]:
    return condition, ("PASS: " if condition else "FAIL: ") + msg


def main() -> int:
    results: list[tuple[bool, str]] = []

    print("\n" + "=" * 70)
    print("火山 TTS 音色解析 / 资源 ID 验证")
    print("=" * 70)

    # 1. 空值清洗：None 与各种"字符串化的空"都要视为未配置
    for raw in (None, "", "   ", "None", "none", "null", "NULL", "undefined", "NaN"):
        results.append(
            _check(
                _sanitize_voice_value(raw) == "",
                f"_sanitize_voice_value({raw!r}) 视为未配置",
            )
        )
    results.append(
        _check(_sanitize_voice_value(REAL_VOICE) == REAL_VOICE, "真实音色 ID 原样保留")
    )

    # 2. 配置里的 model 是字符串 "None" 时，兜底到默认音色而不是发 "None"
    engine_bad = VolcanoTTSEngine(api_key="k", appid="a", model="None")
    results.append(
        _check(
            engine_bad.default_voice == DEFAULT_VOICE,
            f'model="None" 时 default_voice 兜底为 {DEFAULT_VOICE}（实际 {engine_bad.default_voice}）',
        )
    )
    engine_ok = VolcanoTTSEngine(api_key="k", appid="a", model=REAL_VOICE)
    results.append(
        _check(engine_ok.default_voice == REAL_VOICE, "model 正常时保持配置音色")
    )

    # 3. 调用方显式传 voice=None：必须回退默认音色，不能再解析出 None
    engine_map = VolcanoTTSEngine(
        api_key="k", appid="a", model=REAL_VOICE, voice_map=VOICE_MAP
    )
    _, _, voice_id = engine_ok._resolve_voice(None)
    results.append(
        _check(voice_id == REAL_VOICE, f"_resolve_voice(None) -> {voice_id}（不再为 None）")
    )
    _, _, voice_id_blank = engine_ok._resolve_voice("")
    results.append(
        _check(voice_id_blank == REAL_VOICE, f'_resolve_voice("") -> {voice_id_blank}（不再为空）')
    )
    _, _, voice_id_real = engine_map._resolve_voice("Aveline")
    results.append(
        _check(
            voice_id_real == REAL_VOICE,
            f'按角色名查表："Aveline" -> {voice_id_real}',
        )
    )
    # 直接传音色 ID 时必须原样使用，不能被"未登记"逻辑换成默认音色
    _, _, voice_id_direct = engine_ok._resolve_voice(REAL_VOICE)
    results.append(
        _check(voice_id_direct == REAL_VOICE, f"直接传音色 ID 保持原值：{voice_id_direct}")
    )

    # 4. voice_map 命中优先，未命中时回落默认音色（engine_map 在第 3 节已创建）
    _, _, mapped = engine_map._resolve_voice("Ling")
    results.append(
        _check(mapped == "S_LvHb6zN62", f'voice_map 命中："Ling" -> {mapped}')
    )
    _, _, unmapped = engine_map._resolve_voice("未登记角色")
    results.append(
        _check(
            unmapped == REAL_VOICE,
            f"未登记角色回落到引擎默认音色（实际 {unmapped}）",
        )
    )

    # 5. 资源 ID：默认兜底 + 环境变量覆盖
    results.append(
        _check(
            engine_ok.resource_id == DEFAULT_RESOURCE_ID,
            f"未配置时 resource_id 兜底为 {DEFAULT_RESOURCE_ID}",
        )
    )
    os.environ["VOLC_RESOURCE_ID"] = "volc.service_type.10029"
    try:
        engine_env = VolcanoTTSEngine(api_key="k", appid="a", model=REAL_VOICE)
        results.append(
            _check(
                engine_env.resource_id == "volc.service_type.10029",
                "VOLC_RESOURCE_ID 环境变量可覆盖资源 ID",
            )
        )
    finally:
        os.environ.pop("VOLC_RESOURCE_ID", None)
    engine_explicit = VolcanoTTSEngine(
        api_key="k", appid="a", model=REAL_VOICE, resource_id="volc.custom"
    )
    results.append(
        _check(engine_explicit.resource_id == "volc.custom", "构造参数优先于默认值")
    )

    # 6. 请求头确实带上了资源 ID（403 的直接修复点）
    results.append(
        _check(
            '"X-Api-Resource-Id": self.resource_id' in ENGINE_SOURCE,
            "请求头携带 X-Api-Resource-Id（修复 403 code 3001）",
        )
    )
    results.append(
        _check(
            "voice_name = _sanitize_voice_value(kwargs.get(\"voice\")) or self.default_voice"
            in ENGINE_SOURCE,
            "synthesize_bytes 对显式 voice=None 做兜底",
        )
    )

    print("\n" + "-" * 70)
    for ok, msg in results:
        print(msg)
    failed = [msg for ok, msg in results if not ok]
    print("-" * 70)
    print(f"结果：{len(results) - len(failed)}/{len(results)} 通过")
    if failed:
        for msg in failed:
            print(f"  {msg}")
        return 1
    print("全部通过：音色不再解析出 None，请求携带资源 ID。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
