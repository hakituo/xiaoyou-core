import sys
import json
import time
import urllib.request
import urllib.error

API_URL = "http://localhost:8000/api/v1/message"
CONVERSATION_ID = "test_user_loop"

def send_message(content):
    data = {
        "content": content,
        "conversation_id": CONVERSATION_ID,
        "model": "default"
    }
    json_data = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(API_URL, data=json_data, headers={'Content-Type': 'application/json'})
    
    start_time = time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as response:
            body = response.read().decode('utf-8')
            duration = time.time() - start_time
            return {
                "status": response.getcode(),
                "body": json.loads(body),
                "duration": duration
            }
    except urllib.error.HTTPError as e:
        return {"status": e.code, "error": str(e), "duration": time.time() - start_time}
    except Exception as e:
        return {"status": 0, "error": str(e), "duration": time.time() - start_time}

def run_test():
    print(f"Starting chat loop test against {API_URL}...")
    messages = [
        "Hello",
        "How are you?",
        "Tell me a short joke.",
        "What is 2+2?",
        "Goodbye"
    ]
    
    for i, msg in enumerate(messages):
        print(f"\n[{i+1}/{len(messages)}] Sending: '{msg}'")
        result = send_message(msg)
        
        if result['status'] == 200:
            resp = result['body']
            reply = resp.get('response', '')
            print(f"Success ({result['duration']:.2f}s): {reply[:100]}...")
            if "error_code" in resp:
                 print(f"Warning: API returned error code: {resp['error_code']}")
        else:
            print(f"Failed ({result['duration']:.2f}s): {result.get('error')}")
            
        time.sleep(1) # Brief pause

if __name__ == "__main__":
    run_test()
