import requests
import json
import sys

BASE_URL = "http://localhost:8000"

def test_model_switch_flow():
    print("[-] Starting App Simulation Test...")
    
    # 1. Get Models
    print("[-] Fetching models...")
    try:
        resp = requests.get(f"{BASE_URL}/api/v1/models")
        resp.raise_for_status()
        data = resp.json()
        available_models = data.get("available", [])
        print(f"[+] Found {len(available_models)} models")
    except Exception as e:
        print(f"[!] Failed to fetch models: {e}")
        return

    # Filter for a local model
    local_model = next((m for m in available_models if m.get("category") == "local"), None)
    if not local_model:
        # Fallback: look for model without "cloud:" in path
        local_model = next((m for m in available_models if "cloud:" not in m.get("path", "")), None)
    
    if not local_model:
        print("[!] No local model found to test switching!")
        # Just pick any model to test the flow
        if available_models:
            local_model = available_models[0]
            print(f"[*] Fallback to first available model: {local_model['id']}")
        else:
            return

    target_model_id = local_model["id"]
    print(f"[*] Target Model for Switch: {target_model_id} ({local_model.get('provider', 'unknown')})")

    # 2. Simulate sending a message with this model
    # This mimics api.sendMessage in apiService.ts which adds ?model=... or body param
    print(f"[-] Sending message with model={target_model_id}...")
    
    payload = {
        "content": "Hello, this is a test message from App Simulation.",
        "request_id": "test_sim_001",
        "conversation_id": "test_sim_session"
    }
    
    # Note: apiService.ts sends model as query param: ?model=...
    params = {
        "model": target_model_id,
        "stream": False
    }

    try:
        resp = requests.post(
            f"{BASE_URL}/api/v1/message", 
            json=payload, 
            params=params,
            timeout=30
        )
        
        if resp.status_code == 200:
            res_data = resp.json()
            reply = res_data.get("data", {}).get("reply") or res_data.get("reply")
            print(f"[+] Message sent successfully.")
            print(f"[+] Reply received: {reply[:100]}..." if reply else "[+] Reply received (empty)")
            
            # Check if response indicates which model was used (if available in debug headers or logs)
            # For now, we assume success if we get a 200 OK and a reply.
        else:
            print(f"[!] Message failed with status {resp.status_code}")
            print(f"[!] Response: {resp.text}")

    except Exception as e:
        print(f"[!] Exception during message send: {e}")

if __name__ == "__main__":
    test_model_switch_flow()
