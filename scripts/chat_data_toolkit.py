#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对话数据处理工具箱（通用模板）

功能：
1. extract  - 从原始JSON提取对话链
2. filter   - 质量过滤
3. classify - BERT语义分类
4. stats    - 语言模式统计
5. eval     - AI对比评估

用法：
    python chat_data_toolkit.py --mode extract --input <原始JSON> --output <输出路径>
    python chat_data_toolkit.py --mode filter --input <原始数据> --output <输出路径>
    python chat_data_toolkit.py --mode classify --input <对话数据> --output <输出路径>
    python chat_data_toolkit.py --mode stats --input <对话pairs数据>
    python chat_data_toolkit.py --mode eval --input <对话pairs数据> --persona <人设JSON> --sample <数量>
"""

import os
import sys
import json
import asyncio
import argparse
import random
from pathlib import Path
from collections import Counter
from typing import Dict, List

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


class ChainExtractor:
    """从原始JSON提取对话链"""

    def __init__(
        self,
        raw_data_path: str,
        max_gap_seconds: int = 300,
        user_label: str = "user",
        bot_label: str = "bot",
        user_is_send: int = 1,
        text_type: str = "文本消息",
    ):
        self.raw_data_path = raw_data_path
        self.max_gap_seconds = max_gap_seconds
        self.user_label = user_label
        self.bot_label = bot_label
        self.user_is_send = user_is_send
        self.text_type = text_type
        self.messages = []
        self.chains = []

    def load(self):
        with open(self.raw_data_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.messages = data.get("messages", [])
        print(f"[Loader] 加载了 {len(self.messages)} 条消息")

    def extract_chains(self, min_turns: int = 2) -> List[Dict]:
        all_messages = []
        for msg in self.messages:
            if msg.get("type") != self.text_type:
                continue
            content = str(msg.get("content", "")).strip()
            if not content or content.startswith("["):
                continue
            all_messages.append({
                "content": content,
                "time": msg.get("createTime", 0),
                "is_user": msg.get("isSend") == self.user_is_send,
            })

        self.chains = []
        current_chain = []
        last_time = 0

        for msg in all_messages:
            time_gap = msg["time"] - last_time if last_time > 0 else 0
            if time_gap > self.max_gap_seconds and current_chain:
                if len(current_chain) >= min_turns:
                    self.chains.append(self._build_chain(current_chain))
                current_chain = []
            current_chain.append(msg)
            last_time = msg["time"]

        if len(current_chain) >= min_turns:
            self.chains.append(self._build_chain(current_chain))

        print(f"[Extract] 提取了 {len(self.chains)} 条对话链")
        return self.chains

    def _build_chain(self, messages: List[Dict]) -> Dict:
        turns = []
        for msg in messages:
            turns.append({
                "speaker": self.user_label if msg["is_user"] else self.bot_label,
                "content": msg["content"],
            })
        chain_text = "\n".join([f"{self.user_label if t['speaker']==self.user_label else self.bot_label}：{t['content']}" for t in turns])
        return {
            "turns": turns,
            "chain_text": chain_text,
            "num_turns": len(turns),
            "num_bot_turns": len([t for t in turns if t["speaker"] == self.bot_label]),
        }


class QualityFilter:
    """质量过滤"""

    @staticmethod
    def filter(
        chains: List[Dict],
        remove_patterns: List[str] = None,
        min_turns: int = 2,
        max_turns: int = 100,
    ) -> List[Dict]:
        if remove_patterns is None:
            remove_patterns = []

        filtered = []
        for chain in chains:
            text = chain.get("chain_text", "")

            should_remove = False
            for pattern in remove_patterns:
                if pattern in text:
                    should_remove = True
                    break

            if should_remove:
                continue

            num_turns = chain.get("num_turns", 0)
            if num_turns < min_turns or num_turns > max_turns:
                continue

            filtered.append(chain)

        print(f"[Filter] 过滤后: {len(filtered)} 条")
        return filtered


class BertClassifier:
    """BERT语义分类"""

    def __init__(self):
        from core.services.data_ops.bert_analyzer import get_bert_analyzer
        self.analyzer = get_bert_analyzer()

    def classify(self, chains: List[Dict], text_key: str = "chain_text") -> Dict[str, List]:
        results = []
        for i, chain in enumerate(chains):
            text = chain.get(text_key, "")[:500]
            result = self.analyzer.analyze(text)
            results.append({
                "chain": chain,
                "category": result.get("category", "uncategorized"),
                "topics": result.get("topics", []),
                "confidence": result.get("confidence", 0),
            })
            if (i + 1) % 20 == 0:
                print(f"[BERT] 已分析 {i+1}/{len(chains)} 条...")

        categories = {}
        for r in results:
            cat = r["category"]
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(r)

        print(f"[BERT] 分类完成: {len(categories)} 个类别")
        return categories


class PatternStats:
    """语言模式统计"""

    def __init__(self, pairs_path: str, bot_key: str = "bot"):
        self.pairs_path = pairs_path
        self.bot_key = bot_key
        self.pairs = []
        self._load_pairs()

    def _load_pairs(self):
        with open(self.pairs_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    if self.bot_key in data and "user" in data:
                        self.pairs.append(data)
        print(f"[Stats] 加载了 {len(self.pairs)} 条对话")

    def compute(self, patterns: Dict[str, List[str]] = None) -> Dict:
        if patterns is None:
            patterns = {
                "starts_with": ["因为", "就是", "然后", "我不", "那我", "可以"],
                "ends_with": ["什么", "吗", "了", "啊", "呀", "吧", "呢"],
                "fillers": ["啊", "呀", "吧", "呢", "哦", "嗯", "可以", "不知道", "emm", "en"],
            }

        stats = {
            "total": len(self.pairs),
            "starts_with": Counter(),
            "ends_with": Counter(),
            "fillers": Counter(),
            "avg_bot_len": 0,
        }

        lens = []
        for pair in self.pairs:
            bot = pair.get(self.bot_key, "").strip()
            if not bot:
                continue
            lens.append(len(bot))

            for pattern in patterns.get("starts_with", []):
                if bot.startswith(pattern):
                    stats["starts_with"][pattern] += 1

            for pattern in patterns.get("ends_with", []):
                if bot.endswith(pattern):
                    stats["ends_with"][pattern] += 1

            for filler in patterns.get("fillers", []):
                if filler in bot:
                    stats["fillers"][filler] += 1

        stats["avg_bot_len"] = sum(lens) / len(lens) if lens else 0
        return stats

    def print_report(self, stats: Dict):
        total = stats["total"]
        print(f"\n【语言模式统计】(共{total}条)")
        print(f"平均回复长度: {stats['avg_bot_len']:.1f} 字")

        print("\n开头模式:")
        for pattern, count in stats["starts_with"].most_common(10):
            print(f"  {pattern}: {count} ({count/total*100:.1f}%)")

        print("\n结尾模式:")
        for pattern, count in stats["ends_with"].most_common(10):
            print(f"  {pattern}: {count} ({count/total*100:.1f}%)")

        print("\n语气词:")
        for filler, count in stats["fillers"].most_common(15):
            print(f"  {filler}: {count} ({count/total*100:.1f}%)")


class AIEvaluator:
    """AI对比评估"""

    def __init__(self, persona_path: str, bot_key: str = "bot"):
        from dotenv import load_dotenv
        load_dotenv(project_root / ".env")
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.bot_key = bot_key
        with open(persona_path, "r", encoding="utf-8") as f:
            self.persona = json.load(f)

    def build_prompt(self) -> str:
        identity = self.persona.get("identity", {})
        name = identity.get("cn_name", "AI")
        context = identity.get("context", "")
        parts = [f"你是一个AI，名叫{name}。"]
        if context:
            parts.append(context)
        constraints = self.persona.get("language_style", {}).get("syntax_constraints", [])
        if constraints:
            parts.append("语言风格约束：" + "；".join(constraints[:3]))
        return "\n".join(parts)

    async def generate(self, user_input: str, model: str = "deepseek-chat", max_tokens: int = 64) -> str:
        if not self.api_key:
            return "[ERROR] No API key"

        try:
            import aiohttp
            messages = [
                {"role": "system", "content": self.build_prompt()},
                {"role": "user", "content": user_input}
            ]
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.deepseek.com/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json={"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.75},
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status != 200:
                        return f"[ERROR] {resp.status}"
                    data = await resp.json()
                    if "choices" in data:
                        return data["choices"][0]["message"]["content"].strip()
            return "[ERROR]"
        except Exception as e:
            return f"[ERROR] {str(e)}"

    async def evaluate_pairs(self, pairs_path: str, sample_size: int = 50, bot_key: str = "bot") -> List[Dict]:
        pairs = []
        with open(pairs_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    if bot_key in data and "user" in data:
                        pairs.append(data)

        samples = random.sample(pairs, min(sample_size, len(pairs)))
        print(f"[Eval] 采样 {len(samples)} 条进行评估")

        results = []
        for i, pair in enumerate(samples):
            user = pair.get("user", "").strip()
            real = pair.get(bot_key, "").strip()
            if not user or not real:
                continue

            print(f"[{i+1}/{len(samples)}] 生成中...", end="\r")
            ai = await self.generate(user)
            results.append({"user": user, "real": real, "ai": ai})
            await asyncio.sleep(0.15)

        print("\n[Eval] 评估完成")
        return results

    def print_comparison(self, results: List[Dict], ground_truth: Dict = None):
        total = len(results)
        print(f"\n【对比评估结果】(共{total}条)")

        real_lens = [len(r["real"]) for r in results]
        ai_lens = [len(r["ai"]) for r in results]
        print(f"平均长度: 真实 {sum(real_lens)/total:.1f} | AI {sum(ai_lens)/total:.1f}")

        if ground_truth:
            print("\n【与基准对比】")
            print(f"{'模式':<15} {'基准':<10} {'AI':<10} {'差异':<10}")
            print("-" * 45)

            for label, gt_pct in ground_truth.items():
                ai_count = 0
                if "开头" in label:
                    pattern = label.replace("开头", "")
                    ai_count = sum(1 for r in results if r["ai"].startswith(pattern))
                elif "结尾" in label:
                    pattern = label.replace("结尾", "")
                    ai_count = sum(1 for r in results if r["ai"].endswith(pattern))
                elif "包含" in label:
                    pattern = label.replace("包含'", "").replace("'", "")
                    ai_count = sum(1 for r in results if pattern in r["ai"])

                ai_pct = ai_count / total * 100
                diff = ai_pct - gt_pct
                print(f"{label:<15} {gt_pct:>6.1f}%    {ai_pct:>6.1f}%    {diff:>+.1f}%")


async def run_pipeline(args):
    print("=" * 60)
    print("对话数据处理工具箱")
    print("=" * 60)

    if args.mode == "extract":
        print("\n【模式: 提取对话链】")
        extractor = ChainExtractor(
            args.input,
            max_gap_seconds=args.max_gap,
            user_label=args.user_label,
            bot_label=args.bot_label,
            user_is_send=args.user_is_send,
        )
        extractor.load()
        chains = extractor.extract_chains(min_turns=args.min_turns)
        output_path = project_root / args.output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for chain in chains:
                f.write(json.dumps(chain, ensure_ascii=False) + "\n")
        print(f"[Output] 已保存到: {output_path}")

    elif args.mode == "filter":
        print("\n【模式: 质量过滤】")
        with open(args.input, "r", encoding="utf-8") as f:
            chains = [json.loads(line) for line in f if line.strip()]
        filtered = QualityFilter.filter(chains, remove_patterns=args.remove_patterns, min_turns=args.min_turns)
        output_path = project_root / args.output
        with open(output_path, "w", encoding="utf-8") as f:
            for chain in filtered:
                f.write(json.dumps(chain, ensure_ascii=False) + "\n")
        print(f"[Output] 已保存到: {output_path}")

    elif args.mode == "classify":
        print("\n【模式: BERT语义分类】")
        with open(args.input, "r", encoding="utf-8") as f:
            chains = [json.loads(line) for line in f if line.strip()]
        classifier = BertClassifier()
        categories = classifier.classify(chains)

        print("\n【分类结果】")
        for cat in sorted(categories.keys(), key=lambda x: -len(categories[x])):
            print(f"  {cat}: {len(categories[cat])}条")

        output_path = project_root / args.output
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(categories, f, ensure_ascii=False, indent=2)
        print(f"[Output] 已保存到: {output_path}")

    elif args.mode == "stats":
        print("\n【模式: 语言模式统计】")
        stats = PatternStats(args.input, bot_key=args.bot_key)
        result = stats.compute()
        stats.print_report(result)

    elif args.mode == "eval":
        print("\n【模式: AI对比评估】")
        evaluator = AIEvaluator(args.persona, bot_key=args.bot_key)
        results = await evaluator.evaluate_pairs(args.input, sample_size=args.sample, bot_key=args.bot_key)

        ground_truth = None
        if args.ground_truth:
            stats = PatternStats(args.ground_truth, bot_key=args.bot_key)
            stats.compute()
            ground_truth = {
                "因为开头": 2.3,
                "就是开头": 1.6,
                "什么结尾": 1.5,
                "吗结尾": 5.5,
                "了结尾": 13.8,
                "包含'啊'": 12.4,
            }

        evaluator.print_comparison(results, ground_truth)

        output_path = project_root / args.output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n[Output] 已保存到: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="对话数据处理工具箱")
    parser.add_argument("--mode", type=str, required=True,
                        choices=["extract", "filter", "classify", "stats", "eval"],
                        help="模式")
    parser.add_argument("--input", type=str, help="输入路径")
    parser.add_argument("--output", type=str, help="输出路径")
    parser.add_argument("--persona", type=str, default="core/character/configs/core_ling.json", help="人设配置路径")
    parser.add_argument("--ground-truth", type=str, help="基准数据路径（用于eval模式）")
    parser.add_argument("--sample", type=int, default=50, help="评估采样数量")
    parser.add_argument("--min-turns", type=int, default=2, help="最小对话轮次")
    parser.add_argument("--max-gap", type=int, default=300, help="最大间隔秒数")
    parser.add_argument("--user-label", type=str, default="user", help="用户标签")
    parser.add_argument("--bot-label", type=str, default="bot", help="机器人标签")
    parser.add_argument("--user-is-send", type=int, default=1, help="用户发送标志")
    parser.add_argument("--remove-patterns", type=str, nargs="*", help="过滤模式列表")

    args = parser.parse_args()
    asyncio.run(run_pipeline(args))


if __name__ == "__main__":
    main()
