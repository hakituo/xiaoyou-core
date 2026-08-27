"""睡眠场景净化模块

负责 LLM 输出中与睡眠相关的各类净化处理：
- 睡眠时间声明净化（避免 AI 凭空声称知道用户作息）
- 睡眠场景邀请矛盾净化（避免"晚安"与"来聊"同时出现）
- 低打扰输出强制（用户已睡时避免提问或催促）
- 冗余睡眠问题净化（已知入睡时间后不再重复询问）
"""
import random
import re

# 短句关怀类 sys_prompt_type：晚安/早安/睡回去主动消息本身就是低打扰告别/问候，
# 不应被 enforce_sleep_low_disturb_output / sanitize_sleep_scene_invitation
# 误判为"催用户睡觉"或"矛盾邀请"而替换成 fallback 模板。
# 典型 bug：LLM 返回"困了...先去睡了\n晚安~"被 enforce_sleep_low_disturb_output
# 中的"去睡"正则误判为催用户睡觉，最终替换成"你先休息，等你醒来我们再聊。"。
_SHORT_CARE_SYS_PROMPT_TYPES = frozenset(
    {"goodnight_proactive", "good_morning_proactive", "sleep_again_proactive"}
)


class SleepSanitizer:
    @staticmethod
    def sanitize_sleep_time_claims(text: str) -> str:
        """净化 AI 对用户睡眠时间的虚假声明"""
        raw = str(text or "").strip()
        if not raw:
            return raw
        has_sleep_time_claim = bool(
            re.search(
                r"昨晚[^\n]{0,24}(?:\d{1,2}|[零一二三四五六七八九十两]{1,3})\s*(?:点|:|：)[^\n]{0,10}睡",
                raw,
            )
        )
        has_sleep_duration_claim = bool(
            re.search(
                r"(?:昨晚|昨夜)[^\n]{0,16}"
                r"睡(?:了|着|过)?[^\n]{0,6}"
                r"(?:\d{1,2}|[零一二三四五六七八九十两半几]{1,3})"
                r"\s*(?:小时|分钟|min|h|个半小时|个钟)",
                raw,
            )
        )
        if not has_sleep_time_claim and not has_sleep_duration_claim:
            return raw
        fallbacks = [
            "昨晚你应该也挺累了，先照顾好自己。",
            "昨晚辛苦了，好好休息。",
            "昨晚你也挺累的吧，注意休息。",
            "不管怎样，休息好最重要。",
            "昨晚一定很晚才睡吧，今天注意身体。",
        ]
        return random.choice(fallbacks)

    @staticmethod
    def sanitize_sleep_scene_invitation(text: str, *, sys_prompt_type: str = "") -> str:
        """净化睡眠场景中的矛盾邀请（如"晚安"后又说"来聊"）"""
        raw = str(text or "").strip()
        if not raw:
            return raw
        # 短句关怀类场景（晚安/早安/睡回去）本身就是告别/问候，
        # 不会出现"晚安+邀请聊天"的矛盾，跳过此净化避免误伤。
        if str(sys_prompt_type or "").strip() in _SHORT_CARE_SYS_PROMPT_TYPES:
            return raw
        sleep_scene_hit = bool(re.search(r"(晚安|睡|休息|明早|醒来|不用回我|夜里|凌晨)", raw))
        invite_hit = bool(
            re.search(r"(来聊|聊聊|聊会|和我聊|等你回|回我一下|你醒了就|醒了聊|醒了回)", raw)
        )
        if not (sleep_scene_hit and invite_hit):
            return raw
        # fallback 不得包含"你先休息"/"等你醒来"这类用户明确反感的模板话术，
        # 也不得包含邀请聊天的内容（避免与触发条件自相矛盾）。
        fallbacks = [
            "好好休息，明天聊。",
            "夜深了，先休息吧，明天见。",
            "不打扰你了，晚安，明天再聊。",
            "早点休息，明天见。",
            "晚安，好好睡。",
        ]
        return random.choice(fallbacks)

    @staticmethod
    def enforce_sleep_low_disturb_output(
        text: str,
        *,
        sleep_session_active: bool,
        sleep_confirmed_by_silence: bool,
        sys_prompt_type: str = "",
    ) -> str:
        """用户已确认入睡时，强制输出为低打扰内容

        注意：仅适用于主动聊天场景（active_care_chat 等普通主动消息）。
        晚安/早安/睡回去主动消息（goodnight_proactive/good_morning_proactive/
        sleep_again_proactive）本身就是低打扰告别/问候，跳过此净化避免误伤。

        典型 bug：LLM 返回"困了...先去睡了\n晚安~"被 contains_strong_instruction
        中的"去睡"正则误判为催用户睡觉，最终替换成"你先休息，等你醒来我们再聊。"。
        """
        raw = str(text or "").strip()
        if not raw:
            return raw
        # 短句关怀类场景跳过：这些场景的"去睡"/"睡吧"是角色自己入睡，
        # 不是催用户睡觉，不应触发低打扰替换。
        if str(sys_prompt_type or "").strip() in _SHORT_CARE_SYS_PROMPT_TYPES:
            return raw
        if not sleep_session_active or not sleep_confirmed_by_silence:
            return raw
        contains_question = "？" in raw or "?" in raw
        contains_sleep_probe = bool(re.search(r"(睡了没|睡着没|还没睡|醒着吗)", raw))
        # 强指令正则：用负向先行断言排除"去睡了"（角色自己入睡的过去时态），
        # 仅匹配催用户睡觉的祈使语气（去睡吧/去睡觉/快去睡 等）。
        contains_strong_instruction = bool(
            re.search(r"(快睡|睡吧|去睡(?!了)|闭眼|别熬夜|立刻去睡)", raw)
        )
        if not (contains_question or contains_sleep_probe or contains_strong_instruction):
            return raw
        # fallback 不得包含"你先休息"/"等你醒来"这类用户明确反感的模板话术。
        fallbacks = [
            "先安心休息吧，明天再聊。",
            "好好睡，晚安。",
            "夜深了，早点休息哦。",
            "不打扰你了，好好休息。",
            "晚安，好好睡。",
        ]
        return random.choice(fallbacks)

    @staticmethod
    def sanitize_redundant_sleep_question(
        text: str, *, known_sleep_time: str, last_user_message: str
    ) -> str:
        """已知用户入睡时间后，净化冗余的睡眠询问"""
        raw = str(text or "").strip()
        if not raw:
            return raw
        sleep_time = str(known_sleep_time or "").strip()
        if not sleep_time:
            return raw
        asks_bedtime = bool(
            re.search(
                r"((昨晚|昨天).{0,10}(几点|几[点时]).{0,10}(睡|入睡))|((昨晚|昨天).{0,18}(睡了没|几点睡的|啥时候睡))",
                raw,
            )
        )
        asks_sleepiness = bool(
            re.search(r"(现在|今天|还).{0,6}(困|累|乏|想睡|犯困|打瞌睡|精神|睡得够|睡够)", raw)
        )
        if not asks_bedtime and not asks_sleepiness:
            return raw
        anchor = str(last_user_message or "").strip()
        if anchor and len(anchor) > 30:
            anchor = anchor[:30] + "..."
        if asks_sleepiness and not asks_bedtime:
            return f"我知道你昨晚大概{sleep_time}睡的，你先照顾好自己。"
        if anchor:
            return f'我记着你昨晚大概{sleep_time}睡的。你刚提到\u201c{anchor}\u201d，先把眼前的事处理好，不用急着回我。'
        return f"我记着你昨晚大概{sleep_time}睡的。你先照顾好自己，不用急着回我。"
