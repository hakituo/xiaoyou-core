import asyncio
from typing import Optional

import aiohttp


async def get_cloud_tts_session(engine) -> aiohttp.ClientSession:
    loop = asyncio.get_running_loop()
    if engine._session and not engine._session.closed and engine._session_loop is loop:
        return engine._session

    if engine._session_lock is None or engine._session_loop is not loop:
        engine._session_lock = asyncio.Lock()

    async with engine._session_lock:
        if (
            engine._session
            and not engine._session.closed
            and engine._session_loop is loop
        ):
            return engine._session

        if (
            engine._session
            and not engine._session.closed
            and engine._session_loop is not loop
        ):
            try:
                await engine._session.close()
            except Exception:
                pass

        connector = aiohttp.TCPConnector(
            limit=32,
            ttl_dns_cache=300,
            enable_cleanup_closed=True,
        )
        timeout = aiohttp.ClientTimeout(total=300)
        engine._session = aiohttp.ClientSession(connector=connector, timeout=timeout)
        engine._session_loop = loop
        return engine._session


async def synthesize_cloud_tts_bytes(engine, text: str, **kwargs) -> Optional[bytes]:
    if not engine.api_key:
        return None

    url = engine.base_url
    if not url.endswith("speech"):
        if url.endswith("/v1"):
            url += "/audio/speech"
        elif not url.endswith("/"):
            url += "/v1/audio/speech"

    headers = {
        "Authorization": f"Bearer {engine.api_key}",
        "Content-Type": "application/json",
    }

    voice = kwargs.get("voice", engine.voice)
    speed = kwargs.get("speed", 1.0)

    payload = {
        "model": engine.model,
        "input": text,
        "voice": voice,
        "speed": speed,
    }

    try:
        session = await get_cloud_tts_session(engine)
        async with session.post(url, json=payload, headers=headers) as response:
            if response.status != 200:
                return None
            audio_data = await response.read()
            return audio_data or None
    except Exception:
        return None


async def shutdown_cloud_tts(engine):
    try:
        if engine._session and not engine._session.closed:
            await engine._session.close()
    except Exception:
        pass
    engine._session = None
    engine._session_loop = None
