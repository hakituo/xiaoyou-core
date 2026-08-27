"""QQ 会话消息处理。"""
import asyncio
import re
import time
from clients.bots.qq.utils import DEFAULT_QQ_REACTION_DELAY_MAX_SECONDS, extract_leading_reaction_delay, strip_all_reaction_delay_tags
from clients.bots.qq.settings import logger
from clients.bots.qq.media_tags import (
    build_image_cq,
    build_meme_cq,
    extract_media_segments,
    pick_bm_images,
    pick_gallery_images,
    pick_meme_image,
    pick_videos,
)
from clients.bots.qq.utils import (
    _build_cq_video,
    _contains_raw_base64,
    _is_base64_cq_code,
    _split_message_for_qq,
    _strip_base64_from_text,
    _strip_think_for_qq,
    strip_ai_timestamp,
    parse_session_user_id,
)
class SessionMessageHandler:
    """会话消息处理器，负责断句发送、去重、语音标签等。"""

    def __init__(self, session):
        self.session = session

    async def process_stream_buffer(self, buffer: str) -> tuple[str, bool]:
        """处理流式缓冲，发送完整句并返回剩余 buffer。"""
        sent_any = False
        session = self.session

        if not buffer:
            return "", False

        if buffer.startswith('[') and ']' not in buffer:
            return buffer, False

        if buffer.startswith('[') and buffer.endswith(']'):
            if "TRIGGER]" in buffer:
                logger.info(f"[{session.session_id}] Skipping internal trigger message: {buffer}")
                return "", True  # 已消费但未发送
            return buffer, True

        # 使用工具函数进行断句
        # 如果断句被禁用，整段发送
        if session._split_disabled:
            chunks = [buffer]
        else:
            MAX_BUBBLE_LEN = session._cfg.qq_max_bubble_len
            await session._load_bionic_profile()
            comma_split_prob = session._resolve_comma_split_probability()
            chunks = _split_message_for_qq(
                buffer,
                MAX_BUBBLE_LEN,
                comma_split_prob=comma_split_prob,
                min_split_len=session._cfg.qq_min_split_len,
            )

        if not chunks:
            return buffer, False

        # 去重检查：如果最后一条发送的消息和当前要发送的第一条完全一致，
        # 且时间间隔很短（例如 < 5秒），则可能是重复触发，跳过。
        # 注意：这里只做简单去重，防止瞬间双发。

        # 特殊处理：如果 chunks 是因为换行符分隔的（如动作描写和对话）
        # 应该分开处理，先发送前面的 chunks，保留最后一个 chunk 等待更多上下文
        # 但如果最后一个 chunk 有结束标点，也可以发送
        if len(chunks) > 1:
            # 检查是否是因为换行符分隔的
            # 简单判断：如果 chunks 数量 >= 2，且第一个 chunk 没有结束标点
            first_chunk = chunks[0].strip()
            has_end_mark = first_chunk and first_chunk[-1] in ["。", ".", "!", "!", "?", "？", "…"]

            if not has_end_mark:
                # 第一个 chunk 没有结束标点，可能是动作描写
                # 先发送第一个 chunk，保留后面的等待更多上下文
                chunks_to_send = [chunks[0]]
                remaining = "\n".join(chunks[1:])
            else:
                # 第一个 chunk 有结束标点，按正常逻辑处理
                pass  # 继续下面的逻辑

        # 找出最后一个以结束性标点结尾的 chunk
        # 只发送到这个位置，后面的内容保留在 buffer 中
        last_complete_idx = -1
        for i, chunk in enumerate(chunks):
            chunk_stripped = chunk.strip()
            if chunk_stripped and chunk_stripped[-1] in ["。", ".", "!", "!", "?", "？", "…", "\n"]:
                last_complete_idx = i

        # 如果没有找到完整的句子
        if last_complete_idx == -1:
            if len(chunks) > 1:
                # 有多个 chunk 但都没有结束标点
                # 发送除了最后一个之外的所有 chunk
                chunks_to_send = chunks[:-1]
                remaining = chunks[-1] if chunks else ""
            else:
                # 只有一个 chunk 且没有结束标点
                # 但如果这个 chunk 是圆括号包裹的动作描写，也发送
                chunk_stripped = chunks[0].strip() if chunks else ""
                if chunk_stripped.startswith('(') and chunk_stripped.endswith(')'):
                    # 是完整的圆括号动作描写，发送
                    chunks_to_send = chunks
                    remaining = ""
                else:
                    # 保留在 buffer 中，等待更多内容
                    return buffer, False
        else:
            # 发送所有到最后一个完整句子为止的 chunks
            chunks_to_send = chunks[:last_complete_idx + 1]
            remaining = (
                "\n".join(chunks[last_complete_idx + 1:])
                if last_complete_idx + 1 < len(chunks)
                else ""
            )

        for idx, sentence in enumerate(chunks_to_send):
            sentence = sentence.strip()
            if not sentence:
                continue

            if not _is_base64_cq_code(sentence) and _contains_raw_base64(sentence):
                logger.warning(f"[{session.session_id}] 流式chunk含裸base64，剥离: {sentence[:40]}...")
                sentence = _strip_base64_from_text(sentence)
                if not sentence or _contains_raw_base64(sentence):
                    continue

            # 简单去重：检查是否刚发送过完全相同的消息
            # 防止流式重复 chunk 或重新处理 buffer 导致的双发
            now = time.time()
            is_dup = False

            # 对比最近发送的消息
            last_sent_time = session._recent_proactive_messages.get(sentence, 0)
            if (now - last_sent_time) < 2.0:  # 2秒内发送过
                logger.warning(f"[{session.session_id}] Duplicate message suppressed: '{sentence[:20]}...'")
                is_dup = True

            if is_dup:
                continue

            session._recent_proactive_messages[sentence] = now

            char_count = len(sentence)
            final_delay = session._calc_typing_delay(
                sentence,
                allow_surprise_delay=False,
            )

            logger.info(f"[{session.session_id}] Sending chunk: '{sentence[:20]}...' (len={char_count}, delay={final_delay:.2f}s)")
            await session._send_response(sentence)
            await session._smart_sleep(final_delay)
            sent_any = True

        return remaining, sent_any

    async def send_full_response_with_split(
        self,
        full_response: str,
        *,
        enable_surprise_delay: bool = False,
    ):
        """
        发送完整回复，并进行断句。
        用于非流式模式，等后端返回完整回复后一次性断句发送。
        """
        session = self.session
        full_response = _strip_think_for_qq(full_response)
        before_ts_strip = full_response
        full_response = strip_ai_timestamp(full_response)
        if before_ts_strip != full_response:
            logger.info(f"[{session.session_id}] 时间戳剥离: '{before_ts_strip[:60]}' -> '{full_response[:60]}'")
        if not full_response:
            return

        if _contains_raw_base64(full_response):
            logger.warning(f"[{session.session_id}] 检测到回复含裸 base64，尝试剥离 (原始长度={len(full_response)})")
            full_response = _strip_base64_from_text(full_response)
            if not full_response:
                logger.error(f"[{session.session_id}] base64 剥离后回复为空，丢弃")
                return
            if _contains_raw_base64(full_response):
                logger.error(f"[{session.session_id}] base64 剥离后仍含 base64，丢弃")
                return
            logger.info(f"[{session.session_id}] base64 剥离成功 (剩余长度={len(full_response)})")

        # 提取 [VOICE] / [MEME] / [IMG] / [BM] 标签：按位置分段
        # voice 段用语音发送（只发该段），text 段正常断句发文字
        segments = extract_media_segments(full_response)
        # visible_response：所有段文本拼接（去掉时间戳），用于重复检查/纯标签判断
        visible_response = "".join(
            strip_all_reaction_delay_tags(seg.text) for seg in segments
        ).strip()
        # 汇总标签
        all_meme_categories = [cat for seg in segments for cat in seg.meme_categories]
        all_img_count = sum(seg.img_count for seg in segments)
        all_bm_count = sum(seg.bm_count for seg in segments)
        all_video_count = sum(seg.video_count for seg in segments)
        voice_tag_hit = any(seg.voice for seg in segments)
        if not visible_response:
            # 纯标签回复（没有正文）也要把图发出去
            await self.send_media_tags(all_meme_categories, all_img_count, all_bm_count, all_video_count)
            return
        if session._is_duplicate_full_response(visible_response):
            logger.warning(f"[{session.session_id}] Duplicate full response suppressed")
            return

        # 加载会话偏好（voice 段发送和 session_tts 判断都要用）
        qq_user_id = parse_session_user_id(session.session_id)
        prefs = {}
        try:
            cfg_handler = getattr(session.adapter, "config_handler", None)
            if cfg_handler and hasattr(cfg_handler, "get_session_prefs"):
                prefs = await cfg_handler.get_session_prefs(
                    session_id=session.session_id,
                    qq_user_id=qq_user_id,
                )
            elif isinstance(getattr(session.adapter, "_session_prefs", None), dict):
                prefs = session.adapter._session_prefs.get(session.session_id, {}) or {}
            if not isinstance(prefs, dict):
                prefs = {}
        except Exception:
            prefs = {}

        reply_voice_only = bool(prefs.get("reply_voice_only", False))
        session_tts_enabled = bool(prefs.get("session_tts_enabled", False))
        # 整段语音模式：reply_voice_only / session_tts / auto_tts_for_voice_input
        if visible_response and (
            reply_voice_only
            or session_tts_enabled
            or (session._cfg.auto_tts_for_voice_input and getattr(session, "is_voice_input", False))
        ):
            logger.info(
                f"[{session.session_id}] Single-pass response dispatch "
                f"(reply_voice_only={reply_voice_only}, session_tts_enabled={session_tts_enabled})"
            )
            await session._send_response(visible_response, allow_session_tts=not voice_tag_hit)
            await self.send_media_tags(all_meme_categories, all_img_count, all_bm_count, all_video_count)
            return

        # 段感知发送：voice 段发语音（失败回退文字），text 段断句发文字
        sent_any = False
        reaction_delay_max = float(
            getattr(session._cfg, "qq_reaction_delay_max_seconds", DEFAULT_QQ_REACTION_DELAY_MAX_SECONDS)
            or DEFAULT_QQ_REACTION_DELAY_MAX_SECONDS
        )
        total_segments = len(segments)
        seg_idx = 0
        for seg in segments:
            if seg.text:
                voice_sent = False
                if seg.voice:
                    # 该段用语音发送（整段一次性，不断句）
                    try:
                        reference_audio = seg.voice_id or prefs.get("reference_audio")
                        voice_sent = await session.adapter._send_voice_response(
                            session.session_id,
                            seg.text,
                            reference_audio,
                        )
                        if voice_sent:
                            logger.info(
                                f"[{session.session_id}] Voice segment sent "
                                f"(seg{seg_idx+1}/{total_segments}): '{seg.text[:20]}...'"
                            )
                            sent_any = True
                        else:
                            logger.warning(
                                f"[{session.session_id}] [VOICE] 段语音发送失败，回退文字发送"
                            )
                    except Exception as e:
                        logger.warning(
                            f"[{session.session_id}] [VOICE] 段语音发送异常，回退文字发送: {e}"
                        )

                if not voice_sent:
                    # 文字段：断句发送（voice 段回退也走这里）
                    if session._split_disabled:
                        chunks = [seg.text]
                    else:
                        MAX_BUBBLE_LEN = session._cfg.qq_max_bubble_len
                        await session._load_bionic_profile()
                        comma_split_prob = session._resolve_comma_split_probability()
                        chunks = _split_message_for_qq(
                            seg.text,
                            MAX_BUBBLE_LEN,
                            comma_split_prob=comma_split_prob,
                            min_split_len=session._cfg.qq_min_split_len,
                        )
                    chunks = session._compress_repeated_chunks(chunks)

                    for i, sentence in enumerate(chunks):
                        sentence, reaction_delay = extract_leading_reaction_delay(
                            sentence.strip(), max_seconds=reaction_delay_max
                        )
                        if reaction_delay > 0:
                            await session._smart_sleep(reaction_delay)
                        if not sentence:
                            continue
                        char_count = len(sentence)
                        is_last = (seg_idx == total_segments - 1 and i == len(chunks) - 1)
                        final_delay = session._calc_typing_delay(
                            sentence,
                            is_last_chunk=is_last,
                            allow_surprise_delay=(enable_surprise_delay and seg_idx == 0 and i == 0),
                        )

                        logger.info(f"[{session.session_id}] Sending chunk (seg{seg_idx+1}/{total_segments}, {i+1}/{len(chunks)}): '{sentence[:20]}...' (len={char_count}, delay={final_delay:.2f}s)")
                        await session._send_response(sentence, allow_session_tts=not voice_tag_hit)
                        sent_any = True

                        if not is_last:
                            await session._smart_sleep(final_delay)

            # 该段文字发完，立即发该段的图/视频（位置感知发图）
            if seg.meme_categories or seg.img_count or seg.bm_count or seg.video_count:
                await self.send_media_tags(
                    seg.meme_categories, seg.img_count, seg.bm_count, seg.video_count
                )
            seg_idx += 1

    async def send_media_tags(self, meme_categories: list[str], img_count: int,
                               bm_count: int = 0, video_count: int = 0):
        """按 [MEME] / [IMG] / [BM] / [VIDEO] 标签发送媒体（文字全部发完后调用）。

        - 每个 [MEME] 标签发一张对应分类的表情包（普通 CQ:image，保留 PNG 透明背景）；
        - [IMG] 从私藏图库随机选 img_count 张大图；
        - [BM] 从媚黑图库随机选 bm_count 张大图；
        - [VIDEO] 从视频库随机选 video_count 个视频（CQ:video）；
        - 发送失败只记日志，不影响主流程。
        """
        session = self.session
        if not meme_categories and not img_count and not bm_count and not video_count:
            return

        cq_codes: list[str] = []
        for category in meme_categories:
            meme_path = pick_meme_image(category)
            if meme_path is None:
                logger.warning(f"[{session.session_id}] [MEME:{category}] 找不到可用表情包，跳过")
                continue
            cq_codes.append(build_meme_cq(meme_path))
            logger.info(f"[{session.session_id}] [MEME:{category}] 选图: {meme_path.name}")

        if img_count:
            gallery = pick_gallery_images(img_count)
            if not gallery:
                logger.warning(f"[{session.session_id}] [IMG] 私藏图库为空，跳过")
            for img_path in gallery:
                cq_codes.append(build_image_cq(img_path))
                logger.info(f"[{session.session_id}] [IMG] 选图: {img_path.name}")

        if bm_count:
            bm_images = pick_bm_images(bm_count)
            if not bm_images:
                logger.warning(f"[{session.session_id}] [BM] 媚黑图库为空，跳过")
            for img_path in bm_images:
                cq_codes.append(build_image_cq(img_path))
                logger.info(f"[{session.session_id}] [BM] 选图: {img_path.name}")

        if video_count:
            videos = pick_videos(video_count)
            if not videos:
                logger.warning(f"[{session.session_id}] [VIDEO] 视频库为空，跳过")
            for vid_path in videos:
                cq_codes.append(_build_cq_video(str(vid_path)))
                logger.info(f"[{session.session_id}] [VIDEO] 选图: {vid_path.name}")

        for idx, cq in enumerate(cq_codes):
            try:
                await session._send_response(cq, allow_session_tts=False)
            except Exception as e:
                logger.error(f"[{session.session_id}] 媒体标签发送失败: {e}")
            # 多张图/视频之间稍微间隔，避免刷屏触发 NapCat 限流
            if idx < len(cq_codes) - 1:
                await asyncio.sleep(0.3)

    def extract_voice_tag(self, text: str):
        """提取并剥离 [VOICE:xxx] / [VOICE] 标签，返回 (清理后文本, 语音ID, 是否命中)。
        
        同时支持半角方括号 [VOICE] 和全角方括号 ［VOICE］，因为 LLM 可能输出全角括号。
        """
        content = str(text or "")
        voice_id = ""
        voice_tag_hit = False

        # 同时匹配半角 [ 和全角 ［
        matched_with_id = re.search(r"[\[［]VOICE[：:]\s*(.*?)[\]］]", content, flags=re.IGNORECASE)
        if matched_with_id:
            voice_tag_hit = True
            voice_id = str(matched_with_id.group(1) or "").strip()
            content = re.sub(r"[\[［]VOICE[：:]\s*.*?[\]］]", "", content, flags=re.IGNORECASE)

        if re.search(r"[\[［]VOICE[\]］]", content, flags=re.IGNORECASE):
            voice_tag_hit = True
            content = re.sub(r"[\[［]VOICE[\]］]", "", content, flags=re.IGNORECASE)

        # 压缩多余空白，但保留换行符（换行符用于断句分段）
        content = re.sub(r"[^\S\n]{2,}", " ", content)
        content = re.sub(r"\n{3,}", "\n\n", content)
        content = content.strip()
        return content, voice_id, voice_tag_hit
    def is_duplicate_full_response(self, text: str, window_seconds: float = 8.0) -> bool:
        """检测短时间内重复的完整回复。"""
        now = time.time()
        key = "".join(str(text or "").split())
        if not key:
            return False
        if len(key) > 240:
            key = key[:240]
        expired = [
            k
            for k, ts in self.session._recent_outbound_full_responses.items()
            if (now - float(ts)) > max(20.0, window_seconds * 2)
        ]
        for k in expired:
            self.session._recent_outbound_full_responses.pop(k, None)
        last_ts = float(self.session._recent_outbound_full_responses.get(key) or 0.0)
        if last_ts and (now - last_ts) <= window_seconds:
            return True
        self.session._recent_outbound_full_responses[key] = now
        return False

    def compress_repeated_chunks(self, chunks: list[str]) -> list[str]:
        """压缩重复的断句块，避免连续发送相同内容。"""
        cleaned = [str(c).strip() for c in list(chunks or []) if str(c).strip()]
        if len(cleaned) < 4:
            return cleaned
        n = len(cleaned)
        out = []
        i = 0
        while i < n:
            max_k = min((n - i) // 2, 8)
            dup_k = 0
            for k in range(max_k, 2, -1):
                if cleaned[i : i + k] == cleaned[i + k : i + 2 * k]:
                    dup_k = k
                    break
            if dup_k >= 3:
                out.extend(cleaned[i : i + dup_k])
                i += 2 * dup_k
                continue
            out.append(cleaned[i])
            i += 1
        collapsed = []
        recent_idx = {}
        for idx, s in enumerate(out):
            key = "".join(s.split())
            prev = recent_idx.get(key)
            if prev is not None and (idx - prev) <= 6 and len(key) >= 6:
                continue
            recent_idx[key] = idx
            collapsed.append(s)
        return collapsed

    async def send_response(self, content: str, allow_session_tts: bool = True):
        """发送单条回复到 NapCat，并按需触发会话级 TTS。"""
        session = self.session
        if not content:
            return

        if not _is_base64_cq_code(content) and _contains_raw_base64(content):
            logger.warning(f"[{session.session_id}] _send_response 拦截含裸 base64 的消息: {content[:60]}...")
            content = _strip_base64_from_text(content)
            if not content or _contains_raw_base64(content):
                logger.error(f"[{session.session_id}] _send_response base64 剥离失败，丢弃消息")
                return

        await session.adapter.send_to_napcat(session.session_id, content)

        try:
            qq_user_id = parse_session_user_id(session.session_id)

            prefs = {}
            cfg_handler = getattr(session.adapter, "config_handler", None)
            if cfg_handler and hasattr(cfg_handler, "get_session_prefs"):
                prefs = await cfg_handler.get_session_prefs(
                    session_id=session.session_id,
                    qq_user_id=qq_user_id,
                )
            elif isinstance(getattr(session.adapter, "_session_prefs", None), dict):
                prefs = session.adapter._session_prefs.get(session.session_id, {}) or {}
            if not isinstance(prefs, dict):
                prefs = {}
        except Exception as e:
            logger.warning(f"[{session.session_id}] 加载会话偏好失败: {e}")
            prefs = {}

        session_tts_enabled = bool(prefs.get("session_tts_enabled", False))
        session_reply_voice_only = bool(prefs.get("reply_voice_only", False))

        if (
            allow_session_tts
            and not bool(getattr(session.adapter, "reply_voice_only", False))
            and not session_reply_voice_only
            and (
                session_tts_enabled
                or (session._cfg.auto_tts_for_voice_input and getattr(session, "is_voice_input", False))
            )
        ):
            logger.info(f"[{session.session_id}] Session TTS triggered")
            asyncio.create_task(
                session.adapter._send_voice_response(session.session_id, content, prefs.get("reference_audio"))
            )
