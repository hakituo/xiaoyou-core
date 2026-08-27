"""
Generate intent fine-tuning dataset for Xiaoyou-Core BERT intent classifier.

The project uses BERT intent recognition in:
1) core/services/intent/service.py (control intents)
2) core/agents/chat_agent_components/handler.py (status recording intents)

Training data format (used by scripts/finetune_bert_intent.py):
[
  {"text": "...", "intent": "..."},
  ...
]
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List


PROJECT_ROOT = Path(__file__).resolve().parent.parent


INTENTS_CORE = [
    "CLEAR_MEMORY",
    "CLEAR_LOCAL_MEMORY",
    "SHOW_STATUS",
    "SHOW_HELP",
    "LIST_MODELS",
    "LIST_VOICES",
    "SWITCH_MODEL",
    "SWITCH_MODEL_HINT",
    "SWITCH_PERSONA",
    "TOGGLE_LATENCY",
    "ACTIVE_CARE_SNOOZE",
    "IMAGE_GEN",
]

INTENTS_STATUS_RECORDING = [
    "RECORD_WAKEUP",
    "RECORD_MEAL",
    "RECORD_DRINK",
]

INTENT_NONE = "NONE"


@dataclass(frozen=True)
class Example:
    text: str
    intent: str

    def to_json(self) -> Dict[str, str]:
        return {"text": self.text, "intent": self.intent}


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


def _build_templates() -> Dict[str, List[str]]:
    model_names = [
        "qwen",
        "deepseek",
        "deepseek-chat",
        "glm",
        "llama",
        "kimi",
        "gpt",
        "claude",
    ]
    persona_names = [
        "少女",
        "猫娘",
        "御姐",
        "女仆",
        "学姐",
        "冷淡",
        "温柔",
        "毒舌",
        "治愈",
    ]

    templates: Dict[str, List[str]] = {}

    templates["CLEAR_MEMORY"] = _cartesian_templates(
        [
            "清空记忆",
            "清除记忆",
            "清空对话",
            "重置对话",
            "忘掉刚才的内容",
            "把刚才忘了",
            "别记了",
            "清空一下上下文",
            "把聊天记录清一下",
            "/clear",
            "/forget",
            "{please}清空{obj}",
            "{please}{verb}{obj}",
        ],
        please=["", "请", "麻烦", "帮我", "给我"],
        verb=["清空", "清除", "重置", "删除", "忘掉"],
        obj=["记忆", "上下文", "对话", "聊天记录", "会话历史"],
    )

    templates["CLEAR_LOCAL_MEMORY"] = _cartesian_templates(
        [
            "清理本地记忆数据库",
            "删除本地历史记录",
            "格式化本地记忆",
            "清空本地数据库",
            "{please}{verb}本地{obj}",
            "{please}{verb}{obj}（本地）",
        ],
        please=["", "请", "麻烦", "帮我", "给我"],
        verb=["清空", "清除", "删除", "格式化", "重置"],
        obj=["记忆", "历史", "聊天记录", "数据库", "上下文"],
    )

    templates["SHOW_STATUS"] = _cartesian_templates(
        [
            "查看系统状态",
            "系统状态怎么样",
            "看看后台运行情况",
            "显示性能监控",
            "CPU占用多少",
            "GPU显存占用多少",
            "内存使用率",
            "{please}{verb}系统{what}",
            "{please}{verb}{what}",
        ],
        please=["", "请", "帮我", "给我", "麻烦"],
        verb=["查看", "显示", "看下", "看看", "告诉我"],
        what=["状态", "负载", "占用", "性能", "健康状态"],
    )

    templates["SHOW_HELP"] = _cartesian_templates(
        [
            "帮助",
            "/help",
            "怎么用？",
            "使用说明",
            "功能列表",
            "指令大全",
            "{please}{verb}一下{what}",
        ],
        please=["", "请", "帮我", "给我", "麻烦"],
        verb=["说", "列", "展示", "发", "给"],
        what=["指令", "功能", "用法", "菜单", "帮助"],
    )

    templates["LIST_MODELS"] = _cartesian_templates(
        [
            "有哪些模型",
            "列出模型列表",
            "查看可用模型",
            "模型列表",
            "{please}{verb}模型",
            "{please}{verb}可用模型",
        ],
        please=["", "请", "帮我", "给我", "麻烦"],
        verb=["列出", "显示", "查看", "告诉我", "给我看下"],
    )

    templates["LIST_VOICES"] = _cartesian_templates(
        [
            "有哪些声音",
            "有哪些音色",
            "列出音色列表",
            "查看语音列表",
            "声音列表",
            "{please}{verb}音色",
            "{please}{verb}声音",
        ],
        please=["", "请", "帮我", "给我", "麻烦"],
        verb=["列出", "显示", "查看", "告诉我", "给我看下"],
    )

    templates["SWITCH_MODEL"] = _cartesian_templates(
        [
            "切换到{model}",
            "换成{model}",
            "改用{model}",
            "用{model}回答",
            "把模型切到{model}",
            "{please}{verb}模型到{model}",
        ],
        please=["", "请", "帮我", "麻烦"],
        verb=["切换", "换", "改", "设置"],
        model=model_names,
    )

    templates["SWITCH_MODEL_HINT"] = _cartesian_templates(
        [
            "换个更聪明的模型",
            "你太笨了，换一个更厉害的驱动",
            "换个更有逻辑的脑子",
            "升级一下你的认知系统",
            "{please}{verb}一个更{adj}的模型",
            "{please}{verb}更{adj}的引擎",
        ],
        please=["", "请", "帮我", "麻烦"],
        verb=["换", "切", "改用", "升级到", "切换到"],
        adj=["强", "聪明", "快", "稳", "好用", "厉害"],
    )

    templates["SWITCH_PERSONA"] = _cartesian_templates(
        [
            "切换到{persona}模式",
            "换成{persona}人设",
            "变成{persona}",
            "换个性格",
            "切换人设",
            "{please}{verb}{persona}{suffix}",
        ],
        please=["", "请", "帮我", "麻烦"],
        verb=["切换到", "换成", "改成", "变成", "设置为"],
        persona=persona_names,
        suffix=["模式", "人设", "风格", ""],
    )

    templates["TOGGLE_LATENCY"] = _cartesian_templates(
        [
            "开启仿生延迟",
            "关闭仿生延迟",
            "打开延迟模拟",
            "关闭延迟模拟",
            "性能模式",
            "拟人模式",
            "{please}{verb}{what}",
        ],
        please=["", "请", "帮我", "麻烦"],
        verb=["开启", "关闭", "打开", "关掉", "启用", "禁用", "切换到"],
        what=["仿生延迟", "思考模拟", "性能模式", "拟人模式"],
    )

    templates["ACTIVE_CARE_SNOOZE"] = _cartesian_templates(
        [
            "过一会再提醒我",
            "等会再叫我",
            "两小时后再提醒",
            "半小时后再找我",
            "稍后再发消息",
            "晚点再说",
            "{please}{verb}{delay}{suffix}",
        ],
        please=["", "请", "帮我", "麻烦"],
        verb=["", "等", "过", "延后", "稍后"],
        delay=["一会", "半小时", "30分钟", "1小时", "两小时"],
        suffix=["再提醒", "再叫我", "再找我", "再发消息", ""],
    )

    templates["IMAGE_GEN"] = _cartesian_templates(
        [
            "画一只猫",
            "画一张风景",
            "生成一张图片",
            "帮我画一张图片",
            "给我生图：{prompt}",
            "/生图 {prompt}",
            "{please}{verb}{prompt}",
        ],
        please=["", "请", "帮我", "麻烦", "给我"],
        verb=["画", "生成图片：", "画一张：", "生图："],
        prompt=["赛博朋克城市", "可爱猫咪", "日系少女", "未来机甲", "水彩风景"],
    )

    templates["RECORD_WAKEUP"] = _cartesian_templates(
        [
            "我醒了",
            "起床了",
            "刚睡醒",
            "醒来啦",
            "早安，我醒了",
            "{prefix}我醒了",
        ],
        prefix=["", "小澪，", "小优，", "宝，"],
    )

    templates["RECORD_MEAL"] = _cartesian_templates(
        [
            "吃饭了",
            "我吃了",
            "刚吃完午饭",
            "晚饭吃完了",
            "正在吃东西",
            "{meal}吃了",
            "{meal}吃完了",
        ],
        meal=["早饭", "午饭", "晚饭", "夜宵", "下午茶"],
    )

    templates["RECORD_DRINK"] = _cartesian_templates(
        [
            "喝水了",
            "我喝了水",
            "喝杯水",
            "刚喝了咖啡",
            "喝了奶茶",
            "补充水分",
            "{drink}喝了",
            "刚喝完{drink}",
        ],
        drink=["水", "咖啡", "奶茶", "茶", "果汁", "可乐"],
    )

    templates[INTENT_NONE] = [
        "你好",
        "在吗",
        "你是谁",
        "今天天气不错",
        "我有点难过",
        "我最近状态不太好",
        "你今天心情怎么样",
        "讲个笑话",
        "你会画画吗",
        "不要画了",
        "猫娘真可爱",
        "我喜欢你",
        "我们聊聊天吧",
        "随便聊聊",
        "晚安",
        "早安",
    ]

    for k, v in list(templates.items()):
        templates[k] = _dedupe_keep_order([s.strip() for s in v if str(s).strip()])
    return templates


def build_dataset(per_intent: int, none_count: int, seed: int) -> List[Example]:
    rng = random.Random(seed)
    templates = _build_templates()

    intents = _dedupe_keep_order(INTENTS_CORE + INTENTS_STATUS_RECORDING + [INTENT_NONE])

    examples: List[Example] = []
    for intent in intents:
        tpls = templates.get(intent, [])
        target = none_count if intent == INTENT_NONE else per_intent
        picked = _sample(tpls, target, rng)
        examples.extend([Example(text=x, intent=intent) for x in picked])

    rng.shuffle(examples)
    return examples


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default=str(PROJECT_ROOT / "data" / "intent_train_data.json"),
        help="Output JSON path (default: data/intent_train_data.json)",
    )
    parser.add_argument(
        "--per-intent",
        type=int,
        default=40,
        help="Examples per non-NONE intent (default: 40)",
    )
    parser.add_argument(
        "--none",
        type=int,
        default=140,
        help="Examples for NONE intent (default: 140)",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    out_path = Path(args.out)
    if out_path.exists() and not args.overwrite:
        raise SystemExit(
            f"Refusing to overwrite existing file: {out_path} (use --overwrite)"
        )

    examples = build_dataset(
        per_intent=args.per_intent, none_count=args.none, seed=args.seed
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps([e.to_json() for e in examples], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {len(examples)} examples to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
