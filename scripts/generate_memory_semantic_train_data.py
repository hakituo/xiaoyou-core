"""
Generate training datasets for memory semantic analysis:

1) Category classification (work/learning/daily/health/entertainment/emotion/tech/finance/uncategorized)
2) Importance classification (IMPORTANT/CASUAL) for weight tuning

Outputs (default):
- data/memory_category_train_data.json
- data/memory_importance_train_data.json

These datasets are optional, but help fine-tune BERT models to better match
the project's memory "ai-shadow" analysis (core/services/data_ops/analysis_pipeline.py).
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List


PROJECT_ROOT = Path(__file__).resolve().parent.parent


CATEGORIES = [
    "work",
    "learning",
    "daily",
    "health",
    "entertainment",
    "emotion",
    "tech",
    "finance",
    "uncategorized",
]


@dataclass(frozen=True)
class CategoryExample:
    text: str
    category: str

    def to_json(self) -> Dict[str, str]:
        return {"text": self.text, "category": self.category}


@dataclass(frozen=True)
class ImportanceExample:
    text: str
    importance: str  # IMPORTANT | CASUAL

    def to_json(self) -> Dict[str, str]:
        return {"text": self.text, "importance": self.importance}


def _dedupe_keep_order(items: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for x in items:
        x = str(x)
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _cartesian_templates(templates: List[str], **choices: List[str]) -> List[str]:
    if not choices:
        return templates[:]

    out: List[str] = []
    keys = list(choices.keys())

    def rec(i: int, current: str) -> None:
        if i >= len(keys):
            out.append(current)
            return
        k = keys[i]
        for v in choices[k]:
            rec(i + 1, current.replace("{" + k + "}", v))

    for t in templates:
        rec(0, t)
    return out


def _sample(texts: List[str], n: int, rng: random.Random) -> List[str]:
    if n <= 0 or not texts:
        return []
    if n <= len(texts):
        return rng.sample(texts, n)
    out: List[str] = []
    while len(out) < n:
        out.extend(rng.sample(texts, min(len(texts), n - len(out))))
    return out


def build_category_templates() -> Dict[str, List[str]]:
    templates: Dict[str, List[str]] = {}

    templates["work"] = _cartesian_templates(
        [
            "明天{time}有个项目进度汇报会议，记得准备PPT",
            "老板说这个项目必须在周五前上线，否则会有严重后果",
            "我需要把这个需求文档整理好发给同事",
            "今天要写周报，汇总一下本周工作",
            "和同事对齐一下接口联调进度",
        ],
        time=["上午10点", "下午3点", "晚上8点"],
    )

    templates["learning"] = _cartesian_templates(
        [
            "正在复习数据结构与算法，特别是二叉树的遍历",
            "我想学习一下{topic}，你能给我一个学习路线吗",
            "今天准备刷20道{oj}题",
            "我在看一本关于{topic}的书",
        ],
        topic=["机器学习", "深度学习", "NLP", "操作系统", "数据库", "Python"],
        oj=["LeetCode", "洛谷", "Codeforces"],
    )

    templates["daily"] = _cartesian_templates(
        [
            "今天天气不错，想去公园散步",
            "我刚出门，路上有点堵车",
            "晚上打算做个{food}吃",
            "今天要去买点生活用品",
        ],
        food=["番茄牛腩", "炒饭", "意面", "沙拉", "火锅"],
    )

    templates["health"] = _cartesian_templates(
        [
            "我最近睡眠不太好，总是半夜醒",
            "今天去医院复查，医生说要按时吃药",
            "最近想开始健身减肥，你给我个计划",
            "有点头疼嗓子痛，可能感冒了",
        ]
    )

    templates["entertainment"] = _cartesian_templates(
        [
            "最近在玩{game}，感觉特别上头",
            "推荐一部好看的电影吧",
            "我在追一部新剧，剧情太刺激了",
            "想听点音乐放松一下",
        ],
        game=["原神", "王者荣耀", "星露谷", "塞尔达", "Minecraft"],
    )

    templates["emotion"] = _cartesian_templates(
        [
            "我今天有点难过，不知道怎么调节",
            "最近压力很大，感觉要崩溃了",
            "我很开心，今天发生了好事",
            "有点焦虑，总觉得事情做不完",
        ]
    )

    templates["tech"] = _cartesian_templates(
        [
            "我在写Python代码，遇到一个bug卡住了",
            "这段接口返回总是超时，怎么排查性能问题",
            "想了解一下向量检索和embedding是怎么用的",
            "我在研究ONNXRuntime推理加速",
        ]
    )

    templates["finance"] = _cartesian_templates(
        [
            "这个月工资到手多少合适分配到理财里",
            "我想定投指数基金，有什么建议",
            "最近花钱有点多，想做个预算",
            "股票亏了有点难受",
        ]
    )

    templates["uncategorized"] = _cartesian_templates(
        [
            "你好",
            "在吗",
            "你是谁",
            "讲个笑话",
            "随便聊聊",
            "哈哈哈",
        ]
    )

    for k, v in list(templates.items()):
        templates[k] = _dedupe_keep_order([s.strip() for s in v if str(s).strip()])
    return templates


def build_importance_templates() -> Dict[str, List[str]]:
    templates: Dict[str, List[str]] = {}

    templates["IMPORTANT"] = _cartesian_templates(
        [
            "老板说这个项目非常重要，必须在周五前上线，否则会有严重后果",
            "这件事很紧急，马上处理一下",
            "别忘了{task}，这很关键",
            "提醒我{when}{task}",
            "我明天{when}有个重要会议，记得提醒我",
        ],
        task=["交报告", "发邮件", "准备PPT", "提交代码", "缴费"],
        when=["上午", "下午", "晚上", "10点", "3点"],
    )

    templates["CASUAL"] = _cartesian_templates(
        [
            "今天天气不错，想去散步",
            "随便聊聊吧",
            "哈哈",
            "无聊",
            "晚安",
            "早安",
        ]
    )

    for k, v in list(templates.items()):
        templates[k] = _dedupe_keep_order([s.strip() for s in v if str(s).strip()])
    return templates


def build_category_dataset(per_category: int, seed: int) -> List[CategoryExample]:
    rng = random.Random(seed)
    templates = build_category_templates()

    out: List[CategoryExample] = []
    for cat in CATEGORIES:
        picked = _sample(templates.get(cat, []), per_category, rng)
        out.extend([CategoryExample(text=t, category=cat) for t in picked])
    rng.shuffle(out)
    return out


def build_importance_dataset(n_important: int, n_casual: int, seed: int) -> List[ImportanceExample]:
    rng = random.Random(seed)
    templates = build_importance_templates()

    out: List[ImportanceExample] = []
    out.extend([ImportanceExample(text=t, importance="IMPORTANT") for t in _sample(templates["IMPORTANT"], n_important, rng)])
    out.extend([ImportanceExample(text=t, importance="CASUAL") for t in _sample(templates["CASUAL"], n_casual, rng)])
    rng.shuffle(out)
    return out


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--per-category", type=int, default=60)
    parser.add_argument("--important", type=int, default=140)
    parser.add_argument("--casual", type=int, default=140)
    parser.add_argument(
        "--out-category",
        default=str(PROJECT_ROOT / "data" / "memory_category_train_data.json"),
    )
    parser.add_argument(
        "--out-importance",
        default=str(PROJECT_ROOT / "data" / "memory_importance_train_data.json"),
    )
    args = parser.parse_args()

    out_cat = Path(args.out_category)
    out_imp = Path(args.out_importance)

    for p in [out_cat, out_imp]:
        if p.exists() and not args.overwrite:
            raise SystemExit(f"Refusing to overwrite existing file: {p} (use --overwrite)")

    cat_data = build_category_dataset(per_category=args.per_category, seed=args.seed)
    imp_data = build_importance_dataset(
        n_important=args.important, n_casual=args.casual, seed=args.seed
    )

    _write_json(out_cat, [x.to_json() for x in cat_data])
    _write_json(out_imp, [x.to_json() for x in imp_data])

    print(f"Wrote {len(cat_data)} category examples to {out_cat}")
    print(f"Wrote {len(imp_data)} importance examples to {out_imp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

