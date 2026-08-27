import json
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def main() -> int:
    try:
        from core.services.data_ops.bert_analyzer import get_bert_analyzer
    except Exception as e:
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "reason": f"import_failed: {e}",
                    "accuracy": None,
                    "total": 0,
                },
                ensure_ascii=False,
            )
        )
        return 0

    analyzer = get_bert_analyzer()
    candidates = ["RECORD_VOCAB_MISTAKE", "RECORD_VOCAB_UNKNOWN"]
    dataset = [
        ("我把abandon记错了", "RECORD_VOCAB_MISTAKE"),
        ("abandon这个词我又背错了", "RECORD_VOCAB_MISTAKE"),
        ("我老是把obscure记混", "RECORD_VOCAB_MISTAKE"),
        ("这个词我不会，serendipity", "RECORD_VOCAB_UNKNOWN"),
        ("serendipity我不认识", "RECORD_VOCAB_UNKNOWN"),
        ("我不会这个单词 epiphany", "RECORD_VOCAB_UNKNOWN"),
        ("今天我想学英语", "NONE"),
        ("帮我查一下abandon意思", "NONE"),
        ("这个单词挺有趣的", "NONE"),
        ("我刚吃完饭", "NONE"),
    ]

    correct = 0
    rows = []
    for text, expected in dataset:
        result = analyzer.analyze_intent(text, candidates=candidates)
        pred = str((result or {}).get("intent") or "NONE").upper()
        conf = float((result or {}).get("confidence") or 0.0)
        ok = pred == expected
        if ok:
            correct += 1
        rows.append(
            {
                "text": text,
                "expected": expected,
                "pred": pred,
                "confidence": round(conf, 4),
                "ok": ok,
                "reason": str((result or {}).get("reason") or ""),
            }
        )

    total = len(dataset)
    accuracy = (correct / total) if total else 0.0
    print(
        json.dumps(
            {
                "status": "ok",
                "accuracy": round(accuracy, 4),
                "correct": correct,
                "total": total,
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
