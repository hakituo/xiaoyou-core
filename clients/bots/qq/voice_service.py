"""语音处理服务。

从 QQAdapter 中提取的专职组件，负责：
- 判断用户是否想要语音回复
- 判断是否应该只回复语音
- 生成 TTS 并发送语音消息
"""
import base64
import logging
import re
from typing import Awaitable, Callable

from clients.bots.qq.http_client import HttpClient


class VoiceService:
    """语音处理服务，统一管理语音相关的处理逻辑。"""

    # 角色 ID 到音色名称的映射
    _VOICE_NAME_MAP = {
        "aveline": "Aveline",
        "ling": "Ling",
        "luohuan": "罗欢",
    }

    def __init__(
        self,
        http_client: HttpClient,
        role_id: str,
        role_name: str,
        access_token: str = "",
        logger: logging.Logger | None = None,
    ):
        self.http_client = http_client
        self.role_id = str(role_id or "").strip()
        self.role_name = str(role_name or "").strip()
        self.access_token = str(access_token or "").strip()
        self.logger = logger or logging.getLogger("QQAdapter")

    def wants_voice_reply(self, text: str) -> bool:
        """判断用户是否想要语音回复"""
        t = str(text or "").strip()
        if not t:
            return False
        if t.startswith("/"):
            return False
        if "语音转文字" in t:
            return False

        voice_keywords = ("语音", "声音", "听听你", "说句话")
        if not any(k in t for k in voice_keywords):
            return False

        patterns = [
            r"(发|来|给|用|整|搞|想|要)\s*(个|段|条|句|点|下|听听|听)?\s*(语音|声音)",
            r"(用|通过)\s*语音\s*(说|讲|回|回复|念|读|聊)",
            r"想你\s*声音\s*了",
            r"听听\s*你\s*的?\s*声音",
            r"说话\s*给我\s*听",
        ]
        for p in patterns:
            if re.search(p, t):
                return True

        quick_keys = (
            "语音回复",
            "发语音",
            "来段语音",
            "用语音说",
            "用语音回",
            "语音聊天",
            "发条语音",
        )
        if any(k in t for k in quick_keys):
            return True

        return t in {"语音", "发个语音", "来个语音", "想听你声音"}

    async def should_reply_voice_only(
        self,
        content: str,
        get_prefs: Callable[[str], dict | None],
        default_voice_only: bool = False,
    ) -> bool:
        """判断是否应该只回复语音

        Args:
            content: 待发送的文本内容
            get_prefs: 获取会话偏好的回调函数
            default_voice_only: 默认是否只回复语音
        """
        if "[CQ:" in str(content or ""):
            return False
        prefs = get_prefs() if get_prefs else None
        if isinstance(prefs, dict) and "reply_voice_only" in prefs:
            return bool(prefs.get("reply_voice_only"))
        return bool(default_voice_only)

    async def send_voice_response(
        self,
        session_id: str,
        text: str,
        reference_audio: str | None = None,
        send_callback: Callable[[str, str], Awaitable[bool | None]] | None = None,
    ) -> bool:
        """生成 TTS 并发送语音消息

        使用 base64 CQ 码发送（NapCat 无法访问本地文件路径）。

        Args:
            session_id: 会话 ID
            text: 要转语音的文本
            reference_audio: 参考音频路径
            send_callback: 发送 CQ 码的回调函数 (session_id, cq_code) -> None

        Returns:
            是否发送成功
        """
        if not text:
            return False

        try:
            url = self.http_client.base_url + "/api/v1/media/tts"
            voice = self._resolve_voice_name()

            payload = {
                "text": text,
                "stream": False,
                "voice": voice,
            }
            if reference_audio:
                payload["reference_audio"] = reference_audio

            session = await self.http_client.get_session()
            headers = {}
            if self.access_token:
                headers["Authorization"] = f"Bearer {self.access_token}"

            self.logger.info(f"Generating TTS for voice reply: {text[:20]}...")
            async with session.post(url, json=payload, headers=headers, timeout=30) as resp:
                if resp.status != 200:
                    err_text = await resp.text()
                    self.logger.error(
                        f"TTS generation failed ({resp.status}): {err_text}"
                    )
                    return False

                ctype = str(resp.headers.get("Content-Type") or "").lower()
                audio_data = b""
                if "application/json" in ctype:
                    body = await resp.json(content_type=None)
                    audio_data = self._extract_audio_data(body)
                else:
                    audio_data = await resp.read()

            if not audio_data:
                self.logger.error("TTS returned empty data")
                return False

            if len(audio_data) < 44:
                self.logger.error(
                    f"[{session_id}] TTS 音频数据异常过短 "
                    f"({len(audio_data)} bytes)，跳过发送"
                )
                return False

            b64 = base64.b64encode(audio_data).decode("utf-8")
            cq_code = f"[CQ:record,file=base64://{b64}]"
            self.logger.info(
                f"[{session_id}] TTS 语音发送: "
                f"{len(audio_data)} bytes, b64={len(b64)} chars"
            )

            if send_callback:
                send_result = await send_callback(session_id, cq_code)
                if send_result is False:
                    self.logger.error(f"[{session_id}] NapCat 未确认语音消息发送成功")
                    return False
            return True

        except Exception as e:
            self.logger.error(f"Error sending voice response: {e}")
            return False

    def _resolve_voice_name(self) -> str:
        """根据 role_id 确定音色名称"""
        role_id = self.role_id.lower()
        return self._VOICE_NAME_MAP.get(role_id, self.role_name or "Aveline")

    def _extract_audio_data(self, body) -> bytes:
        """从 TTS API 的 JSON 响应中提取音频数据"""
        if not isinstance(body, dict):
            self.logger.error("TTS JSON response invalid")
            return b""

        data = body.get("data")
        if not isinstance(data, dict):
            data = {}

        audio_base64 = str(data.get("audio_base64") or "").strip()
        if audio_base64.startswith("data:"):
            p = audio_base64.find("base64,")
            if p >= 0:
                audio_base64 = audio_base64[p + 7:]

        if not audio_base64:
            return b""

        try:
            return base64.b64decode(audio_base64)
        except Exception as decode_err:
            self.logger.error(f"TTS base64 decode failed: {decode_err}")
            return b""
