"""Active Care 提醒处理器

负责检查到期提醒、完成提醒、格式化提醒消息。
从 executor.py 拆分而来，方法签名与原 xxx 方法保持一致。

依赖注入策略：无外部依赖（仅使用局部 import 和 logger），构造器无参数。
"""
import re
from typing import Any, Optional

from core.utils.logger import get_module_logger

logger = get_module_logger("ACTIVE_CARE_EXECUTOR", "active_care_schedule.log")


class ReminderHandler:
    """提醒消息处理器

    所有方法均无副作用，仅依赖传入参数和局部 import。
    """

    async def check_reminders(self):
        """检查到期提醒"""
        try:
            from core.services.workspace.service import get_workspace_service
            ws = get_workspace_service()
            due_msgs = await ws.check_due_messages(mark_completed=False)
            if due_msgs:
                msg = due_msgs[0]
                logger.info(f"Active Care: 发现到期提醒 - {msg.message}")
                return msg
            return None
        except Exception as e:
            logger.warning(f"Active Care: 检查提醒时出错: {e}")
            return None

    async def complete_reminder(self, msg_id: str, *, triggered_at: Optional[float] = None) -> bool:
        """完成提醒"""
        try:
            from core.services.workspace.service import get_workspace_service
            ws = get_workspace_service()
            return await ws.complete_message(msg_id, triggered_at=triggered_at)
        except Exception as e:
            logger.warning(f"Active Care: 标记提醒完成失败: {e}")
            return False

    def format_due_reminder_message(self, reminder: Any) -> str:
        """格式化到期提醒消息，区分开始/结束类型

        返回的字符串会作为 reminder_msg 注入到 LLM prompt，所以这里要给 LLM
        提供足够的差异化素材（任务描述、分类、科目），让它能自然地改写，
        而不是机械地输出"该开始X了"这种模板话。

        注意：metadata 里的 task_description 等字段是后续版本才加的，
        旧 reminder 数据可能没有，这里要做兼容处理。
        """
        if reminder is None:
            return ""
        metadata = getattr(reminder, "metadata", None) or {}
        message = str(getattr(reminder, "message", "") or "").strip()

        if isinstance(metadata, dict):
            source = str(metadata.get("source") or "").strip().lower()
            task_title = str(metadata.get("task_title") or "").strip()
            task_desc = str(metadata.get("task_description") or "").strip()
            task_category = str(metadata.get("task_category") or "").strip()
            task_subject = str(metadata.get("task_subject") or "").strip()
            reminder_type = str(metadata.get("type") or "start").strip().lower()

            if source == "daily_task" and task_title:
                # 组装成"任务标识 + 任务内容 + 分类标签"的结构化上下文
                # 让 LLM 自己决定怎么说，不要在这里就把话写死
                phase = "结束时间到了，该告一段落" if reminder_type == "end" else "到时间该开始了"
                parts = [f"任务「{task_title}」{phase}"]
                if task_desc:
                    parts.append(f"计划内容：{task_desc}")
                tags = [t for t in (task_category, task_subject) if t]
                if tags:
                    parts.append(f"分类：{'/'.join(tags)}")
                return "；".join(parts)

        # 兼容路径：从原始 message 里尽力提取 task_title
        task_match = re.search(r"(?:开始做任务：|开始「|开\")(.+?)(?:」|\"|。|$)", message)
        if task_match:
            task_title = str(task_match.group(1) or "").strip(" 」\"")
            if task_title:
                return f"任务「{task_title}」到时间该开始了"
        message = re.sub(r"（此提醒由.+?自动触发）", "", message).strip()
        message = re.sub(r"\s+", " ", message).strip()
        return message

    @staticmethod
    def extract_reminder_target(reminder_msg: str) -> str:
        """从结构化提醒上下文中提取必须出现的任务目标。"""
        text = str(reminder_msg or "").strip()
        if not text:
            return ""
        for pattern in (
            r"任务[「\"]([^」\"]+)[」\"]",
            r"^(.+?)(?:到时间|时间到了|该开始|该结束)",
        ):
            match = re.search(pattern, text)
            if match:
                return str(match.group(1) or "").strip(" ：:；;，,。")
        return ""

    def enforce_reminder_target(self, generated_text: str, reminder_msg: str) -> str:
        """确保硬提醒不被近期闲聊话题带偏。

        MDP 仍负责普通主动关怀的高层动作选择；这里只有已经到期的硬提醒
        才做任务目标一致性校验。模型漏掉任务核心词时使用可控兜底文本。
        """
        content = str(generated_text or "").strip()
        target = self.extract_reminder_target(reminder_msg)
        if not target or self._mentions_reminder_target(content, target):
            return content

        reminder_text = str(reminder_msg or "")
        if "告一段落" in reminder_text or "结束" in reminder_text:
            fallback = f"{target}弄得怎么样啦？"
        else:
            fallback = f"{target}要开始啦，要不要先弄一点？"
        logger.warning(
            "Active Care: 到期提醒生成结果偏离任务目标，已使用温和兜底文本 "
            "(target=%s, generated=%s)",
            target,
            content[:120],
        )
        return fallback

    @staticmethod
    def _mentions_reminder_target(content: str, target: str) -> bool:
        """判断自然改写是否提到了任务核心词，避免强迫模型复述完整标题。"""
        normalized_content = re.sub(r"\s+", "", str(content or "")).lower()
        normalized_target = re.sub(r"\s+", "", str(target or "")).lower()
        if not normalized_target or normalized_target in normalized_content:
            return True

        # 中文任务名通常没有分词边界；任一连续双字核心词命中即可视为未跑题。
        chinese = "".join(re.findall(r"[\u4e00-\u9fff]", normalized_target))
        if len(chinese) >= 2:
            grams = {chinese[index : index + 2] for index in range(len(chinese) - 1)}
            if any(gram in normalized_content for gram in grams):
                return True

        # 英文或数字任务名按完整 token 判断，忽略单字符噪声。
        tokens = re.findall(r"[a-z0-9]{2,}", normalized_target)
        return any(token in normalized_content for token in tokens)
