import asyncio


def test_intent_repair_json(monkeypatch):
    import core.services.intent.service as intent_mod

    class _StubLLM:
        def __init__(self):
            self._i = 0
            self._outs = [
                "intent: SWITCH_MODEL_HINT, confidence: 0.91",
                '{"intent":"SWITCH_MODEL_HINT","confidence":0.91,"slots":{}}',
            ]

        def create_chat_completion(self, **kwargs):
            out = self._outs[min(self._i, len(self._outs) - 1)]
            self._i += 1
            return {"choices": [{"message": {"content": out}}]}

    async def _fake_get_intent_llm(model_path: str):
        return _StubLLM()

    monkeypatch.setattr(intent_mod, "get_intent_llm", _fake_get_intent_llm)

    res = asyncio.run(
        intent_mod.classify_intent(
            "换个更聪明的模型",
            candidates=["SWITCH_MODEL_HINT", "NONE"],
            model_path="__stub__",
        )
    )

    assert res["intent"] == "SWITCH_MODEL_HINT"
    assert abs(float(res["confidence"]) - 0.91) < 1e-6
    assert isinstance(res.get("slots"), dict)
