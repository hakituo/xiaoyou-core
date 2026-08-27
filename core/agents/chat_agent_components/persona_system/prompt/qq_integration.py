import json
import os
import re
from typing import Any, Dict, Optional

from .common import get_project_root

_QQ_ADAPTER_CONFIG_CACHE: Dict[str, Any] = {"mtime": 0.0, "data": {}}
_QQ_PUBLIC_TEMPLATE_CACHE: Dict[str, Any] = {"path": "", "mtime": 0.0, "template": ""}
_QQ_REACTION_DELAY_PROMPT = (
    "【QQ 气泡发送能力】\n"
    "- 你可以在某个要发送的气泡开头写 `[DELAY:2.5s]`，表示这个气泡发送前额外等待 2.5 秒。\n"
    "- 这是可选能力，只在需要表现反应时间、犹豫、回神、想了一下时使用，不要每条都加。\n"
    "- 这个额外等待是反应时间，不替代系统已有的打字速度延迟，两者可以同时存在。\n"
    "- 标签只用于控制发送节奏，不要向用户解释这件事。\n"
    "- 示例：`[DELAY:3s]嗯……我刚看到。`\n"
)

# 表情包标签说明模板（分类列表动态填入）
_QQ_MEME_TAG_PROMPT_TEMPLATE = (
    "【发表情包】\n"
    "想发表情包时，不用调用工具，直接在回复文字后面附上标签（和 [VOICE] 同理）：\n"
    "- `[MEME]` 随机发一张表情包\n"
    "- `[MEME:分类名]` 发指定分类的表情包\n"
    "  可用分类（即 data/memes/ 下的文件夹名，会自动同步，不要自创）：{categories}\n"
    "- `[MEME:自然语言描述]` 语义检索——当想要表达的画面无法用现有分类概括时，"
    "用一句话描述你想要的画面感觉，系统会从所有表情包里找最匹配的图。\n"
    "  示例：`[MEME:刚解决问题如释重负的样子]`、`[MEME:被萌到捂心口]`、"
    "`[MEME:得意地叉腰笑]`。描述要具体到动作/情绪，越精准越准。\n"
    "- 标签会被自动剥离，图片在它所在那句话之后立即发出（不是全部文字发完才补图），"
    "所以可以在任意句末插入标签，实现句中插图的效果。\n"
    "- 不想发表情包就不要带标签。\n"
)

# 普通表情包分类列表缓存（带 mtime，目录未变动时直接返回缓存）
_MEME_CATEGORIES_CACHE: Dict[str, Any] = {"mtime": 0.0, "categories": []}

def _load_qq_adapter_config() -> Dict[str, Any]:
    global _QQ_ADAPTER_CONFIG_CACHE
    try:
        project_root = get_project_root()
        cfg_path = os.path.join(project_root, "clients", "bots", "config.json")
        if not os.path.exists(cfg_path):
            return {}
        mtime = float(os.path.getmtime(cfg_path))
        if mtime and mtime == float(_QQ_ADAPTER_CONFIG_CACHE.get("mtime") or 0.0):
            data = _QQ_ADAPTER_CONFIG_CACHE.get("data")
            return data if isinstance(data, dict) else {}
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
        _QQ_ADAPTER_CONFIG_CACHE = {"mtime": mtime, "data": data}
        return data
    except Exception:
        return {}

def get_qq_master_id() -> str:
    env_val = str(os.getenv("XIAOYOU_QQ_MASTER_ID") or "").strip()
    if env_val:
        return env_val
    cfg = _load_qq_adapter_config()
    cfg_val = str(cfg.get("master_qq_id") or "").strip()
    return cfg_val or "123456789"

def _get_qq_public_persona_file() -> str:
    env_val = str(os.getenv("XIAOYOU_QQ_PUBLIC_PERSONA_FILE") or "").strip()
    if env_val:
        return env_val
    cfg = _load_qq_adapter_config()
    cfg_val = str(cfg.get("public_persona_file") or "").strip()
    if cfg_val:
        return cfg_val
    return os.path.normpath(
        os.path.join(
            get_project_root(),
            "core",
            "character",
            "configs",
            "qq",
            "Aveline_QQ_Group.json",
        )
    )

def extract_qq_user_id(conversation_id: Optional[str]) -> str:
    cid = str(conversation_id or "").strip()
    if not cid:
        return ""
    if cid.startswith("private_"):
        return cid[len("private_") :].strip()
    if cid.startswith("group_"):
        parts = cid.split("_")
        if len(parts) >= 3:
            return str(parts[-1] or "").strip()
    return ""

def load_public_qq_prompt_template() -> str:
    global _QQ_PUBLIC_TEMPLATE_CACHE
    persona_path = _get_qq_public_persona_file()
    try:
        mtime = float(os.path.getmtime(persona_path)) if os.path.exists(persona_path) else 0.0
    except Exception:
        mtime = 0.0
    if (
        str(_QQ_PUBLIC_TEMPLATE_CACHE.get("path") or "") == str(persona_path)
        and float(_QQ_PUBLIC_TEMPLATE_CACHE.get("mtime") or 0.0) == mtime
        and str(_QQ_PUBLIC_TEMPLATE_CACHE.get("template") or "").strip()
    ):
        return str(_QQ_PUBLIC_TEMPLATE_CACHE.get("template") or "")
    try:
        with open(persona_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        tmpl = ""
        if isinstance(data, dict):
            v = data.get("system_prompt_template")
            if isinstance(v, str):
                tmpl = v
        tmpl = str(tmpl or "").strip()
        if tmpl:
            _QQ_PUBLIC_TEMPLATE_CACHE = {"path": persona_path, "mtime": mtime, "template": tmpl}
            return tmpl
    except Exception:
        return ""
    return ""


def build_qq_reaction_delay_prompt() -> str:
    """返回 QQ 平台的可选反应延迟能力说明。"""
    return _QQ_REACTION_DELAY_PROMPT.strip()


def _scan_meme_categories() -> list[str]:
    """扫描 data/memes/ 一级子目录（排除 manual），返回分类名列表（带 mtime 缓存）。"""
    global _MEME_CATEGORIES_CACHE
    project_root = get_project_root()
    memes_root = os.path.join(project_root, "data", "memes")
    if not os.path.isdir(memes_root):
        return []
    try:
        mtime = float(os.path.getmtime(memes_root))
    except Exception:
        mtime = 0.0
    if mtime == _MEME_CATEGORIES_CACHE["mtime"] and _MEME_CATEGORIES_CACHE["categories"]:
        return _MEME_CATEGORIES_CACHE["categories"]
    cats: list[str] = []
    try:
        for name in sorted(os.listdir(memes_root)):
            p = os.path.join(memes_root, name)
            if os.path.isdir(p) and name.lower() != "manual":
                cats.append(name)
    except Exception:
        pass
    _MEME_CATEGORIES_CACHE = {"mtime": mtime, "categories": cats}
    return cats


def build_meme_tag_prompt() -> str:
    """返回 [MEME:分类] 表情包标签使用说明，分类列表动态扫描自 data/memes/。

    新增/改名/删除文件夹后自动同步（下次构建 prompt 时检测到 mtime 变化会重新扫描）。
    """
    cats = _scan_meme_categories()
    if not cats:
        return ""
    return _QQ_MEME_TAG_PROMPT_TEMPLATE.format(categories="、".join(cats)).strip()


# 私藏图库 / 媚黑图库标签说明（sensitive persona 在 websocket/Android 平台用）
_WEBSOCKET_IMG_TAG_PROMPT = (
    "【发送图片】\n"
    "想发私藏图库的图时，不用调用工具，直接在回复文字后面附上标签：\n"
    "- `[IMG]` 从私藏图库随机发 1 张图\n"
    "- `[IMG:3]` 发 3 张（1-5 张，超出范围自动收敛）\n"
    "- 标签会被自动剥离，图片在它所在那句话之后立即发出。\n"
    "- 不想发图就不要带标签。\n"
)

_WEBSOCKET_BM_TAG_PROMPT = (
    "【发送媚黑图】\n"
    "想发媚黑图库的图时，直接在回复文字后面附上标签：\n"
    "- `[BM]` 从媚黑图库随机发 1 张图\n"
    "- `[BM:3]` 发 3 张（1-5 张，超出范围自动收敛）\n"
    "- 标签会被自动剥离，图片在它所在那句话之后立即发出。\n"
)


def _is_sensitive_persona(persona_filename: str) -> bool:
    """判断是否 sensitive persona（路径含 /sensitive/）"""
    path_str = str(persona_filename or "").replace("\\", "/").lower()
    return "/sensitive/" in path_str or path_str.startswith("sensitive/")


def apply_qq_optimizations(template: str, user_id: str, current_persona_filename: str) -> str:
    """应用平台特定的 Prompt 优化和媒体标签注入

    - QQ 平台（user_id 含 group_/private_ 前缀）：原有 QQ 专属裁剪 + [MEME] 标签注入
    - websocket/Android 平台（user_id 含 shared__persona__ 前缀，跨平台共享 cid）：
      注入 [MEME] 标签说明；sensitive persona 额外注入 [IMG]/[BM] 标签说明
    """
    is_qq_source = bool(user_id and ("group_" in str(user_id) or "private_" in str(user_id)))
    is_shared_source = bool(user_id and str(user_id).startswith("shared__persona__"))

    if not is_qq_source and not is_shared_source:
        return template

    # QQ 专属裁剪（仅 QQ 源）
    if is_qq_source:
        is_dedicated_qq_persona = "/configs/qq/" in current_persona_filename.replace("\\", "/").lower()
        if not is_dedicated_qq_persona:
            template = re.sub(r"- (环境描写|场景构建|旁白感|第三人称叙述).*?\n", "", template, flags=re.IGNORECASE)
            template = re.sub(
                r"[^\n\r]*动作与神态描写(?:必须|可用)用全角括\s*号[^\n\r]*\r?\n?",
                "",
                template,
                flags=re.IGNORECASE,
            )
            template = re.sub(
                r"[^\n\r]*动作描写必须用全角括\s*号[^\n\r]*\r?\n?",
                "",
                template,
                flags=re.IGNORECASE,
            )

            def prune_long_descriptions(match):
                desc = match.group(0) or ""
                if not desc:
                    return ""
                if desc.startswith("*") and desc.endswith("*"):
                    inner = desc[1:-1]
                    if inner.strip():
                        return ""
                    return desc
                if (desc.startswith("(") and desc.endswith(")")) or (
                    desc.startswith("（") and desc.endswith("）")
                ):
                    inner = desc[1:-1]
                    if not inner.strip():
                        return desc
                    if re.search(r"[\u4e00-\u9fff]", inner) and len(inner) > 6:
                        return ""
                    if len(desc) > 18 and re.search(r"[A-Za-z0-9]", inner):
                        return ""
                return desc

            template = re.sub(r"\(.*?\)|（.*?）|\*.*?\*", prune_long_descriptions, template)

    # QQ 反应延迟标签说明（仅 QQ 源）
    if is_qq_source:
        capability_prompt = build_qq_reaction_delay_prompt()
        if capability_prompt and capability_prompt not in template:
            template = f"{str(template or '').rstrip()}\n\n{capability_prompt}"

    # 注入 [MEME:分类] 表情包标签说明（QQ 和 websocket 平台都需要）
    meme_prompt = build_meme_tag_prompt()
    if meme_prompt and meme_prompt not in template:
        template = f"{str(template or '').rstrip()}\n\n{meme_prompt}"

    # websocket/Android 平台 + sensitive persona：额外注入 [IMG]/[BM] 标签说明
    if is_shared_source and _is_sensitive_persona(current_persona_filename):
        if _WEBSOCKET_IMG_TAG_PROMPT.strip() and _WEBSOCKET_IMG_TAG_PROMPT not in template:
            template = f"{str(template or '').rstrip()}\n\n{_WEBSOCKET_IMG_TAG_PROMPT.strip()}"
        if _WEBSOCKET_BM_TAG_PROMPT.strip() and _WEBSOCKET_BM_TAG_PROMPT not in template:
            template = f"{str(template or '').rstrip()}\n\n{_WEBSOCKET_BM_TAG_PROMPT.strip()}"

    return template
