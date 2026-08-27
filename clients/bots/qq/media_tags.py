"""QQ 媒体标签处理 —— [MEME] 表情包 / [IMG] 图片 / [BM] 私藏图的内联标签机制。

取代原来的 send_sensitive_meme / send_image 工具调用：
模型不再调用工具，而是像 [VOICE] 一样在回复文本里附带标签，
由 QQ 适配器在发送前提取标签、发完文字后补发图片。

支持的标签格式（半角/全角括号、半角/全角冒号均可，大小写不敏感）：
- [MEME]            随机发一张表情包
- [MEME:anime]      按分类发表情包（分类规则见 pick_meme_image）
- [IMG]             从私藏图库随机发 1 张图
- [IMG:3]           发 3 张（1-5 张，超出范围自动收敛）
- [BM]              从第二私藏图库随机发 1 张图
- [BM:3]            发 3 张（1-5 张，超出范围自动收敛）
- [VIDEO]           从 sensitive 视频库随机发 1 个视频
- [VIDEO:3]         发 3 个（1-5 个，超出范围自动收敛）

注意：[WEBM] 和 [DICE] 标签是 Telegram 专属，QQ 不支持，
      由 clients/bots/telegram/sensitive_media.py 独立处理。

发送形式：
- MEME 用普通 CQ:image（不带头像表情 subType，保证 PNG 透明背景不被 QQ 服务端填充）
- IMG / BM 用普通 CQ:image（大图）
- VIDEO 用 CQ:video
"""
from __future__ import annotations

import os
import random
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from core.utils.logger import get_logger

logger = get_logger("media_tags")

# 普通表情包根目录（data/memes，一级子目录即分类，manual 子目录除外）
MEMES_NORMAL_ROOT = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "memes"
)

# sensitive 表情包根目录
MEMES_SENSITIVE_ROOT = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "memes"
    / "manual"
    / "sensitive"
)

# 普通表情包目录下需要排除的子目录名（小写匹配）
_EXCLUDED_MEME_DIRS = {"manual"}

# 普通分类列表缓存（带 mtime，目录未变动时直接返回缓存）
_normal_categories_cache: dict = {"mtime": 0.0, "categories": []}


def list_normal_meme_categories() -> list[str]:
    """扫描 data/memes/ 一级子目录（排除 manual），返回分类名列表。

    带 mtime 缓存：目录未变动时直接返回缓存，新增/改名/删除文件夹后
    下次调用检测到 mtime 变化会自动重新扫描。
    """
    global _normal_categories_cache
    if not MEMES_NORMAL_ROOT.is_dir():
        return []
    try:
        mtime = float(MEMES_NORMAL_ROOT.stat().st_mtime)
    except Exception:
        mtime = 0.0
    if mtime == _normal_categories_cache["mtime"] and _normal_categories_cache["categories"]:
        return _normal_categories_cache["categories"]
    cats = [
        p.name
        for p in sorted(MEMES_NORMAL_ROOT.iterdir())
        if p.is_dir() and p.name.lower() not in _EXCLUDED_MEME_DIRS
    ]
    _normal_categories_cache = {"mtime": mtime, "categories": cats}
    return cats

# 私藏图库 / 第二私藏图库 / 视频库的根目录配置在 sensitive_paths.py（不进 git）
try:
    from clients.bots.qq.sensitive_paths import IMAGE_ROOT, BM_ROOT, VIDEO_ROOT
except ImportError:
    # sensitive_paths.py 不存在时用空路径，相关标签会跳过
    IMAGE_ROOT = Path()
    BM_ROOT = Path()
    VIDEO_ROOT = Path()
    logger.warning("sensitive_paths.py 不存在，[IMG]/[BM]/[VIDEO] 标签将无法发送")

# 支持的图片扩展名
_SUPPORTED_EXTS = (".gif", ".jpg", ".jpeg", ".png")

# 支持的视频扩展名
_VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv")

# IMG / BM 标签单次最多发几张
_IMG_MAX_COUNT = 5

# 最近发送图片的去重窗口（LRU 大小）
# 跨会话共享，避免短时间内重复发同一张图
_MEME_LRU_SIZE = 12
_IMG_LRU_SIZE = 20
# 第二私藏图库较大，LRU 窗口放大
_BM_LRU_SIZE = 30
# mp4 视频较多
_VIDEO_LRU_SIZE = 20

# 模块级最近发送记录（路径字符串）
_recent_meme_paths: "deque[str]" = deque(maxlen=_MEME_LRU_SIZE)
_recent_img_paths: "deque[str]" = deque(maxlen=_IMG_LRU_SIZE)
_recent_bm_paths: "deque[str]" = deque(maxlen=_BM_LRU_SIZE)
_recent_video_paths: "deque[str]" = deque(maxlen=_VIDEO_LRU_SIZE)


def reset_recent_history() -> None:
    """清空最近发送记录（测试用）。"""
    _recent_meme_paths.clear()
    _recent_img_paths.clear()
    _recent_bm_paths.clear()
    _recent_video_paths.clear()


def _pick_and_record(candidates: list[Path], lru: "deque[str]") -> Optional[Path]:
    """从候选里选一张，过滤掉最近发过的，选完登记到 LRU。"""
    if not candidates:
        return None
    recent_set = set(lru)
    fresh = [p for p in candidates if str(p) not in recent_set]
    # 候选全在 LRU 里（候选池太小）时退化成全量随机，避免死循环
    pool = fresh if fresh else candidates
    chosen = random.choice(pool)
    lru.append(str(chosen))
    return chosen

# 标签正则：同时匹配半角 [ ] : 和全角 ［ ］ ：，参数部分可选
_MEME_TAG_RE = re.compile(r"[\[［]MEME(?:[：:]\s*([^\]］]*))?[\]］]", re.IGNORECASE)
_IMG_TAG_RE = re.compile(r"[\[［]IMG(?:[：:]\s*([^\]］]*))?[\]］]", re.IGNORECASE)
_BM_TAG_RE = re.compile(r"[\[［]BM(?:[：:]\s*([^\]］]*))?[\]］]", re.IGNORECASE)
_VOICE_TAG_RE = re.compile(r"[\[［]VOICE(?:[：:]\s*([^\]］]*))?[\]］]", re.IGNORECASE)

# sensitive 视频标签 [VIDEO] 或 [VIDEO:3]
# 参数部分是可选的数量（默认1张，和 [IMG] 一样收敛到1-5）
_VIDEO_TAG_RE = re.compile(r"[\[［]VIDEO(?:[：:]\s*([^\]］]*))?[\]］]", re.IGNORECASE)


def _list_subdirs(root: Path) -> list[Path]:
    """列出目录下的所有子文件夹。"""
    if not root.is_dir():
        return []
    return [p for p in sorted(root.iterdir()) if p.is_dir()]


def _list_images(folder: Path) -> list[Path]:
    """列出文件夹内所有支持的图片文件（仅根目录，不递归子文件夹）。"""
    if not folder.is_dir():
        return []
    return [
        p
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in _SUPPORTED_EXTS
    ]


def _list_images_in_subtree(root: Path) -> list[Path]:
    """列出 root 下所有图片（含根目录文件和所有一级子文件夹内的文件）。"""
    if not root.is_dir():
        return []
    images: list[Path] = []
    images.extend(_list_images(root))
    for sub in _list_subdirs(root):
        images.extend(_list_images(sub))
    return images


def _is_known_category(category: str) -> bool:
    """判断 category 是否是已知分类名（普通分类或 sensitive 大类/子文件夹）。"""
    cat = str(category or "").strip()
    if not cat or cat.lower() == "random":
        return True  # random 是已知
    cat_lower = cat.lower()
    # 普通分类
    for name in list_normal_meme_categories():
        if name.lower() == cat_lower:
            return True
    # sensitive 大类
    if cat_lower in ("anime", "reality"):
        return True
    # sensitive 精确路径
    if "/" in cat:
        return True
    # sensitive 单独子文件夹名
    subdirs = _list_subdirs(MEMES_SENSITIVE_ROOT)
    for sd in subdirs:
        for sub in _list_subdirs(sd):
            if sub.name == cat:
                return True
    return False


def pick_meme_image(category: str = "random") -> Optional[Path]:
    """从表情包目录选一张图片（带 LRU 去重，最近 12 张不重复）。

    支持三类触发方式：
    - **分类名**（angry/happy/anime/中指 等）：从对应文件夹随机选图
    - **语义描述**（非分类名的自然语言，如"刚解决问题后的喜悦"）：
      调用 bge-small-zh 向量检索，从所有普通分类里找最匹配的图。
      需要先运行 scripts/meme/build_meme_descriptions 和 build_meme_vector_index
      建好向量索引；索引不存在时自动 fallback 到 random。
    - **random** / 空：所有普通分类图片随机

    Args:
        category: 分类名 / 自然语言描述 / "random"（大小写不敏感）：
            - "random" / 空：所有普通分类图片随机
            - 普通分类名（如 "happy"）：从 data/memes/happy/ 选图
            - "anime" / "reality"：从 sensitive 大类下所有图片随机
            - "anime/中指" 这类精确路径：精确到 sensitive 子文件夹
            - 单独 sensitive 子文件夹名（如 "中指"）：在所有 sensitive 大类下查找
            - 自然语言描述（如"刚起床伸懒腰"）：走语义检索

    若指定分类不存在且非语义描述，自动 fallback 到 random 全随机，
    避免 LLM 幻觉分类导致图发不出去。
    """
    # 先尝试分类路径（已知分类名）
    if _is_known_category(category):
        candidates = _collect_meme_candidates(category)
        if not candidates and category and category.lower() != "random":
            candidates = _collect_meme_candidates("random")
        if not candidates:
            return None
        return _pick_and_record(candidates, _recent_meme_paths)

    # 非已知分类 → 走语义检索
    try:
        from clients.bots.qq.meme_search import pick_meme_by_semantic
        from config.integrated_config import get_settings

        settings = get_settings()
        meme_cfg = getattr(settings, "meme_search", None)
        top_k = getattr(meme_cfg, "top_k", 5) if meme_cfg else 5
        min_sim = getattr(meme_cfg, "min_similarity", 0.25) if meme_cfg else 0.25

        chosen = pick_meme_by_semantic(
            query=category,
            top_k=top_k,
            min_similarity=min_sim,
            exclude_paths=set(_recent_meme_paths),
        )
        if chosen is not None:
            _recent_meme_paths.append(str(chosen))
            return chosen
        logger.info("语义检索无候选，fallback 到 random")
    except Exception as e:
        logger.warning(f"语义检索失败，fallback 到 random: {e}")

    # fallback：random 全随机
    candidates = _collect_meme_candidates("random")
    if not candidates:
        return None
    return _pick_and_record(candidates, _recent_meme_paths)


def _collect_meme_candidates(category: str) -> list[Path]:
    """按 category 规则收集候选图片列表（不做随机选择）。

    先查普通分类（data/memes/ 一级子目录），没命中再查 sensitive 分类。
    """
    cat = str(category or "random").strip()
    cat_lower = cat.lower()

    # 完全随机：从普通分类全随机
    if not cat_lower or cat_lower == "random":
        all_images: list[Path] = []
        for name in list_normal_meme_categories():
            all_images.extend(_list_images(MEMES_NORMAL_ROOT / name))
        return all_images

    # 普通分类（angry/happy 等）：大小写不敏感匹配 data/memes/ 一级子目录
    for name in list_normal_meme_categories():
        if name.lower() == cat_lower:
            return _list_images(MEMES_NORMAL_ROOT / name)

    # 以下是 sensitive 分类逻辑（anime/reality/精确路径/单独子文件夹名）
    subdirs = _list_subdirs(MEMES_SENSITIVE_ROOT)
    if not subdirs:
        return []

    # 大类随机（anime / reality）
    if cat_lower in ("anime", "reality"):
        target = next((p for p in subdirs if p.name.lower() == cat_lower), None)
        if target is None:
            return []
        return _list_images_in_subtree(target)

    # 精确路径：如 "anime/中指"
    if "/" in cat:
        style_name, theme_name = (s.strip() for s in cat.split("/", 1))
        style_dir = next(
            (p for p in subdirs if p.name.lower() == style_name.lower()), None
        )
        if style_dir is None:
            return []
        theme_dir = next(
            (p for p in _list_subdirs(style_dir) if p.name == theme_name), None
        )
        if theme_dir is None:
            return []
        return _list_images(theme_dir)

    # 单独子文件夹名：在所有 sensitive 大类下查找
    matching: list[Path] = []
    for sd in subdirs:
        for sub in _list_subdirs(sd):
            if sub.name == cat:
                matching.extend(_list_images(sub))
    return matching


def pick_gallery_images(count: int = 1) -> list[Path]:
    """从私藏图库随机选 count 张不重复的图片（带 LRU 去重，目录为空返回空列表）。"""
    all_images = _list_images(IMAGE_ROOT)
    if not all_images:
        return []
    count = max(1, min(int(count), _IMG_MAX_COUNT, len(all_images)))
    # 优先从最近未发过的图里选
    recent_set = set(_recent_img_paths)
    fresh = [p for p in all_images if str(p) not in recent_set]
    pool = fresh if len(fresh) >= count else all_images
    chosen = random.sample(pool, count)
    for p in chosen:
        _recent_img_paths.append(str(p))
    return chosen


def pick_bm_images(count: int = 1) -> list[Path]:
    """从第二私藏图库随机选 count 张不重复的图片（带 LRU 去重，目录为空返回空列表）。"""
    all_images = _list_images(BM_ROOT)
    if not all_images:
        return []
    count = max(1, min(int(count), _IMG_MAX_COUNT, len(all_images)))
    # 优先从最近未发过的图里选
    recent_set = set(_recent_bm_paths)
    fresh = [p for p in all_images if str(p) not in recent_set]
    pool = fresh if len(fresh) >= count else all_images
    chosen = random.sample(pool, count)
    for p in chosen:
        _recent_bm_paths.append(str(p))
    return chosen


def _list_files_by_ext(root: Path, exts: tuple[str, ...]) -> list[Path]:
    """列出 root 下所有指定扩展名的文件（不递归子文件夹）。"""
    if not root.is_dir():
        return []
    return [
        p
        for p in root.iterdir()
        if p.is_file() and p.suffix.lower() in exts
    ]


def pick_videos(count: int = 1) -> list[Path]:
    """从 mp4 目录随机选 count 个视频文件（带 LRU 去重，目录为空返回空列表）。

    Args:
        count: 要选的数量，收敛到 1-5 张

    Returns:
        选中的视频文件路径列表
    """
    all_files = _list_files_by_ext(VIDEO_ROOT, _VIDEO_EXTS)
    if not all_files:
        logger.warning(f"video 目录为空或不存在: {VIDEO_ROOT}")
        return []
    count = max(1, min(int(count), _IMG_MAX_COUNT, len(all_files)))
    # 优先从最近未发过的视频里选
    recent_set = set(_recent_video_paths)
    fresh = [p for p in all_files if str(p) not in recent_set]
    pool = fresh if len(fresh) >= count else all_files
    chosen = random.sample(pool, count)
    for p in chosen:
        _recent_video_paths.append(str(p))
        logger.info(f"[VIDEO] 选图: {p.name}")
    return chosen


def build_meme_cq(file_path: Path) -> str:
    """构造表情包 CQ:image 码（普通图片形式，作为回退方案）。

    注意：不带 subType=1。历史上前者会把图片按 QQ 表情上传，非标准尺寸的 PNG
    会被 QQ 服务端转成 JPG 并用白边填充，导致透明背景丢失、观感变差；
    改用普通 CQ:image 直发原文件，可保留 PNG 透明背景。

    但 QQ 的普通图片上传管线仍会把 PNG 转 JPG（JPG 不支持 alpha 通道），
    透明区域会被填白。主路径应优先走 _send_meme_as_custom_face（自定义表情通道），
    本函数仅在自定义表情 API 不可用时作为回退。
    """
    path_str = str(file_path.resolve()).replace(os.sep, "/")
    return f"[CQ:image,file=file:///{path_str}]"


def build_image_cq(file_path: Path) -> str:
    """构造普通大图 CQ:image 码（不加 subType）。"""
    path_str = str(file_path.resolve()).replace(os.sep, "/")
    return f"[CQ:image,file=file:///{path_str}]"


def extract_media_tags(text: str) -> tuple[str, list[str], int, int]:
    """提取并剥离 [MEME] / [IMG] / [BM] 标签（向后兼容，内部用 extract_media_segments）。

    Returns:
        (清理后文本, 表情包分类列表, 图片张数, 第二私藏图张数)：
        - 每个 [MEME] 标签对应列表里一项（分类字符串，缺省为 "random"）；
        - [IMG] / [BM] 张数取所有标签的数量之和（缺省每个算 1 张），
          最终收敛到 1-5 张；无对应标签时为 0。
        - [WEBM] / [VIDEO] / [DICE] 标签不在这个旧版函数里返回，
          调用方需要用 extract_media_segments 获取完整分段信息。
    """
    segments = extract_media_segments(text)
    if not segments:
        return "", [], 0, 0
    cleaned = "\n".join(seg.text for seg in segments if seg.text)
    meme_categories = [cat for seg in segments for cat in seg.meme_categories]
    img_count = min(_IMG_MAX_COUNT, sum(seg.img_count for seg in segments))
    bm_count = min(_IMG_MAX_COUNT, sum(seg.bm_count for seg in segments))
    return cleaned, meme_categories, img_count, bm_count


@dataclass
class MediaSegment:
    """文本段 + 该段末尾紧跟的媒体标签。

    发送顺序：先发 text（断句后逐句发送），再发该段的 meme/img/bm/video。
    voice=True 时该段文本改用语音发送（不断句），voice_id 为 [VOICE:xxx] 指定的参考音频。
    video_count 非0时在该段文字发完后发 sensitive 视频。

    注意：[WEBM] 和 [DICE] 是 Telegram 专属标签，不在 MediaSegment 里。
    Telegram 适配器在自己的 _send_full_response_with_split 里单独解析这两个标签。
    """
    text: str = ""
    meme_categories: list[str] = field(default_factory=list)
    img_count: int = 0
    bm_count: int = 0
    voice: bool = False
    voice_id: str = ""
    # sensitive mp4 视频数量（1-5），0 表示无
    video_count: int = 0


def _clean_segment_text(text: str) -> str:
    """清理 segment 文本的多余空白（保留换行符用于断句）。"""
    text = re.sub(r"[^\S\n]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_media_segments(text: str) -> list[MediaSegment]:
    """按 [MEME] / [IMG] / [BM] / [VOICE] / [VIDEO] 标签位置把文本分段。

    每个标签附属在它前面那段文本的末尾，发送时：
    文字段A → 图A → 文字段B → 图B → ...
    voice=True 的段改用语音发送（不断句），其余段发文字。
    video_count 非0时在该段文字发完后发 sensitive 视频。

    注意：[WEBM] 和 [DICE] 标签是 Telegram 专属，不在这里解析。
    Telegram 适配器会在 extract_media_segments 返回的 segments 上再扫描
    [WEBM] 和 [DICE] 标签（在 telegram/sensitive_media.py 里处理）。

    示例：
        "文本A[MEME]文本B[MEME:anime]" → [
            MediaSegment("文本A", ["random"], 0),
            MediaSegment("文本B", ["anime"], 0),
        ]
        "纯文本无标签" → [MediaSegment("纯文本无标签")]
        "[MEME]文本" → [MediaSegment("", ["random"], 0), MediaSegment("文本")]
        "文字段[VOICE]" → [MediaSegment("文字段", voice=True)]
        "文字A[VOICE]文字B" → [MediaSegment("文字A", voice=True), MediaSegment("文字B")]
        "看看这个[VIDEO]" → [MediaSegment("看看这个", video_count=1)]

    IMG / BM / VIDEO 数量收敛到单段最多 _IMG_MAX_COUNT。
    """
    content = str(text or "")
    if not content:
        return []

    # 收集所有标签
    # (start, end, meme_cats, img_count, bm_count, voice, voice_id, video_count)
    tags: list[tuple[int, int, list[str], int, int, bool, str, int]] = []
    for m in _MEME_TAG_RE.finditer(content):
        cat = str(m.group(1) or "random").strip() or "random"
        tags.append((m.start(), m.end(), [cat], 0, 0, False, "", 0))
    for m in _IMG_TAG_RE.finditer(content):
        raw = str(m.group(1) or "").strip()
        try:
            cnt = max(1, int(raw)) if raw else 1
        except ValueError:
            cnt = 1
        cnt = min(cnt, _IMG_MAX_COUNT)
        tags.append((m.start(), m.end(), [], cnt, 0, False, "", 0))
    for m in _BM_TAG_RE.finditer(content):
        raw = str(m.group(1) or "").strip()
        try:
            cnt = max(1, int(raw)) if raw else 1
        except ValueError:
            cnt = 1
        cnt = min(cnt, _IMG_MAX_COUNT)
        tags.append((m.start(), m.end(), [], 0, cnt, False, "", 0))
    for m in _VOICE_TAG_RE.finditer(content):
        vid = str(m.group(1) or "").strip()
        tags.append((m.start(), m.end(), [], 0, 0, True, vid, 0))
    # [VIDEO] 或 [VIDEO:3] —— sensitive 视频标签
    for m in _VIDEO_TAG_RE.finditer(content):
        raw = str(m.group(1) or "").strip()
        try:
            cnt = max(1, int(raw)) if raw else 1
        except ValueError:
            cnt = 1
        cnt = min(cnt, _IMG_MAX_COUNT)
        tags.append((m.start(), m.end(), [], 0, 0, False, "", cnt))

    if not tags:
        return [MediaSegment(text=_clean_segment_text(content))]

    tags.sort(key=lambda t: t[0])

    segments: list[MediaSegment] = []
    last_end = 0

    for start, end, meme_cats, img_cnt, bm_cnt, voice_flag, voice_id_val, video_cnt in tags:
        text_before = _clean_segment_text(content[last_end:start])
        segments.append(MediaSegment(
            text=text_before,
            meme_categories=meme_cats,
            img_count=img_cnt,
            bm_count=bm_cnt,
            voice=voice_flag,
            voice_id=voice_id_val,
            video_count=video_cnt,
        ))
        last_end = end

    # 最后一段文本（无标签）
    text_after = _clean_segment_text(content[last_end:])
    if text_after:
        segments.append(MediaSegment(text=text_after))

    return segments
