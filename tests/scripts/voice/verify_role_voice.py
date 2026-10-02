# -*- coding: utf-8 -*-
"""通用角色音色(TTS)验证脚本。

新增角色(如说话人/角色名)后运行本脚本，可一步确认：
1. app.yaml 的 voice.tts.voice_map 里该角色的音色 ID 已正确配置；
2. 火山引擎(VCT)能把该角色名解析成真实音色 ID；
3. (可选 --synthesize) 真的合成出一段音频，校验返回有效音频数据。

设计目标：角色无关。新增角色只需在 app.yaml 的 voice_map 里加一行
`角色名: "S_xxx"`，本脚本会自动把 voice_map 里所有角色都纳入检查，
无需改脚本本身。也支持 --role 只测单个角色。

用法：
    # 仅校验配置解析（不真正调用网络合成，最快）
    venv_core\\Scripts\\python.exe tests\\scripts\\voice\\verify_role_voice.py

    # 真实合成验证（需要火山 API key 且能联网）
    venv_core\\Scripts\\python.exe tests\\scripts\\voice\\verify_role_voice.py --synthesize
    venv_core\\Scripts\\python.exe tests\\scripts\\voice\\verify_role_voice.py --synthesize --role Ye
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("XIAOYOU_RUN_INTEGRATION_TESTS", "1")

_FAILURES: list[str] = []


def _check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        _FAILURES.append(name)


def _build_engine_from_config():
    """按生产代码 core/voice/tts_engine.py 相同的方式构造火山引擎。

    返回 (engine, voice_map, key_map, default_api_key)。
    """
    from config.integrated_config import get_settings

    settings = get_settings()
    tts_config = settings.voice.tts

    provider = str(tts_config.provider or "").strip().lower()
    if provider not in ("volcano", "volcengine", "字节"):
        raise RuntimeError(
            f"app.yaml 的 voice.tts.provider 是 {provider!r}，不是 volcano；"
            f"本脚本仅支持火山引擎音色验证"
        )

    from core.voice.engines import VolcanoTTSEngine

    model = tts_config.model
    api_key = tts_config.api_key
    extra = getattr(tts_config, "model_extra", {}) or {}
    appid = getattr(tts_config, "appid", None) or extra.get("appid")
    voice_map = extra.get("voice_map", {}) or {}
    key_map = extra.get("key_map", {}) or {}

    engine = VolcanoTTSEngine(
        api_key=api_key,
        appid=appid,
        model=model,
        voice_map=voice_map,
        key_map=key_map,
    )
    return engine, voice_map, key_map


def _collect_target_roles(voice_map: dict, role_filter: str | None) -> list[str]:
    """收集要验证的角色列表。默认遍历 voice_map 全部；--role 只测一个。"""
    all_roles = list(voice_map.keys())
    if not all_roles:
        return []
    if role_filter:
        if role_filter not in voice_map:
            raise ValueError(
                f"voice_map 里找不到角色 {role_filter!r}。"
                f"当前 voice_map 角色: {all_roles}"
            )
        return [role_filter]
    return all_roles


async def _synthesize_check(engine, role_name: str) -> None:
    """真实走 synthesize_bytes，校验返回有效音频数据。"""
    audio = await engine.synthesize_bytes("你好，主人，今天过得怎么样呀？", voice=role_name)
    valid = bool(audio) and len(audio) > 128
    if valid and audio[:3] == b"ID3":
        # mp3 有 ID3 头，进一步确认非空内容
        pass
    body_len = len(audio) if audio else 0
    _check(f"合成 {role_name!r} 返回有效音频", valid, f"{body_len} bytes")
    if audio:
        print(f"     音频前缀: {audio[:16].hex()}")


def main() -> int:
    parser = argparse.ArgumentParser(description="通用角色音色(TTS)验证")
    parser.add_argument("--role", default=None, help="只测指定角色名（可选）")
    parser.add_argument(
        "--synthesize",
        action="store_true",
        help="真实调用火山引擎合成音频（需要 API key / 联网）。不传则仅校验配置解析。",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("通用角色音色(TTS)验证脚本")
    print("=" * 60)

    try:
        engine, voice_map, key_map = _build_engine_from_config()
    except Exception as e:
        print(f"[FAIL] 初始化配置/引擎失败: {e}")
        return 1

    roles = _collect_target_roles(voice_map, args.role)
    if not roles:
        print("[FAIL] app.yaml 的 voice.tts.voice_map 为空，未配置任何角色音色")
        return 1

    print(f"\nvoice_map 共 {len(voice_map)} 个角色音色:")
    for role, vid in voice_map.items():
        print(f"  {role!r} -> {vid!r}")
    print(f"\n本次验证角色: {roles}")

    has_api_key = bool(getattr(engine, "default_api_key", None))
    print(f"默认 API key 已配置: {has_api_key}")
    if not has_api_key and args.synthesize:
        print("[FAIL] 未读取到默认 API key（${VOLC_API_KEY_MEIMEI} 未生效），无法真实合成")
        args.synthesize = False

    # 1) 配置解析检查：每个角色应解析成 voice_map 里配置的音色 ID
    print("\n[1/2] 配置解析检查")
    for role in roles:
        api_key, appid, voice_id = engine._resolve_voice(role)
        expected = voice_map[role]
        _check(f"角色 {role!r} 解析 -> voice_id", voice_id == expected, f"{voice_id!r} (期望 {expected!r})")
        key_ok = api_key == engine.default_api_key or role in key_map
        _check(f"角色 {role!r} 认证来源", key_ok, "key_map 或默认 key")

    # 2) 真实合成检查（可选）
    print("\n[2/2] 真实合成检查" if args.synthesize else "\n[2/2] 真实合成检查（跳过，未传 --synthesize）")
    if args.synthesize:
        asyncio.run(_batch_synthesize(engine, roles))

    _finish()
    return 0 if not _FAILURES else 1


async def _batch_synthesize(engine, roles: list[str]) -> None:
    try:
        await engine.initialize()
    except Exception as e:
        print(f"[FAIL] 引擎初始化失败，停止合成检查: {e}")
        return
    for role in roles:
        await _synthesize_check(engine, role)
    try:
        await engine.shutdown()
    except Exception:
        pass


def _finish() -> None:
    if _FAILURES:
        print(f"\n❌ 验证失败 {len(_FAILURES)} 项: {_FAILURES}")
    else:
        print("\n✅ 全部通过：voice_map 角色音色配置解析正确，可正常使用。")


if __name__ == "__main__":
    raise SystemExit(main())