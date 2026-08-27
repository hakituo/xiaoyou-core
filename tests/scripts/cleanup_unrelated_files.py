"""清理 aveline_data 下与 Aveline 无关的文件

按用户要求："qq群的直接删了，无关的也是"
- qq_group 相关：4 个（3 weighted + 1 chat_history）
- mobile_user：1 个 weighted
- default/default_user：8 个 weighted（含子目录）
- 测试文件：12 个 weighted（含子目录）

为安全起见，先备份到 quarantine 目录，再删除原文件。
"""
import shutil
import time
from pathlib import Path

BASE = Path("companion_data")
QUARANTINE = BASE / "_quarantine" / f"unrelated_cleanup_{time.strftime('%Y%m%d_%H%M%S')}"

QQ_GROUP_PATTERNS = ["qq_group"]
MOBILE_PATTERNS = ["mobile_user"]
DEFAULT_PATTERNS = ["default_user_weighted", "default_weighted.json"]
TEST_PATTERNS = [
    "mem_style_smoke",
    "sensitive_test",
    "u1_weighted",
    "sensitive_test_user",
]


def should_delete(file_path: Path) -> str | None:
    name = file_path.name
    name_lower = name.lower()
    if any(p in name_lower for p in QQ_GROUP_PATTERNS):
        return "qq_group"
    if any(p in name_lower for p in MOBILE_PATTERNS):
        return "mobile_user"
    if any(p in name for p in DEFAULT_PATTERNS):
        return "default"
    for p in TEST_PATTERNS:
        if p in name_lower:
            return "test"
    return None


def main() -> None:
    print(f"=== 清理无关文件 (quarantine: {QUARANTINE}) ===\n")

    to_delete: list[tuple[Path, str, str]] = []  # (file, rel, reason)

    # 扫描 weighted / chat_history / short_term / daily
    for sub in ("memories/weighted", "memories/short_term", "chat_history", "daily"):
        root = BASE / "aveline_data" / sub
        if not root.exists():
            continue
        for f in root.rglob("*.json*"):
            if not f.is_file():
                continue
            if "_backup" in f.parts or "legacy" in f.parts:
                continue
            reason = should_delete(f)
            if reason:
                to_delete.append((f, str(f.relative_to(BASE)), reason))

    print(f"扫描到 {len(to_delete)} 个待清理文件\n")

    # 按原因分组打印
    by_reason: dict[str, list[Path]] = {}
    for f, rel, reason in to_delete:
        by_reason.setdefault(reason, []).append(f)
    for reason, paths in by_reason.items():
        print(f"--- {reason} ({len(paths)} 个) ---")
        for p in paths:
            print(f"  {p.relative_to(BASE)}")
        print()

    # 1. 备份到 quarantine
    print(f"=== 备份到 {QUARANTINE} ===")
    for f, rel, reason in to_delete:
        # 保持相对路径结构
        dst = QUARANTINE / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(f), str(dst))
    print(f"  备份 {len(to_delete)} 个文件完成\n")

    # 2. 删除原文件
    print("=== 删除原文件 ===")
    deleted = 0
    for f, rel, reason in to_delete:
        try:
            f.unlink()
            deleted += 1
            print(f"  [del] {rel}")
        except Exception as e:
            print(f"  [fail] {rel}: {e}")
    print(f"\n删除完成: {deleted}/{len(to_delete)}")

    # 3. 检查 aveline_data/memories/weighted 现在剩什么
    print("\n=== aveline_data/memories/weighted 剩余文件 ===")
    w_dir = BASE / "aveline_data" / "memories" / "weighted"
    if w_dir.exists():
        for f in sorted(w_dir.iterdir()):
            if f.is_dir() and f.name.startswith("_"):
                continue
            print(f"  {f.name}")


if __name__ == "__main__":
    main()
