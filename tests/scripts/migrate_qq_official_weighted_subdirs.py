"""迁移 weighted 子目录下残留的 B78B23BF 相关 weighted 文件到 yeye_data

之前迁移只处理了 weighted 根目录下的 short_term/weighted 文件，
但 weighted/daily、weighted/entertainment、weighted/learning 等子目录里
还有 6 个 private_B78B23BF9C7F51857AEB19891AE32C1D__scope__aveline_weighted.json
需要迁移到 yeye_data/memories/weighted/{sub}/ 下，并改名为 __scope__yeye。
"""
import shutil
from pathlib import Path

BASE = Path("companion_data")
AVELINE = BASE / "aveline_data"
YEye = BASE / "yeye_data"

USER_PREFIX = "private_B78B23BF9C7F51857AEB19891AE32C1D"


def main() -> None:
    weighted_root = AVELINE / "memories" / "weighted"
    yeye_weighted_root = YEye / "memories" / "weighted"

    print("=== 扫描 weighted 子目录下的 B78B23BF 相关文件 ===\n")

    migrated = 0
    for src in sorted(weighted_root.rglob(f"{USER_PREFIX}*")):
        if not src.is_file():
            continue
        # 跳过已迁移的根目录文件（已经迁过的）
        if src.parent == weighted_root:
            continue

        rel_to_weighted = src.relative_to(weighted_root)
        sub_dir = rel_to_weighted.parent  # 子目录名（如 daily、learning）
        new_name = src.name.replace("__scope__aveline", "__scope__yeye")

        dst = yeye_weighted_root / sub_dir / new_name
        dst.parent.mkdir(parents=True, exist_ok=True)

        if dst.exists():
            print(f"  [skip] 目标已存在: {dst.relative_to(BASE)}")
            continue

        shutil.move(str(src), str(dst))
        print(f"  [move] {src.relative_to(BASE)}")
        print(f"        -> {dst.relative_to(BASE)}")
        migrated += 1

    print(f"\n迁移完成: {migrated} 个文件")

    # 验证 yeye_data/memories/weighted 现在的所有文件
    print("\n=== yeye_data/memories/weighted 全部文件 ===")
    for f in sorted((YEye / "memories" / "weighted").rglob("*")):
        if f.is_file():
            print(f"  {f.relative_to(BASE)}")

    # 验证 aveline_data 已无 B78B23BF 残留（排除 _backup 和 legacy）
    print("\n=== 验证 aveline_data 已无 B78B23BF 残留（排除备份目录）===")
    bad_patterns = ["B78B23BF9C7F51857AEB19891AE32C1D", "qq_official", "qq_group"]
    residual = []
    for f in AVELINE.rglob("*"):
        if not f.is_file():
            continue
        if any(x in f.parts for x in ("_backup", "_quarantine", "legacy")):
            continue
        name = f.name
        for p in bad_patterns:
            if p in name:
                residual.append((f.relative_to(BASE), p))
                break
    if residual:
        print(f"  [FAIL] 仍有 {len(residual)} 个残留:")
        for path, p in residual:
            print(f"    {path} (匹配 {p!r})")
    else:
        print(f"  [OK] 无残留")


if __name__ == "__main__":
    main()
