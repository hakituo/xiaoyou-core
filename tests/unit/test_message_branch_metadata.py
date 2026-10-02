from types import SimpleNamespace

from core.agents.chat_agent_components.message_branch import (
    branch_metadata_for_role,
    get_request_branch_metadata,
    normalize_branch_metadata,
    reset_request_branch_metadata,
    set_request_branch_metadata,
)
from memory.core.storage import _check_duplicate, _is_low_value_for_weighted


def _branch_payload(**overrides):
    payload = {
        "user_message_id": "android-user",
        "user_parent_id": "android-parent",
        "user_variant_index": 1,
        "user_variant_count": 2,
        "user_variant_of": "android-user-old",
        "assistant_message_id": "android-ai",
        "assistant_parent_id": "android-user",
        "assistant_variant_index": 2,
        "assistant_variant_count": 3,
        "assistant_variant_of": "android-ai-old",
    }
    payload.update(overrides)
    return payload


def test_branch_metadata_normalizes_and_projects_per_role():
    normalized = normalize_branch_metadata(_branch_payload())
    assert normalized is not None

    user = branch_metadata_for_role(normalized, "user")
    assistant = branch_metadata_for_role(normalized, "assistant")

    assert user == {
        "client_message_id": "android-user",
        "parent_id": "android-parent",
        "variant_index": 1,
        "variant_count": 2,
        "variant_of": "android-user-old",
    }
    assert assistant == {
        "client_message_id": "android-ai",
        "parent_id": "android-user",
        "variant_index": 2,
        "variant_count": 3,
        "variant_of": "android-ai-old",
    }


def test_branch_metadata_contextvar_restores_previous_request():
    outer = set_request_branch_metadata(_branch_payload(user_message_id="outer-user"))
    try:
        assert get_request_branch_metadata()["user_message_id"] == "outer-user"
        inner = set_request_branch_metadata(_branch_payload(user_message_id="inner-user"))
        try:
            assert get_request_branch_metadata()["user_message_id"] == "inner-user"
        finally:
            reset_request_branch_metadata(inner)
        assert get_request_branch_metadata()["user_message_id"] == "outer-user"
    finally:
        reset_request_branch_metadata(outer)
    assert get_request_branch_metadata() is None


def test_invalid_branch_metadata_is_rejected():
    assert normalize_branch_metadata({"user_message_id": "only-user"}) is None
    assert normalize_branch_metadata("bad") is None


def test_client_tree_node_is_not_dropped_as_low_value_memory():
    assert not _is_low_value_for_weighted(
        content="嗯",
        source="user",
        category="event",
        is_important=False,
        metadata={"client_message_id": "android-short-node"},
    )
    assert _is_low_value_for_weighted(
        content="嗯",
        source="user",
        category="event",
        is_important=False,
        metadata={},
    )


def test_client_message_id_dedupe_does_not_merge_parallel_same_text():
    memory = {
        "id": "wm-old",
        "content": "完全一样的回复",
        "source": "assistant",
        "category": "event",
        "metadata": {"client_message_id": "android-v2"},
    }
    ctx = SimpleNamespace(
        weighted_memories={"wm-old": memory},
        # 模拟旧版启动重建留下的正文 dedupe key。
        content_dedupe_index={"完全一样的回复\x00assistant\x00event": "wm-old"},
    )

    assert (
        _check_duplicate(
            ctx,
            "完全一样的回复",
            "assistant",
            "event",
            metadata={"client_message_id": "android-v2"},
        )
        == "wm-old"
    )
    assert (
        _check_duplicate(
            ctx,
            "完全一样的回复",
            "assistant",
            "event",
            metadata={"client_message_id": "android-v3"},
        )
        == ""
    )
    # 普通非树记忆也不能误合并到某个 Android 分支节点。
    assert _check_duplicate(ctx, "完全一样的回复", "assistant", "event") == ""
