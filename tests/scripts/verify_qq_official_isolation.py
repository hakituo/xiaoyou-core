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
expected = {"Aveline_QQ_Master.json", "Ling_QQ_Master.json", "Xiaolu.json", "Yeye.json"}
actual = {f.name for f in qq_dir.iterdir() if f.is_file()}
assert expected == actual, f"persona 文件不匹配: {actual}"
print(f"  [OK] 预期 4 个文件，实际 {len(actual)} 个")

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
# 预期：1 个 short_term + 8 个 weighted（根目录 3 个 + 子目录 6 个：daily/entertainment/learning/persona_prompt/thinking/work）
expected_yeye_files = {
    # short_term
    "yeye_data\\memories\\short_term\\private_B78B23BF9C7F51857AEB19891AE32C1D__scope__yeye_short.json",
    # weighted 根目录
    "yeye_data\\memories\\weighted\\private_B78B23BF9C7F51857AEB19891AE32C1D__persona__qq_official_2_weighted.json",
    "yeye_data\\memories\\weighted\\private_B78B23BF9C7F51857AEB19891AE32C1D__scope__yeye_weighted.json",
    # weighted 子目录
    "yeye_data\\memories\\weighted\\daily\\private_B78B23BF9C7F51857AEB19891AE32C1D__scope__yeye_weighted.json",
    "yeye_data\\memories\\weighted\\entertainment\\private_B78B23BF9C7F51857AEB19891AE32C1D__scope__yeye_weighted.json",
    "yeye_data\\memories\\weighted\\learning\\private_B78B23BF9C7F51857AEB19891AE32C1D__scope__yeye_weighted.json",
    "yeye_data\\memories\\weighted\\persona_prompt\\private_B78B23BF9C7F51857AEB19891AE32C1D__scope__yeye_weighted.json",
    "yeye_data\\memories\\weighted\\thinking\\private_B78B23BF9C7F51857AEB19891AE32C1D__scope__yeye_weighted.json",
    "yeye_data\\memories\\weighted\\work\\private_B78B23BF9C7F51857AEB19891AE32C1D__scope__yeye_weighted.json",
}
actual_yeye = {str(f.relative_to(BASE)) for f in yeye_files if f.is_file()}
assert expected_yeye_files == actual_yeye, f"yeye_data 文件不匹配: {actual_yeye}"
print(f"  [OK] 预期 {len(expected_yeye_files)} 个文件，实际 {len(actual_yeye)} 个")

# 4. xiaolu_data 目录结构
print("\n=== 4. xiaolu_data 目录内容 ===")
xiaolu_files = list(Xiaolu.rglob("*"))
file_count = sum(1 for f in xiaolu_files if f.is_file())
dir_count = sum(1 for f in xiaolu_files if f.is_dir())
print(f"  目录: {dir_count} 个，文件: {file_count} 个")
for f in sorted(xiaolu_files):
    if f.is_dir():
        print(f"  [dir] {f.relative_to(BASE)}")
assert file_count == 0, "xiaolu_data 应该是空目录（暂无数据）"
print(f"  [OK] xiaolu_data 是空目录（预期）")

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
    print(f"  [OK] 无 qq_official/qq_group/B78B23BF 残留（备份目录除外）")

# 6. aveline_data/memories/short_term 当前文件
print("\n=== 6. aveline_data/memories/short_term 剩余文件 ===")
st_dir = AVELINE / "memories" / "short_term"
for f in sorted(st_dir.iterdir()):
    print(f"  {f.name}")
expected_st = {"private_10001__scope__aveline_short.json"}
actual_st = {f.name for f in st_dir.iterdir() if f.is_file()}
assert expected_st == actual_st, f"short_term 文件不匹配: {actual_st}"
print(f"  [OK] 只剩 1 个 Aveline 主用户的 short_term 文件")

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
    ("private_10001__persona__aveline_qq_master", "aveline"),
    ("private_10001__persona__ling_qq_master", "ling"),
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
