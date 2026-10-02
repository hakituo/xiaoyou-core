"""验证 QQ 断句对编号列表（1. xxx 2. xxx 3. xxx）的处理。

验证点：
1. 行内编号列表按编号断成多个气泡，每个编号项完整
2. 编号后有句号的行内列表（1. 打开设置。2. 找到选项。）同样按编号断
3. 短前言与首个编号项合并，不会单独发一个"你可以这样做："
4. 英文编号列表按编号断
5. 小数不误伤（3.5 公斤、12.8 元）
6. 版本号/日期不误伤（Python 3.11.2、2026.9.2）
7. 只有一个编号项时保持原样
8. 显式换行 + 编号的列表保持每项独立
9. 不会出现只有数字的空壳气泡（1. / 2. / 3.）

运行：venv_core\\Scripts\\python.exe tests\\scripts\\qq\\verify_numbered_list_split.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from clients.bots.qq.utils import _split_message_for_qq  # noqa: E402

_passed = 0
_failed = 0


def _split(text: str) -> list[str]:
    return _split_message_for_qq(text, 150, comma_split_prob=0.2, min_split_len=40)


def _check(name: str, actual: list[str], expected: list[str]):
    global _passed, _failed
    if actual == expected:
        _passed += 1
        print(f"[PASS] {name}: {actual}")
    else:
        _failed += 1
        print(f"[FAIL] {name}\n  期望: {expected}\n  实际: {actual}")


# ---------- 1. 行内编号列表（空格分隔） ----------
_check(
    "行内编号列表按编号断句",
    _split("1. 先把水烧开 2. 再把面下进去 3. 等三分钟就可以吃了"),
    ["1. 先把水烧开", "2. 再把面下进去", "3. 等三分钟就可以吃了"],
)

# ---------- 2. 行内编号列表（句号分隔） ----------
_check(
    "编号项以句号结尾时按编号断句",
    _split("1. 打开设置。2. 找到隐私选项。3. 关掉它就行了。"),
    ["1. 打开设置。", "2. 找到隐私选项。", "3. 关掉它就行了。"],
)

# ---------- 3. 短前言与首个编号项合并 ----------
_check(
    "短前言与首个编号项合并",
    _split("你可以这样做：1. 打开设置。2. 找到隐私选项。3. 关掉它。"),
    ["你可以这样做：1. 打开设置。", "2. 找到隐私选项。", "3. 关掉它。"],
)

# ---------- 4. 英文编号列表 ----------
_check(
    "英文编号列表按编号断句",
    _split("1. analysis 2. trend 3. emphasize"),
    ["1. analysis", "2. trend", "3. emphasize"],
)

# ---------- 5. 小数不误伤 ----------
_check(
    "小数不被当成编号",
    _split("我买了3.5公斤苹果，一共花了12.8元，够吃两天了。"),
    ["我买了3.5公斤苹果，一共花了12.8元，够吃两天了。"],
)

# ---------- 6. 版本号/日期不误伤 ----------
_check(
    "版本号不被当成编号",
    _split("升级到 Python 3.11.2 之后就好了，你可以试试看。"),
    ["升级到 Python 3.11.2 之后就好了，你可以试试看。"],
)
_check(
    "日期不被当成编号",
    _split("2026.9.2 那天我们去了海边，玩得很开心。"),
    ["2026.9.2 那天我们去了海边，玩得很开心。"],
)

# ---------- 7. 单个编号项保持原样 ----------
_check(
    "只有一个编号项时不拆分",
    _split("1. 就这一条，别的真的没有了。"),
    ["1. 就这一条，别的真的没有了。"],
)

# ---------- 8. 显式换行 + 编号保持每项独立 ----------
_check(
    "显式换行的编号列表保持每项独立",
    _split("1. 第一项。\n2. 第二项。\n3. 第三项。"),
    ["1. 第一项。", "2. 第二项。", "3. 第三项。"],
)

# ---------- 9. 不产生数字空壳气泡 ----------
chunks = _split("复习顺序是 1. 先看昨天错的单词 2. 再背新词 3. 最后做自测，一共三步。")
shells = [c for c in chunks if c.strip() in {"1", "2", "3", "1.", "2.", "3."}]
if shells:
    _failed += 1
    print(f"[FAIL] 不应出现数字空壳气泡: {shells} / {chunks}")
else:
    _passed += 1
    print(f"[PASS] 无数字空壳气泡: {chunks}")

print("-" * 60)
print(f"通过 {_passed} 项，失败 {_failed} 项")
sys.exit(1 if _failed else 0)
