#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""规则体系一致性校验（`.trae/rules/RULES.md` 的机器化配套）。

三类检查（对应 RULES.md §7）：
1. 真源存在性：每条 `（真源: <path>[:行号|#锚点]）` 的路径存在、行号不越界、锚点文本存在
2. 统一数字唯一性：RULES.md 声明「已统一」的数字（当前是「单文件 500 行」）在活文档里
   不得出现第二个不同的值
3. 入口可达性：从 AGENTS.md 的指针闭包能覆盖 RULES.md 的全部真源（无孤儿），
   且闭包内不得反向要求「先读 AGENTS.md」（无循环依赖）

扫描范围排除历史归档：`docs/updates/**`、`.trae/memory/YYYY-MM-DD.md`、`Question_Reviewer/**`
（历史日志只追加不改写，必然含旧措辞）。真源文件本身不算「重复位置」，
重复检查只针对其余活文档。

运行：
    venv_cpu\\Scripts\\python.exe tests\\scripts\\docs\\check_rules_consistency.py
    venv_cpu\\Scripts\\python.exe tests\\scripts\\docs\\check_rules_consistency.py --verbose
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RULES_PATH = ROOT / ".trae" / "rules" / "RULES.md"
AGENTS_PATH = ROOT / "AGENTS.md"

# 历史归档：只追加不改写，所有检查一律跳过
ARCHIVE_DIR_PREFIXES = ("docs/updates/", "Question_Reviewer/")
ARCHIVE_FILE_RE = re.compile(r"^\.trae/memory/\d{4}-\d{2}-\d{2}\.md$")

# RULES.md 里「真源」标注：贪婪匹配到行尾最后一个全角右括号（锚点本身可能含全角括号）
SOURCE_RE = re.compile(r"（真源: (.+)）\s*$")
ANCHOR_RE = re.compile(r"^(?P<path>[^#]+)#(?P<anchor>.+)$")
LINE_RE = re.compile(r"^(?P<path>.+?):(?P<start>\d+)(?:-(?P<end>\d+))?$")

# 行数上限的「定义式」表述：只在代码文件里扫，按文件扩展名推断期望档位。
# 文档（.md）里的数字由 RULES.md 速查表 + 规则正文唯一性检查覆盖，不在这里重复管。
NUMBER_DEF_PATTERNS = [
    re.compile(r"\b[A-Z_]*LINES\s*[:=]\s*(\d{3,5})"),
    re.compile(r"\bline_limit\s*[:=]\s*(\d{3,5})", re.IGNORECASE),
    re.compile(r"单文件\s*[≤<]=?\s*(\d{3,5})\s*行"),
    re.compile(r"单文件上限\s*[:：]?\s*(\d{3,5})"),
    re.compile(r"(?:(?<!不)超过|大于|[>＞])\s*(\d{3,5})\s*行该拆"),
]

# 模块级结构验证脚本：可为单个模块设**更严**的上限，但不得比通用档更宽。
# 清单必须与 RULES.md §2 的登记表一致；新增这类脚本要两边同时加。
MODULE_LIMIT_SCRIPTS = {
    "tests/scripts/android_frontend/verify_chat_screen_decomposition.py": ".kt",
    "tests/scripts/android_frontend/verify_samsung_health_reader_decomposition.py": ".kt",
    "tests/scripts/android_keepalive/verify_foreground_service_decomposition.py": ".kt",
    "tests/scripts/nightly/verify_nightly_responsibility_split.py": ".py",
}
MODULE_LINES_RE = re.compile(r"\b[A-Z_]*LINES\s*[:=]\s*(\d{3,5})")

# 名字带 LINES 但语义不是「源码文件行数上限」的常量：(仓库相对路径, 常量名)
# 例：A11yDiagnosis.MAX_LINES 是日志文件保留行数（a11y_diagnosis.log 的滚动上限）。
# 新增误报就按同样格式加一行并写清原因，不要为此放宽整体模式。
NON_SOURCE_LIMITS = {
    (
        "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile/services/A11yDiagnosis.kt",
        "MAX_LINES",
    ),
}
NAME_IN_LINE_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*[:=]")

# 全仓统一的常量（跨语言、跨配置文件都必须是同一个值）
UNIFIED_CONSTANTS = [
    {
        "name": "Python 行宽",
        "value": 100,
        "patterns": [
            re.compile(r"(?:line-length|line_length|max-line-length)\s*[=:]\s*(\d{2,4})"),
        ],
    },
]

# 参与统一常量扫描的文本扩展名
TEXT_SUFFIXES = (
    ".md", ".py", ".toml", ".cfg", ".ini", ".yml", ".yaml",
    ".kt", ".ts", ".tsx", ".vue", ".swift", ".cpp", ".h",
)

# RULES.md 正文里不该出现的「行数上限」旧值（500 属 Markdown 档，写进代码规则即旧值残留）
STALE_NUMBER_IN_RULES = ("500",)

# 参与数字定义式扫描的代码扩展名（按扩展名推断期望档位）
CODE_SUFFIXES = (
    ".py", ".kt", ".java", ".cpp", ".cc", ".c", ".h", ".hpp",
    ".ts", ".tsx", ".vue", ".swift",
)

# 曾被抄到多份的规则短语：除 RULES.md 外，其余活文档不得再出现。
# 注意：这些字符串是**断言目标**（禁止在别处出现的常量），与 RULES.md 正文同形属预期，
# 不代表规则有第二处正文定义。
DUPLICATE_SENSITIVE_PHRASES = [
    "dry-run 清单就是最终提交范围",
    "从源头杜绝进库",
    "超限文件告警",
    "记录分工固定为",
    "同一规则在全仓库",
]

# 自动查重：RULES.md 判据中的中文长片段不得在其他活文档出现（阈值经实测零误报）
CN_RUN_RE = re.compile(r"[\u4e00-\u9fff]{11,}")
JUDGEMENT_SOURCE_RE = re.compile("（真源: .*?）")
CODE_SPAN_RE = re.compile("`[^`]*`")

# 指针闭包起点与最大深度（防止顺着 docs 索引无限扩散）
BFS_MAX_DEPTH = 3

# 反向依赖：闭包内出现「必读 / 先读 … AGENTS.md」即视为循环依赖
BACK_REFERENCE_RE = re.compile(r"(必读|先读|按.{0,12}顺序读).{0,24}AGENTS\.md")

TOKEN_RE = re.compile(r"`([^`\s]+)`")
LINK_PATH_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

# 能被当成「仓库内文件指针」的后缀与特殊文件名
KNOWN_SUFFIXES = (".md", ".py", ".toml", ".yml", ".yaml", ".txt", ".json")
SPECIAL_FILES = {".gitignore", ".dockerignore", ".flake8"}


def looks_like_path(token: str) -> bool:
    """判断反引号里的内容是否是一个仓库内文件指针。"""
    if token in SPECIAL_FILES:
        return True
    if not token or token.startswith("-") or " " in token:
        return False
    return token.endswith(KNOWN_SUFFIXES)


def _rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def is_archive(rel_path: str) -> bool:
    """判断是否为不可改写的历史归档。"""
    if rel_path.startswith(ARCHIVE_DIR_PREFIXES):
        return True
    return bool(ARCHIVE_FILE_RE.match(rel_path))


def active_docs() -> list[Path]:
    """返回「活规则面」文档（排除历史归档）。"""
    patterns = [
        "AGENTS.md",
        ".trae/rules/*.md",
        ".trae/memory/*.md",
        ".trae/context/*.md",
        ".trae/skills/*/SKILL.md",
        "pyproject.toml",
        "tests/scripts/audit_tests.py",
        "tests/scripts/docs/*.py",
        "scripts/git/README.md",
    ]
    docs: list[Path] = []
    for pattern in patterns:
        docs.extend(p for p in ROOT.glob(pattern) if p.is_file())
    return sorted({p for p in docs if not is_archive(_rel(p))}, key=lambda p: _rel(p))


def parse_rules() -> tuple[list[dict], set[str]]:
    """解析 RULES.md，返回 (真源条目, 真源路径集合)。"""
    entries: list[dict] = []
    sources: set[str] = set()
    for line_no, line in enumerate(RULES_PATH.read_text(encoding="utf-8").splitlines(), 1):
        if not line.startswith("- ["):
            continue
        match = SOURCE_RE.search(line)
        if not match:
            continue
        raw = match.group(1).strip()
        if raw == "本文件":
            continue
        entry = {"line": line_no, "raw": raw, "anchor": None, "start": None, "end": None}
        anchor_match = ANCHOR_RE.match(raw)
        if anchor_match:
            entry["raw_path"] = anchor_match.group("path").strip()
            entry["anchor"] = anchor_match.group("anchor").strip()
        else:
            line_match = LINE_RE.match(raw)
            if line_match:
                entry["raw_path"] = line_match.group("path").strip()
                entry["start"] = int(line_match.group("start"))
                entry["end"] = int(line_match.group("end") or line_match.group("start"))
            else:
                entry["raw_path"] = raw
        sources.add(entry["raw_path"])
        entries.append(entry)
    return entries, sources


def check_sources(entries: list[dict], verbose: bool) -> list[str]:
    """检查 1：真源路径存在、行号不越界、锚点文本存在。"""
    problems: list[str] = []
    for entry in entries:
        target = ROOT / entry["raw_path"]
        if not target.exists():
            problems.append(f"RULES.md:{entry['line']} 真源不存在: {entry['raw']}")
            continue
        if not target.is_file():
            continue
        text = target.read_text(encoding="utf-8", errors="replace")
        if entry["anchor"] is not None:
            if entry["anchor"] not in text:
                problems.append(
                    f"RULES.md:{entry['line']} 锚点未命中: {entry['raw_path']}#{entry['anchor']}"
                )
            elif verbose:
                print(f"  OK 锚点 {entry['raw_path']}#{entry['anchor']}")
        if entry["start"] is not None:
            total = len(text.splitlines())
            if entry["end"] > total:
                problems.append(
                    f"RULES.md:{entry['line']} 行号越界: {entry['raw_path']} 共 {total} 行，"
                    f"引用 {entry['start']}-{entry['end']}"
                )
    return problems


def _iter_code_files() -> list[Path]:
    """收集参与数字定义式扫描的代码文件（排除归档、第三方、构建产物）。"""
    import check_file_sizes

    roots = list(check_file_sizes.CODE_ROOTS) + ["tests"]
    files: list[Path] = []
    for name in roots:
        base = ROOT / name
        if not base.exists():
            continue
        try:
            candidates = list(base.rglob("*"))
        except OSError:
            continue
        for path in candidates:
            if not path.is_file():
                continue
            if any(part in check_file_sizes.SKIP_DIRS for part in path.parts):
                continue
            if path.suffix.lower() not in CODE_SUFFIXES:
                continue
            if is_archive(_rel(path)):
                continue
            files.append(path)
    return files


def check_number_definitions(verbose: bool) -> list[str]:
    """检查 2：行数上限的「定义式」表述必须与所属语言的通用档一致。

    按文件扩展名推断期望档位（`.py` → 300、`.kt` → 400 …）。模块级结构验证脚本
    除外 —— 它们允许更严，由 `check_module_limits` 单独管。文档里的数字由速查表与
    规则正文唯一性检查覆盖，不在这里重复管。
    """
    problems: list[str] = []
    try:
        import check_file_sizes

        limits = check_file_sizes.LIMITS
    except Exception as exc:  # pragma: no cover
        return [f"无法导入 check_file_sizes.py: {exc}"]

    scanned = 0
    for path in _iter_code_files():
        rel = _rel(path)
        if rel in MODULE_LIMIT_SCRIPTS:
            continue
        expected = limits.get(path.suffix.lower())
        if expected is None:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        scanned += 1
        for pattern in NUMBER_DEF_PATTERNS:
            for match in pattern.finditer(text):
                found = int(match.group(1))
                if found == expected:
                    continue
                line_no = text[: match.start()].count("\n") + 1
                line_text = lines[line_no - 1] if line_no <= len(lines) else ""
                name_match = NAME_IN_LINE_RE.search(line_text)
                name = name_match.group(1) if name_match else ""
                if (rel, name) in NON_SOURCE_LIMITS:
                    continue
                problems.append(
                    f"{rel}:{line_no} 行数上限写的是 {found}（{name}），"
                    f"但 {path.suffix} 的通用档是 {expected}"
                )
    if verbose:
        print(f"  OK 扫描 {scanned} 个代码文件的行数上限定义")
    return problems


def check_module_limits(verbose: bool) -> list[str]:
    """检查 2c：模块级结构验证脚本的上限只能比通用档更严，且须在 RULES.md 登记。"""
    problems: list[str] = []
    try:
        import check_file_sizes

        limits = check_file_sizes.LIMITS
    except Exception as exc:  # pragma: no cover
        return [f"无法导入 check_file_sizes.py: {exc}"]

    rules_text = RULES_PATH.read_text(encoding="utf-8")
    for rel, ext in sorted(MODULE_LIMIT_SCRIPTS.items()):
        path = ROOT / rel
        if not path.is_file():
            problems.append(f"登记的结构验证脚本不存在: {rel}")
            continue
        if rel not in rules_text:
            problems.append(f"结构验证脚本 {rel} 未登记在 RULES.md §2")
        cap = limits.get(ext)
        if cap is None:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in MODULE_LINES_RE.finditer(text):
            value = int(match.group(1))
            if value > cap:
                line_no = text[: match.start()].count("\n") + 1
                problems.append(
                    f"{rel}:{line_no} 模块级上限 {value} 比 {ext} 的通用档 {cap} 更宽"
                )
    if verbose:
        print(f"  OK 核对 {len(MODULE_LIMIT_SCRIPTS)} 个模块级结构验证脚本")
    return problems


def _iter_text_files() -> list[Path]:
    """收集参与统一常量扫描的活文本文件（排除归档、第三方、构建产物）。"""
    import check_file_sizes

    files: list[Path] = []
    seen: set[Path] = set()
    for name in ("AGENTS.md", "pyproject.toml", ".flake8", "readme.md"):
        path = ROOT / name
        if path.is_file():
            files.append(path)
            seen.add(path)
    roots = list(check_file_sizes.CODE_ROOTS) + list(check_file_sizes.DOC_ROOTS) + ["tests"]
    for name in roots:
        base = ROOT / name
        if not base.exists():
            continue
        try:
            candidates = list(base.rglob("*"))
        except OSError:
            continue
        for path in candidates:
            if not path.is_file() or path in seen:
                continue
            if any(part in check_file_sizes.SKIP_DIRS for part in path.parts):
                continue
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if is_archive(_rel(path)):
                continue
            seen.add(path)
            files.append(path)
    return files


def check_unified_constants(verbose: bool) -> list[str]:
    """检查 2b：跨文件统一的常量（如 Python 行宽）全仓只能有一个值。"""
    problems: list[str] = []
    scanned = 0
    for path in _iter_text_files():
        rel = _rel(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        scanned += 1
        for rule in UNIFIED_CONSTANTS:
            for pattern in rule["patterns"]:
                for match in pattern.finditer(text):
                    value = int(match.group(1))
                    if value == rule["value"]:
                        continue
                    line_no = text[: match.start()].count("\n") + 1
                    problems.append(
                        f"{rel}:{line_no} 「{rule['name']}」为 {value}，"
                        f"与统一值 {rule['value']} 不一致"
                    )
    if verbose:
        print(f"  OK 扫描 {scanned} 份文本的统一常量")
    return problems


def check_rules_stale_numbers(verbose: bool) -> list[str]:
    """检查 2d：RULES.md 正文（速查表行除外）不得残留别的档位的行数数字。

    专治「把某个语言档的数字当成全局口径写进正文」这类残留 —— 500 是 Markdown 档，
    出现在代码规则正文里说明有旧值没跟着分档改。
    """
    problems: list[str] = []
    for line_no, line in enumerate(RULES_PATH.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("|") or stripped.startswith(">"):
            continue
        for number in STALE_NUMBER_IN_RULES:
            if number in line and "行" in line:
                problems.append(
                    f"RULES.md:{line_no} 正文出现「{number} 行」"
                    f"（{number} 属 Markdown 档，不该写进代码规则；"
                    f"请对照 §2 速查表核对）"
                )
    if verbose:
        print("  OK 核对 RULES.md 正文的行数数字")
    return problems


def _judgement_fragments() -> set[str]:
    """从 RULES.md 每条规则的判据里抽取中文长片段（≥11 个连续汉字）。

    抽取前先剥掉代码片段与真源标注，剩下的是判据的自然语言部分。
    """
    fragments: set[str] = set()
    for line in RULES_PATH.read_text(encoding="utf-8").splitlines():
        if not line.startswith("- ["):
            continue
        body = line.split("——", 1)[-1]
        body = JUDGEMENT_SOURCE_RE.sub("", body)
        body = CODE_SPAN_RE.sub("", body)
        fragments.update(CN_RUN_RE.findall(body))
    return fragments


def _load_audit_line_limit() -> int | None:
    """读取 audit_tests.py 的 LINE_LIMIT（不执行它的 main）。"""
    import importlib.util

    path = ROOT / "tests" / "scripts" / "audit_tests.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("audit_tests_probe", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, "LINE_LIMIT", None)


def check_limits_sync(verbose: bool) -> list[str]:
    """检查 2b：单文件行数分档的数字三方一致。

    `check_file_sizes.LIMITS`（唯一定义处）↔ `RULES.md` 的速查表 ↔ `audit_tests.LINE_LIMIT`。
    任何一处改了、其他没改，这里必须报错。
    """
    problems: list[str] = []
    try:
        import check_file_sizes  # 与本文件同目录
    except Exception as exc:  # pragma: no cover - 导入失败即为硬错误
        return [f"无法导入 check_file_sizes.py: {exc}"]

    limits = check_file_sizes.LIMITS
    table_value_re = re.compile(r"^\|\s*(?P<lang>[^|]+?)\s*\|\s*(?P<value>\d{3,4})\s*\|")
    ext_re = re.compile(r"`(\.[a-zA-Z]+)`")

    seen: set[str] = set()
    for line in RULES_PATH.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        match = table_value_re.match(line)
        if not match:
            continue
        value = int(match.group("value"))
        exts = ext_re.findall(match.group("lang"))
        if not exts:
            continue
        for ext in exts:
            if ext not in limits:
                problems.append(f"RULES.md 速查表里的 {ext} 未在 check_file_sizes.LIMITS 中定义")
                continue
            seen.add(ext)
            if limits[ext] != value:
                problems.append(
                    f"RULES.md 速查表 {ext} = {value}，"
                    f"但 check_file_sizes.LIMITS[{ext}] = {limits[ext]}"
                )

    for ext in limits:
        if ext not in seen:
            problems.append(f"check_file_sizes.LIMITS 的 {ext} 未出现在 RULES.md 速查表中")

    audit_limit = _load_audit_line_limit()
    if audit_limit is None:
        problems.append("无法读取 tests/scripts/audit_tests.py 的 LINE_LIMIT")
    elif audit_limit != limits[".py"]:
        problems.append(
            f"audit_tests.LINE_LIMIT = {audit_limit}，"
            f"但 check_file_sizes.LIMITS['.py'] = {limits['.py']}"
        )

    if verbose:
        print(f"  OK 核对 {len(seen)} 组扩展名 + audit_tests.LINE_LIMIT")
    return problems


def check_duplicate_rules(docs: list[Path], sources: set[str], verbose: bool) -> list[str]:
    """检查 3a：规则正文唯一性（两重判据）。

    ① 曾被抄到多份的规则短语，除 RULES.md 外不得再出现（硬编码断言目标）；
    ② RULES.md 判据中的中文长片段，不得在任何其他活文档出现 —— 自动查重，
       覆盖「把判据整句抄到别处」这类复述。
    """
    problems: list[str] = []
    targets = [d for d in docs if d != RULES_PATH and _rel(d) not in sources]
    texts = {d: d.read_text(encoding="utf-8", errors="replace") for d in docs if d != RULES_PATH}

    for doc in targets:
        text = texts[doc]
        for phrase in DUPLICATE_SENSITIVE_PHRASES:
            index = text.find(phrase)
            if index < 0:
                continue
            line_no = text[:index].count("\n") + 1
            problems.append(
                f"{_rel(doc)}:{line_no} 复述了规则正文「{phrase}」（应改为 `见 RULES.md §x`）"
            )

    fragments = _judgement_fragments()
    for fragment in sorted(fragments):
        for doc, text in texts.items():
            index = text.find(fragment)
            if index < 0:
                continue
            line_no = text[:index].count("\n") + 1
            problems.append(
                f"{_rel(doc)}:{line_no} 与 RULES.md 的判据同文「{fragment}」"
                "（判据只写在 RULES.md，别处改指针）"
            )

    if verbose:
        print(f"  OK 扫描 {len(targets)} 份非真源活文档 + {len(fragments)} 条判据片段")
    return problems


def extract_paths(path: Path) -> set[str]:
    """提取文档中引用的仓库内路径（反引号与 markdown 链接两种写法）。"""
    if not path.is_file():
        return set()
    text = path.read_text(encoding="utf-8", errors="replace")
    found = set()
    for match in TOKEN_RE.finditer(text):
        raw = match.group(1)
        if looks_like_path(raw):
            found.add(raw)
    for match in LINK_PATH_RE.finditer(text):
        raw = match.group(1)
        if looks_like_path(raw):
            found.add(raw)
    cleaned = set()
    for raw in found:
        raw = raw.split("#", 1)[0].strip().strip("/")
        if raw and "<" not in raw:
            cleaned.add(raw)
    return cleaned


def resolve(raw: str, base: Path) -> Path | None:
    """把引用路径解析为真实文件：先按仓库根，再按引用文件所在目录。"""
    for candidate in (ROOT / raw, base.parent / raw):
        if candidate.is_file():
            return candidate.resolve()
    return None


def check_reachability(sources: set[str], verbose: bool) -> list[str]:
    """检查 3b：AGENTS.md 指针闭包覆盖全部真源，且无反向依赖。"""
    problems: list[str] = []
    visited: dict[Path, int] = {AGENTS_PATH.resolve(): 0}
    queue: list[Path] = [AGENTS_PATH.resolve()]
    reverse_hits: list[str] = []

    while queue:
        current = queue.pop(0)
        depth = visited[current]
        if depth >= BFS_MAX_DEPTH:
            continue
        for raw in extract_paths(current):
            resolved = resolve(raw, current)
            if resolved is None or resolved in visited:
                continue
            visited[resolved] = depth + 1
            queue.append(resolved)

    reachable = {_rel(path) for path in visited}
    for source in sorted(sources):
        # 可达性只约束「文档类真源」（.md）：规则指向的代码/配置文件由真源存在性检查覆盖，
        # 不必、也不应该全都塞进入口
        if not source.endswith(".md"):
            continue
        if source not in reachable:
            problems.append(
                f"文档类真源 {source} 无法从 AGENTS.md 到达（孤儿，请补进 AGENTS.md 的读取路由）"
            )

    for path, depth in sorted(visited.items(), key=lambda item: (item[1], _rel(item[0]))):
        rel = _rel(path)
        # 只检查文档（「先读 AGENTS.md」这类要求只写在 .md 里；代码注释不算规则）
        if rel == "AGENTS.md" or is_archive(rel) or depth == 0 or path.suffix != ".md":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), 1):
            if BACK_REFERENCE_RE.search(line):
                reverse_hits.append(f"{rel}:{line_no} 反向要求先读 AGENTS.md（循环依赖）: {line.strip()[:60]}")
    problems.extend(reverse_hits)

    if verbose:
        print(f"  OK 闭包内 {len(visited)} 个文件可达")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="规则体系一致性校验")
    parser.add_argument("--verbose", action="store_true", help="打印每个被检查项")
    args = parser.parse_args()

    if not RULES_PATH.is_file():
        print(f"找不到规则文件: {_rel(RULES_PATH)}")
        return 1

    entries, sources = parse_rules()
    docs = active_docs()

    print("=" * 60)
    print("规则体系一致性校验")
    print("=" * 60)
    print(f"RULES.md 真源条目 {len(entries)} 条；活文档 {len(docs)} 份")

    groups = [
        ("真源存在性", lambda: check_sources(entries, args.verbose)),
        ("数字口径一致性", lambda: check_number_definitions(args.verbose)),
        ("统一常量", lambda: check_unified_constants(args.verbose)),
        ("模块级上限", lambda: check_module_limits(args.verbose)),
        ("RULES 正文旧值", lambda: check_rules_stale_numbers(args.verbose)),
        ("分档数字一致性", lambda: check_limits_sync(args.verbose)),
        ("规则正文唯一性", lambda: check_duplicate_rules(docs, sources, args.verbose)),
        ("入口可达性（无孤儿 / 无循环）", lambda: check_reachability(sources, args.verbose)),
    ]

    total = 0
    for name, fn in groups:
        print(f"\n[{name}]")
        problems = fn()
        if not problems:
            print("  OK  无问题")
            continue
        for problem in problems:
            print(f"  FAIL {problem}")
        total += len(problems)

    print("\n" + "=" * 60)
    if total == 0:
        print("规则体系一致 ✓")
        return 0
    print(f"共发现 {total} 个问题")
    return 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
