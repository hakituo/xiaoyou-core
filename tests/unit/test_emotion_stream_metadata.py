import asyncio


from core.services.aveline.service import AvelineService


def test_stream_conversation_response_done_has_emotion_fields():
    svc = AvelineService.__new__(AvelineService)
    svc._conversation_idempotency_cache = None
    svc.chat_agent = None

    async def fake_stream_generate_response(**_kwargs):
        yield {"type": "token", "content": "你好", "done": False}
        yield {
            "type": "emotion_update",
            "data": {
                "primary_emotion": "sad",
                "intensity": 0.9,
                "confidence": 0.9,
                "sub_emotions": {"sad": 0.9},
            },
            "done": False,
        }
        yield {"done": True}

    svc.stream_generate_response = fake_stream_generate_response

    async def _run():
        out = []
        async for msg in AvelineService.stream_conversation(
            svc,
            user_input="hi",
            conversation_id="u",
            request_id="r",
            message_id="m",
        ):
            out.append(msg)
        return out

    messages = asyncio.run(_run())
    done = [m for m in messages if m.get("type") == "message" and m.get("subtype") == "response_done"]
    assert done, "response_done must be emitted"
    last_done = done[-1]
    assert last_done.get("emotion") == "sad"
    assert last_done.get("emotion_internal") == {"sad": 0.9}

