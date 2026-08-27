import requests
import json
import base64
import os
import time
import wave
import struct

import pytest


pytestmark = pytest.mark.integration


if os.getenv("XIAOYOU_RUN_INTEGRATION_TESTS") != "1":
    pytest.skip(
        "需要设置 XIAOYOU_RUN_INTEGRATION_TESTS=1 才运行集成测试",
        allow_module_level=True,
    )

BASE_URL = "http://localhost:8000"

def print_result(name, success, details):
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"{status} - {name}")
    if not success:
        print(f"   Error: {details}")
    else:
        print(f"   Details: {details}")
    print("-" * 50)

def create_dummy_audio(filename="test_audio.wav"):
    with wave.open(filename, 'w') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        # Write 1 second of silence
        data = struct.pack('<h', 0) * 16000
        f.writeframes(data)
    return filename

def create_dummy_image(filename="test_image.png"):
    # Create a 1x1 white pixel PNG
    # Minimal PNG signature and chunks
    with open(filename, "wb") as f:
        f.write(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAACklEQVR4nGMAAQAABQABDQottAAAAABJRU5ErkJggg=="))
    return filename

def test_llm():
    print("Testing LLM Chat...")
    endpoint = f"{BASE_URL}/api/v1/message"
    payload = {
        "content": "Hello, are you online? This is a test.",
        "request_id": "test_req_001",
        "conversation_id": "test_conv_001"
    }
    try:
        response = requests.post(endpoint, json=payload, timeout=30)
        if response.status_code == 200:
            data = response.json()
            reply = data.get("reply") or data.get("response")
            if reply:
                print_result("LLM Chat", True, f"Reply: {reply[:50]}...")
            else:
                print_result("LLM Chat", False, f"No reply in response: {data}")
        else:
            print_result("LLM Chat", False, f"Status {response.status_code}: {response.text}")
    except Exception as e:
        print_result("LLM Chat", False, str(e))

def test_image_generation():
    print("Testing Image Generation...")
    endpoint = f"{BASE_URL}/api/v1/image/generate"
    # Need to check available models first or just try default
    payload = {
        "prompt": "A cute cat sitting on a futuristic desk, cyberpunk style",
        "modelPath": None, # Use default
        "loraPath": None,
        "loraWeight": 0.7
    }
    try:
        response = requests.post(endpoint, json=payload, timeout=60) # Longer timeout for generation
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                print_result("Image Generation", True, f"Image path: {data.get('image_path')}")
            else:
                print_result("Image Generation", False, f"Success is false: {data}")
        else:
            print_result("Image Generation", False, f"Status {response.status_code}: {response.text}")
    except Exception as e:
        print_result("Image Generation", False, str(e))

def test_stt():
    print("Testing STT (Speech to Text)...")
    endpoint = f"{BASE_URL}/api/v1/stt"
    filename = create_dummy_audio()
    try:
        with open(filename, 'rb') as f:
            files = {'file': (filename, f, 'audio/wav')}
            params = {'model_size': 'base'}
            response = requests.post(endpoint, files=files, params=params, timeout=30)
            
        if response.status_code == 200:
            data = response.json()
            # Even if it transcribes nothing (silence), a 200 means the endpoint works
            print_result("STT", True, f"Response: {data}")
        else:
            print_result("STT", False, f"Status {response.status_code}: {response.text}")
    except Exception as e:
        print_result("STT", False, str(e))
    finally:
        if os.path.exists(filename):
            os.remove(filename)

def test_vision():
    print("Testing Vision Model...")
    endpoint = f"{BASE_URL}/api/v1/vision/describe"
    filename = create_dummy_image()
    try:
        with open(filename, "rb") as f:
            b64_image = base64.b64encode(f.read()).decode('utf-8')
            
        payload = {
            "model_name": "moondream", # Assuming a default name, or we might need to fetch models first
            "image_base64": f"data:image/png;base64,{b64_image}",
            "prompt": "Describe this image"
        }
        
        response = requests.post(endpoint, json=payload, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            print_result("Vision", True, f"Description: {data}")
        elif response.status_code == 500:
             # Often happens if model not loaded, but endpoint reached
            print_result("Vision", False, f"Server Error (Model likely not loaded): {response.text}")
        else:
            print_result("Vision", False, f"Status {response.status_code}: {response.text}")
            
    except Exception as e:
        print_result("Vision", False, str(e))
    finally:
        if os.path.exists(filename):
            os.remove(filename)

if __name__ == "__main__":
    print("Starting Backend Function Tests...")
    print("-" * 50)
    
    # Check if server is up
    try:
        requests.get(f"{BASE_URL}/docs", timeout=2)
    except Exception:
        print("❌ Error: Backend server does not appear to be running at http://localhost:8000")
        print("Please start the backend server first.")
        exit(1)
        
    test_llm()
    # test_image_generation() # This might take time and GPU, careful
    # test_stt()
    # test_vision()
    
    # Run them all sequentially
    test_stt()
    test_vision()
    test_image_generation()
