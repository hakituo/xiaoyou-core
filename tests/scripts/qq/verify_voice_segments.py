"""验证 [VOICE] 标签的段感知分段机制（extract_media_segments）。

验证点：
1. 末尾 [VOICE]：文字段[VOICE] → 单段 voice=True
2. 中间 [VOICE]：文字A[VOICE]文字B → seg1 voice=True, seg2 voice=False
3. [VOICE:xxx] 带语音ID：文字段[VOICE:custom] → voice=True, voice_id="custom"
4. 混合 [MEME] + [VOICE]：文字A[MEME]文字B[VOICE] → seg1 meme, seg2 voice
5. 全角括号：文字段［VOICE］ → voice=True
6. 全角冒号：文字段［VOICE：id］ → voice=True, voice_id="id"
7. 无标签：纯文本 → voice=False
8. 向后兼容：extract_media_tags 剥离 [VOICE] 后的 cleaned 不含标签
9. voice_tag_hit 汇总：any(seg.voice)
10. 用户场景：被你吵醒了...我继续睡去了 [VOICE] → 单段语音

运行：venv_core\\scripts\\python.exe tests\\scripts\\qq\\verify_voice_segments.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from clients.bots.qq.media_tags import (  # noqa: E402
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


# ---------- 测试 1：末尾 [VOICE] ----------
segs = extract_media_segments("被你吵醒了...我继续睡去了 [VOICE]")
if len(segs) != 1:
    _fail(f"末尾[VOICE]应得 1 段，实际 {len(segs)}: {segs}")
if segs[0].text != "被你吵醒了...我继续睡去了" or not segs[0].voice:
    _fail(f"段1应为 voice 且文本正确: {segs[0]}")
_ok(f"末尾[VOICE] → 单段语音 (text='{segs[0].text}', voice={segs[0].voice})")

# ---------- 测试 2：中间 [VOICE]，前后都有文字 ----------
segs = extract_media_segments("今天天气不错。\n被你吵醒了...我继续睡去了 [VOICE]\n你也早点睡吧。")
if len(segs) != 2:
    _fail(f"中间[VOICE]应得 2 段，实际 {len(segs)}: {segs}")
if segs[0].text != "今天天气不错。\n被你吵醒了...我继续睡去了" or not segs[0].voice:
    _fail(f"段1应为 voice: {segs[0]}")
if segs[1].text != "你也早点睡吧。" or segs[1].voice:
    _fail(f"段2应为 text: {segs[1]}")
_ok(f"中间[VOICE] → seg1 voice='{segs[0].text[:10]}...', seg2 text='{segs[1].text}'")

# ---------- 测试 3：[VOICE:xxx] 带语音ID ----------
segs = extract_media_segments("晚安 [VOICE:gentle_voice]")
if len(segs) != 1:
    _fail(f"[VOICE:xxx] 应得 1 段，实际 {len(segs)}: {segs}")
if not segs[0].voice or segs[0].voice_id != "gentle_voice":
    _fail(f"段1 voice_id 应为 'gentle_voice': {segs[0]}")
_ok(f"[VOICE:xxx] → voice=True, voice_id='{segs[0].voice_id}'")

# ---------- 测试 4：混合 [MEME] + [VOICE] ----------
segs = extract_media_segments("看这个 [MEME] 哈哈 [VOICE]")
# 标签位置：[MEME] 在 "看这个 " 后，[VOICE] 在 " 哈哈 " 后
if len(segs) != 2:
    _fail(f"混合标签应得 2 段，实际 {len(segs)}: {segs}")
if segs[0].meme_categories != ["random"] or segs[0].voice:
    _fail(f"段1应为 meme 非 voice: {segs[0]}")
if not segs[1].voice or segs[1].meme_categories:
    _fail(f"段2应为 voice 非 meme: {segs[1]}")
_ok("混合 [MEME]+[VOICE] → seg1 meme, seg2 voice")

# ---------- 测试 5：全角括号 ----------
segs = extract_media_segments("晚安 ［VOICE］")
if len(segs) != 1 or not segs[0].voice:
    _fail(f"全角括号[VOICE]应识别为 voice: {segs}")
_ok("全角括号 ［VOICE］ → voice=True")

# ---------- 测试 6：全角冒号带ID ----------
segs = extract_media_segments("晚安 ［VOICE：soft］")
if len(segs) != 1 or not segs[0].voice or segs[0].voice_id != "soft":
    _fail(f"全角冒号[VOICE：soft]应 voice_id='soft': {segs}")
_ok(f"全角冒号 ［VOICE：soft］ → voice_id='{segs[0].voice_id}'")

# ---------- 测试 7：无标签 ----------
segs = extract_media_segments("纯文字回复没有标签")
if len(segs) != 1 or segs[0].voice:
    _fail(f"无标签应为 text 非 voice: {segs}")
_ok("无标签 → voice=False")

# ---------- 测试 8：向后兼容 extract_media_tags 剥离 [VOICE] ----------
cleaned, meme_cats, img_count, bm_count = extract_media_tags("文字A[VOICE]文字B")
if "[VOICE]" in cleaned or "VOICE" in cleaned:
    _fail(f"extract_media_tags 应剥离 [VOICE]，cleaned='{cleaned}'")
if "文字A" not in cleaned or "文字B" not in cleaned:
    _fail(f"extract_media_tags 应保留文字: '{cleaned}'")
_ok(f"向后兼容 extract_media_tags 剥离 [VOICE] → cleaned='{cleaned}'")

# ---------- 测试 9：voice_tag_hit 汇总 ----------
segs = extract_media_segments("文字A[VOICE]文字B")
voice_tag_hit = any(seg.voice for seg in segs)
if not voice_tag_hit:
    _fail(f"voice_tag_hit 应为 True: {segs}")
segs_no_voice = extract_media_segments("纯文字")
voice_tag_hit_2 = any(seg.voice for seg in segs_no_voice)
if voice_tag_hit_2:
    _fail(f"无 voice 时 voice_tag_hit 应为 False: {segs_no_voice}")
_ok("voice_tag_hit 汇总 → 有voice=True, 无voice=False")

# ---------- 测试 10：用户场景（Active Care 历史消息） ----------
user_msg = "好啦，陪你聊这么久我得回去继续睡了...你也别熬太晚。晚安。 [VOICE]"
segs = extract_media_segments(user_msg)
if len(segs) != 1 or not segs[0].voice:
    _fail(f"用户场景应单段 voice: {segs}")
expected_text = "好啦，陪你聊这么久我得回去继续睡了...你也别熬太晚。晚安。"
if segs[0].text != expected_text:
    _fail(f"文字剥离不正确: 期望 '{expected_text}', 实际 '{segs[0].text}'")
_ok(f"用户场景 → 单段语音, text 长度={len(segs[0].text)}")

# ---------- 测试 11：多句混合，[VOICE] 在中间 ----------
# [VOICE] 标签标记它前面的文本段为语音，后面的文本段为文字
multi = "第一句文字\n第二句语音 [VOICE]\n第三句文字"
segs = extract_media_segments(multi)
if len(segs) != 2:
    _fail(f"多句混合应得 2 段，实际 {len(segs)}: {segs}")
if not segs[0].voice:
    _fail(f"段1应为 voice（[VOICE] 标记前面的文本）: {segs[0]}")
if segs[1].voice:
    _fail(f"段2应为 text（[VOICE] 之后的文本）: {segs[1]}")
if "第三句文字" != segs[1].text:
    _fail(f"段2文本应为 '第三句文字': {segs[1]}")
_ok("多句混合 → seg1 voice, seg2 text (只发前段语音)")

print(f"\n全部通过，共 {_passed} 项验证。")
