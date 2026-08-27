import requests
import base64
import json
import os
import sys

import pytest


pytestmark = [pytest.mark.integration, pytest.mark.gpu]


if os.getenv("XIAOYOU_RUN_IMAGE_TESTS") != "1":
    pytest.skip("需要设置 XIAOYOU_RUN_IMAGE_TESTS=1 才运行图像生成测试", allow_module_level=True)

def test_image_gen():
    url = "http://127.0.0.1:7860"
    print(f"Testing Forge API at {url}...")
    
    # 1. Check Options (Connectivity)
    try:
        resp = requests.get(f"{url}/sdapi/v1/options", timeout=5)
        if resp.status_code == 200:
            print("Successfully connected to Forge.")
            print(f"Current Model: {resp.json().get('sd_model_checkpoint')}")
        else:
            print(f"Failed to connect to Forge: {resp.status_code}")
            return
    except Exception as e:
        print(f"Connection error: {e}")
        return

    # 2. List Models
    try:
        resp = requests.get(f"{url}/sdapi/v1/sd-models", timeout=5)
        if resp.status_code == 200:
            models = resp.json()
            print(f"Found {len(models)} models.")
            for m in models:
                print(f" - {m['title']}")
        else:
            print("Failed to list models.")
    except Exception as e:
        print(f"Error listing models: {e}")

    # 3. Generate Image
    print("\nAttempting to generate image (512x512)...")
    payload = {
        "prompt": "A cute robot sitting on a bench, digital art",
        "steps": 20,
        "width": 512,
        "height": 512,
        "cfg_scale": 7,
        "sampler_name": "Euler a",
        "batch_size": 1
    }
    
    try:
        resp = requests.post(f"{url}/sdapi/v1/txt2img", json=payload, timeout=60)
        if resp.status_code == 200:
            r = resp.json()
            if 'images' in r and len(r['images']) > 0:
                print("Image generation SUCCESS!")
                # Save it
                out_path = os.path.join(os.path.dirname(__file__), "_artifacts")
                os.makedirs(out_path, exist_ok=True)
                file_path = os.path.join(out_path, "test_gen.png")
                with open(file_path, "wb") as f:
                    f.write(base64.b64decode(r['images'][0]))
                print(f"Saved to {file_path}")
            else:
                print("Image generation returned NO IMAGES.")
                print(f"Full response: {r}")
        else:
            print(f"Image generation FAILED: {resp.status_code}")
            print(resp.text)
    except Exception as e:
        print(f"Generation error: {e}")

if __name__ == "__main__":
    test_image_gen()
