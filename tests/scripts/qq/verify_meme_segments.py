"""验证 [MEME]/[IMG] 标签的位置感知分段机制（extract_media_segments）。

验证点：
1. 基础分段：文本A[MEME]文本B[MEME:anime] → 两段各带标签
2. 纯文本无标签 → 单段无标签
3. 标签在开头：[MEME]文本 → 空文本段+标签 + 文字段
4. 标签在末尾：文本[MEME] → 文字段+标签，无尾段
5. 连续标签：[MEME][MEME] → 两个空文本段各带标签
6. 混合 MEME + IMG：文本A[MEME]文本B[IMG:2] → 两段
7. 全角括号分段：文本A［MEME］文本B → 两段
8. 向后兼容：extract_media_tags 汇总结果与 segments 一致
9. 文本拼接还原：所有段 text 拼接 ≈ 原文去掉标签

运行：venv_core\\scripts\\python.exe tests\\scripts\\qq\\verify_meme_segments.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from clients.bots.qq import media_tags  # noqa: E402
from clients.bots.qq.media_tags import (  # noqa: E402
    MediaSegment,
    extract_media_segments,
    extract_media_tags,
)

_passed = 0


def _ok(msg: str):
    global _passed
    _passed += 1
    print(f"[PASS] {msg}")


def _fail(msg: str):
    print(f"[FAIL] {msg}")
    sys.exit(1)


# ---------- 测试 1：基础分段 ----------
segs = extract_media_segments("文本A[MEME]文本B[MEME:anime]")
if len(segs) != 2:
    _fail(f"基础分段应得 2 段，实际 {len(segs)}: {segs}")
if segs[0].text != "文本A" or segs[0].meme_categories != ["random"] or segs[0].img_count != 0:
    _fail(f"段1错误: {segs[0]}")
if segs[1].text != "文本B" or segs[1].meme_categories != ["anime"] or segs[1].img_count != 0:
    _fail(f"段2错误: {segs[1]}")
_ok("基础分段：文本A[MEME]文本B[MEME:anime] → 2 段各带标签")


# ---------- 测试 2：纯文本无标签 ----------
segs = extract_media_segments("纯文本无标签")
if len(segs) != 1 or segs[0].text != "纯文本无标签" or segs[0].meme_categories or segs[0].img_count:
    _fail(f"纯文本分段错误: {segs}")
_ok("纯文本无标签 → 单段无标签")


# ---------- 测试 3：标签在开头 ----------
segs = extract_media_segments("[MEME]文本")
if len(segs) != 2:
    _fail(f"标签在开头应得 2 段，实际 {len(segs)}: {segs}")
if segs[0].text != "" or segs[0].meme_categories != ["random"]:
    _fail(f"段1（空文本+标签）错误: {segs[0]}")
if segs[1].text != "文本" or segs[1].meme_categories:
    _fail(f"段2（纯文本）错误: {segs[1]}")
_ok("标签在开头：[MEME]文本 → 空文本段+标签 + 纯文本段")


# ---------- 测试 4：标签在末尾 ----------
segs = extract_media_segments("文本[MEME]")
if len(segs) != 1:
    _fail(f"标签在末尾应得 1 段（无尾段），实际 {len(segs)}: {segs}")
if segs[0].text != "文本" or segs[0].meme_categories != ["random"]:
    _fail(f"段1错误: {segs[0]}")
_ok("标签在末尾：文本[MEME] → 单段带标签，无尾段")


# ---------- 测试 5：连续标签 ----------
segs = extract_media_segments("[MEME][MEME:anime]")
if len(segs) != 2:
    _fail(f"连续标签应得 2 段，实际 {len(segs)}: {segs}")
if segs[0].text != "" or segs[0].meme_categories != ["random"]:
    _fail(f"段1错误: {segs[0]}")
if segs[1].text != "" or segs[1].meme_categories != ["anime"]:
    _fail(f"段2错误: {segs[1]}")
_ok("连续标签：[MEME][MEME:anime] → 两个空文本段各带标签")


# ---------- 测试 6：混合 MEME + IMG ----------
segs = extract_media_segments("文本A[MEME]文本B[IMG:2]")
if len(segs) != 2:
    _fail(f"混合标签应得 2 段，实际 {len(segs)}: {segs}")
if segs[0].text != "文本A" or segs[0].meme_categories != ["random"] or segs[0].img_count != 0:
    _fail(f"段1错误: {segs[0]}")
if segs[1].text != "文本B" or segs[1].meme_categories != [] or segs[1].img_count != 2:
    _fail(f"段2错误: {segs[1]}")
_ok("混合 MEME+IMG：文本A[MEME]文本B[IMG:2] → 两段分别带不同标签")


# ---------- 测试 6b：BM 第二私藏图标签分段 ----------
segs = extract_media_segments("文本A[BM]文本B[BM:2]")
if len(segs) != 2:
    _fail(f"BM 标签应得 2 段，实际 {len(segs)}: {segs}")
if segs[0].text != "文本A" or segs[0].meme_categories or segs[0].img_count != 0 or segs[0].bm_count != 1:
    _fail(f"BM 段1错误: {segs[0]}")
if segs[1].text != "文本B" or segs[1].meme_categories or segs[1].img_count != 0 or segs[1].bm_count != 2:
    _fail(f"BM 段2错误: {segs[1]}")
_ok("BM 标签：文本A[BM]文本B[BM:2] → 两段各带 bm_count")


# ---------- 测试 6c：MEME+IMG+BM 三种混合 ----------
segs = extract_media_segments("A[MEME]B[IMG:2]C[BM:3]")
if len(segs) != 3:
    _fail(f"三种混合应得 3 段，实际 {len(segs)}: {segs}")
if segs[0].meme_categories != ["random"] or segs[0].img_count or segs[0].bm_count:
    _fail(f"段1错误: {segs[0]}")
if segs[1].img_count != 2 or segs[1].meme_categories or segs[1].bm_count:
    _fail(f"段2错误: {segs[1]}")
if segs[2].bm_count != 3 or segs[2].meme_categories or segs[2].img_count:
    _fail(f"段3错误: {segs[2]}")
_ok("三种混合：A[MEME]B[IMG:2]C[BM:3] → 三段各带一种标签")


# ---------- 测试 6d：BM 全角括号 ----------
segs = extract_media_segments("文本A［BM］文本B")
if len(segs) != 2 or segs[0].bm_count != 1 or segs[1].text != "文本B":
    _fail(f"BM 全角括号错误: {segs}")
_ok("BM 全角括号：文本A［BM］文本B → 2 段")


# ---------- 测试 7：全角括号分段 ----------
segs = extract_media_segments("文本A［MEME］文本B")
if len(segs) != 2:
    _fail(f"全角括号应得 2 段，实际 {len(segs)}: {segs}")
if segs[0].text != "文本A" or segs[0].meme_categories != ["random"]:
    _fail(f"全角段1错误: {segs[0]}")
if segs[1].text != "文本B" or segs[1].meme_categories:
    _fail(f"全角段2错误: {segs[1]}")
_ok("全角括号：文本A［MEME］文本B → 2 段")


# ---------- 测试 8：向后兼容 extract_media_tags ----------
text = "文本A[MEME]文本B[MEME:anime][IMG:3]"
segs = extract_media_segments(text)
cleaned, cats, imgs, bms = extract_media_tags(text)
# extract_media_tags 汇总标签
all_cats = [c for s in segs for c in s.meme_categories]
all_imgs = sum(s.img_count for s in segs)
all_bms = sum(s.bm_count for s in segs)
if cats != all_cats or imgs != all_imgs or bms != all_bms:
    _fail(f"向后兼容不一致: tags=({cats},{imgs},{bms}) vs segments=({all_cats},{all_imgs},{all_bms})")
# cleaned 应包含所有段文本
if "文本A" not in cleaned or "文本B" not in cleaned:
    _fail(f"cleaned 文本缺失: {cleaned!r}")
_ok("向后兼容：extract_media_tags 汇总结果与 segments 一致")


# ---------- 测试 9：文本拼接还原 ----------
text = "这是原始文本[MEME:anime/白眼]，他就像这样说的[MEME:anime/白眼]"
segs = extract_media_segments(text)
# 还原：段文本拼接应包含原文去掉标签后的内容
restored = "".join(s.text for s in segs)
if "这是原始文本" not in restored or "他就像这样说的" not in restored:
    _fail(f"拼接还原缺失原文: {restored!r}")
# 两段各带一个标签
meme_count = sum(len(s.meme_categories) for s in segs)
if meme_count != 2:
    _fail(f"应得 2 个 MEME 标签，实际 {meme_count}: {segs}")
_ok(f"文本拼接还原：原文 {len(text)} 字 → {len(segs)} 段，{meme_count} 个标签")


# ---------- 测试 10：用户场景（断句位置发图） ----------
# 模拟用户描述的场景
text = "这是原始文本[MEME:anime/白眼]，他就像这样说的[MEME:anime/白眼]"
segs = extract_media_segments(text)
# 预期：2 段，每段文字后面跟一个 [MEME]
if len(segs) != 2:
    _fail(f"用户场景应得 2 段，实际 {len(segs)}: {segs}")
if segs[0].text != "这是原始文本" or not segs[0].meme_categories:
    _fail(f"段1应为'这是原始文本'+标签: {segs[0]}")
if "他就像这样说的" not in segs[1].text or not segs[1].meme_categories:
    _fail(f"段2应为'他就像这样说的'+标签: {segs[1]}")
_ok("用户场景：'这是原始文本[MEME]，他就像这样说的[MEME]' → 2 段各带标签")


# ---------- 测试 11：空文本和 None 输入 ----------
if extract_media_segments("") != []:
    _fail("空字符串应返回空列表")
if extract_media_segments(None) != []:
    _fail("None 应返回空列表")
_ok("空文本/None 输入 → 空列表")


# ---------- 测试 12：MediaSegment dataclass 基本功能 ----------
seg = MediaSegment(text="hello", meme_categories=["random"], img_count=0)
if seg.text != "hello" or seg.meme_categories != ["random"] or seg.img_count != 0:
    _fail(f"MediaSegment 构造错误: {seg}")
seg2 = MediaSegment()
if seg2.text != "" or seg2.meme_categories != [] or seg2.img_count != 0 or seg2.bm_count != 0:
    _fail(f"MediaSegment 默认值错误: {seg2}")
_ok("MediaSegment dataclass 基本功能正常（含 bm_count 默认 0）")


# ---------- 测试 13：BM 第二私藏图选图 + LRU 去重 ----------
from clients.bots.qq.media_tags import (  # noqa: E402
    _BM_LRU_SIZE,
    _recent_bm_paths,
    pick_bm_images,
    reset_recent_history,
)
reset_recent_history()
# 选 3 张不重复
batch = pick_bm_images(3)
if len(batch) != 3 or len(set(str(p) for p in batch)) != 3:
    _fail(f"BM 一次选 3 张有重复: {batch}")
_ok("pick_bm_images(3) 一次返回 3 张不重复")

# 连续选 2 批，应尽量不重叠
batch2 = pick_bm_images(2)
overlap = set(str(p) for p in batch) & set(str(p) for p in batch2)
all_bm_imgs = media_tags._list_images(media_tags.BM_ROOT)
if len(all_bm_imgs) > 5 and overlap:
    _fail(f"BM 连续两批重叠: {[Path(p).name for p in overlap]}")
_ok("pick_bm_images 连续两批 LRU 去重生效")

# LRU 登记
reset_recent_history()
pick_bm_images(2)
if len(_recent_bm_paths) != 2:
    _fail(f"BM LRU 长度异常: {len(_recent_bm_paths)}")
_ok(f"BM LRU 登记成功（_BM_LRU_SIZE={_BM_LRU_SIZE}）")


print(f"\n全部 {_passed} 项验证通过")
