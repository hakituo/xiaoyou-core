"""验证 [MEME]/[IMG] 选图的 LRU 去重机制。

验证点：
1. pick_meme_image 连续调用，最近 LRU_SIZE 次内不重复
2. pick_meme_image 不同 category 共享 LRU（同一张图不会被相邻发两次）
3. 候选池极小（精确子文件夹 < LRU_SIZE）时退化成全量随机，不死循环
4. pick_gallery_images 一次选多张不重复 + 跨次 LRU 去重
5. reset_recent_history 能清空记录

运行：venv_core\\scripts\\python.exe tests\\scripts\\qq\\verify_meme_dedup.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from clients.bots.qq import media_tags  # noqa: E402
from clients.bots.qq.media_tags import (  # noqa: E402
    _MEME_LRU_SIZE,
    pick_gallery_images,
    pick_meme_image,
    reset_recent_history,
)

_passed = 0


def _ok(msg: str):
    global _passed
    _passed += 1
    print(f"[PASS] {msg}")


def _fail(msg: str):
    print(f"[FAIL] {msg}")
    sys.exit(1)


# ---------- 测试 1：连续随机选图，最近 LRU_SIZE 次内不重复 ----------
reset_recent_history()
draws: list[str] = []
for _ in range(_MEME_LRU_SIZE + 5):
    p = pick_meme_image("random")
    if p is None:
        _fail("random 选图返回 None，目录可能为空")
    draws.append(str(p))

# 检查任意连续 _MEME_LRU_SIZE 张内没有重复
for i in range(len(draws)):
    window = draws[i : i + _MEME_LRU_SIZE]
    if len(set(window)) != len(window):
        _fail(f"LRU 窗口内出现重复: index={i}, window={window}")
_ok(f"random 连续 {len(draws)} 次，LRU 窗口内无重复")


# ---------- 测试 2：不同 category 共享 LRU ----------
reset_recent_history()
first = pick_meme_image("anime")
if first is None:
    _fail("anime 选图返回 None")
# 再连发 anime，应避开 first
for _ in range(_MEME_LRU_SIZE):
    p = pick_meme_image("anime")
    if p is not None and str(p) == str(first):
        _fail(f"anime LRU 内重复选到 {first}")
_ok("anime 连续选图 LRU 内不重复 first")


# ---------- 测试 3：候选池极小，退化成全量随机不死循环 ----------
reset_recent_history()
# 找一个很小的子文件夹（中指通常只有几张）
small_cat = None
for sub in (media_tags.MEMES_SENSITIVE_ROOT / "anime").iterdir():
    if sub.is_dir():
        files = [f for f in sub.iterdir() if f.suffix.lower() in (".gif", ".jpg", ".jpeg", ".png")]
        if 0 < len(files) < _MEME_LRU_SIZE:
            small_cat = f"anime/{sub.name}"
            small_count = len(files)
            break

if small_cat is None:
    print(f"[SKIP] 未找到 < {_MEME_LRU_SIZE} 张的小子文件夹，跳过退化测试")
else:
    # 连续调用远超候选数的次数，必须不抛异常
    seen = set()
    for _ in range(small_count * 3 + 5):
        p = pick_meme_image(small_cat)
        if p is None:
            _fail(f"{small_cat} 选图返回 None")
        seen.add(str(p))
    # 候选全用过说明退化正常
    if len(seen) < small_count:
        _fail(f"{small_cat} 只覆盖 {len(seen)}/{small_count} 张，退化异常")
    _ok(f"{small_cat} 候选池({small_count}张) 小于 LRU，退化为全量随机不死循环")


# ---------- 测试 4：pick_gallery_images 一次选多张不重复 + 跨次 LRU ----------
reset_recent_history()
batch = pick_gallery_images(3)
if len(batch) != 3 or len(set(str(p) for p in batch)) != 3:
    _fail(f"一次选 3 张有重复: {batch}")
_ok("pick_gallery_images(3) 一次返回 3 张不重复")

# 下一批应尽量避开上一批
batch2 = pick_gallery_images(3)
overlap = set(str(p) for p in batch) & set(str(p) for p in batch2)
# 私藏图库若 > 6 张则不应有重叠
all_imgs = media_tags._list_images(media_tags.IMAGE_ROOT)
if len(all_imgs) > 6 and overlap:
    _fail(f"连续两批重叠: {[Path(p).name for p in overlap]}")
_ok("pick_gallery_images 连续两批 LRU 去重生效")


# ---------- 测试 5：reset_recent_history 清空 ----------
reset_recent_history()
if len(media_tags._recent_meme_paths) != 0:
    _fail(f"reset 后 meme LRU 非空: {list(media_tags._recent_meme_paths)}")
if len(media_tags._recent_img_paths) != 0:
    _fail(f"reset 后 img LRU 非空: {list(media_tags._recent_img_paths)}")
# 填充后再 reset，验证能完全清空
for _ in range(3):
    pick_meme_image("random")
pick_gallery_images(2)
if len(media_tags._recent_meme_paths) != 3 or len(media_tags._recent_img_paths) != 2:
    _fail("填充后 LRU 长度异常")
reset_recent_history()
if len(media_tags._recent_meme_paths) != 0 or len(media_tags._recent_img_paths) != 0:
    _fail("填充后 reset 未能清空 LRU")
_ok("reset_recent_history 清空 meme + img LRU（含填充后场景）")


# ---------- 测试 6：不存在的分类 fallback 到 random ----------
reset_recent_history()
# LLM 幻觉的不存在分类应 fallback 到全随机，不返回 None
for cat in ("anime/白眼", "不存在的分类", "reality/假分类", "幻觉"):
    p = pick_meme_image(cat)
    if p is None:
        _fail(f"分类 {cat!r} fallback 失败，返回 None")
    elif not p.exists():
        _fail(f"分类 {cat!r} fallback 返回不存在的文件: {p}")
_ok("不存在分类（anime/白眼 等）fallback 到 random，不返回 None")


print(f"\n全部 {_passed} 项验证通过")
