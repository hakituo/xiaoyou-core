import pytest

from core.services.active_care.shared.reminder_injection import ReminderInjectionStore


@pytest.mark.asyncio
async def test_reminder_injection_store_merges_multiple_reminders():
    store = ReminderInjectionStore()

    await store.set_pending_reminder(
        reminder_text="该开始「数学复习」了",
        task_title="数学复习",
        recent_chat_summary="刚刚在聊数学",
    )
    await store.set_pending_reminder(
        reminder_text="「英语听力」时间到了，休息一下吧~",
        task_title="英语听力",
        recent_chat_summary="刚刚在聊英语",
    )

    result = await store.get_and_clear()

    assert result is not None
    assert result["merged_count"] == 2
    assert "数学复习" in result["task_title"]
    assert "英语听力" in result["task_title"]
    assert "多条计划提醒" in result["reminder_text"]
    assert len(result["reminder_items"]) == 2
    assert await store.has_pending() is False


@pytest.mark.asyncio
async def test_reminder_injection_store_deduplicates_same_reminder():
    store = ReminderInjectionStore()

    await store.set_pending_reminder(
        reminder_text="该开始「数学复习」了",
        task_title="数学复习",
        recent_chat_summary="第一次",
    )
    await store.set_pending_reminder(
        reminder_text="该开始「数学复习」了",
        task_title="数学复习",
        recent_chat_summary="第二次",
    )

    result = await store.get_and_clear()

    assert result is not None
    assert result["merged_count"] == 1
    assert result["task_title"] == "数学复习"
    assert result["recent_chat_summary"] == "第二次"
