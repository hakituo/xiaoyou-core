from aiohttp import web
import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MockTTSServer")

async def handle_tts(request):
    text = request.query.get('text', '')
    logger.info(f"Received TTS request for: {text}")
    
    # Simulate processing latency (e.g. 0.5s to 2s depending on length)
    latency = 0.5 + (len(text) * 0.05)
    await asyncio.sleep(min(latency, 3.0)) 
    
    # Return a dummy wav (header only or silence)
    # Minimal WAV header (44 bytes)
    dummy_wav = (
        b'RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00'
    )
    
    return web.Response(body=dummy_wav, content_type='audio/wav')

app = web.Application()
app.add_routes([web.get('/', handle_tts)])

if __name__ == '__main__':
    web.run_app(app, port=9880)
