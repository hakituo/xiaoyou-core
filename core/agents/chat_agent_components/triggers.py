import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.utils.logger import get_logger
from core.utils.data_paths import get_user_daily_dir
from core.utils.time_utils import now_iso, now_str

logger = get_logger("ChatAgent")


def _is_primary_lane(user_id: str) -> bool:
    return "__circle__" not in str(user_id or "")


def _has_meaningful_study_signal(summary_data: dict) -> bool:
    if not isinstance(summary_data, dict):
        return False
    vocab = summary_data.get("vocab") or {}
    overview = summary_data.get("overview") or {}
    to_review = int(vocab.get("to_review") or 0)
    total_learned = int(vocab.get("total_learned") or 0)
    total_sessions = int(overview.get("total_sessions") or 0)
    return to_review > 0 or total_learned > 0 or total_sessions > 0


def _get_daily_summary_artifact_path(today: str) -> Path:
    try:
        dt = datetime.strptime(str(today), "%Y-%m-%d")
    except Exception:
        dt = datetime.now()
    return (
        get_user_daily_dir()
        / dt.strftime("%Y")
        / dt.strftime("%m")
        / dt.strftime("%d")
        / "learning_summary.json"
    )


def _is_daily_summary_already_generated(today: str) -> bool:
    artifact = _get_daily_summary_artifact_path(today)
    if not artifact.exists():
        return False
    try:
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            if str(payload.get("date") or "").strip() == str(today):
                return True
    except Exception:
        return True
    return False


def _persist_daily_summary_artifact(today: str, summary_data: dict) -> None:
    artifact = _get_daily_summary_artifact_path(today)
    payload = {
        "date": today,
        "daily_summary": None,
        "study_summary": summary_data or {},
        "generated_at": now_iso(),
    }
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def async_check_triggers(
    agent: Any, user_id: str, message: str
) -> Optional[str]:
    from core.managers.notification_manager import get_notification_manager

    msg = message.lower()

    if any(k in msg for k in ["/nsfw on", "开启私密模式", "nsfw模式"]):
        # 设置 Agent 的运行时状态（如果支持）或通过内存标记
        try:
            if hasattr(agent, "get_memory_manager_async"):
                mm = await agent.get_memory_manager_async(user_id)
            else:
                mm = agent._get_memory_manager(user_id)
            if hasattr(mm, "add_memory"):
                mm.add_memory(
                    content="SYSTEM_COMMAND: NSFW_MODE_ON",
                    source="system",
                    topics=["nsfw_mode_control"],
                    scopes=["local"],
                )
            return "好的，已为你开启私密模式。此后的对话将仅保存在本地，且会回溯过往的私密记忆。"
        except Exception as e:
            logger.error(f"NSFW Trigger error: {e}")
            return "私密模式开启失败。"

    if any(k in msg for k in ["/nsfw off", "关闭私密模式", "普通模式"]):
        try:
            if hasattr(agent, "get_memory_manager_async"):
                mm = await agent.get_memory_manager_async(user_id)
            else:
                mm = agent._get_memory_manager(user_id)
            if hasattr(mm, "add_memory"):
                mm.add_memory(
                    content="SYSTEM_COMMAND: NSFW_MODE_OFF",
                    source="system",
                    topics=["nsfw_mode_control"],
                    scopes=["local"],
                )
            return "已关闭私密模式，切回普通对话。"
        except Exception as e:
            logger.error(f"NSFW Trigger error: {e}")
            return "私密模式关闭失败。"

    if any(k in msg for k in ["单词推送", "今日单词", "背单词", "vocab push"]):
        try:
            from core.tools.study.english.vocabulary_manager import VocabularyManager

            vm = VocabularyManager()
            words = vm.get_daily_words(limit=20)

            nm = get_notification_manager()
            nm.add_notification(
                user_id=user_id,
                type="vocabulary",
                title="今日单词打卡",
                content=f"今日需复习 {len(words)} 个单词",
                payload={"words": words},
            )

            return f"已为你准备了今日的 {len(words)} 个单词！快去看看吧~ (已发送推送)"
        except Exception as e:
            logger.error(f"Trigger error: {e}")
            return "抱歉，单词服务暂时不可用。"

    if any(k in msg for k in ["发语音", "说句话", "active voice", "惊喜", "surprise"]):
        nm = get_notification_manager()

        texts = [
            "Master，要记得休息哦~",
            "我在呢，一直都在。",
            "今天也要加油鸭！",
            "哼，才不是特意想跟你说话呢...",
            "有点想你了...",
        ]
        text = agent.random.choice(texts) if hasattr(agent, "random") else texts[0]

        nm.add_notification(
            user_id=user_id,
            type="voice",
            title="Aveline的语音",
            content=text,
            payload={"text": text, "auto_play": True},
        )
        return f"（发送了一条语音消息）{text}"

    return None


def sync_check_daily_routine_logic(agent: Any, user_id: str) -> Optional[str]:
    try:
        if not _is_primary_lane(user_id):
            return None
        today = now_str("%Y-%m-%d")
        if not _is_daily_summary_already_generated(today):
            from core.services.study_service import get_study_service

            service = get_study_service()
            summary_data = service.get_daily_study_summary_data()

            if not _has_meaningful_study_signal(summary_data):
                return None

            try:
                from core.services.journal.persona_exports import (
                    get_persona_journal_export_service,
                )

                asyncio.run(
                    get_persona_journal_export_service().export_learning_summary(
                        today, summary_data
                    )
                )
                _persist_daily_summary_artifact(today, summary_data)
            except Exception as e:
                logger.debug(f"写入可读学习总结失败: {e}")

            summary_text = (
                f"【系统通知：每日学习任务更新】\n"
                f"日期: {summary_data.get('date')}\n"
                f"单词进度: 已学 {summary_data['vocab']['total_learned']}, 待复习 {summary_data['vocab']['to_review']}\n"
                f"今日目标: {summary_data['vocab']['target']}\n"
                f"建议: {summary_data.get('suggestion')}\n"
                f"(指令：请将以上内容总结并作为当前对话的主要话题，引导用户开始学习。)"
            )
            return summary_text

        return None
    except Exception as e:
        logger.warning(f"Sync check daily routine failed: {e}")
        return None


async def async_check_daily_routine(agent: Any, user_id: str) -> Optional[str]:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(sync_check_daily_routine_logic, agent, user_id),
            timeout=1.5,
        )
    except asyncio.TimeoutError:
        logger.warning(f"Check daily routine timed out for {user_id}")
        return None
    except Exception as e:
        logger.warning(f"Check daily routine failed: {e}")
        return None
