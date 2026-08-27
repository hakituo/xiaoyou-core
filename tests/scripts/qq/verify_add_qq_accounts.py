# -*- coding: utf-8 -*-
"""验证新增两个 QQ 账号（Frost / Coco）接入是否正确。

真实 QQ 号不在此文件硬编码，运行时从已 gitignore 的
core/character/configs/sensitive/qq_accounts_secret.json 读取。

校验点：
1. clients/bots/multi_qq_config.json 已含 rushuang/yeye 角色配置（端口 3003/3004、人设文件存在）
2. .env 已配置 XIAOYOU_QQ_BOT_NUMBER_RUSHUANG/YEYE 与 DEEPSEEK_API_KEY_Rushuang/Yeye
3. NapCat 配置文件（onebot11_<qq>.json）存在且 WebSocket 端口匹配 3003/3004
4. personas.py 已注册 yeye/rushuang（get_all_role_ids / get_peer_role_ids）
5. good_morning/goodnight _ROLE_PERSONA_MAP 已含 yeye/rushuang
6. sleep_manager _ACTIVE_CARE_ENABLED_ROLES 已含 yeye/rushuang
7. 模型路径 cloud:deepseek:yeye/rushuang:... 能注册（对应 API key 存在）

运行方式：
    venv_core/Scripts/python.exe tests/scripts/qq/verify_add_qq_accounts.py
"""
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

NEW_ACCOUNTS = {
    "rushuang": {"port": 3003, "persona": "sensitive/Frost.json"},
    "yeye": {"port": 3004, "persona": "qq/Yeye.json"},
}

# 真实 QQ 号存于 gitignored 的 sensitive 目录，运行测试时从这里读取，不硬编码进仓库
SECRET_QQ_FILE = PROJECT_ROOT / "core" / "character" / "configs" / "sensitive" / "qq_accounts_secret.json"


def _load_secret_qq() -> dict:
    """从 gitignored 的 sensitive 目录读取真实 QQ 号（避免硬编码进仓库）。"""
    try:
        return json.loads(SECRET_QQ_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"  [WARN] 读取敏感 QQ 配置文件失败 {SECRET_QQ_FILE}: {exc}")
        return {}


def _load_dotenv_dict(path: Path) -> dict:
    """轻量解析 .env（兼容 KEY=VAL 与 # 注释），避免外部依赖"""
    result = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        result[key.strip()] = val.strip()
    return result


def _check(cond: bool, msg: str, failures: list) -> None:
    if cond:
        print(f"  [PASS] {msg}")
    else:
        print(f"  [FAIL] {msg}")
        failures.append(msg)


def main() -> int:
    failures: list = []

    # 真实 QQ 号来自 gitignored 的 sensitive 文件，避免硬编码进仓库
    secret_qq = _load_secret_qq()
    for rid in NEW_ACCOUNTS:
        NEW_ACCOUNTS[rid]["qq"] = secret_qq.get(rid)

    print("=" * 60)
    print("验证新增 QQ 账号接入（Frost + Coco）")
    print("=" * 60)

    # ---- 1. multi_qq_config.json ----
    print("\n=== 1. multi_qq_config.json 角色配置 ===")
    cfg_path = PROJECT_ROOT / "clients" / "bots" / "multi_qq_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    for rid, info in NEW_ACCOUNTS.items():
        role = cfg.get(rid)
        _check(role is not None, f"{rid} 角色已配置", failures)
        if role:
            _check(
                str(role.get("napcat_ws_url", "")).endswith(f":{info['port']}"),
                f"{rid} NapCat 端口 = {info['port']}",
                failures,
            )
            persona = role.get("persona_filename", "")
            persona_exists = (PROJECT_ROOT / "core" / "character" / "configs" / persona).exists()
            _check(persona == info["persona"] and persona_exists,
                   f"{rid} 人设 {persona} 存在", failures)
            _check(bool(role.get("default_model_name")), f"{rid} 默认模型已配置", failures)

    # ---- 2. .env ----
    print("\n=== 2. .env 环境变量 ===")
    env = _load_dotenv_dict(PROJECT_ROOT / ".env")
    for rid, info in NEW_ACCOUNTS.items():
        env_key = f"XIAOYOU_QQ_BOT_NUMBER_{rid.upper()}"
        _check(env.get(env_key) == info["qq"], f"{env_key}={info['qq']}", failures)
        api_key = f"DEEPSEEK_API_KEY_{rid.capitalize()}"
        _check(bool(env.get(api_key)), f"{api_key} 已配置", failures)

    # ---- 3. NapCat 配置文件 ----
    print("\n=== 3. NapCat onebot11 配置文件 ===")
    napcat_cfg_dir = (
        PROJECT_ROOT / "external" / "NapCatQQ-main" / "packages" / "napcat-shell" / "dist" / "config"
    )
    for rid, info in NEW_ACCOUNTS.items():
        np_path = napcat_cfg_dir / f"onebot11_{info['qq']}.json"
        _check(np_path.exists(), f"{np_path.name} 存在", failures)
        if np_path.exists():
            np_cfg = json.loads(np_path.read_text(encoding="utf-8"))
            ports = [
                srv.get("port")
                for srv in np_cfg.get("network", {}).get("websocketServers", [])
            ]
            _check(info["port"] in ports, f"{np_path.name} WS 端口含 {info['port']}", failures)

    # ---- 4. personas.py 注册 ----
    print("\n=== 4. personas.py 角色注册 ===")
    try:
        from core.services.dual_role.personas import (
            get_all_role_ids,
            get_peer_role_ids,
            get_persona,
        )
        all_ids = get_all_role_ids()
        for rid, info in NEW_ACCOUNTS.items():
            _check(rid in all_ids, f"get_all_role_ids 含 {rid}", failures)
            p = get_persona(rid)
            _check(p is not None and p.scope == rid, f"get_persona('{rid}') scope={rid}", failures)
        # N 角色互聊：互相能看到对方
        _check("yeye" in get_peer_role_ids("rushuang"), "rushuang 的 peer 含 yeye", failures)
        _check("rushuang" in get_peer_role_ids("yeye"), "yeye 的 peer 含 rushuang", failures)
        _check("ling" in get_peer_role_ids("aveline"), "aveline 的 peer 仍含 ling（向后兼容）", failures)
    except Exception as e:
        _check(False, f"personas.py 导入/校验异常: {e}", failures)

    # ---- 5. 主动关怀 _ROLE_PERSONA_MAP ----
    print("\n=== 5. good_morning/goodnight _ROLE_PERSONA_MAP ===")
    try:
        import core.services.active_care.good_morning_proactive as gm
        import core.services.active_care.goodnight_proactive as gn
        for rid, info in NEW_ACCOUNTS.items():
            _check(
                gm._ROLE_PERSONA_MAP.get(rid) == info["persona"],
                f"good_morning {rid} -> {info['persona']}",
                failures,
            )
            _check(
                gn._ROLE_PERSONA_MAP.get(rid) == info["persona"],
                f"goodnight {rid} -> {info['persona']}",
                failures,
            )
        # 未知角色仍不 fallback（防回归）
        _check(gm._resolve_persona_filename("xiaolu") is None,
               "未知角色 xiaolu 不 fallback（防回归）", failures)
    except Exception as e:
        _check(False, f"主动关怀 _ROLE_PERSONA_MAP 校验异常: {e}", failures)

    # ---- 6. sleep_manager 白名单 ----
    print("\n=== 6. sleep_manager 白名单 ===")
    try:
        import core.services.life_simulation.sleep_manager as sm
        for rid in NEW_ACCOUNTS:
            _check(rid in sm._ACTIVE_CARE_ENABLED_ROLES,
                   f"_ACTIVE_CARE_ENABLED_ROLES 含 {rid}", failures)
    except Exception as e:
        _check(False, f"sleep_manager 白名单校验异常: {e}", failures)

    # ---- 7. 模型路径注册 ----
    print("\n=== 7. DeepSeek key 别名 ===")
    try:
        from config.settings_model import _load_cloud_provider_keys_from_env
        keys = _load_cloud_provider_keys_from_env()
        ds = keys.get("deepseek", {})
        for rid in NEW_ACCOUNTS:
            _check(rid in ds, f"deepseek key 别名含 {rid}", failures)
    except Exception as e:
        _check(False, f"模型 key 别名校验异常: {e}", failures)

    print("\n" + "=" * 60)
    if failures:
        print(f"结果: {len(failures)} 项失败")
        for f in failures:
            print(f"  - {f}")
        print("=" * 60)
        return 1
    print("结果: 全部通过")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
