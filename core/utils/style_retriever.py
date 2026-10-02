import json
import os
import re
from typing import Dict, List, Optional

from core.utils.logger import get_logger

logger = get_logger("StyleRetriever")


class StyleRetriever:
    def __init__(self, memory_file_path: str, static_fallback_path: Optional[str] = None):
        """
        初始化性格/风格检索器
        :param memory_file_path: 包含聊天记录的 JSON/JSONL 文件路径
        :param static_fallback_path: 包含人工筛选对话块的 TXT 或 JSON 文件路径
        """
        self.memory_file_path = memory_file_path
        self.static_fallback_path = static_fallback_path

        self.conversations = self._load_memory()
        self.static_examples = self._load_static_examples()

        logger.info("Loaded %d conversation fragments from memory bank.", len(self.conversations))
        if self.static_examples:
            logger.info("Loaded %d manual fallback dialogue examples.", len(self.static_examples))

    @staticmethod
    def _normalize_dialogue_line(line: str) -> str:
        text = str(line or "").strip()
        if not text:
            return ""
        text = re.sub(r"^用户[:：]\s*", "用户：", text)
        text = re.sub(r"^Ling[:：]\s*", "Ling：", text)
        return text

    def _parse_manual_dialogue_blocks(self, content: str) -> List[Dict]:
        blocks = re.split(r"(?:\n\s*[-=]{8,}\s*\n)+", str(content or ""))
        examples: List[Dict] = []
        for block in blocks:
            lines = []
            for raw_line in block.splitlines():
                normalized = self._normalize_dialogue_line(raw_line)
                if normalized:
                    lines.append(normalized)
            block_text = "\n".join(lines).strip()
            if block_text:
                examples.append({"text": block_text})
        return examples

    def _load_memory(self) -> List[Dict]:
        """加载并预处理数据，支持 .json 和 .jsonl 格式"""
        if not self.memory_file_path or not os.path.exists(self.memory_file_path):
            logger.warning("Memory file not found: %s", self.memory_file_path)
            return []

        conversations: List[Dict] = []
        try:
            if self.memory_file_path.endswith(".jsonl"):
                with open(self.memory_file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            obj = json.loads(line)
                            if isinstance(obj, dict) and isinstance(obj.get("chain"), dict):
                                chain = obj.get("chain") or {}
                                turns = chain.get("turns") or []
                                user_lines = []
                                ling_lines = []
                                for turn in turns:
                                    if not isinstance(turn, dict):
                                        continue
                                    speaker = str(turn.get("speaker") or "").strip()
                                    content = str(turn.get("content") or "").strip()
                                    if not content:
                                        continue
                                    if speaker == "user":
                                        user_lines.append(content)
                                    elif speaker == "ling":
                                        ling_lines.append(content)
                                if user_lines or ling_lines:
                                    conversations.append(
                                        {
                                            "user": "\n".join(user_lines),
                                            "ling": "\n".join(ling_lines),
                                            "chain_turns": turns,
                                            "chain_text": chain.get("chain_text", ""),
                                        }
                                    )
                                    continue
                            conversations.append(obj)
            else:
                with open(self.memory_file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # 兼容不同结构的 JSON，如果本身是列表就直接返回
                    if isinstance(data, list):
                        conversations = data
                    elif isinstance(data, dict):
                        conversations = data.get("data", []) or data.get("examples", [])
            return conversations
        except Exception as e:
            logger.error("Failed to load memory file: %s", e)
            return []

    def _load_static_examples(self) -> List[Dict]:
        """加载人工筛选的补充对话示例"""
        if not self.static_fallback_path or not os.path.exists(self.static_fallback_path):
            return []
        try:
            if self.static_fallback_path.lower().endswith(".txt"):
                with open(self.static_fallback_path, "r", encoding="utf-8") as f:
                    return self._parse_manual_dialogue_blocks(f.read())
            with open(self.static_fallback_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("few_shot", data.get("examples", []))
        except Exception as e:
            logger.warning("Failed to load static examples: %s", e)
            return []

    def _tokenize(self, text: str) -> set:
        """简单的中文分词（按字/词切分，这里用简单的正则模拟）"""
        if not text:
            return set()
        # 移除标点符号
        text = re.sub(r"[^\w\s]", "", str(text))
        # 简单按字符和常用词切分（实际生产环境建议用 jieba，这里用原生实现以减少依赖）
        # 采用 n-gram (1-gram 和 2-gram)
        tokens = set(text)
        for i in range(len(text) - 1):
            tokens.add(text[i : i + 2])
        return tokens

    def _calculate_similarity(self, query_tokens: set, doc_text: str) -> float:
        """计算 Jaccard 相似度"""
        if not doc_text or not isinstance(doc_text, str):
            return 0.0

        doc_tokens = self._tokenize(doc_text)
        if not doc_tokens:
            return 0.0

        intersection = len(query_tokens & doc_tokens)
        union = len(query_tokens | doc_tokens)

        return intersection / union if union > 0 else 0.0

    def retrieve(
        self, user_input: str, k: int = 3, threshold: float = 0.05
    ) -> List[Dict]:
        """
        根据用户当前输入，从历史记录中检索最相关的 k 条对话
        策略：Dynamic First -> Static Fallback
        """
        query_tokens = self._tokenize(user_input)
        scored_docs = []

        for conv in self.conversations:
            # 根据对话内容计算相似度，优先比较用户说的话 (user/user_input)，
            # 这样可以找出“历史中用户说了类似的话时，玲是怎么回答的”
            text_content = (
                conv.get("user", "")
                or conv.get("user_input", "")
                or conv.get("chain_text", "")
                or conv.get("text", "")
            )
            score = self._calculate_similarity(query_tokens, text_content)

            if score > threshold:
                scored_docs.append((score, conv))

        scored_docs.sort(key=lambda x: x[0], reverse=True)
        retrieved_results = [item[1] for item in scored_docs[:k]]

        final_results = []
        final_results.extend(retrieved_results)

        needed = k - len(final_results)

        if self.static_examples:
            if len(final_results) == 0:
                final_results = self.static_examples[:k]
            elif needed > 0:
                # 过滤掉可能重复的例子
                for static_ex in self.static_examples:
                    if static_ex not in final_results:
                        final_results.append(static_ex)
                        needed -= 1
                        if needed <= 0:
                            break

        return final_results

    def format_for_prompt(self, examples: List[Dict], user_label: str = "User", ai_label: str = "Assistant") -> str:
        """将检索到的例子格式化为 Prompt 字符串"""
        output = []
        for ex in examples:
            # 兼容 .pairs.jsonl 格式 (user/ling)
            if "user" in ex and "ling" in ex:
                user_text = ex["user"]
                ai_text = ex["ling"]
                output.append(f"[{user_label}]: {user_text}\n[{ai_label}]: {ai_text}")
            # 兼容旧格式
            elif "text" in ex:
                role = ex.get("role", "Unknown")
                text = ex.get("text", "")
                if role == "Unknown":
                    output.append(str(text))
                else:
                    output.append(f"[{role}]: {text}")
            elif "user_input" in ex and "aveline_response" in ex:
                user_text = ex["user_input"]
                ai_text = ex["aveline_response"]
                output.append(f"[{user_label}]: {user_text}\n[{ai_label}]: {ai_text}")
                
        return "\n\n".join(output)


# 简单的测试逻辑
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Test Style Retriever")
    parser.add_argument(
        "--memory",
        type=str,
        default=os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "../../data/character/ling/best/私聊_玲🍀.best.jsonl",
            )
        ),
        help="Memory dialogue file",
    )
    parser.add_argument(
        "--static",
        type=str,
        default=os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "../../data/character/ling/curated/ling_style_manual_selected.txt",
            )
        ),
        help="Manual fallback dialogue file",
    )
    args = parser.parse_args()

    MEMORY_PATH = args.memory
    STATIC_PATH = args.static

    retriever = StyleRetriever(MEMORY_PATH, STATIC_PATH)

    # 测试场景
    test_queries = [
        "你觉得我厉害吗",
        "不想上班了，好累",
        "今天天气真好，想去火星种土豆" # 应该触发 Fallback 或找完全无关的
    ]

    for q in test_queries:
        print(f"\n--- Scenario: '{q}' ---")
        results = retriever.retrieve(q, k=3)
        formatted = retriever.format_for_prompt(results, user_label="User", ai_label="玲")
        print(formatted)
        print("-" * 40)
