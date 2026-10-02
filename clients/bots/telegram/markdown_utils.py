"""Telegram Markdown → HTML 转换工具。

把 LLM 输出的 Markdown 语法转换成 Telegram HTML 模式支持的标签。

支持的格式化语法（转成 Telegram HTML 模式）：
- **加粗** / __加粗__  -> <b>加粗</b>
- *斜体* / _斜体_      -> <i>斜体</i>
- ~~删除线~~           -> <s>删除线</s>
- `code`               -> <code>code</code>
- ```lang\ncode```     -> <pre><code class="language-lang">code</code></pre>
- ||隐藏||             -> <tg-spoiler>隐藏</tg-spoiler>
- [text](url)          -> <a href="url">text</a>
"""
from __future__ import annotations

import re


def html_escape(text: str) -> str:
    """转义 HTML 特殊字符（Telegram HTML 模式要求）。"""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def strip_markdown(text: str) -> str:
    """简单的 Markdown 清理（Telegram 对 Markdown 解析较严格）。

    保留代码块和行内代码的内容，只清理加粗/斜体/删除线/隐藏等标记符号。
    """
    if not text:
        return text
    # 先把代码块和行内代码里的内容取出来保护，避免被错误清理
    code_blocks: list[str] = []
    def _save_block(m: "re.Match") -> str:
        code_blocks.append(m.group(0))
        return f"\x00CB{len(code_blocks)-1}\x00"
    tmp = re.sub(r"```[\s\S]*?```", _save_block, text)
    inline_codes: list[str] = []
    def _save_inline(m: "re.Match") -> str:
        inline_codes.append(m.group(0))
        return f"\x00IC{len(inline_codes)-1}\x00"
    tmp = re.sub(r"`[^`\n]+`", _save_inline, tmp)

    tmp = tmp.replace("**", "").replace("__", "")
    tmp = tmp.replace("~~", "").replace("||", "")

    # 还原代码块和行内代码
    for i, c in enumerate(inline_codes):
        tmp = tmp.replace(f"\x00IC{i}\x00", c)
    for i, c in enumerate(code_blocks):
        tmp = tmp.replace(f"\x00CB{i}\x00", c)
    return tmp.strip()


def markdown_to_telegram_html(text: str) -> tuple[str, str]:
    """把常见的 Markdown 语法转换成 Telegram HTML 格式。

    返回 (html_text, parse_mode)，parse_mode 固定为 "HTML"。
    """
    if not text:
        return text, "HTML"

    # 用占位符保护代码块和行内代码，避免内容被二次处理
    placeholders: list[str] = []

    def _stash(html_content: str) -> str:
        placeholders.append(html_content)
        return f"\x00P{len(placeholders) - 1}\x00"

    # 1. 代码块 ```lang\ncode``` -> <pre><code class="language-lang">code</code></pre>
    def _repl_block(m: "re.Match") -> str:
        lang = (m.group(1) or "").strip()
        code = m.group(2) or ""
        cls = f' class="language-{lang}"' if lang else ""
        return _stash(f"<pre><code{cls}>{html_escape(code)}</code></pre>")
    text = re.sub(r"```(\w*)\n?([\s\S]*?)```", _repl_block, text)

    # 2. 行内代码 `code` -> <code>code</code>
    def _repl_inline(m: "re.Match") -> str:
        return _stash(f"<code>{html_escape(m.group(1))}</code>")
    text = re.sub(r"`([^`\n]+)`", _repl_inline, text)

    # 先转义剩余文本的 HTML 特殊字符
    text = html_escape(text)

    # 3. 加粗 **text** 或 __text__ -> <b>text</b>
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

    # 4. 隐藏文字 ||text|| -> <tg-spoiler>text</tg-spoiler>
    text = re.sub(r"\|\|(.+?)\|\|", r"<tg-spoiler>\1</tg-spoiler>", text)

    # 5. 删除线 ~~text~~ -> <s>text</s>
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

    # 6. 斜体 *text* 或 _text_ -> <i>text</i>
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_(?!_)(.+?)(?<!\w)_(?!\w)", r"<i>\1</i>", text)

    # 7. 链接 [text](url) -> <a href="url">text</a>
    text = re.sub(r"\[(.+?)\]\((https?://[^\s)]+)\)", r'<a href="\2">\1</a>', text)

    # 还原占位符（代码块和行内代码）
    for i, p in enumerate(placeholders):
        text = text.replace(f"\x00P{i}\x00", p)

    return text, "HTML"
