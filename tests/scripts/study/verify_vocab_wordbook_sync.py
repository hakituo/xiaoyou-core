"""验证 daily 里未收录的词会被增量补进全量词书（CET-全量.json）。

覆盖：
1. 目标词从 ECDICT 补录进全量词书，释义解析与构建脚本一致；
2. 已收录的词不会被重复追加；
3. ECDICT 里也没有的词不会污染词书；
4. 写回是原子的（不残留 .tmp），且文件内容合法。
"""

from __future__ import annotations

import csv
import json
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.tools.study.english.wordbook_sync import (  # noqa: E402
    sync_words,
)

ECDICT_FIELDS = [
    "word",
    "phonetic",
    "definition",
    "translation",
    "pos",
    "collins",
    "oxford",
    "tag",
    "bnc",
    "frq",
    "exchange",
    "detail",
    "audio",
]


def _write_ecdict(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ECDICT_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in ECDICT_FIELDS})


def main() -> int:
    problems: list[str] = []
    temp_root = tempfile.mkdtemp(prefix="verify_vocab_wordbook_sync_")
    try:
        ecdict_path = Path(temp_root) / "ecdict.csv"
        master_path = Path(temp_root) / "CET-全量.json"
        _write_ecdict(
            ecdict_path,
            [
                {
                    "word": "situate",
                    "phonetic": "'sitjueit",
                    "definition": "v. determine or indicate the place",
                    "translation": "vt. 使位于, 使处于",
                    "exchange": "d:situated/3:situates",
                },
                {
                    "word": "skyline",
                    "definition": "n. the outline of objects seen against the sky",
                    "translation": "n. 天涯, 地平线, 空中轮廓线",
                    "collins": "1",
                },
            ],
        )
        with master_path.open("w", encoding="utf-8") as handle:
            json.dump([{"word": "known", "translations": []}], handle)

        added = sync_words(
            ["situate", "skyline", "known", "not_in_ecdict"],
            ecdict_path=ecdict_path,
            master_path=master_path,
        )
        if sorted(added) != ["situate", "skyline"]:
            problems.append(f"补录结果不符合预期: {added}")

        with master_path.open("r", encoding="utf-8") as handle:
            entries = json.load(handle)
        words = [entry.get("word") for entry in entries]
        if words != ["known", "situate", "skyline"]:
            problems.append(f"全量词书内容错误: {words}")
        by_word = {entry["word"]: entry for entry in entries}
        if by_word.get("situate", {}).get("translations") != [
            {"type": "vt", "translation": "使位于, 使处于"}
        ]:
            problems.append(
                f"situate 释义解析错误: {by_word.get('situate', {}).get('translations')}"
            )
        if list(Path(temp_root).glob("*.tmp")):
            problems.append("补录后残留临时文件")

        # 重复补录必须幂等
        again = sync_words(["situate"], ecdict_path=ecdict_path, master_path=master_path)
        if again:
            problems.append(f"重复补录未幂等: {again}")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    if problems:
        print("验证失败:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print("验证通过: 未收录的用户词会按 ECDICT 增量补进全量词书且幂等")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
