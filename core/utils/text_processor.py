import hashlib
import random
import re
from typing import Optional, Tuple


_EMO_PREFIX_RE = re.compile(r"^\s*(\[EMO:[^\]]+\])\s*")
_LEADING_STAGE_RE = re.compile(
    r"^\s*(?:"
    r"(?:旁白|场景|动作|系统|叙述)\s*[:：]\s*"
    r"|（[^）]{0,80}）\s*"
    r"|\([^)]{0,80}\)\s*"
    r"|【[^】]{0,80}】\s*"
    r"|\[[^\]]{0,80}\]\s*"
    r"|\*[^*]{0,80}\*\s*"
    r")+"
)
_LEADING_APOLOGY_RE = re.compile(
    r"^\s*(?:很抱歉|对不起|抱歉|不好意思|非常抱歉)(?:[，,。.!！?？]\s*)*"
)
_LEADING_ASSISTANTISH_RE = re.compile(
    r"^\s*(?:作为(?:一名|一个)?(?:AI|人工智能|助手)|我(?:作为|身为)(?:AI|助手)|我是(?:一名|一个)?AI助手|我是(?:AI|助手)|作为语言模型|我是(?:你的|您的)?(?:专属)?(?:AI|人工智能)?助手)"
    r"(?:[，,。.!！?？]\s*)*"
)
_LEADING_CANNED_OPENING_RE = re.compile(
    r"^\s*(?:"
    r"当然可以|当然没问题|没问题|非常乐意|我很乐意|我可以帮你|我可以为你|我来帮你|我会尽力"
    r")(?:[，,。.!！?？]\s*)*"
)
_LEADING_STRUCTURED_PREFACE_RE = re.compile(
    r"^\s*(?:"
    r"下面(?:我来)?|以下(?:是)?|接下来|我将|我会|让我"
    r")(?:[，,。.!！?？]\s*)*"
    r"(?:为你)?(?:[，,。.!！?？]\s*)*"
    r"(?:整理|总结|列出|提供|介绍|说明|讲解)"
    r"(?:[：:，,。.!！?？]\s*)*"
)
_LEADING_PUNCT_RE = re.compile(r"^\s*[:：\-—|｜]+\s*")
_LEADING_I_COLON_RE = re.compile(r"^\s*我\s*[:：]\s*")
_SELF_NAME_PREFIX_RE = re.compile(
    r"^\s*(?:澪|Aveline|aveline)\s*[:：]\s*", re.IGNORECASE
)
_SELF_NAME_AFTER_I_RE = re.compile(
    r"我\s*(?:叫|是)\s*(?:澪|Aveline|aveline)\b", re.IGNORECASE
)
_LEADING_ROLE_PREFIX_RE = re.compile(
    r"^\s*(?:assistant|system|user|developer|tool|function|ai|bot|助手|系统|用户)\s*[:：|]\s*",
    re.IGNORECASE,
)
_ROLE_LINE_PREFIX_RE = re.compile(
    r"(?m)^\s*(?:assistant|system|user|developer|tool|function|助手|系统|用户)\s*[:：|]\s*",
    re.IGNORECASE,
)


_EMOJI_RE = re.compile(
    r"(?:"
    r"[\U0001F000-\U0001FAFF]"
    # r"|[\U00002600-\U000026FF]"  # Removed to protect kaomoji symbols like ♥, ☆
    # r"|[\U00002700-\U000027BF]"  # Removed to protect kaomoji symbols
    r")",
    flags=re.UNICODE,
)

_QQ_FACE_CODES = {"/wzm", "/xin", "/xjj", "/ybyb", "/qq", "/yqq", "/emm", "/doge"}

_COMMON_KAOMOJIS = [
    "(^_^)",
    "(^_-)",
    "(*^▽^*)",
    "(≧◡≦)",
    "(o^▽^o)",
    "(´• ω •`)",
    "(⌒▽⌒)☆",
    "ヽ(>∀<☆)ノ",
    "(￣▽￣)",
    "(o_ _)ﾉ彡☆",
    "(¬_¬ )",
    "(＃＞＜)",
    "(;¬_¬)",
    "(￣ω￣;)",
    "(T_T)",
    "(; ω ; )",
    "(｡•́︿•̀｡)",
    "(._.)",
    "(///_///)",
    "(⁄ ⁄•⁄ω⁄•⁄ ⁄)⁄",
    "(´｡• ᵕ •｡`)",
    "(o´∀`o)",
    "(´･ᴗ･ ` )",
    "(ﾉ◕ヮ◕)ﾉ*:･ﾟ✧",
    "( ˙꒳​˙ )",
    "(´･ω･`)",
    "(・_・;)",
    "(>_<)",
    "(o_O)",
    "(._.)?",
    "(¬‿¬)",
    "(￣▽￣)b",
    "(ง'̀-'́)ง",
    "(=^･ω･^=)",
    "(^._.^)",
    "(◕‿◕)",
    "(｡･ω･｡)",
    "(o･ω･o)",
    "(・∀・)",
    "(´∀｀)",
    "(￣^￣)",
    "(｀Д´)",
    "(;´Д`)",
    "(°ロ°)",
    "(⊙_⊙)",
    "(´-﹏-`；)",
    "(｡╯3╰｡)",
    "( ˘ ³˘)♥",
    "(´ε｀ )",
    "(~_~;)",
    "(⁄ ⁄•⁄ω⁄•⁄ ⁄)⁄",
    "(///ω///)",
    "(*/ω＼*)",
    "(o_ _)o",
    "(⁄ ⁄>⁄ ▽ ⁄<⁄ ⁄)",
    "(„• ֊ •„)",
    "(*/▽＼*)",
    "(⁄ ⁄•⁄-⁄•⁄ ⁄)",
    "(//▽//)",
    "(///￣ ￣///)",
    "(⁄ ⁄>⁄ ▽ ⁄<⁄ ⁄)",
    "(//ω//)",
    "(///△///)",
    "(⁄ ⁄•⁄ω⁄•⁄ ⁄)⁄",
    "(*/ω＼*)",
    "(´｡• ᵕ •｡`)",
    "(♡μ_μ)",
    "( ◡‿◡ *)",
    "(*/_＼)",
    "(//▽//)",
    "(◡‿◡✿)",
    "(´ε｀ )♡",
    "( ˘ ³˘)♥",
    "(´｡• ᵕ •｡`) ♡",
    "(♡˙︶˙♡)",
    "(♡°▽°♡)",
    "(≧◡≦) ♡",
    "(´• ω •`) ♡",
    "( ´ ▽ ` ).｡ｏ♡",
    "(╰(*´︶`*)╯♡)",
    "(♡ε♡ )",
    "( ( ˘ ³˘)♥ )",
    "( ˘ ³˘)♥",
    "(´ε｀ )",
    "( ˘ ³˘)♡",
    "(´∩｡• ᵕ •｡∩`)",
    "(｡・//ε//・｡)",
    "(♡-_-♡)",
    "(///ω///)",
    "(´｡• ᵕ •｡`)",
    "(o_ _)o",
    "(o´∀`o)",
    "(´･ᴗ･ ` )",
    "(ﾉ◕ヮ◕)ﾉ*:･ﾟ✧",
    "( ˙꒳​˙ )",
]

_EMOJI_TO_KAOMOJI = {
    "🙂": ["(^_^)", "(*^▽^*)", "(o^▽^o)", "(´･ᴗ･ ` )", "(≧◡≦)", "(^o^)"],
    "❤️": [
        "(<3)",
        "(♥)",
        "(♡)",
        "(｡♥‿♥｡)",
        "(♥_♥)",
        "( ˘ ³˘)♥",
        "(´ε｀ )",
        "(♡μ_μ)",
        "(´｡• ᵕ •｡`) ♡",
        "(♡˙︶˙♡)",
    ],
    "❤": ["(<3)", "(♥)", "(♡)", "(｡♥‿♥｡)", "( ˘ ³˘)♥", "(♡μ_μ)", "(´｡• ᵕ •｡`) ♡"],
    "✨": [
        "(^_^)",
        "(✧ω✧)",
        "(*^▽^*)",
        "(☆_☆)",
        "(ﾉ◕ヮ◕)ﾉ*:･ﾟ✧",
        "°˖✧◝(⁰▿⁰)◜✧˖°",
        "☆*:.｡.o(≧▽≦)o.｡.:*☆",
    ],
    "🔥": ["(ง'̀-'́)ง", "ヽ( `д´*)ノ", "(#`皿´)", "(🔥🔥)", "٩(̾●̮̮̃̾•̃̾)۶", "(｀Д´)", "(;´Д`)"],
    "🎉": [
        "(^_^)／",
        "ヽ(>∀<☆)ノ",
        "(*^ω^)八(⌒▽⌒)八(-‿‿- )ヽ",
        "☆*:.｡.o(≧▽≦)o.｡.:*☆",
        "٩(｡•́‿•̀｡)۶",
    ],
    "👍": ["(ง'̀-'́)ง", "(b~_^)b", "(￣▽￣)b", "(o´∀`o)b", "d(>_・ )", "(^o^)y"],
    "🙏": ["(._.)", "(人)", "(-人-)", "(｡･人･｡)", "m(_ _)m", "(o_ _)o"],
    "😀": ["(^_^)", "(*^▽^*)", "(o^▽^o)", "(´･ᴗ･ ` )", "(≧◡≦)", "(^o^)"],
    "😁": ["(^_^)", "(≧◡≦)", "(⌒▽⌒)☆", "(´∀｀)", "(^0^)", "(＾▽＾)"],
    "😄": ["(^_^)", "(*^▽^*)", "(´• ω •`)", "(o´∀`o)", "(´｡• ᵕ •｡`)"],
    "😊": [
        "(^_^)",
        "(*^▽^*)",
        "(o^▽^o)",
        "(´｡• ᵕ •｡`)",
        "(´･ω･`)",
        "(◡‿◡✿)",
        "(´ε｀ )",
    ],
    "😉": ["(^_-)", "(^_<)", "(¬‿¬)", "(>ω^)", "(~_^)"],
    "😳": [
        "(///_///)",
        "(⁄ ⁄•⁄ω⁄•⁄ ⁄)⁄",
        "(o_O)",
        "(°ロ°)",
        "(⊙_⊙)",
        "(///ω///)",
        "(*/ω＼*)",
        "(o_ _)o",
    ],
    "🥺": [
        "(T_T)",
        "(｡•́︿•̀｡)",
        "(; ω ; )",
        "(o_ _)o",
        "(´-﹏-`；)",
        "(´｡• ᵕ •｡`)",
        "(｡T ω T｡)",
    ],
    "😭": ["(T_T)", "(; ω ; )", "(╥_╥)", "(｡•́︿•̀｡)", "(;´Д`)", "(个_个)"],
    "😢": ["(T_T)", "(; ω ; )", "(｡•́︿•̀｡)", "(._.)", "(｡T ω T｡)"],
    "😂": ["(>_<)", "(≧◡≦)", "(o_ _)ﾉ彡☆", "(´∀｀)", "(*≧▽≦)", "(≧▽≦)"],
    "😅": ["(・_・;)", "(￣ω￣;)", "(;¬_¬)", "(~_~;)", "(^_^;)", "(´-﹏-`；)"],
    "😔": ["(._.)", "(; ω ; )", "(￣ヘ￣)", "(´･ω･`)", "(︶qa︶)", "(｡•́︿•̀｡)"],
    "😡": ["(ง'̀-'́)ง", "(＃＞＜)", "ヽ( `д´*)ノ", "(｀Д´)", "(#`皿´)", "(;´Д`)"],
    "😠": ["(ง'̀-'́)ง", "(＃＞＜)", "(｀Д´)", "(`へ´*)ノ"],
    "🤔": ["(._.)?", "(¬_¬ )", "(￣ω￣;)", "(?_?)", "(・_・;)", "(˘･_･˘)"],
    "😏": ["(-_-)", "(¬‿¬)", "(￣▽￣)", "(≖‿≖)", "(¬_¬)"],
    "😎": ["(-_-)", "(⌐■_■)", "(￣▽￣)", "(´･ᴗ･ ` )"],
    "🥵": [
        "(///_///)",
        "(;´Д`)",
        "(///ω///)",
        "(o_ _)o",
        "(//▽//)",
        "(///△///)",
        "(*/ω＼*)",
    ],
    "💋": ["( ˘ ³˘)♥", "(´ε｀ )", "( ˘ ³˘)♡", "(´ε｀ )♡", "(｡・//ε//・｡)"],
    "👅": ["(ڡ)", "(p^)", "(ڡ)", "(´ڡ`)", "(｡・//ε//・｡)"],
}


def _replace_emoji_with_kaomoji(s: str) -> str:
    if not s:
        return s

    for k in sorted(_EMOJI_TO_KAOMOJI.keys(), key=len, reverse=True):
        if k in s:
            while k in s:
                replacement = random.choice(_EMOJI_TO_KAOMOJI[k])
                s = s.replace(k, replacement, 1)

    matches = list(_EMOJI_RE.finditer(s))
    for m in reversed(matches):
        replacement = random.choice(_COMMON_KAOMOJIS)
        s = s[: m.start()] + replacement + s[m.end() :]

    return s


def enforce_dialogue_style(
    text: str,
    max_chars: Optional[int] = None,
    at_start: bool = True,
    skip_breathing: bool = False,
    preserve_edge_whitespace: bool = False,
    replace_emoji_with_kaomoji: bool = False,
    strip_comma_period: bool = False,
    enable_start_fillers: bool = True,
    strip_trailing_punct: bool = True,
    strip_parentheses_tags: bool = False,
) -> str:
    if not text:
        return text

    s = str(text)
    emo_prefix = ""
    m = _EMO_PREFIX_RE.match(s)
    if m:
        emo_prefix = m.group(1).strip() + " "
        s = s[m.end() :]

    leading_ws = ""
    trailing_ws = ""
    if preserve_edge_whitespace:
        if at_start:
            s = s.lstrip()
        else:
            m = re.match(r"\s+", s)
            if m:
                leading_ws = m.group(0)
                s = s[m.end() :]

        m = re.search(r"\s+$", s)
        if m:
            trailing_ws = m.group(0)
            s = s[: m.start()]
    else:
        s = s.strip()

    if at_start:
        for _ in range(6):
            before = s
            s = _SELF_NAME_PREFIX_RE.sub("", s)
            s = _LEADING_ROLE_PREFIX_RE.sub("", s)
            # SFW 模式下清理开头的舞台提示/旁白，Sensitive 模式下保留以增强沉浸感
            if skip_breathing:
                s = _LEADING_STAGE_RE.sub("", s)
            s = _LEADING_ASSISTANTISH_RE.sub("", s)
            s = _LEADING_APOLOGY_RE.sub("", s)
            s = _LEADING_CANNED_OPENING_RE.sub("", s)
            s = _LEADING_STRUCTURED_PREFACE_RE.sub("", s)
            s = _LEADING_PUNCT_RE.sub("", s)
            s = _LEADING_I_COLON_RE.sub("", s)
            s = s.strip()
            if s == before:
                break

        if enable_start_fillers and s and len(s) >= 6:
            fillers = ["嗯", "那个", "其实", "唔", "唉"]
            if not any(s.startswith(f) for f in fillers):
                h = hashlib.md5(s.encode("utf-8")).hexdigest()
                v = int(h[:8], 16)
                if v % 100 < 12:
                    s = fillers[v % len(fillers)] + " " + s

    s = _SELF_NAME_AFTER_I_RE.sub("我", s)
    if at_start:
        s = _LEADING_I_COLON_RE.sub("", s)

    s = _ROLE_LINE_PREFIX_RE.sub("", s)

    if replace_emoji_with_kaomoji:
        s = _replace_emoji_with_kaomoji(s)

    if strip_comma_period:
        for p in ["，", ",", "。", "."]:
            s = s.replace(p, " ")

    s = re.sub(r"\s+", " ", s)

    # 只有在不保留边缘空格时才进行全局 strip
    if not preserve_edge_whitespace:
        s = s.strip()

    if max_chars is not None and max_chars > 0 and len(s) > max_chars:
        s = s[:max_chars].rstrip()

    s = re.sub(r"[，,。.!！?？…]+[ \t]*[~～]+", "~", s)
    s = re.sub(r"[~～]+$", "~", s)

    s = re.sub(r"。\.{3,}", "......", s)
    s = re.sub(r"。…+", "……", s)

    # 只移除末尾的逗号/句号与空格，保留 ? ! ~ 等
    if strip_trailing_punct:
        if preserve_edge_whitespace:
            # 此时 s 可能包含内部空格，我们要保留它们
            s = s.rstrip(" ,，。.")
            out = emo_prefix + leading_ws + s + trailing_ws
            return out

        s = s.rstrip(" ,，。.")

    if preserve_edge_whitespace:
        out = emo_prefix + leading_ws + s + trailing_ws
        return out

    out = (emo_prefix + s).strip()
    return out


def extract_and_strip_emotion(content: str) -> Tuple[str, Optional[str]]:
    """
    从回复中提取情绪标签 [EMO: emotion] 或 [emotion]
    返回: (content_without_tag, emotion_label)
    """
    emo_block_pattern = r"\[\s*EMO\s*:\s*([\s\S]*?)\]"
    emo_match = re.search(emo_block_pattern, content, flags=re.IGNORECASE)
    if emo_match:
        emo_payload = str(emo_match.group(1) or "").strip()
        emotion = ""
        keyed = re.search(
            r"(?:mood|emotion|primary_emotion)\s*[:=]\s*['\"]?([a-zA-Z0-9_\u4e00-\u9fa5]+)",
            emo_payload,
            flags=re.IGNORECASE,
        )
        if keyed:
            emotion = str(keyed.group(1) or "").strip().lower()
        else:
            token = re.search(r"([a-zA-Z0-9_\u4e00-\u9fa5]+)", emo_payload)
            if token:
                emotion = str(token.group(1) or "").strip().lower()
        new_content = re.sub(emo_block_pattern, "", content, flags=re.IGNORECASE).strip()
        new_content = re.sub(
            r"^\s*(?:mood|emotion|primary_emotion|intensity|confidence)\s*[:=].*$",
            "",
            new_content,
            flags=re.IGNORECASE | re.MULTILINE,
        ).strip()
        return new_content, validate_emotion(emotion) if emotion else None

    # 2. 尝试匹配 [label] 格式 (仅限常见情绪词，避免误伤)
    # 常用情绪关键词列表
    emotion_keywords = r"(happy|neutral|angry|excited|lost|wronged|jealous|coquetry|shy|calm|sad|depressed|joy|开心|愉快|高兴|满足|喜悦|生气|愤怒|火大|暴躁|烦|不爽|兴奋|激动|期待|热情|亢奋|委屈|难过|伤心|失落|沮丧|低落|嫉妒|吃醋|傲娇|撒娇|害羞|羞涩|脸红|平静|中性|冷淡|冷静)"
    pattern2 = r"\[(" + emotion_keywords + r")\]"
    match2 = re.search(pattern2, content, re.IGNORECASE)
    if match2:
        emotion = match2.group(1).lower()
        new_content = re.sub(pattern2, "", content).strip()
        # For keyword match, we trust the regex but still normalize
        # Note: Chinese keywords are not in VALID_EMOTIONS, so validate_emotion might return None
        # We need to map Chinese to English first if we want to support Chinese tags here.
        # But CN_TO_EN_MAP is in emotion/constants.py. To avoid circular import, we skip CN map here or move map to utils.
        # For now, we assume english tags or aliases defined in validate_emotion.
        return new_content, validate_emotion(emotion)

    # 3. 清理 (?:...) 或 (?...) 或 (:?...) 等正则残留或错误的思维链标签
    # 这里的 ? 可能是半角或全角，( 可能是半角或全角
    # 匹配模式： (?: ... ) 或 (? ... ) 或 (:? ... )
    # 许多 LLM 会产生 (?:思考内容) 这种奇怪的格式

    # 清理开头可能的 (? 或 (?: 或 (:?
    content = re.sub(r"^\(\?[:：]?\s*", "", content)
    content = re.sub(r"^\(:\?\s*", "", content)

    # 清理非捕获组残留，如 (?:text) -> (text) 或者直接去掉 ?:
    # 简单策略：把 (?: 替换为 (
    content = content.replace("(?:", "(")
    content = content.replace("(:?", "(")
    content = content.replace("(?：", "(")  # 全角冒号情况

    return content, None


# Valid emotion keys supported by frontend
VALID_EMOTIONS = {
    "neutral",
    "happy",
    "shy",
    "angry",
    "jealous",
    "wronged",
    "coquetry",
    "lost",
    "excited",
    "sad",
    "anxious",
    "tired",
}

_CN_EMOTION_ALIASES = {
    "中性": "neutral",
    "平静": "neutral",
    "冷静": "neutral",
    "冷淡": "neutral",
    "开心": "happy",
    "愉快": "happy",
    "高兴": "happy",
    "喜悦": "happy",
    "生气": "angry",
    "愤怒": "angry",
    "火大": "angry",
    "暴躁": "angry",
    "不爽": "angry",
    "嫉妒": "jealous",
    "吃醋": "jealous",
    "委屈": "wronged",
    "撒娇": "coquetry",
    "傲娇": "coquetry",
    "粘人": "coquetry",
    "害羞": "shy",
    "羞涩": "shy",
    "脸红": "shy",
    "兴奋": "excited",
    "激动": "excited",
    "期待": "excited",
    "悲伤": "sad",
    "难过": "lost",
    "伤心": "lost",
    "失落": "lost",
    "沮丧": "lost",
    "低落": "lost",
    "焦虑": "anxious",
    "紧张": "anxious",
    "疲惫": "tired",
    "好累": "tired",
    "困": "tired",
}

_EN_EMOTION_ALIASES = {
    "calm": "neutral",
    "joy": "happy",
    "depressed": "sad",
    "fear": "anxious",
    "worried": "anxious",
    "annoyed": "angry",
    "envy": "jealous",
    "grievance": "wronged",
    "spoiled": "coquetry",
    "confused": "lost",
    "expect": "excited",
}


def validate_emotion(emotion: str) -> Optional[str]:
    """
    Validate and normalize emotion string against valid set.
    Returns normalized emotion or None.
    """
    if not emotion:
        return None

    e = emotion.lower().strip()

    if e in _CN_EMOTION_ALIASES:
        e = _CN_EMOTION_ALIASES[e]

    # Direct match
    if e in VALID_EMOTIONS:
        return e

    if e in _EN_EMOTION_ALIASES:
        return _EN_EMOTION_ALIASES[e]

    return None


def strip_parentheses_tags(text: str) -> str:
    """
    移除所有 (情绪词) 或 （情绪词） 格式的标签。
    仅当括号内的内容明确属于已知情绪词列表时才移除，
    以避免误伤短的环境描写（如 "(看着你)"）。
    """
    if not text:
        return text

    # 定义替换函数
    def _repl(match):
        content = match.group(1).strip()

        # 检查是否命中中文情绪词
        if content in _CN_EMOTION_ALIASES:
            return ""

        # 检查是否命中英文情绪词或标准情绪词
        content_lower = content.lower()
        if content_lower in VALID_EMOTIONS or content_lower in _EN_EMOTION_ALIASES:
            return ""

        # 如果不是情绪词，保留原样
        return match.group(0)

    # 匹配 (content) 或 （content）
    # content 允许汉字、字母、数字、下划线，长度 1-10
    pattern = r"[\(\（]([\u4e00-\u9fa5a-zA-Z0-9_]{1,10})[\)\）]"
    return re.sub(pattern, _repl, text)
