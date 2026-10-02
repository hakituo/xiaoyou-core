import jieba

jieba.setLogLevel(jieba.logging.INFO)

STOPWORDS = frozenset({
    "的", "了", "在", "是", "我", "你", "他", "她", "它", "们",
    "啊", "呢", "吗", "呀", "哦", "嗯", "啦", "噢", "嘛", "哈", "喔", "呃", "嘻", "哼", "唉", "哎", "喂", "哟", "嘿", "咦", "咯", "哇",
    "而", "与", "和", "或", "但", "却", "因", "为", "所", "以", "于", "从", "到", "把", "被", "让", "给", "向", "往",
    "这", "那", "有", "没", "很", "都", "也", "还", "就", "又", "才", "要", "会", "能", "可", "想", "说", "看", "听", "做", "用", "来", "去",
    "上", "下", "前", "后", "里", "外", "中", "内", "间", "之", "其", "无", "一", "不",
})

MODAL_PARTICLES = frozenset({"吧", "呀", "啊", "嘛", "哦", "嗯", "啦", "喔", "呃", "哈", "哇"})


def segment_keyphrase(keyphrase: str) -> str:
    words = list(jieba.cut(keyphrase, cut_all=False))
    meaningful = [w for w in words if w not in STOPWORDS and len(w) > 1]
    if not meaningful:
        meaningful = [w for w in words if w not in STOPWORDS and len(w) >= 1]
    if meaningful:
        result = "".join(meaningful)
        if len(result) >= 2 and result[-1] in MODAL_PARTICLES:
            result = result[:-1]
        return result
    return keyphrase
