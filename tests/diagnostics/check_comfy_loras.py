
import aiohttp
import asyncio

async def check_loras():
    url = "http://127.0.0.1:8188/object_info/LoraLoader"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    lora_list = data["LoraLoader"]["input"]["required"]["lora_name"][0]
                    print("Available LoRAs:", lora_list)
                else:
                    print(f"Failed: {resp.status}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check_loras())
