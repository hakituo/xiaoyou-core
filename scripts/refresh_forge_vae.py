import requests
import json
import time

url = "http://127.0.0.1:7860"

def main():
    print("Refreshing VAEs...")
    try:
        # Trigger refresh
        res = requests.post(f"{url}/sdapi/v1/refresh-vae")
        
        time.sleep(1)
        
        # Get List
        res = requests.get(f"{url}/sdapi/v1/sd-vae")
        vaes = res.json()
        print(f"Raw response: {json.dumps(vaes, indent=2)}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
