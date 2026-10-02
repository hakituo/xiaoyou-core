# -*- coding: utf-8 -*-
"""只读检查：三个保留账号的 nt_msg.db 头部是否含可离线读取的 key_meta。

注意：key_meta 是换取数据库密钥的凭证，属敏感信息，本脚本只输出
「是否存在 / 长度 / 掩码」，不打印明文，也不写入任何文件。
"""

from __future__ import annotations

import re
from pathlib import Path

BASE = Path(r"D:\QQ\Tencent Files")
ACCOUNTS = {
    "123456789": "主人号",
    "123456789": "aveline Aveline",
    "123456789": "ling Ling",
}

HEX128 = re.compile(rb"[0-9a-f]{128}")


def inspect(db: Path) -> dict:
    info = {"exists": db.is_file()}
    if not info["exists"]:
        return info

    info["size_mb"] = db.stat().st_size / 1024 / 1024
    with db.open("rb") as f:
        head = f.read(1024)

    info["marker"] = b"QQ_NT DB" in head
    info["header_ver"] = None
    m = re.search(rb"1\.\d+\.\d+\.\d+", head)
    if m:
        info["header_ver"] = m.group().decode()

    # key_meta：头部里的 128 个 hex 字符（紧跟前置长度字段，无 null 分隔）
    m = HEX128.search(head)
    if m:
        info["key_meta"] = m.group().decode()
    return info


def main() -> None:
    for acct, label in ACCOUNTS.items():
        db = BASE / acct / "nt_qq_backup" / "nt_db" / "nt_msg.db"
        info = inspect(db)
        print(f"=== {acct} ({label}) ===")
        if not info["exists"]:
            print("  nt_msg.db 不存在")
            continue
        print(f"  文件大小      : {info['size_mb']:.1f} MB")
        print(f"  QQ_NT DB 标记 : {info['marker']}")
        print(f"  头部版本      : {info['header_ver']}")
        km = info.get("key_meta")
        if km:
            print(f"  key_meta      : 存在，长度 {len(km)} 字符（已掩码）")
            print(f"                  掩码样例 {km[:8]}...{km[-8:]}")
        else:
            print("  key_meta      : 未找到")
        print()


if __name__ == "__main__":
    main()
