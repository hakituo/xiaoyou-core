"""验证本机英语短语原始来源的完整性与版本。

数据目录被 Git 忽略，本脚本只做只读验收，不下载、不改写真实数据。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PHRASE_ROOT = PROJECT_ROOT / "data" / "study_data" / "English" / "Phrases" / "raw"

OPEN_SOURCE_FILES = {
    "cet4.txt": (2744, "f66814a93fcb7867baa539e418dd2ddfa86b711c0c699614ca01619f6546812c"),
    "cet6.txt": (3482, "eede6a3d96e5c4d53a18e7f07b4014b7289840f5835f5379f4ab1b73ef06e51a"),
    "ielts.txt": (205, "e76cc39a2124423bec17d82c9b66117068e7d6f00ae07dd7bcb397cd5b24de55"),
    "toefl.txt": (158, "fe6dacadd94442d86e697451fd0138bd8169b347540f780d03437491701adf0e"),
}

PEARSON_FILE = "The_Academic_Collocation_List.xlsx"
PEARSON_SHA256 = "441a8c621eab088547a081c16b57bd9a77607bdd9f522ff6dc07052be07a0089"

OXFORD_FILES = {
    "Oxford_Phrase_List.pdf": "35da430c8c0353d4a44c6293ca0d05ae00787488562beaed1ff2835c6e37e118",
    "OPAL_written_phrases.pdf": "62154fe569a9def8b7107cc4a8dd29d2e34d48876200c6ea0292d9dc582ab0bf",
    "OPAL_spoken_phrases.pdf": "8c219ea17738d7f38e4146f938fccd7b1fe158228273b16d6b844625576df728",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_phrases(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def main() -> None:
    open_root = PHRASE_ROOT / "english-phrases"
    for filename, (expected_count, expected_hash) in OPEN_SOURCE_FILES.items():
        path = open_root / filename
        assert path.is_file(), f"缺少短语源文件: {path}"
        phrases = _read_phrases(path)
        normalized = {" ".join(item.lower().split()) for item in phrases}
        assert len(phrases) == expected_count, (
            f"{filename} 条目数变化: {len(phrases)} != {expected_count}"
        )
        assert len(normalized) == expected_count, f"{filename} 存在规范化重复条目"
        assert _sha256(path) == expected_hash, f"{filename} 文件哈希不匹配"

    license_path = open_root / "LICENSE"
    assert license_path.is_file(), "开源短语源缺少 LICENSE"
    assert "Attribution-ShareAlike 4.0" in license_path.read_text(encoding="utf-8")

    oxford_root = PHRASE_ROOT / "oxford-learner-wordlists"
    for filename, expected_hash in OXFORD_FILES.items():
        path = oxford_root / filename
        assert path.is_file(), f"缺少 Oxford 原件: {path}"
        assert path.read_bytes().startswith(b"%PDF-"), f"{filename} 不是有效 PDF 文件"
        assert _sha256(path) == expected_hash, f"{filename} 文件哈希不匹配"

    pearson_path = PHRASE_ROOT / "pearson-academic-collocation" / PEARSON_FILE
    assert pearson_path.is_file(), f"缺少 Pearson 原件: {pearson_path}"
    assert zipfile.is_zipfile(pearson_path), "Pearson 原件不是有效 XLSX 文件"
    assert _sha256(pearson_path) == PEARSON_SHA256, "Pearson 原件文件哈希不匹配"

    print("PASS: 四六级、雅思、托福、Oxford 与 Pearson 原始来源完整")


if __name__ == "__main__":
    main()
