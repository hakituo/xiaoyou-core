"""配置管理器。

从 QQAdapter 中提取的专职组件，负责：
- 启动时从后端同步人设、模型、参考音频等配置
- 双QQ模式与单QQ模式的配置同步策略
"""
import logging
from typing import Awaitable, Callable

from clients.bots.qq.config import QQAdapterConfig
from clients.bots.qq.http_client import HttpClient


class ConfigManager:
    """配置管理器，负责从后端同步配置。"""

    def __init__(
        self,
        http_client: HttpClient,
        cfg: QQAdapterConfig,
        logger: logging.Logger | None = None,
    ):
        self.http_client = http_client
        self.cfg = cfg
        self.logger = logger or logging.getLogger("QQAdapter")

    async def sync_from_backend(
        self,
        *,
        get_reference_audio: Callable[[str], str] | None = None,
        persist_config: Callable[[str, dict], Awaitable[None]] | None = None,
        on_config_updated: Callable[[], None] | None = None,
    ) -> None:
        """启动时从后端同步配置

        双QQ模式下 persona、reference_audio、模型 由 adapter 自身配置决定；
        单QQ模式下从后端 API 获取。

        Args:
            get_reference_audio: 根据 persona_filename 获取参考音频路径的回调
            persist_config: 持久化用户配置的回调 (master_qq_id, overrides) -> None
            on_config_updated: 配置更新后的回调（通常用于清除缓存）
        """
        try:
            base = str(self.cfg.xiaoyou_http_base_url or "").rstrip("/")
            if not base:
                return

            mid = str(self.cfg.master_qq_id or "").strip()
            if not mid:
                return

            self.logger.info("[Sync] 正在从后端同步配置...")

            role_id = str(self.cfg.role_id or "").strip()
            own_persona = str(self.cfg.persona_filename or "").strip()
            own_ref_audio = str(self.cfg.default_reference_audio or "").strip()
            own_model_provider = str(self.cfg.default_model_provider or "").strip()
            own_model_name = str(self.cfg.default_model_name or "").strip()

            # 1. 确定人设
            persona_filename = await self._resolve_persona(own_persona)

            # 2. 确定模型
            model_provider, model_name = await self._resolve_model(
                own_model_provider, own_model_name
            )

            # 3. 确定参考音频
            reference_audio = await self._resolve_reference_audio(
                own_ref_audio, persona_filename, get_reference_audio
            )

            # 4. 更新本地配置
            if any([persona_filename, model_provider, model_name, reference_audio]):
                if persist_config:
                    await persist_config(mid, {
                        "persona_filename": persona_filename or "",
                        "model_provider": model_provider or "",
                        "model_name": model_name or "",
                        "reference_audio": reference_audio or "",
                    })
                if on_config_updated:
                    on_config_updated()
                self.logger.info(
                    f"[Sync] 配置同步完成 (role_id={role_id or '单QQ'}, "
                    f"persona={persona_filename or '无'}, "
                    f"model={model_provider}/{model_name or '无'})"
                )

        except Exception as e:
            self.logger.warning(f"[Sync] 同步配置失败: {e}")

    async def _resolve_persona(self, own_persona: str) -> str:
        """确定人设文件名

        双QQ模式：始终使用 adapter 自身配置
        单QQ模式：从后端 API 获取当前人设
        """
        if own_persona:
            self.logger.info(f"[Sync] 使用 adapter 自身配置的人设: {own_persona}")
            return own_persona

        try:
            status, data = await self.http_client.request(
                "GET", "/api/v1/personas/current"
            )
            if status == 200 and isinstance(data, dict):
                persona_filename = str(data.get("filename") or "").strip()
                if persona_filename:
                    self.logger.info(f"[Sync] 后端人设: {persona_filename}")
                    return persona_filename
        except Exception as e:
            self.logger.warning(f"[Sync] 获取人设失败: {e}")
        return ""

    async def _resolve_model(
        self, own_provider: str, own_model: str
    ) -> tuple[str, str]:
        """确定模型 provider 和 name

        双QQ模式：优先使用 adapter 自身配置
        单QQ模式：从后端 API 获取当前模型
        """
        if own_provider and own_model:
            self.logger.info(
                f"[Sync] 使用 adapter 自身配置的模型: {own_provider}/{own_model}"
            )
            return own_provider, own_model

        try:
            status, data = await self.http_client.request("GET", "/api/v1/models")
            if status == 200 and isinstance(data, dict):
                current = data.get("current", {})
                if isinstance(current, dict):
                    provider = str(current.get("provider") or "").strip()
                    model = str(current.get("model") or "").strip()
                    if provider and model:
                        self.logger.info(f"[Sync] 后端模型: {provider}/{model}")
                        return provider, model
        except Exception as e:
            self.logger.warning(f"[Sync] 获取模型失败: {e}")
        return "", ""

    async def _resolve_reference_audio(
        self,
        own_ref_audio: str,
        persona_filename: str,
        get_reference_audio: Callable[[str], str] | None,
    ) -> str:
        """确定参考音频

        双QQ模式：始终使用 adapter 自身配置
        单QQ模式：根据人设获取参考音频
        """
        if own_ref_audio:
            self.logger.info(
                f"[Sync] 使用 adapter 自身配置的参考音频: {own_ref_audio}"
            )
            return own_ref_audio

        if get_reference_audio and persona_filename:
            reference_audio = get_reference_audio(persona_filename) or ""
            if reference_audio:
                self.logger.info(f"[Sync] 参考音频: {reference_audio}")
            return reference_audio

        return ""
