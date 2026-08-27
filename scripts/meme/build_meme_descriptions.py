"""表情包描述生成脚本（离线一次性）

遍历 data/memes/ 下所有图片（排除 manual/），调用 SiliconFlow VL 模型
给每张图生成中文 caption，输出到 data/memes/_index/descriptions.json。

特性：
- 增量处理：已生成 caption 的图片不重复处理
- 失败重试：每张图最多重试 2 次
- 限速：复用 SiliconFlowClient 内置速率限制
- 支持断点续传：随时 Ctrl+C，下次继续
- 支持 --only 子目录参数，只处理指定分类

用法：
    python -m scripts.meme.build_meme_descriptions
    python -m scripts.meme.build_meme_descriptions --force  # 强制重建
    python -m scripts.meme.build_meme_descriptions --only normal  # 只处理 normal 子目录
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

# 支持直接运行（python scripts/meme/build_meme_descriptions.py）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.logger import get_logger

logger = get_logger("build_meme_descriptions")

# 输入：表情包根目录
MEMES_ROOT = PROJECT_ROOT / "data" / "memes"
# 排除的子目录（小写匹配）
EXCLUDED_DIRS = {"manual", "_index"}
# 输出目录
INDEX_DIR = MEMES_ROOT / "_index"
DESCRIPTIONS_PATH = INDEX_DIR / "descriptions.json"

# 支持的图片扩展名
SUPPORTED_EXTS = (".gif", ".jpg", ".jpeg", ".png", ".webp")

# VL 询问 prompt（场景导向，参考增强版 semantic_metadata 的 caption 结构）
# 关键：让 VL 生成"使用场景"描述，而非纯客观画面描述，
# 这样 LLM 查询时（如 [MEME:被气到想打人]）才能语义匹配到对应的图
VL_PROMPT = (
    "你是表情包语义分析专家。这张表情包将用于语义检索——"
    "用户会用自然语言描述想表达的情绪/场景来搜索表情包。\n\n"
    "请分析图片并严格按以下格式输出（不要 markdown，不要多余解释）：\n\n"
    "CAPTION: <先简述画面（角色、动作、表情、画面文字），"
    "再用\"常在...时使用\"句式说明这张图适合的对话场景>\n"
    "TAGS: <3-8个关键词，顿号分隔，涵盖情绪、动作、使用场景>\n"
    "TEXT: <画面中的文字，无则写\"无\">\n\n"
    "示例：\n"
    "CAPTION: 卡通女仆张嘴伸手喊「别让我逮到你」，恼火中带玩笑的追打姿态。"
    "常在被对方气到、对方闯祸后用来抱怨算账，表示\"等着瞧\"的激烈反对。\n"
    "TAGS: 愤怒威胁、恼火追打、半开玩笑算账、抱怨反对、被气到\n"
    "TEXT: 别让我逮到你"
)

# VL 中转模型（SiliconFlow 已禁用 Qwen3-VL-235B-A22B-Thinking，改用 32B-Instruct）
VL_VISION_MODEL = "Qwen/Qwen3-VL-32B-Instruct"


def _list_meme_images(only: Optional[str] = None) -> list[Path]:
    """扫描 data/memes/ 下所有图片（排除 manual、_index），返回 Path 列表。

    支持两种目录结构：
    - memes/<cat>/*.png  （一级子目录直接放图片）
    - memes/<cat>/<sub>/*.png  （二级子目录，如 normal/2/*.png）

    Args:
        only: 若指定子目录名（如 "normal"），则只扫描该子目录
    """
    if not MEMES_ROOT.is_dir():
        return []
    images: list[Path] = []

    if only:
        sub = MEMES_ROOT / only
        if not sub.is_dir():
            logger.error(f"子目录不存在: {sub}")
            return []
        targets = [sub]
    else:
        targets = [
            sub
            for sub in sorted(MEMES_ROOT.iterdir())
            if sub.is_dir() and sub.name.lower() not in EXCLUDED_DIRS
        ]

    for sub in targets:
        # 递归扫描所有图片（rglob 自动处理 1 级或 2 级子目录）
        for img in sorted(sub.rglob("*")):
            if img.is_file() and img.suffix.lower() in SUPPORTED_EXTS:
                # 排除 _index 和 manual 目录下的文件
                if any(
                    part.lower() in EXCLUDED_DIRS for part in img.relative_to(MEMES_ROOT).parts
                ):
                    continue
                images.append(img)
    return images


def _encode_image_b64(path: Path) -> Optional[str]:
    """读取图片并编码为 data URL。"""
    ext = path.suffix.lower().lstrip(".")
    if ext == "jpg":
        mime = "image/jpeg"
    elif ext == "webp":
        mime = "image/webp"
    else:
        mime = f"image/{ext}"
    try:
        with open(path, "rb") as f:
            data = f.read()
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except Exception as e:
        logger.error(f"读取图片失败 {path}: {e}")
        return None


def _load_existing() -> dict[str, dict[str, Any]]:
    """加载已生成的描述，返回 {相对路径: {caption, tags, text}}。

    兼容三种旧格式：
    - v1: items: [{path, caption(str)}]
    - v2: items: [{path, caption(str), tags, text}]
    - 旧 dict: {rel_path: caption(str)}
    """
    if not DESCRIPTIONS_PATH.is_file():
        return {}
    try:
        with open(DESCRIPTIONS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "items" in data:
            items = data["items"]
        elif isinstance(data, dict):
            items = data
        else:
            return {}
        result: dict[str, dict[str, Any]] = {}
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                p = item.get("path") or item.get("rel_path")
                if not p:
                    continue
                p = str(p)
                cap = item.get("caption") or item.get("description") or ""
                tags = item.get("tags") or []
                text = item.get("text") or item.get("visible_text") or ""
                if cap:
                    result[p] = {
                        "caption": str(cap),
                        "tags": list(tags) if isinstance(tags, list) else [],
                        "text": str(text),
                    }
        elif isinstance(items, dict):
            for k, v in items.items():
                if isinstance(v, str):
                    result[str(k)] = {"caption": v, "tags": [], "text": ""}
                elif isinstance(v, dict):
                    cap = v.get("caption") or v.get("description") or ""
                    if cap:
                        result[str(k)] = {
                            "caption": str(cap),
                            "tags": list(v.get("tags") or []),
                            "text": str(v.get("text") or ""),
                        }
        return result
    except Exception as e:
        logger.warning(f"加载已有描述失败，将从头开始: {e}")
        return {}


def _save_descriptions(descs: dict[str, dict[str, Any]]) -> None:
    """保存描述到 JSON，格式 {version, model, count, items: [{path, caption, tags, text}]}。"""
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for path, info in sorted(descs.items()):
        items.append({
            "path": path,
            "caption": info.get("caption", ""),
            "tags": info.get("tags", []),
            "text": info.get("text", ""),
        })
    payload = {
        "version": 2,
        "model": VL_VISION_MODEL,
        "count": len(items),
        "items": items,
    }
    tmp_path = DESCRIPTIONS_PATH.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, DESCRIPTIONS_PATH)
    logger.info(f"已保存 {len(items)} 条描述到 {DESCRIPTIONS_PATH}")


def _parse_vl_output(text: str) -> Optional[dict[str, Any]]:
    """解析 VL 模型的三段式输出（CAPTION / TAGS / TEXT）。

    宽容匹配：不区分大小写、允许换行、允许字段缺失。
    """
    if not text or not text.strip():
        return None
    # CAPTION: 匹配到下一个大写字段标签或行尾
    cap_match = re.search(
        r"CAPTION\s*[:：]\s*(.*?)(?=\s*(?:TAGS|TEXT)\s*[:：]|\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    tags_match = re.search(
        r"TAGS\s*[:：]\s*(.*?)(?=\s*(?:CAPTION|TEXT)\s*[:：]|\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    text_match = re.search(
        r"TEXT\s*[:：]\s*(.*?)(?=\s*(?:CAPTION|TAGS)\s*[:：]|\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    caption = cap_match.group(1).strip() if cap_match else ""
    tags_raw = tags_match.group(1).strip() if tags_match else ""
    visible_text = text_match.group(1).strip() if text_match else ""

    # 兜底：如果完全没匹配到 CAPTION 标签，整段当 caption（兼容旧 prompt 输出）
    if not caption and not tags_raw and not visible_text:
        caption = text.strip()

    # 解析 tags（顿号/逗号分隔）
    tags: list[str] = []
    if tags_raw:
        for t in re.split(r"[、,，]", tags_raw):
            t = t.strip()
            if t and t != "无":
                tags.append(t)

    # TEXT 写"无"时清空
    if visible_text in ("无", "none", "None", ""):
        visible_text = ""

    if not caption:
        return None
    return {"caption": caption, "tags": tags, "text": visible_text}


async def _describe_one(client, image_path: Path) -> Optional[dict[str, Any]]:
    """调 SiliconFlowClient._vision_inference 给一张图生成场景导向描述。

    返回 {caption, tags, text} 或 None。
    """
    data_url = _encode_image_b64(image_path)
    if not data_url:
        return None
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": VL_PROMPT},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }
    ]
    # max_tokens 提到 220：场景描述 + tags + text 需要更多 token
    result = await client._vision_inference(messages, max_tokens=220, temperature=0.4)
    if result.get("status") != "success":
        logger.error(f"VL 失败 {image_path.name}: {result.get('error')}")
        return None
    raw = str(result.get("text") or "").strip()
    parsed = _parse_vl_output(raw)
    if parsed:
        logger.info(f"  → {parsed.get('caption', '')[:50]}...")
    return parsed


async def run(
    force: bool = False,
    only: Optional[str] = None,
    limit: Optional[int] = None,
) -> int:
    """主流程。返回处理的图片数。"""
    # 延迟导入避免循环依赖
    from core.llm.siliconflow_client import SiliconFlowClient

    images = _list_meme_images(only=only)
    if not images:
        logger.error(f"未在 {MEMES_ROOT} 找到任何图片")
        return 0
    if limit and limit > 0:
        images = images[:limit]
        logger.info(f"限制处理前 {limit} 张")

    existing = {} if force else _load_existing()
    logger.info(f"扫描到 {len(images)} 张图片，已有描述 {len(existing)} 条")

    client = SiliconFlowClient(vision_model=VL_VISION_MODEL)
    # Qwen3-VL-32B-Instruct 生成场景描述偶尔需要超过 60s，提到 120s
    client.timeout = 120
    if not client.api_key:
        logger.error("未设置 SILICONFLOW_API_KEY 环境变量，无法调用 VL 模型")
        return 0

    descs: dict[str, dict[str, Any]] = dict(existing) if not force else {}
    processed = 0
    failed: list[str] = []

    for idx, img in enumerate(images, 1):
        rel = str(img.relative_to(MEMES_ROOT)).replace(os.sep, "/")
        if rel in descs and descs[rel].get("caption"):
            continue
        logger.info(f"[{idx}/{len(images)}] {rel}")
        info: Optional[dict[str, Any]] = None
        for attempt in range(2):
            try:
                info = await _describe_one(client, img)
                if info:
                    break
            except Exception as e:
                logger.warning(f"  尝试 {attempt+1} 失败: {e}")
                await asyncio.sleep(1.0)
        if info:
            descs[rel] = info
            processed += 1
            # 每 10 张保存一次，支持断点续传
            if processed % 10 == 0:
                _save_descriptions(descs)
        else:
            failed.append(rel)

    _save_descriptions(descs)
    if failed:
        logger.warning(f"{len(failed)} 张图描述失败：{failed[:5]}...")
    logger.info(f"完成：新增 {processed} 条，累计 {len(descs)} 条，失败 {len(failed)} 条")
    return processed


def main() -> int:
    parser = argparse.ArgumentParser(description="生成表情包中文描述")
    parser.add_argument(
        "--force", action="store_true", help="强制重建（忽略已有描述）"
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="只处理指定子目录（如 normal），不指定则处理全部",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="只处理前 N 张（测试用）",
    )
    args = parser.parse_args()
    count = asyncio.run(run(force=args.force, only=args.only, limit=args.limit))
    return 0 if count >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
