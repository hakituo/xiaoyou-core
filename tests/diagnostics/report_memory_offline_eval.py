import argparse
import asyncio
import json
import math
import os
import statistics
import sys
import time
from typing import Any, Dict, List

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from memory.weighted_memory_manager import get_weighted_memory_manager  # noqa: E402


def _load_samples(input_path: str) -> List[Dict[str, Any]]:
    if input_path and os.path.exists(input_path):
        samples: List[Dict[str, Any]] = []
        with open(input_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if isinstance(obj, dict):
                    samples.append(obj)
        return samples
    return [
        {"content": "今天完成了项目评审和发布排期。", "category": "work", "topics": ["项目", "评审"], "importance": 3},
        {"content": "晚上去跑步五公里，状态很好。", "category": "health", "topics": ["运动", "健康"], "importance": 2},
        {"content": "给妈妈买了生日礼物，准备周末回家。", "category": "family", "topics": ["家庭", "礼物"], "importance": 3},
        {"content": "学习了FastAPI异步任务与队列调度。", "category": "study", "topics": ["学习", "编程"], "importance": 2},
        {"content": "这个周末想看电影和吃火锅。", "category": "life", "topics": ["娱乐", "生活"], "importance": 1},
    ]


def _topic_prf(golds: List[List[str]], preds: List[List[str]]) -> Dict[str, float]:
    tp = 0
    fp = 0
    fn = 0
    for g, p in zip(golds, preds):
        gs = set([str(x).strip() for x in g if str(x).strip()])
        ps = set([str(x).strip() for x in p if str(x).strip()])
        tp += len(gs & ps)
        fp += len(ps - gs)
        fn += len(gs - ps)
    precision = float(tp) / float(max(1, tp + fp))
    recall = float(tp) / float(max(1, tp + fn))
    f1 = 0.0 if (precision + recall) == 0 else (2.0 * precision * recall) / (precision + recall)
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def _macro_f1(golds: List[str], preds: List[str]) -> float:
    labels = sorted(set(golds) | set(preds))
    if not labels:
        return 0.0
    f1s: List[float] = []
    for label in labels:
        tp = 0
        fp = 0
        fn = 0
        for g, p in zip(golds, preds):
            if p == label and g == label:
                tp += 1
            elif p == label and g != label:
                fp += 1
            elif p != label and g == label:
                fn += 1
        precision = float(tp) / float(max(1, tp + fp))
        recall = float(tp) / float(max(1, tp + fn))
        f1 = 0.0 if (precision + recall) == 0 else (2.0 * precision * recall) / (precision + recall)
        f1s.append(f1)
    return round(sum(f1s) / float(len(f1s)), 4)


def _rank(values: List[float]) -> List[float]:
    indexed = sorted([(v, i) for i, v in enumerate(values)], key=lambda x: x[0])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j < len(indexed) and indexed[j][0] == indexed[i][0]:
            j += 1
        avg_rank = (i + j - 1) / 2.0 + 1.0
        for k in range(i, j):
            ranks[indexed[k][1]] = avg_rank
        i = j
    return ranks


def _spearman(xs: List[float], ys: List[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    rx = _rank(xs)
    ry = _rank(ys)
    mx = statistics.mean(rx)
    my = statistics.mean(ry)
    num = 0.0
    dx = 0.0
    dy = 0.0
    for a, b in zip(rx, ry):
        xa = a - mx
        yb = b - my
        num += xa * yb
        dx += xa * xa
        dy += yb * yb
    den = math.sqrt(dx * dy)
    if den <= 0:
        return 0.0
    return round(num / den, 4)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=str, default="")
    parser.add_argument("--output", type=str, default="")
    parser.add_argument("--user-id", type=str, default=f"offline_eval_{int(time.time())}")
    args = parser.parse_args()

    samples = _load_samples(args.input)
    if not samples:
        print("No samples found.")
        return 1

    mm = get_weighted_memory_manager(args.user_id)
    mm.clear_memory(mode="all")
    try:
        expected_categories: List[str] = []
        predicted_categories: List[str] = []
        expected_topics: List[List[str]] = []
        predicted_topics: List[List[str]] = []
        expected_importance: List[float] = []
        predicted_weight: List[float] = []

        for sample in samples:
            content = str(sample.get("content") or "").strip()
            if not content:
                continue
            memory_id = mm.add_memory(
                content=content,
                source="user",
                metadata={"defer_analysis": True, "case": "offline_eval"},
            )
            if not memory_id:
                continue
            mm.process_pending_analysis(limit=1)
            memories = mm.get_weighted_memories(limit=64)
            target = None
            for m in memories:
                if m.get("id") == memory_id:
                    target = m
                    break
            if not isinstance(target, dict):
                continue
            expected_categories.append(str(sample.get("category") or "uncategorized"))
            predicted_categories.append(str(target.get("category") or "uncategorized"))
            expected_topics.append([str(t).strip() for t in (sample.get("topics") or []) if str(t).strip()])
            predicted_topics.append([str(t).strip() for t in (target.get("topics") or []) if str(t).strip()])
            expected_importance.append(float(sample.get("importance") or 0.0))
            predicted_weight.append(float(target.get("weight") or 0.0))

        total = len(predicted_categories)
        if total == 0:
            print("No valid evaluated samples.")
            return 1
        category_acc = round(
            sum(1 for g, p in zip(expected_categories, predicted_categories) if g == p)
            / float(total),
            4,
        )
        topic_metrics = _topic_prf(expected_topics, predicted_topics)
        report = {
            "sample_count": total,
            "category": {
                "accuracy": category_acc,
                "macro_f1": _macro_f1(expected_categories, predicted_categories),
            },
            "topics": topic_metrics,
            "weight": {"spearman": _spearman(expected_importance, predicted_weight)},
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "input_path": args.input or "builtin_samples",
        }

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
        print(json.dumps(report, ensure_ascii=False))
        return 0
    finally:
        mm.clear_memory(mode="all")
        mm.shutdown()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
