"""验证 QQ Official 数据隔离修复的最终状态"""
import json
from pathlib import Path

BASE = Path("companion_data")
AVELINE = BASE / "aveline_data"
YEye = BASE / "yeye_data"
Xiaolu = BASE / "xiaolu_data"

print("=" * 70)
print("QQ Official 数据隔离修复 - 最终状态验证")
print("=" * 70)

# 1. persona 文件
print("\n=== 1. persona 文件 ===")
qq_dir = Path("core/character/configs/qq")
for f in sorted(qq_dir.iterdir()):
    print(f"  {f.name}")
# Aveline/Ling已不再维护 QQ 专属人设，改用核心人设 core_aveline.json / core_ling.json
expected = {"Xiaolu.json", "Yeye.json"}
actual = {f.name for f in qq_dir.iterdir() if f.is_file()}
assert expected == actual, f"persona 文件不匹配: {actual}"
print(f"  [OK] 预期 {len(expected)} 个文件，实际 {len(actual)} 个")

# 2. bot 配置文件
print("\n=== 2. bot 配置 persona_filename 引用 ===")
for cfg_name in ("config_official_bot1.json", "config_official_bot2.json"):
    cfg_path = Path("clients/bots/config") / cfg_name
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    print(f"  {cfg_name}: persona_filename={cfg.get('persona_filename')!r}, role_name={cfg.get('role_name')!r}")
    assert "QQ_Official_" not in cfg.get("persona_filename", ""), f"{cfg_name} 还在引用旧文件名"

# 3. yeye_data 目录结构
print("\n=== 3. yeye_data 目录内容 ===")
yeye_files = list(YEye.rglob("*"))
for f in sorted(yeye_files):
    if f.is_file():
        print(f"  {f.relative_to(BASE)}")
# 只校验隔离性：文件清单会随角色日常运行不断增长，快照式断言必然过期
actual_yeye = [str(f.relative_to(BASE)) for f in yeye_files if f.is_file()]
print(f"  共 {len(actual_yeye)} 个文件")

foreign = [
    rel
    for rel in actual_yeye
    if any(
        token in rel
        for token in ("aveline", "ling", "xiaolu", "rushuang", "mianmian")
    )
]
assert not foreign, f"yeye_data 混入了其它角色的数据文件: {foreign}"
print("  [OK] 未混入其它角色数据")

yeye_scope_files = [rel for rel in actual_yeye if "__scope__yeye" in rel]
assert yeye_scope_files, "yeye_data 下没有 __scope__yeye 记忆文件，隔离目录可能未生效"
print(f"  [OK] yeye scope 记忆文件 {len(yeye_scope_files)} 个")

# 4. xiaolu_data 目录结构
print("\n=== 4. xiaolu_data 目录内容 ===")
xiaolu_files = list(Xiaolu.rglob("*"))
file_count = sum(1 for f in xiaolu_files if f.is_file())
dir_count = sum(1 for f in xiaolu_files if f.is_dir())
print(f"  目录: {dir_count} 个，文件: {file_count} 个")
for f in sorted(xiaolu_files):
    if f.is_dir():
        print(f"  [dir] {f.relative_to(BASE)}")

actual_xiaolu = [str(f.relative_to(BASE)) for f in xiaolu_files if f.is_file()]
xiaolu_foreign = [
    rel
    for rel in actual_xiaolu
    if any(
        token in rel
        for token in ("aveline", "ling", "yeye", "rushuang", "mianmian")
    )
]
assert not xiaolu_foreign, f"xiaolu_data 混入了其它角色的数据文件: {xiaolu_foreign}"
print("  [OK] 未混入其它角色数据")

# 5. aveline_data 已无 qq_official / qq_group 相关文件
print("\n=== 5. aveline_data 已无 QQ official/group 残留 ===")
bad_patterns = ["qq_official", "qq_group", "B78B23BF9C7F51857AEB19891AE32C1D"]
residual = []
for f in AVELINE.rglob("*"):
    if not f.is_file():
        continue
    # 跳过所有备份目录：_backup_*, _quarantine, short_term_legacy_backup
    if any(p.startswith("_backup") or p == "_quarantine" or p == "short_term_legacy_backup"
           for p in f.parts):
        continue
    name = f.name.lower()
    for p in bad_patterns:
        if p.lower() in name:
            residual.append((f.relative_to(BASE), p))
            break
if residual:
    print(f"  [FAIL] 发现 {len(residual)} 个残留文件:")
    for path, p in residual:
        print(f"    {path} (匹配 {p!r})")
    raise SystemExit(1)
else:
    print("  [OK] 无 qq_official/qq_group/B78B23BF 残留（备份目录除外）")

# 6. aveline_data/memories/short_term 当前文件
print("\n=== 6. aveline_data/memories/short_term 剩余文件 ===")
st_dir = AVELINE / "memories" / "short_term"
for f in sorted(st_dir.iterdir()):
    print(f"  {f.name}")
expected_st = {"private_10001__scope__aveline_short.json"}
actual_st = {f.name for f in st_dir.iterdir() if f.is_file()}
assert expected_st == actual_st, f"short_term 文件不匹配: {actual_st}"
print("  [OK] 只剩 1 个 Aveline 主用户的 short_term 文件")

# 7. 备份和隔离目录
print("\n=== 7. 备份与隔离目录 ===")
backup_dir = AVELINE / "memories" / "_backup_before_qq_official_migration"
quarantine_dir = BASE / "_quarantine"
if backup_dir.exists():
    backup_count = sum(1 for _ in backup_dir.rglob("*") if _.is_file())
    print(f"  迁移前备份: {backup_dir.relative_to(BASE)} ({backup_count} 个文件)")
if quarantine_dir.exists():
    for sub in sorted(quarantine_dir.iterdir()):
        if sub.is_dir():
            cnt = sum(1 for _ in sub.rglob("*") if _.is_file())
            print(f"  无关文件隔离: {sub.relative_to(BASE)} ({cnt} 个文件)")

# 8. scope 解析验证
print("\n=== 8. 代码 scope 解析验证 ===")
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.utils.data_paths import resolve_data_scope_from_conversation_id, resolve_memory_user_id

cases = [
    ("private_B78B23BF9C7F51857AEB19891AE32C1D__persona__qq_official_1", "xiaolu"),
    ("private_B78B23BF9C7F51857AEB19891AE32C1D__persona__qq_official_2", "yeye"),
    ("private_B78B23BF9C7F51857AEB19891AE32C1D__persona__Xiaolu", "xiaolu"),
    ("private_B78B23BF9C7F51857AEB19891AE32C1D__persona__Yeye", "yeye"),
    ("private_10001__persona__core_aveline", "aveline"),
    ("private_10001__persona__core_ling", "ling"),
]
for cid, expected in cases:
    actual = resolve_data_scope_from_conversation_id(cid)
    flag = "[OK]" if actual == expected else "[FAIL]"
    print(f"  {flag} {cid[:60]}: {actual} (期望 {expected})")
    assert actual == expected

memory_cases = [
    ("private_B78B23BF9C7F51857AEB19891AE32C1D__persona__qq_official_2",
     "private_B78B23BF9C7F51857AEB19891AE32C1D__scope__yeye"),
    ("private_B78B23BF9C7F51857AEB19891AE32C1D__persona__qq_official_1",
     "private_B78B23BF9C7F51857AEB19891AE32C1D__scope__xiaolu"),
]
for cid, expected in memory_cases:
    actual = resolve_memory_user_id(cid)
    flag = "[OK]" if actual == expected else "[FAIL]"
    print(f"  {flag} memory_user_id: {actual}")
    assert actual == expected

print("\n" + "=" * 70)
print("所有验证通过！QQ Official 数据隔离修复完成。")
print("=" * 70)
