"""Telegram 最终回复发送（Response Sender）Mixin。

负责把完整 LLM 回复（或流式剩余部分）做断句、媒体标签分段、Telegram 专属标签
（[WEBM]/[DICE]）发送。包括：

- _send_full_response_with_split：完整回复分段发送（文字 + 图/视频 + webm + 骰子）
- _send_text_with_split：纯文本断句发送（含 [WEBM]/[DICE] 剥离）
- _send_in_chunks：超长消息按 4096 字符分片
- _calc_typing_delay：仿生打字延迟

本 Mixin 依赖主类 TelegramSession 提供：
- self.adapter（含 send_text_to_chat / _send_media_tags / send_animation_path_to_chat / _send_dice_emoji 等）
- self.session_id
- _reset_stream_edit / _process_media_tags_only 等方法（来自 StreamEditMixin）
- _split_message_for_tg（来自 clients.bots.telegram.split_utils）
"""
import asyncio
import random
import time

from clients.bots.telegram.settings import (
    TG_MESSAGE_MAX_LEN,
    TG_STREAM_LONG_THRESHOLD,
    TG_STREAM_SPLIT,
    TG_TYPING_DELAY_MAX_SECONDS,
    TG_TYPING_DELAY_MIN_SECONDS,
    TG_TYPING_DELAY_PER_CHAR_SECONDS,
    logger,
)


def _calc_typing_delay(sentence: str, *, is_last_chunk: bool = False) -> float:
    """计算打字延迟（模拟仿生回复节奏）。"""
    char_count = len(str(sentence or ""))
    if char_count <= 0:
        return TG_TYPING_DELAY_MIN_SECONDS
    delay = char_count * TG_TYPING_DELAY_PER_CHAR_SECONDS
    delay = max(TG_TYPING_DELAY_MIN_SECONDS, min(delay, TG_TYPING_DELAY_MAX_SECONDS))
    # 随机化
    delay *= random.uniform(0.9, 1.2)
    return round(delay, 2)


class ResponseSenderMixin:
    """完整回复发送相关逻辑，注入到 TelegramSession。"""

    async def _send_full_response_with_split(self, full_response: str,
                                             *, is_proactive: bool = False):
        """发送完整回复，支持 [MEME]/[IMG]/[BM]/[VOICE] 媒体标签分段发送。

        发送顺序（与 QQ 适配器一致）：
        - 文字段A → 图A → 文字段B → 图B → ...
        - [VOICE] 段改用语音发送（失败回退文字）
        - 无标签时走原断句逻辑

        Args:
            is_proactive: 是否为主动关怀消息。True 时在夜间（22:00-08:00）
                          自动静音发送，不打扰用户。
        """
        from clients.bots.telegram.split_utils import (
            _strip_think_tags, _strip_ai_timestamp, _normalize_newlines,
        )
        full_response = _strip_think_tags(full_response)
        full_response = _strip_ai_timestamp(full_response)
        full_response = _normalize_newlines(full_response)
        if not full_response or not full_response.strip():
            return

        # 主动关怀消息在夜间静音发送（22:00-08:00）
        silent = False
        if is_proactive:
            hour = time.localtime().tm_hour
            if hour >= 22 or hour < 8:
                silent = True
                logger.info(f"[{self.session_id}] 夜间主动关怀消息静音发送 (hour={hour})")

        # 尝试提取媒体标签分段
        segments = None
        try:
            from clients.bots.qq.media_tags import extract_media_segments
            segments = extract_media_segments(full_response)
        except Exception as e:
            logger.debug(f"media_tags 不可用，走纯文本发送: {e}")
            segments = None

        # Telegram 专属标签：从原始文本里提取 [WEBM] 和 [DICE]
        # （这些标签不在 MediaSegment 里，因为 QQ 不支持）
        tg_webm_descs: list[str] = []
        tg_dice_emojis: list[str] = []
        try:
            from clients.bots.telegram.sensitive_media import (
                extract_webm_tags, extract_dice_tags
            )
            tg_webm_descs = extract_webm_tags(full_response)
            tg_dice_emojis = extract_dice_tags(full_response)
        except Exception as e:
            logger.debug(f"sensitive_media 不可用，跳过 [WEBM]/[DICE] 提取: {e}")

        has_tg_only_tags = bool(tg_webm_descs or tg_dice_emojis)

        # 无标签或单段纯文本：走原断句逻辑
        if not segments or (
            len(segments) == 1
            and not segments[0].meme_categories
            and not segments[0].img_count
            and not segments[0].bm_count
            and not segments[0].voice
            and not segments[0].video_count
            and not has_tg_only_tags
        ):
            await self._send_text_with_split(full_response, disable_notification=silent)
            return

        # 有标签：分段发送
        total_segments = len(segments) if segments else 0
        if segments:
            for seg_idx, seg in enumerate(segments):
                # 1. 发送文字段（voice 段走语音，失败回退文字）
                if seg.text:
                    if seg.voice:
                        voice_ok = False
                        try:
                            ref_audio = seg.voice_id or None
                            voice_ok = await self.adapter._send_voice_response(
                                self.session_id, seg.text, ref_audio
                            )
                            if voice_ok:
                                logger.info(
                                    f"[{self.session_id}] [VOICE] 段已发送 "
                                    f"(seg{seg_idx+1}/{total_segments}): '{seg.text[:20]}...'"
                                )
                        except Exception as e:
                            logger.warning(f"[{self.session_id}] [VOICE] 段发送异常，回退文字: {e}")
                        if not voice_ok:
                            logger.info(f"[{self.session_id}] [VOICE] 段回退文字发送")
                            await self._send_text_with_split(seg.text, disable_notification=silent)
                    else:
                        await self._send_text_with_split(seg.text, disable_notification=silent)

                # 2. 段末尾补发该段的图/视频（位置感知发图）
                if seg.meme_categories or seg.img_count or seg.bm_count or seg.video_count:
                    try:
                        await self.adapter._send_media_tags(
                            self.session_id,
                            seg.meme_categories,
                            seg.img_count,
                            seg.bm_count,
                            video_count=seg.video_count,
                            disable_notification=silent,
                        )
                    except Exception as e:
                        logger.error(f"[{self.session_id}] 媒体标签发送失败: {e}")

        # Telegram 专属标签：在所有段发完后发送 [GIF]/[WEBM] 和 [DICE]
        # （这些标签不参与分段，因为 QQ 的 extract_media_segments 不识别它们，
        #   它们会被留在段的 text 里，需要先从 text 里剥离再单独发）
        if tg_webm_descs:
            try:
                from clients.bots.telegram.sensitive_media import pick_webm
                for desc in tg_webm_descs:
                    webm_path = pick_webm(desc)
                    if webm_path is None:
                        logger.warning(f"[{self.session_id}] [GIF:{desc}] 找不到可用动画，跳过")
                        continue
                    await self.adapter.send_animation_path_to_chat(
                        self.session_id, str(webm_path),
                        disable_notification=silent,
                    )
                    logger.info(f"[{self.session_id}] [GIF:{desc}] 已发送: {webm_path.name}")
            except Exception as e:
                logger.warning(f"[{self.session_id}] [GIF] 发送失败: {e}")

        if tg_dice_emojis:
            try:
                for emoji in tg_dice_emojis:
                    await self.adapter._send_dice_emoji(
                        self.session_id, emoji,
                        disable_notification=silent,
                    )
                    logger.info(f"[{self.session_id}] [DICE] 已发送: emoji={emoji}")
            except Exception as e:
                logger.warning(f"[{self.session_id}] [DICE] 发送失败: {e}")

    async def _send_text_with_split(self, text: str, *, disable_notification: bool = False):
        """纯文本断句发送（原 _send_full_response_with_split 的逻辑）。

        Args:
            disable_notification: True=静音发送（夜间主动关怀）
        """
        text = str(text or "").strip()
        if not text:
            return

        # 剥离 Telegram 专属标签（[WEBM] [DICE]），它们由 _send_full_response_with_split 单独处理
        try:
            from clients.bots.telegram.sensitive_media import (
                strip_webm_tags, strip_dice_tags
            )
            text = strip_webm_tags(text)
            text = strip_dice_tags(text)
        except Exception:
            pass
        text = text.strip()
        if not text:
            return

        # 超长消息强制断句
        force_split = len(text) >= TG_STREAM_LONG_THRESHOLD

        if not TG_STREAM_SPLIT and not force_split:
            await self._send_in_chunks(text, disable_notification=disable_notification)
            return

        from clients.bots.telegram.split_utils import _split_message_for_tg
        chunks = _split_message_for_tg(text)
        if not chunks:
            return

        for i, sentence in enumerate(chunks):
            sentence = sentence.strip()
            if not sentence:
                continue
            is_last = (i == len(chunks) - 1)
            await self._send_in_chunks(sentence, disable_notification=disable_notification)
            if not is_last:
                delay = _calc_typing_delay(sentence, is_last_chunk=is_last)
                await asyncio.sleep(delay)

    async def _send_in_chunks(self, text: str, *, disable_notification: bool = False):
        """发送文本，超过 Telegram 4096 字符限制时自动分片。

        Args:
            disable_notification: True=静音发送（夜间主动关怀）
        """
        text = str(text or "").strip()
        if not text:
            return
        if len(text) <= TG_MESSAGE_MAX_LEN:
            await self.adapter.send_text_to_chat(
                self.session_id, text,
                disable_notification=disable_notification,
            )
            return
        # 分片
        for i in range(0, len(text), TG_MESSAGE_MAX_LEN):
            chunk = text[i:i + TG_MESSAGE_MAX_LEN]
            await self.adapter.send_text_to_chat(
                self.session_id, chunk,
                disable_notification=disable_notification,
            )
            if i + TG_MESSAGE_MAX_LEN < len(text):
                await asyncio.sleep(1.2)  # 避免频率限制
