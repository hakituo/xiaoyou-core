# -*- coding: utf-8 -*-
"""验证新增 QQ 账号（Frost / Ye）接入是否正确。

真实 QQ 号不在此文件硬编码，运行时从已 gitignore 的
core/character/configs/sensitive/qq_accounts_secret.json 读取。

历史说明：原Coco（yeye）账号 QQ 123456789 已切换为Ye（ye），
本测试同步改为校验 ye；secret 文件缺失时 QQ 号相关检查降级为 WARN。

校验点：
1. clients/bots/multi_qq_config.json 已含 rushuang/ye 角色配置（端口 3003/3004、人设文件存在）
2. .env 已配置 XIAOYOU_QQ_BOT_NUMBER_RUSHUANG/YE 与 DEEPSEEK_API_KEY_Rushuang/Yeye
3. NapCat 配置文件（onebot11_<qq>.json）存在且 WebSocket 端口匹配 3003/3004
4. personas.py 已注册 ye/rushuang（get_all_role_ids / get_peer_role_ids）
5. good_morning/goodnight 的 QQ 人设解析（personas.get_qq_persona_filename，权威源 multi_qq_config.json）已含 ye/rushuang
6. sleep_manager _ACTIVE_CARE_ENABLED_ROLES 配置驱动（app.yaml）
7. 模型路径 cloud:deepseek:yeye/rushuang:... 能注册（对应 API key 存在）

运行方式：
    venv_core/Scripts/python.exe tests/scripts/qq/verify_add_qq_accounts.py
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

NEW_ACCOUNTS = {
    "rushuang": {
        "port": 3003,
        "persona": "legacy/Frost/Frost.json",
        "api_key_env": "DEEPSEEK_API_KEY_Rushuang",
        "key_alias": "rushuang",
        "in_active_care": False,
    },
    "ye": {
        "port": 3004,
        "persona": "core_ye.json",
        "api_key_env": "DEEPSEEK_API_KEY_Yeye",
        # DEEPSEEK_API_KEY_Yeye 按环境变量后缀小写生成别名 yeye（非 ye）
        "key_alias": "yeye",
        "in_active_care": True,
    },
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
            # 兼容 v2 分层人设（如 ye/core_ye.json，入口文件名 core_ye.json 也算存在）
            from core.character.managers.persona_manager import PersonaManager

            persona_exists = PersonaManager()._persona_file_exists(persona)
            _check(persona == info["persona"] and persona_exists,
                   f"{rid} 人设 {persona} 存在", failures)
            _check(bool(role.get("default_model_name")), f"{rid} 默认模型已配置", failures)

    # ---- 2. .env ----
    print("\n=== 2. .env 环境变量 ===")
    env = _load_dotenv_dict(PROJECT_ROOT / ".env")
    for rid, info in NEW_ACCOUNTS.items():
        env_key = f"XIAOYOU_QQ_BOT_NUMBER_{rid.upper()}"
        if info["qq"] is None:
            print(f"  [WARN] {rid} 缺少真实 QQ 号（secret 文件缺失），跳过 {env_key} 数值比对")
        else:
            _check(env.get(env_key) == info["qq"], f"{env_key}={info['qq']}", failures)
        _check(bool(env.get(env_key)), f"{env_key} 已配置", failures)
        _check(bool(env.get(info["api_key_env"])), f"{info['api_key_env']} 已配置", failures)

    # ---- 3. NapCat 配置文件 ----
    print("\n=== 3. NapCat onebot11 配置文件 ===")
    napcat_cfg_dir = (
        PROJECT_ROOT / "external" / "NapCatQQ-main" / "packages" / "napcat-shell" / "dist" / "config"
    )
    for rid, info in NEW_ACCOUNTS.items():
        if info["qq"] is None:
            print(f"  [WARN] {rid} 缺少真实 QQ 号（secret 文件缺失），跳过 NapCat 配置检查")
            continue
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
        # 互聊门禁：peer = ROOMMATE_RELATIONS 注册的相互认识角色（aveline↔ling），
        # 未注册室友关系的角色（rushuang/yeye/ye）不参与 peer chat
        _check(get_peer_role_ids("rushuang") == [], "rushuang 无 peer（未注册室友关系）", failures)
        _check(get_peer_role_ids("yeye") == [], "yeye 无 peer（未注册室友关系）", failures)
        _check("ling" in get_peer_role_ids("aveline"), "aveline 的 peer 仍含 ling（向后兼容）", failures)
    except Exception as e:
        _check(False, f"personas.py 导入/校验异常: {e}", failures)

    # ---- 5. 主动关怀 QQ 人设解析 ----
    print("\n=== 5. good_morning/goodnight QQ 人设解析 ===")
    try:
        import core.services.active_care.good_morning_proactive as gm
        import core.services.active_care.goodnight_proactive as gn
        for rid, info in NEW_ACCOUNTS.items():
            _check(
                gm._resolve_persona_filename(rid) == info["persona"],
                f"good_morning {rid} -> {info['persona']}",
                failures,
            )
            _check(
                gn._resolve_persona_filename(rid) == info["persona"],
                f"goodnight {rid} -> {info['persona']}",
                failures,
            )
        # 未知角色仍不 fallback（防回归）
        _check(gm._resolve_persona_filename("xiaolu") is None,
               "未知角色 xiaolu 不 fallback（防回归）", failures)
    except Exception as e:
        _check(False, f"主动关怀 QQ 人设解析校验异常: {e}", failures)

    # ---- 6. sleep_manager 白名单 ----
    print("\n=== 6. sleep_manager 白名单 ===")
    # 断言更新说明：自主角色白名单已统一迁移到 character_runtime.yaml
    # （core/character/runtime_roles.py 是唯一资格入口）；
    # rushuang/yeye 不在白名单中（未接入主动关怀），按新语义校验。
    try:
        from core.character.runtime_roles import get_autonomous_role_ids

        autonomous_roles = set(get_autonomous_role_ids())
        # 白名单由 character_runtime.yaml 配置驱动，只断言稳定基线与账号期望，
        # 不硬编码完整名单（ling 是否在列由配置决定）。
        _check("aveline" in autonomous_roles,
               "自主角色白名单含 aveline（基线常驻角色）", failures)
        for rid, info in NEW_ACCOUNTS.items():
            _check(
                (rid in autonomous_roles) == info["in_active_care"],
                f"{rid} 主动关怀白名单状态 = {info['in_active_care']}（由 character_runtime.yaml 配置驱动）",
                failures,
            )
    except Exception as e:
        _check(False, f"sleep_manager 白名单校验异常: {e}", failures)

    # ---- 7. 模型路径注册 ----
    print("\n=== 7. DeepSeek key 别名 ===")
    try:
        from config.settings_model import _load_cloud_provider_keys_from_env
        keys = _load_cloud_provider_keys_from_env()
        ds = keys.get("deepseek", {})
        for rid, info in NEW_ACCOUNTS.items():
            _check(info["key_alias"] in ds, f"deepseek key 别名含 {info['key_alias']}（{rid}）", failures)
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
