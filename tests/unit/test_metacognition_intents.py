import asyncio


def test_metacognition_precompute_and_inject(tmp_path, monkeypatch):
    """未完成意图会被记录，并在相关话题下注入跟进提示"""
    import core.services.metacognition.service as meta_mod

    class _Mem:
        history_dir = str(tmp_path)

    class _Settings:
        memory = _Mem()

    monkeypatch.setattr(meta_mod, "get_settings", lambda: _Settings())

    svc = meta_mod.MetaIntentService()

    tracked = asyncio.run(
        svc.precompute_after_turn(
            user_id="u1",
            scope="local",
            message_id="m1",
            user_text="我下周想做一个提醒功能，怎么设计比较好？",
            assistant_text="好的，我们可以先拆分需求。",
        )
    )
    assert tracked is not None, "含明确意图的用户发言应被追踪"
    assert tracked.status == "pending"

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
    content, chosen_ids = inj
    assert content.startswith("【未完成意图追踪"), f"注入内容缺少现行标题: {content[:40]}"
    assert "提醒功能" in content, "注入内容应包含原始意图摘要"
    assert chosen_ids, "应返回被选中的意图 id"


def test_metacognition_no_injection_without_pending_intent(tmp_path, monkeypatch):
    """没有待跟进意图时不注入，避免空提示进入 Prompt"""
    import core.services.metacognition.service as meta_mod

    class _Mem:
        history_dir = str(tmp_path)

    class _Settings:
        memory = _Mem()

    monkeypatch.setattr(meta_mod, "get_settings", lambda: _Settings())

    svc = meta_mod.MetaIntentService()

    assert (
        asyncio.run(
            svc.precompute_after_turn(
                user_id="u2",
                scope="local",
                message_id="m2",
                user_text="",
                assistant_text="",
            )
        )
        is None
    )

    inj = asyncio.run(
        svc.build_injection(
            user_id="u2",
            scope="local",
            message="随便聊点什么",
            max_items=2,
            cooldown_seconds=0,
        )
    )
    assert inj is None
