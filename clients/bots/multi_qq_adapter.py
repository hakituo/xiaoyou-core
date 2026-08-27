import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", ".."))

# 添加项目根目录到 sys.path，确保可以导入 clients 模块
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

env_path = os.path.join(PROJECT_ROOT, ".env")
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    load_dotenv()

for proxy_key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(proxy_key, None)
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

from clients.bots.qq.config import QQAdapterConfig  # noqa: E402
from clients.bots.qq.main import QQAdapter  # noqa: E402


def load_multi_config():
    # P2-2: 通过 pydantic model 统一加载入口（环境变量覆盖逻辑已收敛到 get_multi_qq_raw_dict）
    from config.settings_adapters import get_multi_qq_raw_dict

    raw = get_multi_qq_raw_dict()
    if not raw:
        logger.error("多QQ配置为空或加载失败（请检查 clients/bots/multi_qq_config.json）")
        sys.exit(1)

    if not isinstance(raw, dict):
        logger.error("multi_qq_config.json 格式错误，期望 dict")
        sys.exit(1)

    # 环境变量覆盖（保留原逻辑：QQAdapterConfig.from_dict 不读 env，需在外部覆盖）
    master_qq_id = os.getenv("XIAOYOU_QQ_MASTER_ID", "").strip()
    xiaoyou_access_token = os.getenv("XIAOYOU_ACCESS_TOKEN", "").strip()
    napcat_access_token = os.getenv("NAPCAT_ACCESS_TOKEN", "").strip()
    group_id = os.getenv("XIAOYOU_QQ_GROUP_ID", "").strip()
    # 向后兼容:aveline/ling 用旧 env var 名
    aveline_qq = os.getenv("XIAOYOU_QQ_BOT_NUMBER", "").strip()
    ling_qq = os.getenv("XIAOYOU_QQ_BOT_NUMBER_LING", "").strip()

    # N 角色通用:收集每个角色自己的 QQ 号(从 env var XIAOYOU_QQ_BOT_NUMBER_{ROLE_ID_UPPER})
    # 注意:角色自己的 QQ 号不存到 QQAdapterConfig(无该字段),仅用于填充其他角色的 peer_qq_id
    # 向后兼容:aveline/ling 已单独读取
    role_own_qq = {
        "aveline": aveline_qq,
        "ling": ling_qq,
    }
    # 扫描所有 XIAOYOU_QQ_BOT_NUMBER_* 环境变量
    for env_key, env_val in os.environ.items():
        if env_key.startswith("XIAOYOU_QQ_BOT_NUMBER_"):
            # 提取 role_id(去掉前缀,转小写)
            role_suffix = env_key[len("XIAOYOU_QQ_BOT_NUMBER_"):].lower()
            if role_suffix and env_val.strip():
                role_own_qq[role_suffix] = env_val.strip()

    configs = {}
    for role_id, role_cfg in raw.items():
        if not isinstance(role_cfg, dict):
            continue
        cfg = QQAdapterConfig.from_dict(role_cfg, role_id=role_id)
        if master_qq_id and not cfg.master_qq_id:
            cfg.master_qq_id = master_qq_id
        if xiaoyou_access_token and not cfg.xiaoyou_access_token:
            cfg.xiaoyou_access_token = xiaoyou_access_token
        if napcat_access_token and not cfg.napcat_access_token:
            cfg.napcat_access_token = napcat_access_token
        if group_id and not cfg.group_id:
            cfg.group_id = group_id
        # peer_qq_id 自动填充:取第一个其他角色的 own QQ(向后兼容原双角色逻辑)
        # 原逻辑:aveline 的 peer = ling_qq, ling 的 peer = aveline_qq
        # N 角色系统:遍历 role_own_qq,选第一个非自己的 QQ 填入 peer_qq_id
        # (真正的多 peer 解析在 peer_chat_scheduler 里从 config 动态读)
        if not cfg.peer_qq_id:
            for other_role_id, other_own_qq in role_own_qq.items():
                if other_role_id == role_id:
                    continue
                if other_own_qq:
                    cfg.peer_qq_id = other_own_qq
                    break
        configs[role_id] = cfg

    return configs


async def run_multi():
    configs = load_multi_config()

    if not configs:
        logger.error("未找到任何角色配置")
        sys.exit(1)

    adapters = {}
    for role_id, cfg in configs.items():
        logger.info(
            "初始化角色: %s (NapCat=%s, Persona=%s)",
            cfg.role_name or role_id,
            cfg.napcat_ws_url,
            cfg.persona_filename,
        )
        adapters[role_id] = QQAdapter(adapter_config=cfg)

    tasks = []
    for role_id, adapter in adapters.items():
        tasks.append(asyncio.create_task(adapter.run(), name=f"adapter_{role_id}"))

    try:
        from core.tools.notify_master_tool import register_qq_adapters
        register_qq_adapters(adapters)
    except Exception as e:
        logger.warning("注册QQ适配器到NotifyMasterTool失败: %s", e, exc_info=True)

    logger.info(
        "多QQ适配器已启动 (%d 个角色，互聊由Active Care调度)",
        len(adapters),
    )
    logger.info(
        "角色: %s",
        ", ".join(
            f"{cfg.role_name or rid}({cfg.napcat_ws_url})" for rid, cfg in configs.items()
        ),
    )

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
    for task in done:
        if task.exception():
            role_name = task.get_name()
            logger.error("%s 异常退出: %s", role_name, task.exception(), exc_info=task.exception())
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)


if __name__ == "__main__":
    # 配置日志格式，与项目其他模块保持一致
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    try:
        asyncio.run(run_multi())
    except KeyboardInterrupt:
        logger.info("多QQ适配器已停止")
    except Exception as e:
        logger.fatal("多QQ适配器异常退出: %s", e, exc_info=True)
        if os.name == "nt":
            input("按回车键退出...")
