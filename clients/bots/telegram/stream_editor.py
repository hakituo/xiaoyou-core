"""Telegram 流式增量编辑（Stream Edit）Mixin。

把 LLM 的流式 chunk 边收边编辑到同一条 Telegram 消息上（而非等 response_done
才一次性发送），并附带"正在输入"状态与 429 退避节流。

本 Mixin 依赖主类 TelegramSession 提供：
- self.adapter（含 application / edit_text_message / send_text_to_chat 等）
- self.session_id
- 多个 _stream_edit_* 状态字段（在 TelegramSession.__init__ 初始化）
- 文本清洗函数 _strip_think_tags / _strip_ai_timestamp / _normalize_newlines
  （来自 clients.bots.telegram.split_utils）
"""
import asyncio
import time

from clients.bots.telegram.settings import (
    TG_STREAM_EDIT_BACKOFF_MAX_SECONDS,
    TG_STREAM_EDIT_BACKOFF_MULTIPLIER,
    TG_STREAM_EDIT_ENABLED,
    TG_STREAM_EDIT_INTERVAL_SECONDS,
    TG_STREAM_EDIT_MAX_LEN,
    TG_STREAM_EDIT_TYPING_ACTION,
    logger,
)


class StreamEditMixin:
    """流式增量编辑相关逻辑，注入到 TelegramSession。"""

    # ===== 流式增量编辑核心逻辑 =====

    async def _on_stream_chunk(self, content: str):
        """收到一个流式 chunk：增量编辑同一条 Telegram 消息。

        策略：
        - 首个 chunk：立即创建一条新消息（让用户尽快看到回复开始）
        - 后续 chunk：累积到 buffer，按 TG_STREAM_EDIT_INTERVAL_SECONDS 节流编辑
        - 超过 TG_STREAM_EDIT_MAX_LEN：停止编辑，标记溢出，等 done 后断句发送剩余部分
        - 主动关怀消息（is_proactive）不走流式编辑，保持原有一次性发送
        """
        if not TG_STREAM_EDIT_ENABLED:
            return  # 流式编辑未开启，只累积不编辑（由 _on_stream_done 统一发送）

        # 已经溢出，不再编辑
        if self._stream_edit_overflowed:
            return

        # 首个 chunk：立即创建消息
        if self._stream_edit_msg_id is None:
            # 先把已有 buffer（如果有）和本次 content 合并
            first_text = self._stream_edit_buffer + content
            from clients.bots.telegram.split_utils import _strip_think_tags, _strip_ai_timestamp, _normalize_newlines
            first_text = _strip_think_tags(first_text)
            first_text = _strip_ai_timestamp(first_text)
            first_text = _normalize_newlines(first_text)
            if not first_text:
                return
            # 超长检查
            if len(first_text) > TG_STREAM_EDIT_MAX_LEN:
                self._stream_edit_overflowed = True
                return
            msg = await self._adapter_send_stream_message(first_text)
            if msg is None:
                # 发送失败，放弃流式编辑，等 done 一次性发
                self._stream_edit_overflowed = True
                return
            self._stream_edit_msg_id = msg.message_id
            self._stream_edit_text = first_text
            self._stream_edit_buffer = ""
            self._stream_edit_first_sent = True
            self._stream_edit_last_ts = time.time()
            # 重置动态间隔（新对话开始时恢复默认值）
            self._stream_edit_interval = TG_STREAM_EDIT_INTERVAL_SECONDS
            logger.info(f"[{self.session_id}] 流式编辑：首条消息已发送 (msg_id={msg.message_id}, {len(first_text)}字)")
            # 启动"正在输入"状态循环（让用户持续看到 AI 在打字）
            self._start_typing_action_loop()
            return

        # 后续 chunk：追加到 buffer，节流编辑
        self._stream_edit_buffer += content

        # 超长检查：如果合并后超过限制，停止编辑
        total_len = len(self._stream_edit_text) + len(self._stream_edit_buffer)
        if total_len > TG_STREAM_EDIT_MAX_LEN:
            self._stream_edit_overflowed = True
            logger.info(f"[{self.session_id}] 流式编辑：超过 {TG_STREAM_EDIT_MAX_LEN} 字，停止编辑，等 done 后断句发送")
            return

        # 节流：距离上次编辑不足动态间隔则跳过（等定时任务或 done 时刷新）
        now = time.time()
        elapsed = now - self._stream_edit_last_ts
        if elapsed >= self._stream_edit_interval:
            await self._stream_edit_flush()
        else:
            # 调度一个定时刷新
            self._schedule_stream_edit_flush()

    def _schedule_stream_edit_flush(self):
        """调度一个延迟刷新任务（如果还没调度的话）。"""
        if self._stream_edit_task is not None and not self._stream_edit_task.done():
            return
        delay = self._stream_edit_interval - (time.time() - self._stream_edit_last_ts)
        if delay <= 0:
            delay = 0.1
        self._stream_edit_task = asyncio.create_task(self._stream_edit_flush_delayed(delay))

    async def _stream_edit_flush_delayed(self, delay: float):
        """延迟后执行刷新。"""
        try:
            await asyncio.sleep(delay)
            await self._stream_edit_flush()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"[{self.session_id}] 流式编辑定时刷新异常: {e}")

    async def _stream_edit_flush(self):
        """把 buffer 里的文本编辑到当前流式消息上。"""
        if self._stream_edit_msg_id is None:
            return
        if not self._stream_edit_buffer:
            return

        new_text = self._stream_edit_text + self._stream_edit_buffer
        from clients.bots.telegram.split_utils import _strip_think_tags, _strip_ai_timestamp, _normalize_newlines
        new_text = _strip_think_tags(new_text)
        new_text = _strip_ai_timestamp(new_text)
        new_text = _normalize_newlines(new_text)
        if not new_text or new_text == self._stream_edit_text:
            self._stream_edit_buffer = ""
            return

        try:
            await self.adapter.edit_text_message(
                self.session_id, self._stream_edit_msg_id, new_text
            )
            self._stream_edit_text = new_text
            self._stream_edit_buffer = ""
            self._stream_edit_last_ts = time.time()
            # 编辑成功，缓慢恢复间隔（向默认值靠拢）
            if self._stream_edit_interval > TG_STREAM_EDIT_INTERVAL_SECONDS:
                self._stream_edit_interval = max(
                    TG_STREAM_EDIT_INTERVAL_SECONDS,
                    self._stream_edit_interval * 0.9,
                )
        except Exception as e:
            err_str = str(e)
            self._stream_edit_last_ts = time.time()
            # 检测 429 Too Many Requests，自动拉长间隔
            if "429" in err_str or "Too Many Requests" in err_str or "Flood" in err_str:
                new_interval = min(
                    self._stream_edit_interval * TG_STREAM_EDIT_BACKOFF_MULTIPLIER,
                    TG_STREAM_EDIT_BACKOFF_MAX_SECONDS,
                )
                if new_interval != self._stream_edit_interval:
                    logger.info(
                        f"[{self.session_id}] 流式编辑触发 429 退避："
                        f"{self._stream_edit_interval:.1f}s → {new_interval:.1f}s"
                    )
                    self._stream_edit_interval = new_interval
                # 429 时不丢数据，保留 buffer 等下次刷新
            else:
                logger.debug(f"[{self.session_id}] 流式编辑刷新失败（可忽略）: {e}")
                # 其他错误也不丢数据，保留 buffer

    def _sanitize_stream_text(self, text: str) -> str:
        """对流式编辑中的文本做轻量清洗（不做断句和媒体标签处理，那些留到 done）。

        只做：
        - 剥离 think 标签
        - 剥离 AI 时间戳前缀
        - 规范化字面 \\n
        """
        from clients.bots.telegram.split_utils import _strip_think_tags, _strip_ai_timestamp, _normalize_newlines
        text = _strip_think_tags(text)
        text = _strip_ai_timestamp(text)
        text = _normalize_newlines(text)
        return text

    def _start_typing_action_loop(self):
        """启动"正在输入"状态循环，每 4 秒发送一次 typing 状态。

        Telegram 的 typing 状态只持续 5 秒，所以每 4 秒刷新一次。
        这让用户在流式编辑期间持续看到"正在输入..."提示，增强打字感。
        """
        if not TG_STREAM_EDIT_TYPING_ACTION:
            return
        if self._stream_edit_typing_task is not None and not self._stream_edit_typing_task.done():
            return  # 已经在运行
        self._stream_edit_typing_task = asyncio.create_task(self._typing_action_loop())

    async def _typing_action_loop(self):
        """持续发送 typing 状态，直到被取消。"""
        try:
            from telegram.constants import ChatAction
            while True:
                if self._stream_edit_msg_id is None:
                    break
                try:
                    raw = str(self.session_id)
                    if raw.startswith("tg_"):
                        raw = raw[3:]
                    try:
                        chat_id = int(raw)
                    except ValueError:
                        chat_id = self.session_id
                    if self.adapter.application and self.adapter.application.bot:
                        await self.adapter.application.bot.send_chat_action(
                            chat_id=chat_id, action=ChatAction.TYPING
                        )
                except Exception:
                    pass  # typing 失败不影响流式
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _adapter_send_stream_message(self, text: str):
        """发送流式编辑的第一条消息，返回 Message 对象或 None。"""
        if not self.adapter.application or not self.adapter.application.bot:
            return None
        raw = str(self.session_id)
        if raw.startswith("tg_"):
            raw = raw[3:]
        try:
            chat_id = int(raw)
        except ValueError:
            chat_id = self.session_id

        from clients.bots.telegram.markdown_utils import markdown_to_telegram_html, strip_markdown
        from clients.bots.telegram.settings import STRIP_MARKDOWN as _STRIP_MD

        try:
            if _STRIP_MD:
                msg = await self.adapter.application.bot.send_message(
                    chat_id=chat_id, text=strip_markdown(text),
                )
            else:
                html_text, parse_mode = markdown_to_telegram_html(text)
                msg = await self.adapter.application.bot.send_message(
                    chat_id=chat_id, text=html_text,
                    parse_mode=parse_mode, disable_web_page_preview=True,
                )
            return msg
        except Exception as e:
            logger.warning(f"[{self.session_id}] 流式编辑首条消息发送失败: {e}")
            return None

    async def _on_stream_done(self, full_response: str, *, is_proactive: bool = False):
        """流式结束：处理最终文本发送（含断句、媒体标签）。

        三种情况：
        1. 有流式编辑消息且未溢出：把剩余 buffer 刷上去，然后对"超出已发送部分"
           的内容做断句发送（如果完整回复比单条消息长）
        2. 有流式编辑消息但已溢出：重置编辑状态，对完整回复做断句发送
        3. 没有流式编辑消息（未开启/首个 chunk 就超长/主动关怀）：直接断句发送完整回复
        """
        try:
            # 主动关怀消息不走流式编辑，直接一次性发送
            if is_proactive:
                await self._reset_stream_edit()
                if full_response:
                    await self._send_full_response_with_split(
                        full_response, is_proactive=True
                    )
                return

            # 没有流式编辑消息：直接断句发送完整回复
            if self._stream_edit_msg_id is None:
                await self._reset_stream_edit()
                if full_response:
                    await self._send_full_response_with_split(
                        full_response, is_proactive=is_proactive
                    )
                else:
                    logger.warning(f"[{self.session_id}] response_done 到达但 full_response 为空")
                return

            # 有流式编辑消息：先刷新剩余 buffer
            if self._stream_edit_buffer:
                await self._stream_edit_flush()

            # 取消可能挂起的定时刷新
            if self._stream_edit_task is not None and not self._stream_edit_task.done():
                self._stream_edit_task.cancel()
                try:
                    await self._stream_edit_task
                except BaseException:
                    pass
                self._stream_edit_task = None

            # 已溢出或完整回复没有被编辑到消息里：重置后断句发送完整回复
            if self._stream_edit_overflowed or not self._stream_edit_text:
                await self._reset_stream_edit()
                if full_response:
                    await self._send_full_response_with_split(
                        full_response, is_proactive=is_proactive
                    )
                return

            # 正常情况：流式编辑消息已包含部分文本
            # 如果完整回复和已编辑文本一致，无需额外发送
            sanitized_full = self._sanitize_stream_text(full_response)
            if sanitized_full == self._stream_edit_text:
                # 完整回复已全部编辑到消息里，无需额外发送
                # 但仍需处理媒体标签（[MEME] 等）
                await self._process_media_tags_only(sanitized_full, is_proactive=is_proactive)
                await self._reset_stream_edit()
                return

            # 完整回复比已编辑部分长：发送剩余部分
            # 已编辑部分就是 sanitized_full 的前缀（大致），取尾部差异
            remaining = self._compute_remaining_text(self._stream_edit_text, sanitized_full)
            if remaining and remaining.strip():
                await self._send_remaining_after_stream_edit(
                    remaining, is_proactive=is_proactive
                )
            else:
                # 没有剩余文本，处理媒体标签即可
                await self._process_media_tags_only(sanitized_full, is_proactive=is_proactive)

            await self._reset_stream_edit()
        except Exception as e:
            logger.error(f"[{self.session_id}] _on_stream_done 异常: {e}", exc_info=True)
            await self._reset_stream_edit()
            # 异常时兜底：直接断句发送完整回复
            if full_response:
                try:
                    await self._send_full_response_with_split(
                        full_response, is_proactive=is_proactive
                    )
                except Exception:
                    pass

    def _compute_remaining_text(self, edited_text: str, full_text: str) -> str:
        """计算完整回复中，尚未编辑到消息里的剩余部分。

        edited_text 通常是 full_text 的前缀（流式编辑是追加的），
        但由于 sanitize 可能略有差异，用前缀匹配取尾部。
        """
        if not edited_text or not full_text:
            return full_text
        if full_text.startswith(edited_text):
            return full_text[len(edited_text):]
        # 尝试反向：edited 可能比 full 长（done 时清理了 think 标签）
        if edited_text.startswith(full_text):
            return ""
        # 模糊匹配：取 edited 最后一个字符在 full 中的位置
        if len(edited_text) > 0:
            last_char = edited_text[-1]
            idx = full_text.rfind(last_char)
            if idx >= 0 and idx + 1 < len(full_text):
                candidate = full_text[:idx + 1]
                if edited_text.endswith(candidate[-20:]) if len(candidate) >= 20 else edited_text.endswith(candidate):
                    return full_text[idx + 1:]
        return ""

    async def _send_remaining_after_stream_edit(self, remaining: str, *, is_proactive: bool = False):
        """流式编辑消息已发送了前半部分，发送剩余部分（带断句和媒体标签）。"""
        # 夜间静音检查
        silent = False
        if is_proactive:
            hour = time.localtime().tm_hour
            if hour >= 22 or hour < 8:
                silent = True

        remaining = remaining.strip()
        if not remaining:
            return

        # 尝试提取媒体标签分段
        try:
            from clients.bots.qq.media_tags import extract_media_segments
            segments = extract_media_segments(remaining)
        except Exception:
            segments = None

        if not segments or (
            len(segments) == 1
            and not segments[0].meme_categories
            and not segments[0].img_count
            and not segments[0].bm_count
            and not segments[0].voice
            and not segments[0].video_count
        ):
            await self._send_text_with_split(remaining, disable_notification=silent)
            return

        # 有标签：分段发送
        for seg in segments:
            if seg.text:
                if seg.voice:
                    voice_ok = False
                    try:
                        voice_ok = await self.adapter._send_voice_response(
                            self.session_id, seg.text, seg.voice_id or None
                        )
                    except Exception:
                        pass
                    if not voice_ok:
                        await self._send_text_with_split(seg.text, disable_notification=silent)
                else:
                    await self._send_text_with_split(seg.text, disable_notification=silent)
            if seg.meme_categories or seg.img_count or seg.bm_count or seg.video_count:
                try:
                    await self.adapter._send_media_tags(
                        self.session_id,
                        seg.meme_categories, seg.img_count, seg.bm_count,
                        video_count=seg.video_count,
                        disable_notification=silent,
                    )
                except Exception as e:
                    logger.error(f"[{self.session_id}] 剩余媒体标签发送失败: {e}")

    async def _process_media_tags_only(self, full_text: str, *, is_proactive: bool = False):
        """流式编辑消息已包含全部文本，只处理媒体标签（[MEME]/[IMG] 等）的图片发送。"""
        silent = False
        if is_proactive:
            hour = time.localtime().tm_hour
            if hour >= 22 or hour < 8:
                silent = True
        try:
            from clients.bots.qq.media_tags import extract_media_segments
            segments = extract_media_segments(full_text)
        except Exception:
            return
        if not segments:
            return
        for seg in segments:
            if seg.meme_categories or seg.img_count or seg.bm_count or seg.video_count:
                try:
                    await self.adapter._send_media_tags(
                        self.session_id,
                        seg.meme_categories, seg.img_count, seg.bm_count,
                        video_count=seg.video_count,
                        disable_notification=silent,
                    )
                except Exception as e:
                    logger.error(f"[{self.session_id}] 媒体标签发送失败: {e}")

    async def _reset_stream_edit(self):
        """重置流式编辑状态，准备下一次对话。"""
        # 取消挂起的定时刷新任务
        if self._stream_edit_task is not None and not self._stream_edit_task.done():
            self._stream_edit_task.cancel()
            try:
                await self._stream_edit_task
            except BaseException:
                pass
        # 取消"正在输入"状态循环
        if self._stream_edit_typing_task is not None and not self._stream_edit_typing_task.done():
            self._stream_edit_typing_task.cancel()
            try:
                await self._stream_edit_typing_task
            except BaseException:
                pass
        self._stream_edit_msg_id = None
        self._stream_edit_text = ""
        self._stream_edit_buffer = ""
        self._stream_edit_last_ts = 0.0
        self._stream_edit_task = None
        self._stream_edit_typing_task = None
        self._stream_edit_first_sent = False
        self._stream_edit_overflowed = False
        # 恢复默认节流间隔
        self._stream_edit_interval = TG_STREAM_EDIT_INTERVAL_SECONDS
