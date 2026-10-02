import requests
import json
import sys

# 配置
BASE_URL = "http://127.0.0.1:8000"
API_URL = f"{BASE_URL}/api/v1/system/preferences"

def test_update_preferences():
    print(f"Testing API: {API_URL}")
    
    # 1. 获取当前偏好
    try:
        resp = requests.get(API_URL)
        if resp.status_code != 200:
            print(f"Failed to get preferences: {resp.status_code} {resp.text}")
            return False
        
        current_prefs = resp.json().get('data', {})
        print(f"Current preferences: {json.dumps(current_prefs, indent=2, ensure_ascii=False)}")
        
        original_mode = current_prefs.get('mode', 'normal')
    except Exception as e:
        print(f"Error connecting to API: {e}")
        return False

    # 2. 切换到 study 模式
    print("\nSwitching to STUDY mode...")
    payload = {"mode": "study"}
    try:
        resp = requests.post(API_URL, json=payload)
        if resp.status_code != 200:
            print(f"Failed to update preferences: {resp.status_code} {resp.text}")
            return False
        
        data = resp.json()
        print(f"Update response: {json.dumps(data, indent=2, ensure_ascii=False)}")
        
        if data.get('data', {}).get('mode') != 'study':
            print("❌ Mode update failed in response data")
            return False
            
    except Exception as e:
        print(f"Error updating preferences: {e}")
        return False

    # 3. 验证是否已保存
    print("\nVerifying update...")
    try:
        resp = requests.get(API_URL)
        new_prefs = resp.json().get('data', {})
        if new_prefs.get('mode') != 'study':
            print(f"❌ Verification failed. Expected 'study', got '{new_prefs.get('mode')}'")
            return False
        else:
            print("✅ Verification successful: Mode is 'study'")
    except Exception as e:
        print(f"Error verifying: {e}")
        return False

    # 4. 恢复原始模式
    print(f"\nRestoring original mode: {original_mode}...")
    try:
        requests.post(API_URL, json={"mode": original_mode})
        print("✅ Restored.")
    except Exception as e:
        print(f"Error restoring: {e}")
    
    return True

if __name__ == "__main__":
    success = test_update_preferences()
    if success:
        print("\n🎉 Test Passed!")
        sys.exit(0)
    else:
        print("\n💥 Test Failed!")
        sys.exit(1)
