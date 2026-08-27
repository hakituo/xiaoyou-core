"""语义去重模块

负责 LLM 输出的语义去重处理：
- 文本归一化与分词
- 相似度计算与语义重复判定
- 重复锚点收集
- 最近发送内容构建
- 非重复回退消息生成
"""
import difflib
import re
from typing import Any, Dict, List, Optional


class Deduplicator:
    @staticmethod
    def _resolve_repeat_policy(scene: str = "general") -> Dict[str, float]:
        """按场景返回重复检测阈值

        reminder 场景的表达空间天然更窄，因此阈值要更宽松，
        避免把正常提醒误判成复读。
        """
        scene_key = str(scene or "general").strip().lower()
        if scene_key == "reminder":
            return {
                "whole_threshold": 0.82,
                "whole_ratio_threshold": 0.72,
                "whole_combo_score_threshold": 0.52,
                "substring_min_len": 24.0,
                "partial_jaccard_threshold": 0.42,
                "partial_unigram_threshold": 0.68,
                "partial_ratio_threshold": 0.62,
            }
        return {
            # 放宽整句阈值：主动关怀场景下，模型常做"换活动词/换句式"的合理改写
            # （如"在做家务"↔"在看书"），bigram Jaccard 仍会偏高。
            # 原阈值 0.74 会把这类有效改写误判为复读并跳过发送。
            # 拉到 0.86：仅当整句词面高度重叠（近乎字面重复）才拦截，
            # 把"换汤不换药"的判断交给二次改写与少量规则，而非相似度算法。
            "whole_threshold": 0.86,
            # 整句 SequenceMatcher 比例阈值同步放宽，避免句式骨架一致就被杀。
            "whole_ratio_threshold": 0.80,
            # 组合分阈值：仅在两者都高时触发，放宽以提高容错。
            "whole_combo_score_threshold": 0.65,
            "substring_min_len": 20.0,
            "partial_jaccard_threshold": 0.45,
            "partial_unigram_threshold": 0.65,
            "partial_ratio_threshold": 0.70,
        }

    @staticmethod
    def normalize_for_repeat_check(text: str) -> str:
        """归一化文本用于重复检测：去除表情标记、保留中文/字母/数字"""
        raw = str(text or "").strip().lower()
        if not raw:
            return ""
        raw = re.sub(r"\[emo:.*?\]", "", raw)
        raw = re.sub(r"[^\u4e00-\u9fffa-z0-9]+", "", raw)
        return raw

    @staticmethod
    def tokenize_for_repeat_check(text: str) -> List[str]:
        """对归一化文本进行分词（拉丁词 + CJK bigram）"""
        normalized = Deduplicator.normalize_for_repeat_check(text)
        if not normalized:
            return []
        latin_tokens = re.findall(r"[a-z0-9]+", normalized)
        cjk_chunks = re.findall(r"[\u4e00-\u9fff]+", normalized)
        cjk_tokens: List[str] = []
        for chunk in cjk_chunks:
            if len(chunk) <= 1:
                continue
            for i in range(0, len(chunk) - 1):
                cjk_tokens.append(chunk[i : i + 2])
        if not cjk_tokens:
            cjk_tokens = cjk_chunks
        return latin_tokens + cjk_tokens

    @staticmethod
    def similarity_score(a: str, b: str) -> float:
        """基于 token 集合的 Jaccard 相似度"""
        ta = Deduplicator.tokenize_for_repeat_check(a)
        tb = Deduplicator.tokenize_for_repeat_check(b)
        if not ta or not tb:
            return 0.0
        sa = set(ta)
        sb = set(tb)
        common = len(sa & sb)
        denom = max(len(sa), len(sb), 1)
        return common / float(denom)

    @staticmethod
    def is_semantically_repetitive(
        new_text: str,
        previous_text: str,
        threshold: Optional[float] = None,
        scene: str = "general",
    ) -> bool:
        """判断新文本是否与旧文本语义重复"""
        policy = Deduplicator._resolve_repeat_policy(scene)
        new_norm = Deduplicator.normalize_for_repeat_check(new_text)
        prev_norm = Deduplicator.normalize_for_repeat_check(previous_text)
        if not new_norm or not prev_norm:
            return False
        if (
            min(len(new_norm), len(prev_norm)) >= int(policy["substring_min_len"])
            and (new_norm in prev_norm or prev_norm in new_norm)
        ):
            return True
        score = Deduplicator.similarity_score(new_text, previous_text)
        ratio = difflib.SequenceMatcher(None, new_norm, prev_norm).ratio()
        # 整句分支：仅当"词面 Jaccard 高"且"序列比例高"同时成立才判重复。
        # ratio（difflib 序列比对）对"换词不换结构"过于敏感——两条消息只要
        # 句式骨架一致（如"被踢出来→歇眼睛→这会儿在做X→你打算干嘛"），
        # ratio 就会偏高，但 Jaccard 能反映"到底换了多少词"。
        # 二者取 AND 且要求 Jaccard 也显著高，避免把"有效改写"误杀为复读。
        if (
            score >= policy["whole_ratio_threshold"]
            and ratio >= policy["whole_ratio_threshold"]
            and score >= policy["whole_combo_score_threshold"]
        ):
            return True
        final_threshold = (
            float(threshold)
            if threshold is not None
            else float(policy["whole_threshold"])
        )
        return score >= final_threshold

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        """将文本拆分为句子（支持中英文标点）"""
        # 按中英文句号、问号、感叹号、分号拆分
        parts = re.split(r"[。！？!?;；\n]+", str(text or ""))
        return [p.strip() for p in parts if len(p.strip()) >= 4]

    @staticmethod
    def _char_unigram_overlap(a: str, b: str) -> float:
        """基于中文字符 unigram 的重叠率

        比 bigram Jaccard 更能捕捉换词复述，例如：
        "饱了" vs "饱得很" → "饱" 字匹配
        "怎么还不去睡觉" vs "你到底睡不睡" → "睡" 字匹配
        """
        a_norm = Deduplicator.normalize_for_repeat_check(a)
        b_norm = Deduplicator.normalize_for_repeat_check(b)
        if not a_norm or not b_norm:
            return 0.0
        # 提取中文字符集合
        a_chars = set(re.findall(r"[\u4e00-\u9fff]", a_norm))
        b_chars = set(re.findall(r"[\u4e00-\u9fff]", b_norm))
        if not a_chars or not b_chars:
            return 0.0
        common = len(a_chars & b_chars)
        # 使用较短文本的字符数作为分母，避免长文本稀释
        denom = min(len(a_chars), len(b_chars))
        return common / float(denom)

    @staticmethod
    def is_partially_repetitive(
        new_text: str,
        anchors: List[str],
        sentence_threshold: Optional[float] = None,
        scene: str = "general",
    ) -> bool:
        analysis = Deduplicator.analyze_partial_repetition(
            new_text,
            anchors,
            sentence_threshold=sentence_threshold,
            scene=scene,
        )
        return bool(analysis["triggered"])

    @staticmethod
    def analyze_partial_repetition(
        new_text: str,
        anchors: List[str],
        sentence_threshold: Optional[float] = None,
        scene: str = "general",
    ) -> Dict[str, Any]:
        """句子级部分包含检测

        将新消息拆成句子，逐句与每条锚点比对。
        只有严格多数句子与某条锚点语义重复，才判定整条消息重复。

        检测方式：bigram Jaccard + 字符 unigram 重叠率 + SequenceMatcher，
        任一指标超过阈值即判定该句重复。
        """
        policy = Deduplicator._resolve_repeat_policy(scene)
        unigram_threshold = (
            float(sentence_threshold)
            if sentence_threshold is not None
            else float(policy["partial_unigram_threshold"])
        )
        sentences = Deduplicator._split_sentences(new_text)
        if len(sentences) <= 1:
            # 单句消息走原有的整句检测
            return {
                "triggered": False,
                "scene": scene,
                "sentences": sentences,
                "repetitive_count": 0,
                "required_count": 0,
                "matches": [],
            }
        repetitive_count = 0
        matches: List[Dict[str, Any]] = []
        required_count = (len(sentences) // 2) + 1
        for idx, sent in enumerate(sentences):
            is_rep = False
            matched_anchor = ""
            matched_reason = ""
            for anchor in anchors:
                # bigram Jaccard
                jaccard = Deduplicator.similarity_score(sent, anchor)
                if jaccard >= policy["partial_jaccard_threshold"]:
                    is_rep = True
                    matched_anchor = anchor
                    matched_reason = f"jaccard={jaccard:.2f}"
                    break
                # 字符 unigram 重叠率（对换词复述更敏感）
                unigram_overlap = Deduplicator._char_unigram_overlap(sent, anchor)
                if unigram_overlap >= unigram_threshold:
                    is_rep = True
                    matched_anchor = anchor
                    matched_reason = f"unigram={unigram_overlap:.2f}"
                    break
                # SequenceMatcher
                sent_norm = Deduplicator.normalize_for_repeat_check(sent)
                anchor_norm = Deduplicator.normalize_for_repeat_check(anchor)
                if sent_norm and anchor_norm:
                    ratio = difflib.SequenceMatcher(None, sent_norm, anchor_norm).ratio()
                    if ratio >= policy["partial_ratio_threshold"]:
                        is_rep = True
                        matched_anchor = anchor
                        matched_reason = f"ratio={ratio:.2f}"
                        break
            if is_rep:
                repetitive_count += 1
                matches.append(
                    {
                        "sentence_index": idx,
                        "sentence": sent,
                        "anchor": matched_anchor,
                        "reason": matched_reason,
                    }
                )
        return {
            "triggered": repetitive_count >= required_count,
            "scene": scene,
            "sentences": sentences,
            "repetitive_count": repetitive_count,
            "required_count": required_count,
            "matches": matches,
        }

    @staticmethod
    def collect_repeat_anchors(
        *,
        last_proactive_assistant_message: str,
        last_assistant_message: str,
        proactive_state: Dict[str, Any],
        recent_assistant_messages: List[str] | None = None,
    ) -> List[str]:
        """从历史消息中收集去重锚点

        新增 recent_assistant_messages 参数：最近多条助手消息（含普通对话），
        解决 active care 合并多条历史话题导致单条相似度被稀释的问题。
        """
        anchors: List[str] = []
        for candidate in [last_proactive_assistant_message, last_assistant_message]:
            text = str(candidate or "").strip()
            if text:
                anchors.append(text)
        state_last = str((proactive_state or {}).get("last_sent_content") or "").strip()
        if state_last:
            anchors.append(state_last)
        recent = (proactive_state or {}).get("recent_sent_contents")
        if isinstance(recent, list):
            for item in recent:
                text = str(item or "").strip()
                if text:
                    anchors.append(text)
        # 加入最近多条助手消息作为去重锚点
        if isinstance(recent_assistant_messages, list):
            for item in recent_assistant_messages:
                text = str(item or "").strip()
                if text:
                    anchors.append(text)
        deduped: List[str] = []
        seen = set()
        for text in anchors:
            norm = Deduplicator.normalize_for_repeat_check(text)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            deduped.append(text)
        return deduped

    @staticmethod
    def build_recent_sent_contents(
        proactive_state: Dict[str, Any], final_text: str, limit: int = 6
    ) -> List[str]:
        """构建最近发送内容列表（用于持久化）"""
        history: List[str] = []
        existing = (proactive_state or {}).get("recent_sent_contents")
        if isinstance(existing, list):
            for item in existing:
                text = str(item or "").strip()
                if text:
                    history.append(text)
        current = str(final_text or "").strip()
        if current:
            history.append(current)
        deduped: List[str] = []
        seen = set()
        for text in reversed(history):
            norm = Deduplicator.normalize_for_repeat_check(text)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            deduped.append(text)
        deduped.reverse()
        return deduped[-max(1, int(limit or 1)) :]

    @staticmethod
    def build_non_repetitive_fallback(
        *,
        last_user_message: str,
        previous_proactive_message: str,
        preferred_language: str,
    ) -> str:
        """生成非重复回退消息（当检测到泄露且无法提取安全消息时使用）"""
        anchor = str(last_user_message or "").strip()
        if len(anchor) > 60:
            anchor = anchor[:60] + "..."
        prev = str(previous_proactive_message or "").strip()
        if len(prev) > 60:
            prev = prev[:60] + "..."
        if str(preferred_language or "").strip().lower() == "en":
            if anchor:
                return (
                    f"You just said \"{anchor}\". "
                    "I am here with you, which part should we continue first?"
                )
            if prev:
                return (
                    "I am here with you. "
                    "Want to switch to a different angle and keep going?"
                )
            return "I am here with you. Tell me your current focus and I will continue from there."
        if anchor:
            return f"你刚说\u201c{anchor}\u201d，我在呢。你现在最想先聊哪一点？"
        if prev:
            return "我在呢。我们换个角度继续，你想先聊哪一块？"
        return "我在呢，你现在最想让我先接哪一段？"
