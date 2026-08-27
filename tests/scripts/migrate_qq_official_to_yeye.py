"""迁移 QQ Official Coco（yeye）相关 short_term 和 weighted 文件到独立目录

将以下文件从 aveline_data 迁移到 yeye_data：
- short_term/private_B78B23BF9C7F51857AEB19891AE32C1D__scope__aveline_short.json
    → yeye_data/.../__scope__yeye_short.json
- weighted/private_B78B23BF9C7F51857AEB19891AE32C1D__persona__qq_official_2_weighted.json
    → yeye_data/.../（保持原名，cid 是历史 slug，不动）
- weighted/private_B78B23BF9C7F51857AEB19891AE32C1D__scope__aveline_weighted.json
    → yeye_data/.../__scope__yeye_weighted.json

文件内容里的 conversation_id 保留历史 cid（__persona__qq_official_2），
代码层兼容旧 slug 识别为 yeye scope。

同时为 xiaolu_data 建立空目录结构。
"""
import shutil
from pathlib import Path

BASE = Path("companion_data")
AVELINE = BASE / "aveline_data"
YEye = BASE / "yeye_data"
Xiaolu = BASE / "xiaolu_data"

# 备份目录
BACKUP = AVELINE / "memories" / "_backup_before_qq_official_migration"

# 用户 ID 前缀（QQ 用户 B78B23BF9C7F51857AEB19891AE32C1D）
USER_PREFIX = "private_B78B23BF9C7F51857AEB19891AE32C1D"


def main() -> None:
    import time

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    print(f"=== QQ Official 数据迁移 (timestamp={timestamp}) ===\n")

    # 1. 新建数据目录结构
    for data_dir in (YEye, Xiaolu):
        for sub in ("memories/short_term", "memories/weighted", "chat_history", "daily"):
            target = data_dir / sub
            target.mkdir(parents=True, exist_ok=True)
            print(f"  [mkdir] {target}")

    # 2. 备份目录
    BACKUP.mkdir(parents=True, exist_ok=True)
    print(f"  [mkdir] {BACKUP}")

    # 3. 迁移Coco相关文件
    migrations = [
        # (src, dst, rename_scope_in_filename)
        (
            AVELINE / "memories/short_term" / f"{USER_PREFIX}__scope__aveline_short.json",
            YEye / "memories/short_term" / f"{USER_PREFIX}__scope__yeye_short.json",
            True,
        ),
        (
            AVELINE / "memories/weighted" / f"{USER_PREFIX}__persona__qq_official_2_weighted.json",
            YEye / "memories/weighted" / f"{USER_PREFIX}__persona__qq_official_2_weighted.json",
            False,
        ),
        (
            AVELINE / "memories/weighted" / f"{USER_PREFIX}__scope__aveline_weighted.json",
            YEye / "memories/weighted" / f"{USER_PREFIX}__scope__yeye_weighted.json",
            True,
        ),
    ]

    print("\n=== 迁移文件 ===")
    for src, dst, _ in migrations:
        if not src.exists():
            print(f"  [skip] 源文件不存在: {src}")
            continue
        if dst.exists():
            print(f"  [skip] 目标已存在: {dst}")
            continue
        # 先备份到 BACKUP
        backup_path = BACKUP / src.name
        if not backup_path.exists():
            shutil.copy2(str(src), str(backup_path))
            print(f"  [backup] {src.name} -> {backup_path}")
        # 移动并改名
        shutil.move(str(src), str(dst))
        print(f"  [move] {src.name}")
        print(f"        -> {dst.relative_to(BASE)}")

    # 4. 确认结果
    print("\n=== 迁移后 yeye_data 结构 ===")
    for f in sorted(YEye.rglob("*")):
        if f.is_file():
            print(f"  {f.relative_to(BASE)}")

    print("\n=== aveline_data/memories/short_term 剩余文件 ===")
    st_dir = AVELINE / "memories/short_term"
    if st_dir.exists():
        for f in sorted(st_dir.iterdir()):
            print(f"  {f.name}")

    print("\n=== aveline_data/memories/weighted 剩余文件 ===")
    w_dir = AVELINE / "memories/weighted"
    if w_dir.exists():
        for f in sorted(w_dir.iterdir()):
            if f.is_dir() and f.name.startswith("_"):
                continue
            print(f"  {f.name}")


if __name__ == "__main__":
    main()
