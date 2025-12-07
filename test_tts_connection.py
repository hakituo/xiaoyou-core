import aiohttp
import asyncio
import os

async def test_tts():
    url = "http://127.0.0.1:9880/tts"
    params = {
        "text": "测试语音合成",
        "text_lang": "zh",
        "ref_audio_path": r"d:\AI\xiaoyou-core\ref_audio\female\ref_calm.wav",
        "prompt_text": "这是中文纯语音测试，不包含英文内容",
        "prompt_lang": "zh"
    }
    
    print(f"Connecting to {url}...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                print(f"Status: {response.status}")
                if response.status == 200:
                    content = await response.read()
                    print(f"Received {len(content)} bytes")
                    with open("test_output.wav", "wb") as f:
                        f.write(content)
                else:
                    text = await response.text()
                    print(f"Error: {text}")
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    asyncio.run(test_tts())