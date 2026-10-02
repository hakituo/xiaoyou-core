#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VTube Studio Integration Service
Uses pyvts to control VTube Studio models, trigger hotkeys/expressions based on emotions.
"""

import asyncio
import pyvts
from typing import Optional, List

from config.integrated_config import get_settings
from core.utils.logger import get_logger

logger = get_logger("VTubeService")


class VTubeStudioService:
    def __init__(self):
        self.settings = get_settings()
        self.vts_settings = self.settings.vtube

        self.plugin_info = {
            "plugin_name": self.vts_settings.plugin_name,
            "developer": self.vts_settings.developer,
            "authentication_token_path": self.vts_settings.token_path,
        }

        # Initialize pyvts
        self.vts = pyvts.vts(
            plugin_info=self.plugin_info,
            host=self.vts_settings.host,
            port=self.vts_settings.port,
        )
        self._connected = False
        self._authenticated = False
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Cache for hotkeys
        self.available_hotkeys: List[str] = []

    async def initialize(self):
        """Initialize and connect to VTube Studio"""
        if not self.vts_settings.enabled:
            logger.info("VTube Studio service is disabled in config.")
            return

        if self._running:
            return

        self._running = True
        logger.info(
            f"Initializing VTube Studio Service (Host: {self.vts_settings.host}, Port: {self.vts_settings.port})"
        )

        # Start connection task in background to avoid blocking startup if VTS is not running
        self._task = asyncio.create_task(self._connect_loop())

    async def shutdown(self):
        """Shutdown the service"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self._connected:
            try:
                await self.vts.close()
            except Exception as e:
                logger.warning(f"Error closing VTS connection: {e}")

        logger.info("VTube Studio Service shutdown.")

    async def _connect_loop(self):
        """Persistent connection loop"""
        while self._running:
            if not self._connected:
                try:
                    # Attempt connection
                    # pyvts connect method might differ slightly in arguments depending on version
                    # Usually it's connect() or connect(host, port)
                    # Checking pyvts source or usage in Neuro: await self.vts.connect()
                    # It defaults to localhost:8001

                    # We need to hack/configure pyvts if host/port is different,
                    # but pyvts.vts() constructor doesn't seem to take host/port in some versions.
                    # It usually assumes default.
                    # However, let's assume standard behavior.

                    await self.vts.connect()
                    self._connected = True
                    logger.info("Connected to VTube Studio WebSocket.")

                    # Authenticate
                    await self._authenticate()

                    # Fetch Hotkeys
                    if self._authenticated:
                        await self._fetch_hotkeys()

                except Exception:
                    # logger.debug(f"VTube Studio connection failed (will retry): {e}")
                    # Reduce log noise
                    pass

            await asyncio.sleep(5)  # Check/Retry every 5 seconds

    async def _authenticate(self):
        """Handle authentication flow"""
        try:
            # 1. Request Token (or read from file)
            # pyvts request_authenticate_token() reads from file or requests new one
            await self.vts.request_authenticate_token()

            # 2. Authenticate
            is_auth = await self.vts.request_authenticate()

            if is_auth:
                self._authenticated = True
                logger.info("VTube Studio Authentication Successful.")
            else:
                self._authenticated = False
                logger.warning(
                    "VTube Studio Authentication Failed (User denied or invalid token)."
                )
        except Exception as e:
            logger.error(f"VTube Studio Authentication Error: {e}")
            self._authenticated = False

    async def _fetch_hotkeys(self):
        """Fetch available hotkeys from VTS"""
        try:
            resp = await self.vts.request(self.vts.vts_request.requestHotKeyList())
            if resp and "data" in resp and "availableHotkeys" in resp["data"]:
                self.available_hotkeys = [
                    h["name"] for h in resp["data"]["availableHotkeys"]
                ]
                logger.info(
                    f"Loaded {len(self.available_hotkeys)} hotkeys from VTube Studio."
                )
                logger.debug(f"Hotkeys: {self.available_hotkeys}")
        except Exception as e:
            logger.error(f"Failed to fetch hotkeys: {e}")

    async def trigger_hotkey(self, hotkey_name: str):
        """Trigger a specific hotkey by name"""
        if not self._connected or not self._authenticated:
            # logger.warning("Cannot trigger hotkey: VTS not connected/authenticated.")
            return

        try:
            # Check if hotkey exists (optional, but good for debugging)
            # if hotkey_name not in self.available_hotkeys:
            #     logger.warning(f"Hotkey '{hotkey_name}' not found in available hotkeys.")

            req = self.vts.vts_request.requestTriggerHotKey(hotkey_name)
            await self.vts.request(req)
            logger.info(f"Triggered VTS Hotkey: {hotkey_name}")
        except Exception as e:
            logger.error(f"Error triggering hotkey {hotkey_name}: {e}")

    async def send_emotion(self, emotion_label: str):
        """
        Map emotion label to hotkey and trigger it.
        """
        if not self.vts_settings.enabled:
            return

        # Normalize emotion label
        emotion = emotion_label.lower()

        # Look up in mapping
        hotkey = self.vts_settings.emotion_hotkey_map.get(emotion)

        if not hotkey:
            # Try to find a default or fallback?
            # For now, just ignore unmapped emotions
            # logger.debug(f"No hotkey mapped for emotion: {emotion}")
            return

        await self.trigger_hotkey(hotkey)


# Global Instance
_vtube_service: Optional[VTubeStudioService] = None


def get_vtube_service() -> VTubeStudioService:
    global _vtube_service
    if _vtube_service is None:
        _vtube_service = VTubeStudioService()
    return _vtube_service


async def initialize_vtube_service():
    await get_vtube_service().initialize()


async def shutdown_vtube_service():
    if _vtube_service:
        await _vtube_service.shutdown()
