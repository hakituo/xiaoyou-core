#!/usr/bin/env python3
"""公开仓库发布脚本：白名单正向复制 + 内容脱敏 + 残留扫描门禁。

用途：
    把 private 仓库中可公开的内容按白名单复制到独立目录，用于发布
    GitHub public 作品集仓库。private 仓库源文件零修改。

流程：
    1. git ls-files 获取已跟踪文件（天然排除未跟踪的模型/数据/构建产物）
    2. 白名单过滤（include_dirs / include_files，剔除 exclude_relpaths 与 exclude_globs）
    3. 复制到目标目录：
       - text_replacements：内容级脱敏（真实姓名/QQ号 → 占位值）
       - sanitize_line_prefixes：按行前缀剔除敏感词表条目
       - stub_files：被代码引用的敏感数据文件替换为接口占位桩
    4. 生成公开仓库专用 .gitignore
    5. 残留扫描门禁：目标目录出现禁止字符串/密钥模式 → 报警并以非 0 退出

用法（Windows / Linux 通用，需在仓库根目录运行）：
    venv_cpu python scripts/publish/publish_public.py --target D:/AI/xiaoyou-public
    venv_cpu python scripts/publish/publish_public.py --dry-run        # 只列清单不写入
    venv_cpu python scripts/publish/publish_public.py --scan-only --target <dir>  # 只扫描已有目录
    venv_cpu python scripts/publish/publish_public.py --clean          # 复制前清空目标（保留 .git）

配置：
    scripts/publish/publish_whitelist.json（真实值，已被 .gitignore 排除）
    scripts/publish/publish_whitelist.example.json（公开模板，占位值）
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

# 项目根目录（scripts/publish/ 上两级）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(__file__).resolve().parent / "publish_whitelist.json"

# 默认发布目录：与 private 仓库同级
DEFAULT_TARGET = PROJECT_ROOT.parent / "xiaoyou-public"

# 视为文本处理的扩展名（无扩展名的常见文件如 Dockerfile/.gitignore 会尝试 utf-8 解码）
TEXT_EXTS = {
    ".py", ".md", ".json", ".yaml", ".yml", ".txt", ".toml", ".cfg", ".ini",
    ".ts", ".tsx", ".js", ".jsx", ".css", ".html", ".kt", ".kts", ".swift",
    ".xml", ".gradle", ".properties", ".ps1", ".bat", ".sh", ".spec",
    ".svg", ".example", ".flake8", ".gitignore", ".npmrc", ".editorconfig",
    ".proto", ".cpp", ".h", ".hpp", ".c", ".cu", ".cmake", ".lock",
}

# 公开仓库专用 .gitignore（private 版含敏感文件名，不能直接复用）
PUBLIC_GITIGNORE = """# Python
__pycache__/
*.py[cod]
venv*/
.venv/
.pytest_cache/
.ruff_cache/
.mypy_cache/

# Node.js
node_modules/
.next/

# Android / Gradle
.gradle/
build/
local.properties
*.apk

# 环境与密钥
.env
.env.*
!.env.example

# IDE
.idea/
.vscode/

# 运行时数据（只匹配根目录，避免误伤 core/utils/data/ 与 Android data 包源码）
/data/
/logs/
/cache/
"""


# ---------------------------------------------------------------------------
# 占位桩：被代码引用的敏感数据文件，用接口兼容的空实现替换
# ---------------------------------------------------------------------------

TAXONOMY_STUB = '''"""记忆主题分类词表（公开仓库占位版）。

说明：私有版本包含完整词表与额外分类；公开仓库出于隐私考虑仅保留
分类结构占位，接口签名与私有版一致，保证导入链完整。
"""

from typing import Dict, List


TOPIC_KEYWORDS: Dict[str, List[str]] = {
    "daily": ["today", "sleep", "eat", "weather", "日常", "今天", "睡觉", "吃饭", "天气"],
    "learning": ["learn", "study", "code", "python", "学习", "研究", "代码", "读书"],
    "work": ["work", "meeting", "project", "工作", "开会", "项目", "加班"],
    "health": ["health", "sick", "医院", "生病", "运动", "健康"],
    "entertainment": ["game", "movie", "music", "游戏", "电影", "音乐", "动漫"],
    "tech": ["tech", "software", "科技", "数码", "编程"],
    "emotion": ["mood", "happy", "sad", "心情", "开心", "难过", "情绪"],
    "relationship": ["friend", "family", "朋友", "家人"],
}

CATEGORY_ORDER: List[str] = [
    "daily", "learning", "work", "health",
    "entertainment", "tech", "emotion", "relationship",
]


def detect_topics(content: str) -> List[str]:
    """检测文本命中的主题（占位实现：关键词子串匹配）。"""
    text = str(content or "").strip().lower()
    if not text:
        return []
    topics: List[str] = ["Chat"]
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(str(kw).lower() in text for kw in keywords):
            topics.append(topic)
    return topics


def classify_category(content: str) -> str:
    """将文本归类到主要分类（占位实现）。"""
    topics = detect_topics(content)
    for topic in CATEGORY_ORDER:
        if topic in topics:
            return topic
    return "general"
'''

DETAILED_PERSONA_STUB = '''"""详细人设构建（公开仓库占位版）。

说明：私有版本基于角色配置生成详细人设文本；公开仓库不含人设数据，
仅保留接口签名占位，保证导入链完整。
"""


def build_detailed_persona(*args: Any, **kwargs: Any) -> str:
    """构建详细人设文本（占位：公开仓库无人设数据，返回空串）。"""
    return ""


def _calculate_age_from_birth_date(birth_date: Any) -> str:
    """根据出生日期计算年龄（占位实现）。"""
    return "未知"
'''

DIALOGUE_EXAMPLES_STUB = '''"""对话示例选择（公开仓库占位版）。

说明：私有版本基于真实对话语料做示例检索与风格抽取；公开仓库不含
语料数据，仅保留接口签名占位，保证导入链完整。
"""

from typing import Any, List


def get_dialogue_examples(*args: Any, **kwargs: Any) -> str:
    """获取对话示例注入文本（占位：公开仓库无语料，返回空串）。"""
    return ""


def tokenize_for_example_rank(text: str) -> List[str]:
    """示例排序用分词（占位实现：按空白切分）。"""
    return str(text or "").split()


def has_real_chat_corpus(*args: Any, **kwargs: Any) -> bool:
    """是否存在真实对话语料（占位：恒为 False）。"""
    return False


def select_real_chat_examples(*args: Any, **kwargs: Any) -> List[Any]:
    """选取真实对话示例（占位：返回空列表）。"""
    return []


def _load_real_chat_cache(*args: Any, **kwargs: Any) -> Any:
    """加载真实对话缓存（占位：返回空字典）。"""
    return {}


def _select_examples(*args: Any, **kwargs: Any) -> List[Any]:
    """内部示例选择（占位：返回空列表）。"""
    return []


def _get_style_retriever(*args: Any, **kwargs: Any) -> Any:
    """获取风格检索器（占位：返回 None）。"""
    return None
'''

STUB_TEMPLATES: dict[str, str] = {
    "taxonomy": TAXONOMY_STUB,
    "detailed_persona": DETAILED_PERSONA_STUB,
    "dialogue_examples": DIALOGUE_EXAMPLES_STUB,
}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def load_config(config_path: Path) -> dict[str, Any]:
    """加载白名单配置。"""
    if not config_path.exists():
        raise FileNotFoundError(
            f"白名单配置不存在：{config_path}\n"
            f"请复制 publish_whitelist.example.json 为 publish_whitelist.json 并填入真实值"
        )
    return json.loads(config_path.read_text(encoding="utf-8"))


def git_tracked_files() -> list[str]:
    """获取 git 已跟踪文件列表（正斜杠相对路径，UTF-8 安全）。"""
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files"],
        cwd=PROJECT_ROOT,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git ls-files 失败: {result.stderr.decode('utf-8', errors='replace')}")
    return [line for line in result.stdout.decode("utf-8", errors="replace").splitlines() if line.strip()]


def is_excluded(rel: str, exclusions: list[str], globs: list[str] | None = None) -> bool:
    """判断相对路径是否命中排除项。

    三种命中方式：文件精确匹配、目录前缀匹配、exclude_globs 通配
    （同时对文件名和完整相对路径做 fnmatch，便于排除散落的 payload_*.json）。
    """
    if any(rel == ex or rel.startswith(ex + "/") for ex in exclusions):
        return True
    if not globs:
        return False
    name = rel.rsplit("/", 1)[-1]
    return any(fnmatch(name, g) or fnmatch(rel, g) for g in globs)


def select_files(cfg: dict[str, Any], tracked: list[str]) -> list[str]:
    """按白名单筛选待发布文件。"""
    includes = list(cfg.get("include_dirs", [])) + list(cfg.get("include_files", []))
    exclusions = list(cfg.get("exclude_relpaths", []))
    globs = list(cfg.get("exclude_globs", []))
    selected = []
    for rel in tracked:
        included = any(rel == inc or rel.startswith(inc + "/") for inc in includes)
        if included and not is_excluded(rel, exclusions, globs):
            selected.append(rel)
    return selected


def is_text_file(path: Path) -> bool:
    """判断是否为文本文件：按扩展名，或尝试 utf-8 解码。"""
    if path.suffix.lower() in TEXT_EXTS:
        return True
    try:
        path.read_bytes().decode("utf-8")
        return True
    except (UnicodeDecodeError, OSError):
        return False


def transform_text(text: str, rel: str, cfg: dict[str, Any]) -> tuple[str, list[str]]:
    """对文本内容做脱敏：全局替换 + 敏感词表行剔除。返回（新文本, 生效操作列表）。"""
    applied: list[str] = []
    for old, new in cfg.get("text_replacements", {}).items():
        if old in text:
            text = text.replace(old, new)
            applied.append(f"替换 {old}→{new}")
    for prefix in cfg.get("sanitize_line_prefixes", {}).get(rel, []):
        lines = text.splitlines(keepends=True)
        kept = [ln for ln in lines if not ln.startswith(prefix)]
        if len(kept) != len(lines):
            text = "".join(kept)
            applied.append(f"剔除敏感词表条目（行前缀 {prefix.strip()}）")
    return text, applied


def scan_target(target: Path, cfg: dict[str, Any]) -> list[str]:
    """扫描目标目录中的禁止字符串/密钥模式，返回违规清单。

    注意：先中和误报复合词（如“角色情绪”包含字面子串“色情”）再匹配，
    避免“角色情绪”“情绪高潮”这类正常工程用语被误报。
    """
    violations: list[str] = []
    forbidden: list[str] = cfg.get("scan_forbidden", [])
    compounds: list[str] = cfg.get("scan_false_positive_compounds", [])
    regexes = [re.compile(p) for p in cfg.get("scan_regex", [])]
    # 检测器自身必然包含敏感词表字面量，需豁免，否则永远自报违规
    scan_excludes: list[str] = cfg.get("scan_exclude_relpaths", [])
    for file_path in sorted(target.rglob("*")):
        if not file_path.is_file():
            continue
        if ".git" in file_path.relative_to(target).parts:
            continue
        try:
            content = file_path.read_bytes().decode("utf-8", errors="ignore")
        except OSError:
            continue
        rel = file_path.relative_to(target).as_posix()
        if is_excluded(rel, scan_excludes):
            continue
        for lineno, raw_line in enumerate(content.splitlines(), start=1):
            # 中和误报复合词（仅影响扫描匹配，不改动发布内容）
            line = raw_line
            for compound in compounds:
                if compound in line:
                    line = line.replace(compound, "＃" * len(compound))
            for pattern in forbidden:
                if pattern in line:
                    violations.append(f"{rel}:{lineno} 命中禁止字符串 [{pattern}]")
            for regex in regexes:
                if regex.search(line):
                    violations.append(f"{rel}:{lineno} 命中密钥模式 [{regex.pattern}]")
    return violations


def clean_target(target: Path) -> None:
    """清空目标目录（保留 .git 以保护已初始化的仓库）。"""
    if not target.exists():
        return
    for child in target.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def publish(target: Path, cfg: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    """执行发布：选择 → 复制/脱敏 → 写 .gitignore，返回统计信息。"""
    tracked = git_tracked_files()
    selected = select_files(cfg, tracked)
    stub_files: dict[str, str] = cfg.get("stub_files", {})

    stats: dict[str, Any] = {
        "tracked": len(tracked),
        "selected": len(selected),
        "copied": 0,
        "replaced_files": 0,
        "stubbed": 0,
        "sanitized": 0,
        "binary": 0,
    }

    if dry_run:
        return stats

    target.mkdir(parents=True, exist_ok=True)
    for rel in selected:
        src = PROJECT_ROOT / rel
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if rel in stub_files:
            # 敏感数据文件 → 接口占位桩（导入链保持完整）
            dst.write_text(STUB_TEMPLATES[stub_files[rel]], encoding="utf-8", newline="\n")
            stats["stubbed"] += 1
            continue
        if not src.exists():
            print(f"[警告] 已跟踪但磁盘上不存在，跳过: {rel}")
            continue
        if is_text_file(src):
            text = src.read_text(encoding="utf-8")
            new_text, applied = transform_text(text, rel, cfg)
            dst.write_text(new_text, encoding="utf-8", newline="")
            stats["copied"] += 1
            if any(op.startswith("替换") for op in applied):
                stats["replaced_files"] += 1
            if any(op.startswith("剔除") for op in applied):
                stats["sanitized"] += 1
        else:
            shutil.copy2(src, dst)
            stats["binary"] += 1

    # 公开仓库专用 .gitignore（private 版含敏感文件名，不能复用）
    (target / ".gitignore").write_text(PUBLIC_GITIGNORE, encoding="utf-8", newline="\n")
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="公开仓库白名单发布脚本")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET, help="目标目录（默认与 private 仓库同级的 xiaoyou-public）")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH, help="白名单配置 JSON 路径")
    parser.add_argument("--dry-run", action="store_true", help="只统计与列清单，不写入任何文件")
    parser.add_argument("--scan-only", action="store_true", help="只扫描已有目标目录（不复制）")
    parser.add_argument("--clean", action="store_true", help="复制前清空目标目录（保留 .git）")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    try:
        cfg = load_config(args.config)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"[错误] {exc}")
        return 2

    if args.scan_only:
        if not args.target.exists():
            print(f"[错误] 目标目录不存在: {args.target}")
            return 2
        violations = scan_target(args.target, cfg)
        if violations:
            print(f"[扫描失败] 发现 {len(violations)} 处残留：")
            for item in violations:
                print(f"  {item}")
            return 1
        print(f"[扫描通过] {args.target} 无禁止字符串/密钥残留")
        return 0

    if args.clean and args.target.exists():
        clean_target(args.target)
        print(f"[清理] 已清空目标目录（保留 .git）: {args.target}")

    stats = publish(args.target, cfg, dry_run=args.dry_run)

    print("=" * 60)
    print(f"git 跟踪文件: {stats['tracked']}")
    print(f"白名单选中:   {stats['selected']}")
    if not args.dry_run:
        print(f"实际复制:     {stats['copied'] + stats['binary']}")
        print(f"  - 文本文件（含脱敏）: {stats['copied']}")
        print(f"  - 二进制文件:         {stats['binary']}")
        print(f"  - 占位桩替换:         {stats['stubbed']}")
        print(f"  - 内容替换生效文件数: {stats['replaced_files']}")
        print(f"  - 词表剔除生效文件数: {stats['sanitized']}")
    print("=" * 60)

    if args.dry_run:
        print("[Dry-run] 未写入任何文件")
        return 0

    # 残留扫描门禁：任何命中即失败
    violations = scan_target(args.target, cfg)
    if violations:
        print(f"[发布阻断] 目标目录发现 {len(violations)} 处禁止内容残留：")
        for item in violations:
            print(f"  {item}")
        return 1

    print(f"[发布完成] {args.target} 扫描通过，可推送公开仓库")
    return 0


if __name__ == "__main__":
    sys.exit(main())
