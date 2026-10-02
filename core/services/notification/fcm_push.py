# -*- coding: utf-8 -*-
"""FCM（Firebase Cloud Messaging）离线推送通道 —— HTTP v1，可插拔、缺配置即降级。

为什么需要它：安卓端 AvelineFirebaseMessagingService 早就会把 token 上报到
`POST /system/mobile-push-token`，但后端一直没有发送实现，通道是死的 ——
App 进程被回收或常驻模式关闭后，通知只能等下次打开 App 拉取队列。

设计约定：
1. **可插拔**：`push.fcm_enabled` + project id + service account JSON + 已注册
   token，四项齐全才发送；缺任何一项直接返回 False，调用方继续走
   WebSocket 广播 + 通知队列，绝不抛异常拖垮主流程。
2. **不加依赖**：用项目已有的 PyJWT（带 cryptography）与 requests 走 HTTP v1
   （服务账号私钥签 JWT → 换 access_token → messages:send）。firebase-admin
   未安装，不为一个可选通道去改虚拟环境。
3. **字段与 WebSocket 通知一致**：data 里带 title / body / target，
   target 取值由调用方传 `app_push.TARGET_*`，安卓端才能用同一套深链规则。
4. **异步派发**：真正发送在后台线程里跑，调用方（请求协程 / APScheduler 线程）
   不被网络阻塞。
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

from core.utils.logger import get_logger

logger = get_logger("FCM_PUSH")

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
FCM_SEND_URL = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

# FCM data 载荷上限 4KB：单个值超过该长度、或结构化字段（整份词表）会被丢弃，
# 否则整条消息会被 FCM 直接拒收（400），连 title/body 都发不出去。
MAX_DATA_VALUE_CHARS = 512
MAX_DATA_BYTES = 3500

# 缺凭据时的统一提示（只打日志，不影响调用方）
NOT_CONFIGURED_HINT = (
    "FCM 未配置（需要 push.fcm_enabled / push.fcm_project_id / "
    "push.fcm_service_account_path，且安卓端已注册 token），"
    "本次通知走 WebSocket + 通知队列"
)


class FcmPushChannel:
    """FCM HTTP v1 发送器：配置懒加载，任何失败都只降级、不外抛。"""

    def __init__(self, settings: Any = None):
        # 传入 settings 便于单测/验证脚本注入；None 时从全局配置里取 push 段
        self._settings = settings
        self._service_account: Optional[Dict[str, Any]] = None
        self._service_account_loaded = False

    # ---------------- 配置读取 ----------------

    def _push_settings(self):
        """取全局配置的 push 段；取不到返回 None（按未配置处理）。"""
        if self._settings is None:
            try:
                from config.integrated_config import get_settings

                self._settings = getattr(get_settings(), "push", None)
            except Exception as e:
                logger.debug(f"读取 push 配置失败: {e}")
                return None
        return self._settings

    def enabled(self) -> bool:
        return bool(getattr(self._push_settings(), "fcm_enabled", False))

    def project_id(self) -> str:
        return str(getattr(self._push_settings(), "fcm_project_id", "") or "").strip()

    def channel_id(self) -> str:
        """安卓通知渠道 ID：须与客户端已创建的渠道一致，否则会落到默认渠道。"""
        value = str(
            getattr(self._push_settings(), "fcm_android_channel_id", "") or ""
        ).strip()
        return value or "aveline_messages"

    def timeout_seconds(self) -> float:
        try:
            return float(
                getattr(self._push_settings(), "fcm_timeout_seconds", 10.0) or 10.0
            )
        except Exception:
            return 10.0

    def service_account_path(self) -> str:
        return str(
            getattr(self._push_settings(), "fcm_service_account_path", "") or ""
        ).strip()

    def service_account(self) -> Optional[Dict[str, Any]]:
        """读取并缓存服务账号 JSON；路径为空或文件损坏一律返回 None。"""
        if self._service_account_loaded:
            return self._service_account
        self._service_account_loaded = True

        path = self.service_account_path()
        if not path:
            return None
        if not os.path.exists(path):
            logger.warning(f"FCM 服务账号 JSON 不存在: {path}")
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or not data.get("private_key") or not data.get(
                "client_email"
            ):
                logger.warning("FCM 服务账号 JSON 缺少 private_key / client_email")
                return None
            self._service_account = data
        except Exception as e:
            logger.warning(f"FCM 服务账号 JSON 读取失败: {e}")
            return None
        return self._service_account

    def device_tokens(self) -> List[str]:
        """已注册的移动端 token（安卓端上报，落在 user_preferences.json）。"""
        try:
            from core.managers.preference_manager import get_preference_manager

            token = str(get_preference_manager().get("mobile_push_token") or "").strip()
        except Exception as e:
            logger.debug(f"读取移动端推送 token 失败: {e}")
            return []
        return [token] if token else []

    def is_configured(self) -> bool:
        """四项齐全才算通道可用；缺任一项返回 False，由调用方降级。"""
        return bool(
            self.enabled()
            and self.project_id()
            and self.service_account()
            and self.device_tokens()
        )

    # ---------------- 发送 ----------------

    def _get_access_token(self) -> Optional[str]:
        """用服务账号私钥签 JWT 换 OAuth2 access_token（HTTP v1 的前置步骤）。"""
        service_account = self.service_account()
        if not service_account:
            return None
        try:
            import jwt  # PyJWT（依赖树里是 PyJWT[crypto]，带 RS256 支持）
            import requests
        except ImportError as e:  # pragma: no cover - 依赖缺失时降级
            logger.warning(f"FCM 依赖缺失（需要 PyJWT 与 requests）: {e}")
            return None

        token_uri = service_account.get("token_uri") or DEFAULT_TOKEN_URI
        now = int(time.time())
        claims = {
            "iss": service_account.get("client_email", ""),
            "scope": FCM_SCOPE,
            "aud": token_uri,
            "iat": now,
            "exp": now + 3600,
        }
        try:
            assertion = jwt.encode(
                claims, service_account.get("private_key", ""), algorithm="RS256"
            )
            if isinstance(assertion, bytes):
                assertion = assertion.decode("utf-8")
            resp = requests.post(
                token_uri,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
                timeout=self.timeout_seconds(),
            )
            if getattr(resp, "status_code", 0) != 200:
                logger.warning(
                    f"FCM access_token 获取失败: HTTP {resp.status_code} "
                    f"{str(getattr(resp, 'text', ''))[:200]}"
                )
                return None
            return resp.json().get("access_token")
        except Exception as e:
            logger.warning(f"FCM access_token 获取异常: {e}")
            return None

    def _build_message(
        self,
        title: str,
        body: str,
        target: Optional[str],
        data: Optional[Dict[str, Any]],
        token: str,
    ) -> Dict[str, Any]:
        """构造 HTTP v1 message：data 与 WebSocket 通知同字段（title/body/target）。"""
        payload_data: Dict[str, str] = {}
        for key, value in (data or {}).items():
            # FCM data 只接受字符串值，结构化字段（如整份词表）直接跳过
            if value is None or isinstance(value, (dict, list, tuple, set)):
                continue
            text = str(value)
            if len(text) > MAX_DATA_VALUE_CHARS:
                continue
            payload_data[str(key)] = text

        # title / body / target 是深链与兜底标题的依据，始终带上
        payload_data["title"] = title
        payload_data["body"] = body
        if target:
            payload_data["target"] = target

        essential = {"title", "body", "target"}
        extra_keys = [k for k in payload_data if k not in essential]
        while (
            extra_keys
            and len(json.dumps(payload_data, ensure_ascii=False).encode("utf-8")) > MAX_DATA_BYTES
        ):
            payload_data.pop(extra_keys.pop())

        return {
            "message": {
                "token": token,
                "notification": {"title": title, "body": body},
                "data": payload_data,
                "android": {
                    "priority": "high",
                    "notification": {"channel_id": self.channel_id()},
                },
            }
        }

    def send(
        self,
        title: str,
        body: str,
        target: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """同步发送到所有已注册 token（通常在后台线程里调用）。

        Returns:
            至少一个 token 发送成功才返回 True；未配置/失败一律 False。
        """
        try:
            if not self.is_configured():
                logger.debug(NOT_CONFIGURED_HINT)
                return False

            access_token = self._get_access_token()
            if not access_token:
                return False

            import requests

            url = FCM_SEND_URL.format(project_id=self.project_id())
            headers = {"Authorization": f"Bearer {access_token}"}
            tokens = self.device_tokens()
            sent = False
            for token in tokens:
                message = self._build_message(title, body, target, data, token)
                try:
                    resp = requests.post(
                        url,
                        json=message,
                        headers=headers,
                        timeout=self.timeout_seconds(),
                    )
                    if getattr(resp, "status_code", 0) == 200:
                        sent = True
                    else:
                        logger.warning(
                            f"FCM 发送失败: HTTP {resp.status_code} "
                            f"{str(getattr(resp, 'text', ''))[:200]}"
                        )
                except Exception as e:
                    # 单个 token 失败（网络抖动 / token 失效）不影响其余 token
                    logger.warning(f"FCM 单条发送异常: {e}")
            if sent:
                logger.info(f"FCM 已推送: {title}（{len(tokens)} 个 token）")
            return sent
        except Exception as e:
            logger.warning(f"FCM 发送失败（降级为 WebSocket + 通知队列）: {e}")
            return False


_channel: Optional[FcmPushChannel] = None
_channel_lock = threading.Lock()


def get_fcm_channel() -> FcmPushChannel:
    """获取 FCM 通道单例（配置懒加载，不成立时不产生任何副作用）。"""
    global _channel
    if _channel is None:
        with _channel_lock:
            if _channel is None:
                _channel = FcmPushChannel()
    return _channel


def dispatch_fcm_notification(
    title: str,
    body: str,
    target: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
) -> bool:
    """后台线程派发一次 FCM 推送，不阻塞调用方。

    Returns:
        是否已派发；配置不全或派发失败返回 False（调用方继续走 WebSocket + 队列）。
    """
    try:
        channel = get_fcm_channel()
        if not channel.is_configured():
            logger.debug(NOT_CONFIGURED_HINT)
            return False
        threading.Thread(
            target=channel.send,
            args=(title, body, target, data),
            name="fcm-push",
            daemon=True,
        ).start()
        return True
    except Exception as e:
        logger.warning(f"FCM 派发失败（降级为 WebSocket + 通知队列）: {e}")
        return False
