"""Prompt/推理泄露检测模块

负责检测 LLM 输出中是否泄露了系统提示词或推理过程：
- 泄露特征检测（强标记 + 推理语言标记 + 关键词命中）
- 从泄露文本中提取安全消息

P1-6 修复：原版关键词过度宽泛，把"我应该"、"让我想想"、"第一步"、
"首先/其次"、"用户/对话"等正常中文表达误判为泄露。现按"强泄露→
弱泄露组合→结构特征"三级收紧判定，并修复 extract_safe_message 的
行选择逻辑（原版 len(line)>24 跳过短句反而漏过正确回复）。
"""
import re


class LeakDetector:
    @staticmethod
    def looks_like_prompt_or_reasoning_dump(text: str) -> bool:
        """判断文本是否像 prompt 或推理过程的泄露

        判定层级（任一命中即判为泄露）：
        1. 强泄露标记：prompt 模板片段、工具调用标记
        2. 明确引用规则/人设/指令的元推理语言
        3. 代码字段 + 输出格式模板组合（≥2 个）
        4. 推理连接词密集 + 元引用密集的组合
        """
        raw = str(text or "").strip()
        if not raw:
            return False

        # ── 层级 1：强泄露标记（单独命中即触发） ──
        # 这些是 prompt 模板字面片段或工具调用标记，
        # 用户正常对话中不可能出现
        strong_leak_markers = [
            "【核心指令", "【核心约束", "【主动发起模式",
            "【强制字数限制", "【句式多样性",
            "[TOOL_CALL]", "[/TOOL_CALL]",
        ]
        for marker in strong_leak_markers:
            if marker in raw:
                return True

        # ── 层级 2：明确引用规则/人设/指令的元推理语言 ──
        # 必须是"明确暴露了在遵循规则/扮演角色"的表述，
        # 不包含"我应该"等正常自我表达
        explicit_meta_reasoning = [
            # 明确指代系统提示词
            "规则说", "指令说", "约束说",
            "按照规则", "根据指令", "根据约束", "根据要求",
            "遵守人设", "参考对话风格", "根据人设",
            # 暴露角色设定
            "我作为七濑", "我作为他的",
            "保持傲娇", "带点唠叨",
            # 暴露推理流程的元表述（区别于普通"我决定"）
            "我需要主动发起", "我需要自然衔接", "我需要推进",
            "换角度推进对话", "考虑到时间锚点",
            "不能重复之前的", "句式多样性",
            "确保理解上下文",
            "用户状态显示", "用户最近的消息是",
            "我的上一条回复是", "我最后一句",
            "回顾最近对话", "回顾一下最近",
            # prompt 内部术语
            "主动发起对话", "核心指令", "核心约束",
            "should_send", "next_check_seconds",
            "最终选择", "只输出一句", "输出格式",
        ]
        for marker in explicit_meta_reasoning:
            if marker in raw:
                return True

        # ── 层级 3：代码字段 + 输出格式模板组合 ──
        # 单独出现"```"可能是用户贴代码，需配合其他字段
        if len(raw) < 20:
            # 短文本只靠强标记和明确元推理判断，避免误伤正常短句
            return False

        code_or_format_keywords = [
            "should_send", "next_check_seconds",
            "我需要：", "输出格式", "```",
            "强制字数", "句式多样性",
        ]
        hit_count = sum(1 for kw in code_or_format_keywords if kw in raw)
        if hit_count >= 2:
            return True

        # ── 层级 4：推理连接词密集 + 元引用密集的组合 ──
        # 注意：移除了"首先/其次/然后/同时/因此/所以/于是/不过/然而"
        # 等普通中文连接词，它们在正常表达中也常用。
        # 只保留明显推理性的连接词组合
        reasoning_connectives = [
            "于是我决定", "因此我选择", "所以我需要",
            "综合考虑", "权衡之后", "分析之后",
        ]
        # 元引用：明确指向 prompt/规则/人设的元词汇
        # 注意：移除了"用户/对话/话题/消息/回复/之前"等普通词汇
        meta_ref_keywords = [
            "人设要求", "规则要求", "指令要求",
            "核心指令", "核心约束",
            "上一条回复", "上一次回复",
        ]
        connective_count = sum(1 for c in reasoning_connectives if c in raw)
        meta_ref_count = sum(1 for m in meta_ref_keywords if m in raw)
        if connective_count >= 1 and meta_ref_count >= 1:
            return True
        if meta_ref_count >= 2:
            return True

        # ── 层级 5：长文本 + 多段落 + 密集元推理 ──
        # 仅当文本特别长（≥8 段）且明确含"我决定用"等推理动词时触发
        if raw.count("\n") >= 8:
            long_reasoning_markers = ["我决定用", "我最终选择", "我选择用"]
            if any(m in raw for m in long_reasoning_markers):
                # 但还需配合至少一个元引用，避免误判长篇正常叙述
                if meta_ref_count >= 1:
                    return True

        return False

    @staticmethod
    def extract_safe_message_from_dump(text: str) -> str:
        """从泄露文本中尝试提取安全消息

        P1-6 修复：原版行选择逻辑存在两个 bug：
        - 用过长的阈值跳过短句，导致正常短回复被跳过、长推理句被选中
        - 阈值过短几乎不过滤任何行，随便返回一行
        现按"先尝试引号提取→再扫描最后几行→严格过滤元推理词"的顺序提取。
        """
        raw = str(text or "").strip()
        if not raw:
            return ""

        # 步骤 1：尝试从"最终：..."、"我决定用：..."等模式提取引号内消息
        direct_pick_patterns = [
            r"最终[：:]\s*[\u201c\"](.+?)[\u201d\"]",
            r"我决定用[：:]\s*[\u201c\"](.+?)[\u201d\"]",
            r"选择[：:]\s*[\u201c\"](.+?)[\u201d\"]",
        ]
        for pattern in direct_pick_patterns:
            m = re.search(pattern, raw, flags=re.DOTALL)
            if not m:
                continue
            candidate = str(m.group(1) or "").strip()
            if candidate and not LeakDetector.looks_like_prompt_or_reasoning_dump(candidate):
                # 候选必须是完整的回复句（含终止标点或足够长）
                if len(candidate) >= 4 and (
                    re.search(r"[。！？!?\.]$", candidate) or len(candidate) >= 8
                ):
                    return candidate

        # 步骤 2：扫描最后一行（最可能是 LLM 实际输出的回复）
        lines = [str(x or "").strip() for x in raw.splitlines()]
        lines = [x for x in lines if x]

        # 严格过滤：包含元推理词的行直接排除
        blocked_words = [
            "我需要", "遵守人设", "参考对话", "最终选择", "输出格式", "考虑到",
            "核心指令", "核心约束", "主动发起", "强制字数",
            "规则说", "指令说", "按照规则", "根据指令", "根据约束",
            "我应该", "优先顺着", "优先选择",
            "根据人设", "我作为七濑", "我作为他的",
            "保持傲娇", "带点唠叨",
            "should_send", "next_check_seconds",
        ]

        # 候选行要求：
        # - 长度 ≥ 4（避免选到单字/标点）
        # - 不以数字+点开头（避免选到列表序号行）
        # - 不含元推理词
        # - 优先有终止标点的句子
        candidate_lines: list[str] = []
        for line in lines:
            if len(line) < 4:
                continue
            if any(b in line for b in blocked_words):
                continue
            if re.match(r"^\d+[.、．)\s]", line):
                continue
            if LeakDetector.looks_like_prompt_or_reasoning_dump(line):
                continue
            candidate_lines.append(line)

        if not candidate_lines:
            return ""

        # 优先返回最后一个有终止标点的候选行（最可能是实际回复）
        for line in reversed(candidate_lines):
            if re.search(r"[。！？!?\.]$", line):
                return line.strip("""\u201c\u201d"'""")

        # 否则返回最后一个候选行
        return candidate_lines[-1].strip("""\u201c\u201d"'""")
