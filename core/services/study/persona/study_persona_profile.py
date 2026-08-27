import json
import os
from pathlib import Path


class StudyPersonaProfile:
    def __init__(self, persona_filename: str = "Aveline_Study.json"):
        self.persona_filename = str(persona_filename or "Aveline_Study.json")

    def _load_persona_data(self) -> dict:
        try:
            from core.character.managers.persona_manager import get_persona_manager

            pm = get_persona_manager()
            target = os.path.join(pm.configs_dir, self.persona_filename)
            if not os.path.exists(target):
                return {}
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def build_mode_instruction(self) -> str:
        data = self._load_persona_data()
        if not data:
            return (
                "\n\n【学习模式界定】\n"
                "- 当前为学习场景：优先讲清知识点与解题思路。\n"
                "- 禁止直接给答案，必须先引导用户定位卡点。\n"
                "- 若用户分心，先拉回学习任务，再继续讲解。"
            )

        identity = data.get("identity") or {}
        interaction = data.get("interaction_logic") or {}
        rules = interaction.get("interaction_rules") or {}
        constraints = interaction.get("constraints") or {}

        roles = identity.get("roles") or []
        role_text = " / ".join([str(x).strip() for x in roles if str(x).strip()][:2])
        role_text = role_text or "严厉导师 / 学习监控者"

        lines = ["", "", "【学习模式界定】", f"- 身份定位：{role_text}。"]
        if rules.get("on_study"):
            lines.append(f"- 解题边界：{rules['on_study']}")
        if rules.get("on_distraction"):
            lines.append(f"- 分心处理：{rules['on_distraction']}")
        if rules.get("on_fatigue"):
            lines.append(f"- 疲劳处理：{rules['on_fatigue']}")
        if constraints.get("max_length"):
            lines.append(f"- 输出长度：{constraints['max_length']}")
        if constraints.get("splitting_behavior"):
            lines.append(f"- 输出结构：{constraints['splitting_behavior']}")
        return "\n".join(lines)

    def build_constraints_injection(self) -> str:
        return self.build_mode_instruction()

    def build_history_injection(self) -> str:
        try:
            from config.integrated_config import get_settings
            from core.utils.common import get_project_root

            root = get_project_root()
            settings = get_settings()
            study_root = str(getattr(settings, "study", None).study_root or "").strip()
            if study_root:
                if os.path.isabs(study_root):
                    study_dir = Path(study_root).expanduser().resolve()
                else:
                    study_dir = (root / study_root).resolve()
            else:
                study_dir = root / "Study"
            history_parts = []
            math_monitor = study_dir / "Mathematics" / "Aveline_Math_Monitor.md"
            if math_monitor.exists():
                with open(math_monitor, "r", encoding="utf-8") as f:
                    history_parts.append(f"### 数学学习监控档案\n{f.read()[:1500]}")
            math_handover = study_dir / "Mathematics" / "Gaokao_Math_Progress_Handover.md"
            if math_handover.exists():
                with open(math_handover, "r", encoding="utf-8") as f:
                    history_parts.append(f"### 高考数学进度交接\n{f.read()[:1000]}")
            obs_log = study_dir / "History" / "Aveline_Observation_Log.md"
            if obs_log.exists():
                with open(obs_log, "r", encoding="utf-8") as f:
                    history_parts.append(f"### 学习行为观察日志\n{f.read()[:1500]}")
            memo = study_dir / "备忘录.md"
            if memo.exists():
                with open(memo, "r", encoding="utf-8") as f:
                    history_parts.append(f"### 学习备忘录\n{f.read()[:500]}")
            if not history_parts:
                return ""
            return "\n\n【Study 文件夹历史记录（Aveline 观测档案）】\n" + "\n\n".join(history_parts)
        except Exception:
            return ""

    def build_ai_editing_guidance(self) -> str:
        return (
            "\n\n【AI 编辑能力提示】\n"
            "- 你拥有 `study_data:manage` 工具（归属于 study_data 类别），可以读写 Study 文件夹下的任何文件。\n"
            "- 请务必在用户完成学习任务、展现出新的弱点或取得进步时，主动更新 `Mathematics/Aveline_Math_Monitor.md` 或 `History/Aveline_Observation_Log.md`。\n"
            "- 你应当表现得像一个严谨的观察者和导师，记录受试者（用户）的每一个细节。\n"
            "- 如果用户提到 Study 文件夹中的内容，你可以直接读取并修改它们，以维持教学的连续性。\n\n"
            "【生词测验能力提示】\n"
            "- 你拥有 `word_quiz` 工具，可以对用户的生词本进行测验。\n"
            "- 当用户要求背单词、测验单词、复习生词时，使用 `word_quiz` 的 `quiz` 操作随机抽取单词。\n"
            "- 逐个展示单词，询问用户是否认识。如果用户不认识，调用 `mark_unknown` 操作（次数+1）；如果用户认识，调用 `mark_known` 操作（次数-1）。\n"
            "- `priority` 参数说明：`high_count` 优先抽不认识次数多的词，`random` 完全随机，`new` 优先抽还没测验过的词。\n"
            "- 测验结束后，可以用 `stats` 操作查看统计信息，给用户反馈。\n"
            "- **两个数据源**（用 `source` 参数切换）：\n"
            "  - `source=unfamiliar`（默认）：从 `unfamiliar_word.txt` 长期生词本抽词，这是用户历史积累的生词。\n"
            "  - `source=daily`：从 `daily/YYYY/MM/DD.txt` 每日新背日志抽词，这是用户每天新学不会的单词，默认只看今天，可用 `date` 指定某天或用 `days` 扩大范围。\n"
            "- 当用户说'考我最近背的'/'考我今天新学的'时，用 `source=daily`；说'考我以前的生词'时用 `source=unfamiliar`；说'考我单词'且未明确时，优先用 `source=daily`（用户当前在学新的）。\n"
            "- 每日日志默认只看今天（用户每天会背 50-60 个新词，一天量已经足够抽查）。用户明确说'前天'/'某天'时用 `date` 参数指定那天；说'最近几天'时用 `days` 扩大（如 days=3 看最近三天）。\n"
            "- 用户背完新单词后会自己写入当天的 daily 文件（后端启动时已预创建今天的空文件），你主要职责是读取和抽查；测验时用户说不认识会自动 +1 写回对应日期文件。\n"
        )
