import asyncio
import uuid
import json
import requests
import sys
import time

# Use API instead of direct service call to avoid resource contention
API_URL = "http://localhost:8000/api/v1/message"

def main():
    print("\n=== Starting NSFW Chat Test (API Mode) ===\n")
    
    # Simulate a conversation flow
    messages = [
        "宝贝，我回来了。",
        "我想看看你现在的样子，能不能给我发一张私密的照片？",
        "再露骨一点，我想要更刺激的。",
        "描述一下你现在身体的感觉，用最淫荡的词。"
    ]
    
    conversation_id = "test_conv_nsfw_api"
    
    for user_text in messages:
        print(f"\n[User]: {user_text}")
        
        payload = {
            "content": user_text,
            "conversation_id": conversation_id
        }
        
        print("[Client]: Sending request to API...")
        try:
            start_time = time.time()
            response = requests.post(API_URL, json=payload, timeout=120) # 2 min timeout
            duration = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                # API response structure from handle_message:
                # { "status": "success", "reply": "...", "emotion": "...", "image_prompt": "...", ... }
                # OR legacy: { "response": "..." }
                
                reply = data.get("reply") or data.get("response") or data.get("content") or ""
                emotion = data.get("emotion", "unknown")
                image_prompt = data.get("image_prompt")
                image_base64 = data.get("image_base64")
                image_path = data.get("image_path")
                
                print(f"[Time]: {duration:.2f}s")
                print(f"[Emotion]: {emotion}")
                print(f"[Response]: {reply}")
                
                if image_prompt:
                    print(f"[Image Prompt]: {image_prompt}")
                
                if image_base64:
                    print(f"[Image Generated]: Yes (Base64 length: {len(image_base64)})")
                elif image_path:
                    print(f"[Image Generated]: Yes (Path: {image_path})")
                else:
                    print(f"[Image Generated]: No")
                    
            else:
                print(f"[Error]: API returned {response.status_code}")
                print(f"[Content]: {response.text}")
                
        except Exception as e:
            print(f"[Error]: Request failed: {e}")
            
        print("-" * 50)

if __name__ == "__main__":
    main()
