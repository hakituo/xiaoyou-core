"""
学习模式工具

AI可以主动调用进入/退出学习模式，系统会相应地：
- 注入学习模式prompt
- 触发学习会话压缩（退出时）

工具列表：
- EnterStudyModeTool: 进入学习模式
- ExitStudyModeTool: 退出学习模式
"""
from __future__ import annotations
from core.utils.logger import get_logger

import time

from typing import Dict, Optional
from pydantic import BaseModel, Field

from core.tools.base import BaseTool

logger = get_logger("Tools.StudyMode")

# 学习会话存储（按用户隔离）
_study_sessions: Dict[str, dict] = {}


def is_study_mode_active(user_id: str) -> bool:
    """检查用户是否处于学习模式"""
    session = _study_sessions.get(str(user_id).strip())
    return bool(session and session.get("active"))


def get_study_session(user_id: str) -> Optional[dict]:
    """获取学习会话信息"""
    return _study_sessions.get(str(user_id).strip())


def get_study_prompt_for_injection(user_id: str) -> Optional[str]:
    """获取当前用户应注入的学习模式prompt"""
    session = _study_sessions.get(str(user_id).strip())
    if not session or not session.get("active"):
        return None
    
    subject = session.get("subject", "")
    topic = session.get("topic", "")
    
    # 基础学习模式prompt
    prompt = _STUDY_MODE_PROMPT
    
    # 如果指定了学科/主题，添加专门的指导
    if subject:
        prompt += f"\n\n当前学习学科：{subject}"
    if topic:
        prompt += f"\n当前学习主题：{topic}"
    
    return prompt


def _set_study_state(user_id: str, active: bool, subject: str = "", topic: str = ""):
    """设置学习模式状态"""
    uid = str(user_id).strip()
    if active:
        _study_sessions[uid] = {
            "active": True,
            "subject": subject,
            "topic": topic,
            "entered_at": time.time(),
        }
        logger.info(f"用户 {uid} 进入学习模式 subject={subject} topic={topic}")
    else:
        session = _study_sessions.get(uid)
        if session:
            session["active"] = False
            session["exited_at"] = time.time()
            logger.info(f"用户 {uid} 退出学习模式")


# 学习模式prompt
_STUDY_MODE_PROMPT = """【学习模式已激活】

你现在处于教学/学习辅助模式。请遵循以下原则：

1. **知识准确性优先**：回答要准确、有依据，不要猜测或编造
2. **循序渐进**：根据用户水平调整解释深度，从基础开始逐步深入
3. **引导思考**：不要直接给答案，引导用户自己思考（适当情况下）
4. **举例说明**：用具体例子帮助理解抽象概念
5. **结构化输出**：使用标题、列表、代码块等格式让内容更清晰
6. **鼓励提问**：欢迎用户追问，耐心解答每一个问题

【注意】
- 这是学习场景，请保持专业、耐心的态度
- 如果涉及专业知识，尽量引用来源或说明依据
- 退出学习模式时，我会自动压缩学习过程中的长上下文
"""


class EnterStudyModeInput(BaseModel):
    """进入学习模式参数"""
    subject: str = Field(
        default="",
        description="学习学科（可选），如：佛学、印度历史、Python编程"
    )
    topic: str = Field(
        default="",
        description="具体学习主题（可选），如：般若心经、莫卧儿帝国、装饰器"
    )


class EnterStudyModeTool(BaseTool):
    name = "enter_study_mode"
    description = "进入学习模式。当用户开始学习、请教知识、讨论学术话题时调用。系统会注入教学指导prompt，并在退出学习模式时自动压缩学习过程的长上下文。"
    short_description = "进入学习模式，优化教学场景"
    args_schema = EnterStudyModeInput
    category = "study"
    enabled_by_default = True

    async def _run(self, subject: str = "", topic: str = "") -> str:
        user_id = self._get_ctx("user_id", "default")
        
        # 如果已经在学习模式，更新主题
        if is_study_mode_active(user_id):
            session = get_study_session(user_id)
            if subject and subject != session.get("subject"):
                _set_study_state(user_id, True, subject, topic)
                return f"已更新学习主题：学科={subject}, 主题={topic}"
            return "已经在学习模式中"
        
        _set_study_state(user_id, True, subject, topic)
        
        subject_str = f"（学科：{subject}）" if subject else ""
        topic_str = f"（主题：{topic}）" if topic else ""
        return f"已进入学习模式{subject_str}{topic_str}。我会以更专业、耐心的方式协助你学习。退出学习模式时会自动压缩学习过程的长上下文。"


class ExitStudyModeInput(BaseModel):
    """退出学习模式参数"""
    reason: str = Field(
        default="",
        description="退出原因（可选），如：学完了、换个话题、休息一下"
    )


class ExitStudyModeTool(BaseTool):
    name = "exit_study_mode"
    description = "退出学习模式。当用户表示学完了、要切换话题、或想休息时调用。系统会自动压缩学习过程中的长上下文以节省token。"
    short_description = "退出学习模式，压缩学习上下文"
    args_schema = ExitStudyModeInput
    category = "study"
    enabled_by_default = True

    async def _run(self, reason: str = "") -> str:
        user_id = self._get_ctx("user_id", "default")
        
        if not is_study_mode_active(user_id):
            return "当前不在学习模式"
        
        session = get_study_session(user_id)
        subject = session.get("subject", "")
        duration = time.time() - session.get("entered_at", time.time())
        duration_min = round(duration / 60, 1)
        
        _set_study_state(user_id, False)
        
        # 学习会话压缩会在context_budget.py中自动触发（通过检测学习→非学习边界）
        
        reason_str = f"（原因：{reason}）" if reason else ""
        subject_str = f"学科：{subject}，" if subject else ""
        return f"已退出学习模式{reason_str}。{subject_str}学习时长：{duration_min}分钟。学习过程中的长上下文会在下次构建时自动压缩。"
