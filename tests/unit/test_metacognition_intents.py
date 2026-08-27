import asyncio


def test_metacognition_precompute_and_inject(tmp_path, monkeypatch):
    import core.services.metacognition.service as meta_mod

    class _Mem:
        history_dir = str(tmp_path)

    class _Settings:
        memory = _Mem()

    monkeypatch.setattr(meta_mod, "get_settings", lambda: _Settings())

    svc = meta_mod.MetaIntentService()

    asyncio.run(
        svc.precompute_after_turn(
            user_id="u1",
            scope="local",
            message_id="m1",
            user_text="我下周想做一个提醒功能，怎么设计比较好？",
            assistant_text="好的，我们可以先拆分需求。",
        )
    )

    inj = asyncio.run(
        svc.build_injection(
            user_id="u1",
            scope="local",
            message="提醒功能我现在开始做了，先从存储结构开始",
            max_items=2,
            cooldown_seconds=0,
        )
    )

    assert inj is not None
    assert "元认知线索" in inj[0]

