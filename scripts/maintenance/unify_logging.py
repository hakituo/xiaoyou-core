"""P2-3 批量替换脚本：将 logging.getLogger 替换为 get_logger

只处理 core/ 目录下的文件（除豁免文件外）。
策略：
1. logging.getLogger(__name__) → get_logger(__name__)
2. logging.getLogger("FOO") → get_logger("FOO")
3. 添加 from core.utils.logger import get_logger（如未存在）
4. 保留 import logging（如果仍使用 logging.ERROR 等常量）
5. logging.basicConfig(...) 调用替换为 setup_logging() 或注释掉

豁免文件：
- core/utils/logger.py（实现 get_logger 的模块本身）
- core/utils/log_sanitizer.py（注释明确说明循环依赖）
- core/utils/error_collector.py（注释明确说明循环依赖）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CORE_DIR = PROJECT_ROOT / "core"

# 豁免文件（实现日志基础设施或显式注释了循环依赖）
EXEMPT_FILES = {
    CORE_DIR / "utils" / "logger.py",
    CORE_DIR / "utils" / "log_sanitizer.py",
    CORE_DIR / "utils" / "error_collector.py",
}

# 匹配 logging.getLogger(...)
_GET_LOGGER_PATTERN = re.compile(
    r"logging\.getLogger\(\s*"
    r"(?P<arg>"
    r"__name__"
    r"|"
    r"(?P<quote>['\"])[\w\.]+(?P=quote)"
    r")"
    r"\s*\)"
)

# 匹配 import logging（顶层）
_IMPORT_LOGGING_PATTERN = re.compile(r"^import logging\s*$", re.MULTILINE)

# 匹配 from core.utils.logger import get_logger（已存在）
_HAS_GET_LOGGER_IMPORT_PATTERN = re.compile(
    r"^from core\.utils\.logger import\s+.*\bget_logger\b.*$",
    re.MULTILINE,
)

# 匹配其他 logging.XXX 使用（如 logging.ERROR、logging.INFO、logging.StreamHandler 等）
_OTHER_LOGGING_USAGE_PATTERN = re.compile(
    r"logging\.(ERROR|WARNING|INFO|DEBUG|CRITICAL|NOTSET|"
    r"StreamHandler|RotatingFileHandler|TimedRotatingFileHandler|"
    r"Formatter|Filter|LogRecord|Handler|getLogger|basicConfig|"
    r"WARN|FATAL|exception|captureWarnings|getLogRecordFactory|"
    r"setLogRecordFactory|disable|root|lastResort|log|debug|info|"
    r"warning|error|critical|makeLogRecord|shutdown|"
    r"LogRecord|BufferingFormatter|FileHandler|NullHandler|"
    r"QueueHandler|QueueListener|SocketHandler|SysLogHandler|"
    r"NTEventLogHandler|MemoryHandler|HTTPHandler|SMTPHandler|"
    r"watchtower|coloredformatter|addLevelName|getLevelName)"
)


def find_target_files() -> list[Path]:
    """查找 core/ 目录下使用 logging.getLogger 的 Python 文件"""
    targets: list[Path] = []
    for py_file in CORE_DIR.rglob("*.py"):
        if py_file in EXEMPT_FILES:
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except Exception:
            continue
        if _GET_LOGGER_PATTERN.search(text):
            targets.append(py_file)
    return targets


def process_file(file_path: Path) -> dict:
    """处理单个文件，返回修改统计"""
    text = file_path.read_text(encoding="utf-8")
    original_text = text

    stats = {
        "file": str(file_path.relative_to(PROJECT_ROOT)),
        "get_logger_replacements": 0,
        "added_import": False,
        "removed_import_logging": False,
        "basic_config_removed": 0,
        "skipped": False,
        "skip_reason": "",
    }

    # 1. 替换 logging.getLogger(...) → get_logger(...)
    def _replace_get_logger(m: re.Match) -> str:
        stats["get_logger_replacements"] += 1
        arg = m.group("arg")
        return f"get_logger({arg})"

    new_text = _GET_LOGGER_PATTERN.sub(_replace_get_logger, text)

    # 2. 检查是否还需要 import logging
    # 如果不再有任何 logging.XXX 使用，则可以删除 import logging
    if _IMPORT_LOGGING_PATTERN.search(new_text):
        # 检查除 import logging 这一行外，是否还有 logging. 使用
        # 临时移除 import logging 行后再检查
        text_without_import = _IMPORT_LOGGING_PATTERN.sub("", new_text)
        if not _OTHER_LOGGING_USAGE_PATTERN.search(text_without_import):
            # 不再使用任何 logging.XXX，可以删除 import
            new_text = text_without_import
            stats["removed_import_logging"] = True

    # 3. 添加 from core.utils.logger import get_logger（如未存在且需要）
    if stats["get_logger_replacements"] > 0:
        if not _HAS_GET_LOGGER_IMPORT_PATTERN.search(new_text):
            # 在第一个 import 语句之前插入
            # 找到第一行 import 或 from 语句
            lines = new_text.split("\n")
            insert_idx = 0
            for i, line in enumerate(lines):
                # 跳过模块 docstring
                if line.startswith('"""') or line.startswith("'''"):
                    # 找到 docstring 结束
                    quote = line[:3]
                    if line.count(quote) >= 2 and len(line) > 3:
                        # 单行 docstring
                        insert_idx = i + 1
                        continue
                    # 多行 docstring，找到结束
                    for j in range(i + 1, len(lines)):
                        if quote in lines[j]:
                            insert_idx = j + 1
                            break
                    continue
                if line.startswith("import ") or line.startswith("from "):
                    insert_idx = i
                    break
            else:
                insert_idx = 0

            # 找到插入点后，跳过 __future__ import
            while insert_idx < len(lines):
                line = lines[insert_idx].strip()
                if line.startswith("from __future__"):
                    insert_idx += 1
                    continue
                break

            # 插入导入语句
            lines.insert(insert_idx, "from core.utils.logger import get_logger")
            # 如果下一行不是空行且不是 import，加一个空行
            if insert_idx + 1 < len(lines) and lines[insert_idx + 1].strip() and not lines[insert_idx + 1].startswith(("import ", "from ")):
                lines.insert(insert_idx + 1, "")
            new_text = "\n".join(lines)
            stats["added_import"] = True

    if new_text == original_text:
        stats["skipped"] = True
        stats["skip_reason"] = "no changes"
        return stats

    file_path.write_text(new_text, encoding="utf-8")
    return stats


def main() -> int:
    print("=" * 60)
    print("P2-3 批量替换：logging.getLogger → get_logger")
    print("=" * 60)

    targets = find_target_files()
    print(f"\n找到 {len(targets)} 个文件需要处理\n")

    total_replacements = 0
    total_added_imports = 0
    total_removed_imports = 0
    skipped_count = 0

    for py_file in targets:
        stats = process_file(py_file)
        if stats["skipped"]:
            skipped_count += 1
            continue
        rel_path = stats["file"]
        msg = f"  {rel_path}: {stats['get_logger_replacements']} 处替换"
        if stats["added_import"]:
            msg += " +import"
            total_added_imports += 1
        if stats["removed_import_logging"]:
            msg += " -import logging"
            total_removed_imports += 1
        print(msg)
        total_replacements += stats["get_logger_replacements"]

    print("\n" + "=" * 60)
    print(f"总计:")
    print(f"  处理文件数: {len(targets) - skipped_count}")
    print(f"  替换次数: {total_replacements}")
    print(f"  新增 import: {total_added_imports}")
    print(f"  移除 import logging: {total_removed_imports}")
    print(f"  跳过文件: {skipped_count}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
