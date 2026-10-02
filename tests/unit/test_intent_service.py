import asyncio


class _StubBertAnalyzer:
    """意图识别用的 BERT 替身

    意图服务只依赖 analyzer.analyze_intent(text, candidates) 的同步返回值，
    这里用替身固定语义层判定，让规则层与语义层的融合逻辑可被确定性地测试，
    不再受本地 BERT 模型与阈值的漂移影响。
    """

    def __init__(self, intent="NONE", confidence=0.0, raise_error=False):
        self.intent = intent
        self.confidence = confidence
        self.raise_error = raise_error
        self.calls = []

    def analyze_intent(self, text, candidates=None):
        self.calls.append((text, list(candidates or [])))
        if self.raise_error:
            raise RuntimeError("BERT 不可用")
        return {"intent": self.intent, "confidence": self.confidence}


def _patch_bert(monkeypatch, analyzer):
    import core.services.intent.service as intent_mod

    monkeypatch.setattr(intent_mod, "get_bert_analyzer", lambda: analyzer)


def _classify(monkeypatch, text, candidates, analyzer):
    import core.services.intent.service as intent_mod

    _patch_bert(monkeypatch, analyzer)
    return asyncio.run(intent_mod.classify_intent(text, candidates=candidates))


def test_classify_intent_empty_text_returns_none():
    import core.services.intent.service as intent_mod

    res = asyncio.run(intent_mod.classify_intent("", candidates=["NONE"]))
    assert res["intent"] == "NONE"
    assert res["confidence"] == 0.0


def test_bert_primary_intent(monkeypatch):
    """语义层单独命中且通过安全守卫时，直接返回语义层意图与置信度"""
    res = _classify(
        monkeypatch,
        "帮我切换到 deepseek",
        ["SWITCH_MODEL_HINT", "NONE"],
        _StubBertAnalyzer(intent="SWITCH_MODEL_HINT", confidence=0.91),
    )

    assert res["intent"] == "SWITCH_MODEL_HINT"
    assert abs(float(res["confidence"]) - 0.91) < 1e-6
    assert res["raw"] == "[FUSION_BERT_PRIMARY]"


def test_bert_guard_blocks_intent_without_command_tone(monkeypatch):
    """缺少指令语气的模型切换表述，即使语义层命中也要否决"""
    res = _classify(
        monkeypatch,
        "换个更聪明的模型",
        ["SWITCH_MODEL_HINT", "NONE"],
        _StubBertAnalyzer(intent="SWITCH_MODEL_HINT", confidence=0.91),
    )

    assert res["intent"] == "NONE"
    assert res["confidence"] == 0.0
    assert res["raw"] == "[BERT_GUARD]"


def test_bert_guard_blocks_image_gen_negative(monkeypatch):
    """负面画图表述命中 IMAGE_GEN 时，由 IMAGE_GEN 专属守卫否决"""
    res = _classify(
        monkeypatch,
        "你会画画吗",
        ["IMAGE_GEN", "NONE"],
        _StubBertAnalyzer(intent="IMAGE_GEN", confidence=0.95),
    )

    assert res["intent"] == "NONE"
    assert res["raw"] == "[BERT_GUARD_IMAGE_GEN]"


def test_rule_primary_fused_with_bert(monkeypatch):
    """规则层与语义层一致时，置信度按规则 0.6 + 语义 0.4 融合"""
    res = _classify(
        monkeypatch,
        "帮我清空记忆",
        ["CLEAR_MEMORY", "NONE"],
        _StubBertAnalyzer(intent="CLEAR_MEMORY", confidence=0.9),
    )

    assert res["intent"] == "CLEAR_MEMORY"
    assert abs(float(res["confidence"]) - (0.97 * 0.6 + 0.9 * 0.4)) < 1e-6
    assert res["raw"] == "[FUSION_RULE_PRIMARY]"


def test_rule_only_when_bert_unavailable(monkeypatch):
    """语义层不可用时，规则层结果降权返回而不是被否决"""
    res = _classify(
        monkeypatch,
        "帮我清空记忆",
        ["CLEAR_MEMORY", "NONE"],
        _StubBertAnalyzer(raise_error=True),
    )

    assert res["intent"] == "CLEAR_MEMORY"
    assert abs(float(res["confidence"]) - 0.97 * 0.6) < 1e-6
    assert res["raw"] == "[FUSION_RULE_ONLY_BERT_UNAVAILABLE]"


def test_rule_vetoed_when_bert_returns_none(monkeypatch):
    """语义层判定为 NONE 且置信度偏低时，否决规则层结果"""
    res = _classify(
        monkeypatch,
        "帮我清空记忆",
        ["CLEAR_MEMORY", "NONE"],
        _StubBertAnalyzer(intent="NONE", confidence=0.1),
    )

    assert res["intent"] == "NONE"
    assert res["confidence"] == 0.0
    assert res["raw"] == "[FUSION_RULE_VETOED_BY_BERT]"
