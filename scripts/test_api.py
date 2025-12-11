import requests
import json
import time

API_URL = "http://localhost:8000/api/v1/generate"

def test_generate():
    payload = {
        "prompt": "你好，请介绍一下你自己。",
        "max_length": 100,
        "temperature": 0.7
    }
    
    print(f"Sending request to {API_URL}...")
    try:
        start_time = time.time()
        response = requests.post(API_URL, json=payload, timeout=120)
        end_time = time.time()
        
        print(f"Status Code: {response.status_code}")
        print(f"Time Taken: {end_time - start_time:.2f}s")
        
        if response.status_code == 200:
            print("Response:")
            print(json.dumps(response.json(), indent=2, ensure_ascii=False))
        else:
            print("Error:")
            print(response.text)
            
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    test_generate()
