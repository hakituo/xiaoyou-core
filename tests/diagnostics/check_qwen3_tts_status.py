import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from core.voice.qwen3_tts_cloud import Qwen3TTSCloudEngine

async def test():
    engine = Qwen3TTSCloudEngine()
    status = engine.get_status()
    print('引擎状态:')
    for k, v in status.items():
        print(f'  - {k}: {v}')

asyncio.run(test())
