"""Telegram 媒体发送 Mixin。

包含所有媒体发送和处理方法：
- 文本消息发送（支持 Markdown → HTML 转换）
- 图片/表情包/动画/视频发送
- 语音消息发送（TTS 生成）
- 骰子/游戏表情发送
- 正在输入指示器
- 媒体标签批量发送（[MEME]/[IMG]/[BM]/[VIDEO]）

本 Mixin 依赖主类 TelegramAdapter 提供以下属性：
- self.application: telegram.ext.Application
- self.strip_markdown: bool
- self.http_client: HttpClient
- self.persona_filename: str
"""
from __future__ import annotations

import base64
import io
import os

from telegram.constants import ChatAction
from telegram.error import TelegramError

from clients.bots.telegram.markdown_utils import (
    markdown_to_telegram_html,
    strip_markdown,
)
from clients.bots.telegram.settings import logger


class MediaSenderMixin:
    """媒体发送 Mixin：提供文本/图片/表情包/动画/视频/语音/骰子等发送能力。"""

    # ===== 输入指示器 =====

    async def _send_typing_action(self, chat_id_str: str):
        """发送"正在输入..."指示器到 Telegram。

        Telegram 的 chat_action 在5秒内有效，超时后自动消失。
        AI 生成回复期间调一次，让用户知道 bot 在处理。
        """
        if not self.application or not self.application.bot:
            return
        raw = str(chat_id_str)
        if raw.startswith("tg_"):
            raw = raw[3:]
        try:
            chat_id = int(raw)
        except ValueError:
            return
        try:
            await self.application.bot.send_chat_action(
                chat_id=chat_id, action=ChatAction.TYPING
            )
        except Exception as e:
            logger.debug(f"send_chat_action 失败（可忽略）: {e}")

    # ===== 骰子/游戏表情 =====

    async def _send_dice(self, chat_id_str: str, emoji: str):
        """发送 Telegram 骰子/游戏表情消息。"""
        if not self.application or not self.application.bot:
            return
        raw = str(chat_id_str)
        if raw.startswith("tg_"):
            raw = raw[3:]
        try:
            chat_id = int(raw)
        except ValueError:
            chat_id = chat_id_str
        try:
            await self.application.bot.send_dice(chat_id=chat_id, emoji=emoji)
            logger.info(f"发骰子到 {chat_id}: {emoji}")
        except TelegramError as e:
            logger.error(f"发骰子失败: {e}")

    async def _send_dice_emoji(self, chat_id_str: str, emoji: str,
                                *, disable_notification: bool = False):
        """发送 Telegram 骰子/游戏表情消息（供 session 的 [DICE] 标签调用）。

        Args:
            emoji: Telegram 骰子 emoji（🎲🎯🎰🏀⚽🎳）
            disable_notification: True=静音发送
        """
        if not self.application or not self.application.bot:
            return
        raw = str(chat_id_str)
        if raw.startswith("tg_"):
            raw = raw[3:]
        try:
            chat_id = int(raw)
        except ValueError:
            chat_id = chat_id_str
        try:
            await self.application.bot.send_dice(
                chat_id=chat_id, emoji=emoji,
                disable_notification=disable_notification,
            )
            logger.info(f"发骰子到 {chat_id}: {emoji} (silent={disable_notification})")
        except TelegramError as e:
            logger.error(f"发骰子失败: {e}")

    # ===== 文本消息发送 =====

    async def send_text_to_chat(self, chat_id_str: str, text: str,
                                reply_markup=None, disable_notification: bool = False):
        """发送文本消息到 Telegram chat。

        支持的格式化语法（转成 Telegram HTML 模式）：
        - **加粗** / __加粗__  -> <b>加粗</b>
        - *斜体* / _斜体_      -> <i>斜体</i>
        - ~~删除线~~           -> <s>删除线</s>
        - `code`               -> <code>code</code>
        - ```lang\ncode```     -> <pre><code class="language-lang">code</code></pre>
        - ||隐藏||             -> <tg-spoiler>隐藏</tg-spoiler>

        Args:
            reply_markup: 可选，InlineKeyboardMarkup 等 Telegram 键盘对象
            disable_notification: True=静音发送（不打扰用户，用于夜间主动关怀）
        """
        if not self.application or not self.application.bot:
            return
        # 去掉 tg_ 前缀（如果有），然后转 int
        raw = str(chat_id_str)
        if raw.startswith("tg_"):
            raw = raw[3:]
        try:
            chat_id = int(raw)
        except ValueError:
            chat_id = chat_id_str

        # 如果 strip_markdown=True（旧默认值），直接清掉所有标记后发纯文本
        if self.strip_markdown:
            text = strip_markdown(text)
            try:
                await self.application.bot.send_message(
                    chat_id=chat_id, text=text,
                    reply_markup=reply_markup,
                    disable_notification=disable_notification,
                )
                logger.debug(f"发送到 {chat_id} (纯文本): {text[:50]}...")
            except TelegramError as e:
                logger.error(f"发送消息失败: {e}")
            return

        # strip_markdown=False：把 LLM 输出的 Markdown 转成 Telegram HTML
        html_text, parse_mode = markdown_to_telegram_html(text)

        try:
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=html_text,
                parse_mode=parse_mode,
                disable_web_page_preview=True,
                reply_markup=reply_markup,
                disable_notification=disable_notification,
            )
            logger.debug(f"发送到 {chat_id} ({parse_mode}): {text[:50]}...")
        except TelegramError as e:
            logger.warning(f"发送 HTML 消息失败，回退纯文本: {e}")
            # 回退：剥离所有标记后纯文本发送
            fallback = strip_markdown(text)
            try:
                await self.application.bot.send_message(
                    chat_id=chat_id, text=fallback,
                    reply_markup=reply_markup,
                    disable_notification=disable_notification,
                )
            except Exception as e2:
                logger.error(f"发送纯文本也失败: {e2}")

    # ===== 流式增量编辑 =====

    async def edit_text_message(self, chat_id_str: str, message_id: int,
                                text: str, *, disable_notification: bool = False):
        """编辑已发送的 Telegram 文本消息（流式增量更新用）。

        把新文本编辑到指定 message_id 上。如果新文本为空或编辑失败（如消息
        未变化、频率限制），静默忽略，不影响流式流程。

        Args:
            chat_id_str: chat id（可能带 tg_ 前缀）
            message_id: 要编辑的消息 ID
            text: 新的完整文本
            disable_notification: 静音编辑（Telegram edit 不支持此参数，保留兼容）
        """
        if not self.application or not self.application.bot:
            return
        raw = str(chat_id_str)
        if raw.startswith("tg_"):
            raw = raw[3:]
        try:
            chat_id = int(raw)
        except ValueError:
            chat_id = chat_id_str

        # strip_markdown=True：纯文本编辑
        if self.strip_markdown:
            text = strip_markdown(text)
            try:
                await self.application.bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id, text=text,
                )
            except TelegramError as e:
                err_str = str(e)
                # "Message is not modified" 是最常见的无害错误（节流时文本没变）
                if "not modified" in err_str.lower():
                    return
                # 429 / Flood 控制：重新抛出，让调用方做退避
                if "429" in err_str or "Too Many Requests" in err_str or "Flood" in err_str:
                    raise
                logger.debug(f"编辑消息失败（可忽略）: {e}")
            return

        # strip_markdown=False：Markdown -> HTML
        html_text, parse_mode = markdown_to_telegram_html(text)
        try:
            await self.application.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text=html_text, parse_mode=parse_mode,
                disable_web_page_preview=True,
            )
        except TelegramError as e:
            # "Message is not modified" 是最常见的无害错误（节流时文本没变）
            err_str = str(e)
            if "not modified" in err_str.lower():
                return
            # 429 / Flood 控制：重新抛出，让调用方做退避
            if "429" in err_str or "Too Many Requests" in err_str or "Flood" in err_str:
                raise
            logger.debug(f"编辑 HTML 消息失败（回退纯文本）: {e}")
            fallback = strip_markdown(text)
            try:
                await self.application.bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id, text=fallback,
                )
            except TelegramError:
                pass

    # ===== 图片发送 =====

    async def send_photo_path_to_chat(self, chat_id_str: str, image_path: str):
        """发送本地图片文件到 Telegram。"""
        if not self.application or not self.application.bot:
            return
        if not os.path.exists(image_path):
            logger.warning(f"图片文件不存在: {image_path}")
            return
        raw = str(chat_id_str)
        if raw.startswith("tg_"):
            raw = raw[3:]
        try:
            chat_id = int(raw)
        except ValueError:
            chat_id = chat_id_str
        try:
            with open(image_path, "rb") as f:
                await self.application.bot.send_photo(chat_id=chat_id, photo=f)
            logger.info(f"发送图片到 {chat_id}: {image_path}")
        except TelegramError as e:
            logger.error(f"发送图片失败: {e}")

    @staticmethod
    def _resize_image_bytes(image_path: str, max_size: int = 240) -> bytes | None:
        """把图片缩小到 max_size×max_size 以内（保持比例），返回 JPEG 字节。

        已弃用：Telegram 的 send_photo 永远显示为大图，缩小像素尺寸不影响
        Telegram 的渲染方式。保留仅为向后兼容。
        失败返回 None，调用方回退到原图。
        """
        try:
            from PIL import Image
        except ImportError:
            return None
        try:
            img = Image.open(image_path)
            if img.mode in ("RGBA", "P", "LA"):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
                img = bg
            else:
                img = img.convert("RGB")
            w, h = img.size
            if max(w, h) > max_size:
                ratio = max_size / max(w, h)
                img = img.resize((max(1, int(w * ratio)), max(1, int(h * ratio))), Image.LANCZOS)
            buf = io.BytesIO()
            buf.name = "meme.jpg"
            img.save(buf, format="JPEG", quality=85)
            return buf.getvalue()
        except Exception as e:
            logger.warning(f"缩小图片失败: {e}，将用原图发送")
            return None

    @staticmethod
    def _image_to_sticker_webp(image_path: str, max_size: int = 512) -> bytes | None:
        """把图片转换成 Telegram 贴纸格式的 WebP 字节。

        Telegram 贴纸要求：
        - 格式：WebP
        - 尺寸：最长边 512px（另一边 ≤ 512）
        - 文件 ≤ 512KB

        转成 512×512 以内的 WebP 后用 send_sticker 发送，Telegram 会以"贴纸"
        形式显示，即小图 + 点击放大，与 QQ 的 subType=1 表情包效果一致。

        失败返回 None，调用方回退到 send_photo。
        """
        try:
            from PIL import Image
        except ImportError:
            logger.warning("Pillow 未安装，无法转换贴纸格式，回退普通图片")
            return None
        try:
            img = Image.open(image_path)
            # 贴纸必须是 PNG（带 alpha）或 RGBA 才能转 WebP 透明背景
            if img.mode not in ("RGBA", "RGB"):
                img = img.convert("RGBA")

            # 等比缩放到最长边 512（只缩不放）
            w, h = img.size
            if max(w, h) > max_size:
                ratio = max_size / max(w, h)
                new_w = max(1, int(w * ratio))
                new_h = max(1, int(h * ratio))
                img = img.resize((new_w, new_h), Image.LANCZOS)

            buf = io.BytesIO()
            buf.name = "meme.webp"
            img.save(buf, format="WEBP", quality=90, method=6)
            data = buf.getvalue()
            if len(data) > 512 * 1024:
                # 太大，降低质量再试
                buf = io.BytesIO()
                img.save(buf, format="WEBP", quality=70, method=6)
                data = buf.getvalue()
            return data
        except Exception as e:
            logger.warning(f"转换贴纸 WebP 失败: {e}，回退普通图片")
            return None

    async def send_meme_path_to_chat(self, chat_id_str: str, image_path: str):
        """发送表情包到 Telegram（模拟 QQ 的 subType=1 小图效果）。

        策略（优先级从高到低）：
        1. 转成 512×512 WebP，用 send_sticker 发送 —— Telegram 会以"贴纸"
           形式显示（小图 + 点击放大），最接近 QQ 表情包效果。
        2. send_sticker 失败 -> send_document 以"文件"形式发送，显示小缩略图。
        3. send_document 也失败 -> send_photo 发原图兜底。
        """
        if not self.application or not self.application.bot:
            return
        if not os.path.exists(image_path):
            logger.warning(f"表情包文件不存在: {image_path}")
            return
        raw = str(chat_id_str)
        if raw.startswith("tg_"):
            raw = raw[3:]
        try:
            chat_id = int(raw)
        except ValueError:
            chat_id = chat_id_str

        # 1. 尝试转成 WebP 贴纸发送
        webp_bytes = self._image_to_sticker_webp(image_path, max_size=512)
        if webp_bytes:
            try:
                buf = io.BytesIO(webp_bytes)
                buf.name = "meme.webp"
                await self.application.bot.send_sticker(chat_id=chat_id, sticker=buf)
                logger.info(
                    f"发表情包贴纸到 {chat_id}: {image_path} "
                    f"(webp {len(webp_bytes)} bytes)"
                )
                return
            except TelegramError as e:
                logger.warning(f"send_sticker 失败，回退 send_document: {e}")
            except Exception as e:
                logger.warning(f"send_sticker 异常，回退 send_document: {e}")

        # 2. 回退：以"文件"形式发送（显示小缩略图，不是大图）
        try:
            with open(image_path, "rb") as f:
                file_bytes = f.read()
            buf = io.BytesIO(file_bytes)
            ext = os.path.splitext(image_path)[1].lower() or ".jpg"
            buf.name = f"meme{ext}"
            await self.application.bot.send_document(
                chat_id=chat_id, document=buf, disable_content_type_detection=True
            )
            logger.info(f"发表情包文件到 {chat_id}: {image_path} (send_document)")
            return
        except TelegramError as e:
            logger.warning(f"send_document 失败，回退 send_photo: {e}")
        except Exception as e:
            logger.warning(f"send_document 异常，回退 send_photo: {e}")

        # 3. 最终兜底：发原图
        try:
            with open(image_path, "rb") as f:
                await self.application.bot.send_photo(chat_id=chat_id, photo=f)
            logger.info(f"发表情包原图到 {chat_id}: {image_path} (兜底 send_photo)")
        except TelegramError as e:
            logger.error(f"发表情包失败 (所有方式都失败): {e}")

    # ===== 动画/视频发送 =====

    async def send_animation_path_to_chat(self, chat_id_str: str, animation_path: str,
                                            *, disable_notification: bool = False):
        """发送动画（webm/GIF）到 Telegram chat。

        Telegram 的 send_animation 会把 webm/GIF 显示为自动播放的动画消息，
        类似 Telegram 原生的 GIF 消息效果。

        Args:
            chat_id_str: chat_id
            animation_path: webm/gif 文件路径
            disable_notification: True=静音发送
        """
        if not self.application or not self.application.bot:
            return
        if not os.path.exists(animation_path):
            logger.warning(f"动画文件不存在: {animation_path}")
            return
        raw = str(chat_id_str)
        if raw.startswith("tg_"):
            raw = raw[3:]
        try:
            chat_id = int(raw)
        except ValueError:
            chat_id = chat_id_str

        try:
            with open(animation_path, "rb") as f:
                file_bytes = f.read()
            buf = io.BytesIO(file_bytes)
            ext = os.path.splitext(animation_path)[1].lower() or ".webm"
            buf.name = f"animation{ext}"
            # 显式用 InputFile 指定 filename，确保 PTB 正确推断 MIME 为 video/webm，
            # 否则 webm 会被 Telegram 当普通文件（document）发出，不自动播放。
            from telegram import InputFile
            input_file = InputFile(buf, filename=buf.name)
            await self.application.bot.send_animation(
                chat_id=chat_id,
                animation=input_file,
                disable_notification=disable_notification,
            )
            logger.info(
                f"发动画到 {chat_id}: {animation_path} "
                f"({len(file_bytes)} bytes, silent={disable_notification})"
            )
        except TelegramError as e:
            err_str = str(e)
            logger.warning(f"send_animation 失败（{err_str}），回退 send_video: {animation_path}")
            # 回退：用 send_video 发送（Telegram 对视频格式更宽容，显示为可播放视频而非文件）
            try:
                with open(animation_path, "rb") as f:
                    vid_buf = io.BytesIO(f.read())
                vid_buf.name = f"video{ext}"
                from telegram import InputFile as _IF
                await self.application.bot.send_video(
                    chat_id=chat_id,
                    video=_IF(vid_buf, filename=vid_buf.name),
                    disable_notification=disable_notification,
                )
                logger.info(f"回退 send_video 成功: {animation_path}")
            except Exception as e2:
                logger.error(f"发动画（webm）失败: {e2}")

    async def send_video_path_to_chat(self, chat_id_str: str, video_path: str,
                                        *, disable_notification: bool = False):
        """发送视频（mp4）到 Telegram chat。

        Telegram 的 send_video 会把 mp4 显示为可播放的视频消息，
        支持内联播放和全屏播放。

        Args:
            chat_id_str: chat_id
            video_path: mp4/mov 文件路径
            disable_notification: True=静音发送
        """
        if not self.application or not self.application.bot:
            return
        if not os.path.exists(video_path):
            logger.warning(f"视频文件不存在: {video_path}")
            return
        raw = str(chat_id_str)
        if raw.startswith("tg_"):
            raw = raw[3:]
        try:
            chat_id = int(raw)
        except ValueError:
            chat_id = chat_id_str

        try:
            with open(video_path, "rb") as f:
                file_bytes = f.read()
            buf = io.BytesIO(file_bytes)
            ext = os.path.splitext(video_path)[1].lower() or ".mp4"
            buf.name = f"video{ext}"
            await self.application.bot.send_video(
                chat_id=chat_id,
                video=buf,
                disable_notification=disable_notification,
                supports_streaming=True,
            )
            logger.info(
                f"发视频到 {chat_id}: {video_path} "
                f"({len(file_bytes)} bytes, silent={disable_notification})"
            )
        except TelegramError as e:
            logger.error(f"发视频失败: {e}")

    # ===== 语音发送 + TTS =====

    async def send_voice_to_chat(self, chat_id_str: str, audio_bytes: bytes,
                                  duration: int | None = None) -> bool:
        """发送语音消息到 Telegram chat。

        Args:
            chat_id_str: chat_id（可带 tg_ 前缀）
            audio_bytes: 音频字节（TTS 返回的 ogg/mp3/wav 均可）
            duration: 可选时长（秒）

        Returns:
            是否发送成功
        """
        if not self.application or not self.application.bot:
            return False
        if not audio_bytes or len(audio_bytes) < 44:
            logger.warning(f"音频数据过短 ({len(audio_bytes)} bytes)，跳过发送")
            return False
        raw = str(chat_id_str)
        if raw.startswith("tg_"):
            raw = raw[3:]
        try:
            chat_id = int(raw)
        except ValueError:
            chat_id = chat_id_str

        # 用 BytesIO 包装，filename 给 .ogg（Telegram 语音消息标准格式）
        buf = io.BytesIO(audio_bytes)
        buf.name = "voice.ogg"
        try:
            kwargs = {"chat_id": chat_id, "voice": buf}
            if duration is not None and duration > 0:
                kwargs["duration"] = int(duration)
            await self.application.bot.send_voice(**kwargs)
            logger.info(f"发送语音到 {chat_id}: {len(audio_bytes)} bytes")
            return True
        except TelegramError as e:
            logger.error(f"发送语音失败: {e}")
            return False

    async def _generate_tts_audio(self, text: str, reference_audio: str | None = None) -> bytes:
        """调用后端 /api/v1/media/tts 生成 TTS 音频字节。

        Args:
            text: 要转语音的文本
            reference_audio: 可选参考音频路径

        Returns:
            音频字节；失败返回空 bytes
        """
        if not text:
            return b""
        try:
            voice = self._resolve_voice_name()
            payload = {"text": text, "stream": False, "voice": voice}
            if reference_audio:
                payload["reference_audio"] = reference_audio

            status, data = await self.http_client.request(
                "POST", "/api/v1/media/tts", json_body=payload, timeout_seconds=30.0
            )
            if status != 200:
                logger.error(f"TTS 生成失败 (HTTP {status}): {data}")
                return b""

            # 兼容两种返回：直接二进制 或 JSON 含 audio_base64
            if isinstance(data, dict):
                inner = data.get("data") if isinstance(data.get("data"), dict) else data
                b64 = str(inner.get("audio_base64") or "").strip()
                if b64.startswith("data:"):
                    p = b64.find("base64,")
                    if p >= 0:
                        b64 = b64[p + 7:]
                if not b64:
                    logger.error("TTS JSON 响应中无 audio_base64")
                    return b""
                return base64.b64decode(b64)
            # 非 JSON：http_client 已包成 {"text": ...}，这里兜底
            return b""
        except Exception as e:
            logger.error(f"TTS 生成异常: {e}", exc_info=True)
            return b""

    def _resolve_voice_name(self) -> str:
        """根据当前人设推断音色名称。"""
        persona = str(getattr(self, "persona_filename", "") or "").strip().lower()
        if "aveline" in persona:
            return "Aveline"
        if "ling" in persona:
            return "Ling"
        if "luohuan" in persona:
            return "罗欢"
        return "Aveline"

    async def _send_voice_response(self, chat_id_str: str, text: str,
                                    reference_audio: str | None = None) -> bool:
        """生成 TTS 并发送语音消息。

        Args:
            chat_id_str: chat_id
            text: 要转语音的文本
            reference_audio: 可选参考音频路径

        Returns:
            是否发送成功
        """
        audio = await self._generate_tts_audio(text, reference_audio)
        if not audio:
            return False
        return await self.send_voice_to_chat(chat_id_str, audio)

    # ===== 媒体标签批量发送 =====

    async def _send_media_tags(self, chat_id_str: str, meme_categories: list[str],
                               img_count: int = 0, bm_count: int = 0,
                               *, video_count: int = 0,
                               disable_notification: bool = False):
        """按 [MEME]/[IMG]/[BM]/[VIDEO] 标签发送媒体（复用 QQ 的 media_tags 选图逻辑）。

        与 QQ 适配器对齐：
        - [MEME] 表情包用小图发送（缩到 240×240 以内，模拟 QQ 的 subType=1 效果）
        - [IMG]/[BM] 用原图大图发送
        - [VIDEO] 用 send_video 发送（可播放视频）
        - 发送失败只记日志，不影响主流程

        注意：[WEBM] 和 [DICE] 是 Telegram 专属标签，不在这里处理。
        它们在 session.py 的 _send_full_response_with_split 里通过
        sensitive_media.py 单独处理。

        Args:
            video_count: [VIDEO] 标签的数量（1-5）
            disable_notification: True=静音发送
        """
        has_media = bool(meme_categories or img_count or bm_count or video_count)
        if not has_media:
            return
        try:
            from clients.bots.qq.media_tags import (
                pick_meme_image, pick_gallery_images, pick_bm_images, pick_videos
            )
        except Exception as e:
            logger.warning(f"无法导入 media_tags 模块: {e}，跳过媒体标签发送")
            return

        # (path, is_meme) 列表：表情包标记为 True 走小图，IMG/BM 走大图
        send_list: list[tuple[str, bool]] = []

        for category in meme_categories:
            try:
                p = pick_meme_image(category)
                if p is None:
                    logger.warning(f"[MEME:{category}] 找不到可用表情包，跳过")
                    continue
                send_list.append((str(p), True))
                logger.info(f"[MEME:{category}] 选图: {p.name}")
            except Exception as e:
                logger.warning(f"[MEME:{category}] 选图失败: {e}")

        if img_count:
            try:
                for img_path in pick_gallery_images(img_count):
                    send_list.append((str(img_path), False))
                    logger.info(f"[IMG] 选图: {img_path.name}")
            except Exception as e:
                logger.warning(f"[IMG] 选图失败: {e}")

        if bm_count:
            try:
                for img_path in pick_bm_images(bm_count):
                    send_list.append((str(img_path), False))
                    logger.info(f"[BM] 选图: {img_path.name}")
            except Exception as e:
                logger.warning(f"[BM] 选图失败: {e}")

        # 发送图片
        for path, is_meme in send_list:
            try:
                if is_meme:
                    # 表情包：缩小后发小图（模拟 QQ subType=1）
                    await self.send_meme_path_to_chat(chat_id_str, path)
                else:
                    # IMG/BM：发大图
                    await self.send_photo_path_to_chat(chat_id_str, path)
            except Exception as e:
                logger.error(f"媒体标签图片发送失败: {e}")
            # 多张图之间稍间隔，避免刷屏
            import asyncio as _aio
            await _aio.sleep(0.5)

        # [VIDEO] 视频（QQ 和 Telegram 共用，选图逻辑在 qq/media_tags.py）
        if video_count:
            try:
                for vid_path in pick_videos(video_count):
                    await self.send_video_path_to_chat(
                        chat_id_str, str(vid_path),
                        disable_notification=disable_notification,
                    )
                    # 多个视频之间稍间隔
                    import asyncio as _aio
                    await _aio.sleep(0.5)
            except Exception as e:
                logger.error(f"[VIDEO] 视频发送失败: {e}")
