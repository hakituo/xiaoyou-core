"""Telegram 文本处理与断句工具（纯函数，无会话状态依赖）。

提供：
- build_persona_conversation_id：构建跨平台共享的 conversation_id
- 文本清洗：_strip_think_tags / _strip_ai_timestamp / _normalize_newlines
- _split_message_for_tg：按标点/长度断句，且**保留 markdown 标记**
  （与 QQ 版本的关键差异：不剥离 markdown，因为 Telegram 端要转 HTML）
"""
import hashlib
import re

from clients.bots.telegram.settings import (
    TG_MAX_BUBBLE_LEN,
    TG_MIN_SPLIT_LEN,
    logger,
)


def build_persona_conversation_id(session_id: str, persona_filename: str) -> str:
    """构建跨平台共享的 conversation_id（与 QQ 适配器一致）。

    所有平台（QQ/Telegram/websocket/Android）使用同一 persona 时返回相同的 cid：
    `shared__persona__{slug}`，让聊天历史和记忆跨平台互通。

    session_id 参数保留为兼容签名，但实际不再用作前缀（用 "shared"）。
    """
    try:
        from core.utils.data_paths import build_shared_persona_conversation_id
        return build_shared_persona_conversation_id(persona_filename)
    except Exception:
        base = "shared"
        raw = str(persona_filename or "").strip()
        if not raw:
            return base
        normalized = raw.replace("\\", "/").strip("/")
        stem = normalized.rsplit("/", 1)[-1]
        if "." in stem:
            stem = stem.rsplit(".", 1)[0]
        safe = re.sub(r"[^a-zA-Z0-9_\u4e00-\u9fff]+", "_", stem).strip("_").lower()
        if not safe:
            digest = hashlib.md5(normalized.encode("utf-8")).hexdigest()[:8]
            safe = f"persona_{digest}"
        return f"{base}__persona__{safe}"


def _strip_think_tags(text: str) -> str:
    """剥离 AI 回复中的 think 标签。"""
    _THINK_OPEN = chr(60) + "think" + chr(62)
    _THINK_CLOSE = chr(60) + "/think" + chr(62)
    return re.sub(_THINK_OPEN + ".*?" + _THINK_CLOSE, "", text, flags=re.DOTALL).strip()


def _strip_ai_timestamp(text: str) -> str:
    return re.sub(r"^\[\d{1,2}:\d{2}\]\s*", "", text.strip()).strip()


def _normalize_newlines(text: str) -> str:
    """把字面 \\n（反斜杠+n）转成真正的换行符，让断句能正常工作。

    LLM 有时会输出字面 "\\n" 而不是真换行，导致 Telegram 把它当普通字符发出。
    """
    if not text:
        return text
    # 字面 \n -> 真换行；字面 \t -> 制表符（少见但顺手处理）
    text = text.replace("\\n", "\n").replace("\\t", "\t")
    # 连续 3+ 换行收敛成 2 个
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


# ===== markdown 标记占位符保护（断句前保护，断句后还原）=====
_TG_MD_STASH: list[str] = []

_TG_MD_PATTERNS = [
    # 代码块 ```lang\ncode``` —— 必须最先处理，避免内部被其他规则误伤
    re.compile(r"```[\s\S]*?```"),
    # 行内代码 `code`
    re.compile(r"`[^`\n]+`"),
    # 加粗 **text** 或 __text__
    re.compile(r"\*\*[^*\n]+?\*\*|__[^_\n]+?__"),
    # 隐藏 ||text||
    re.compile(r"\|\|[^|\n]+?\|\|"),
    # 删除线 ~~text~~
    re.compile(r"~~[^~\n]+?~~"),
    # 链接 [text](url)
    re.compile(r"\[[^\]\n]+?\]\(https?://[^\s)\n]+?\)"),
]


def _tg_stash_md(match: "re.Match") -> str:
    """把 markdown 标记段存入占位符表，返回占位符。"""
    _TG_MD_STASH.append(match.group(0))
    return f"\x00MD{len(_TG_MD_STASH) - 1}\x00"


def _tg_restore_md(text: str) -> str:
    """还原占位符为原始 markdown 标记段。"""
    if not _TG_MD_STASH:
        return text
    for i, original in enumerate(_TG_MD_STASH):
        text = text.replace(f"\x00MD{i}\x00", original)
    return text


def _split_message_for_tg(text: str, max_bubble_len: int = TG_MAX_BUBBLE_LEN,
                          min_split_len: int = TG_MIN_SPLIT_LEN) -> list[str]:
    """断句：移植自 QQ 的 _split_message_for_qq，适配 Telegram 频率限制。

    与 QQ 版本的关键差异：**不剥离 markdown 标记**。
    QQ 版本入口会调用 `_strip_markdown_for_qq` 把 `**加粗**` 变成 `加粗`
    （QQ 不解析 markdown），但 Telegram 端 STRIP_MARKDOWN=false 时需要保留
    `**`/`||`/`~~` 等标记用于后续 markdown_to_telegram_html 转换。因此本函数
    先用占位符把完整的 markdown 标记段保护起来（避免被断句从中间切开），
    断句后再还原。

    规则（与 QQ 对齐）：
    1. 优先在句号、问号、感叹号处断句（仅当当前累积长度 >= min_split_len）
    2. 其次在逗号、分号处断句（仅当当前累积长度 >= max_bubble_len）
    3. 超过 max_bubble_len*2 强制在最近的逗号/空格处折断
    4. 保留标点符号，让消息读起来更完整
    5. 硬边界标点后紧跟的 emoji 会粘到当前句尾，不被推到下一句开头
    6. 续接词开头的段落会合并到前一段
    7. 括号/引号内的内容不会被断句拆碎
    8. markdown 标记段（**...** / ||...|| / ~~...~~ / `...` 等）保持完整不断开

    针对 Telegram 调优：避免过于频繁的发送（Telegram 限制 1条/秒/chat）。
    """
    text = str(text or "")
    if not text:
        return []

    # 用占位符保护 markdown 标记段，避免断句从中间切开导致标记配对丢失
    _TG_MD_STASH.clear()
    protected = text
    for pat in _TG_MD_PATTERNS:
        protected = pat.sub(_tg_stash_md, protected)

    # 复用 QQ 的断句逻辑（此时 markdown 标记已是 \x00MDn\x00 占位符，不会被剥离，
    # 也不会被 _strip_markdown_for_qq 抹掉——因为占位符里没有 * | ~ ` 等字符）
    try:
        from clients.bots.qq.utils import _split_message_for_qq
        chunks = _split_message_for_qq(
            protected,
            max_len=max_bubble_len,
            comma_split_prob=0.0,
            min_split_len=min_split_len,
        )
    except Exception as e:
        logger.warning(f"复用 QQ 断句逻辑失败，回退简版: {e}")
        # 回退到简版断句（旧逻辑）
        lines = [line.strip() for line in protected.split("\n") if line.strip()]
        chunks: list[str] = []
        for line in lines:
            if len(line) <= max_bubble_len:
                chunks.append(line)
            else:
                sub = re.split(r"(?<=[。！？!?\.\n])", line)
                current = ""
                for s in sub:
                    s = s.strip()
                    if not s:
                        continue
                    if len(current) + len(s) <= max_bubble_len:
                        current += s
                    else:
                        if current:
                            chunks.append(current)
                        current = s
                if current:
                    chunks.append(current)
        if len(chunks) <= 1:
            return [_tg_restore_md(c) for c in chunks] if chunks else []
        merged: list[str] = []
        buf = ""
        for c in chunks:
            if len(buf) + len(c) < min_split_len:
                buf += c
            else:
                if buf:
                    merged.append(buf)
                buf = c
        if buf:
            merged.append(buf)
        chunks = merged

    # 还原占位符
    result = [_tg_restore_md(c) for c in chunks if c and c.strip()]
    _TG_MD_STASH.clear()
    return result
