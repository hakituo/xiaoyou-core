import requests
import websocket
import json
import time
import threading

# Configuration
BASE_URL = "http://127.0.0.1:8000"
WS_URL = "ws://127.0.0.1:8000/api/v1/ws"


def print_status(component, status, details=""):
    symbol = "✅" if status else "❌"
    print(f"{symbol} [{component}]: {details}")


def check_http_health():
    try:
        # 1. Check Root/Docs
        try:
            r = requests.get(f"{BASE_URL}/docs", timeout=5)
            print_status(
                "HTTP Server", r.status_code == 200, f"Status: {r.status_code}"
            )
        except Exception as e:
            print_status("HTTP Server", False, f"Connection Failed: {e}")
            return False

        # 2. Check Health Endpoint
        try:
            r = requests.get(f"{BASE_URL}/health", timeout=5)
            if r.status_code == 200:
                data = r.json()
                print_status("Health API", True, "Response received")

                # Check Services
                services = data.get("services", {})
                for svc, status in services.items():
                    print(f"   - Service {svc}: {status}")
            else:
                print_status("Health API", False, f"Status: {r.status_code}")
        except Exception as e:
            print_status("Health API", False, f"Error: {e}")

        # 3. Check System Stats (User mentioned seeing CPU/GPU, so this likely works)
        try:
            r = requests.get(f"{BASE_URL}/api/v1/system/stats", timeout=5)
            if r.status_code == 200:
                print_status("System Stats API", True, "Data received")
            else:
                print_status("System Stats API", False, f"Status: {r.status_code}")
        except Exception as e:
            print_status("System Stats API", False, f"Error: {e}")

        return True
    except Exception as e:
        print(f"Critical Error in HTTP Check: {e}")
        return False


def check_websocket():
    print("\nChecking WebSocket Connection...")
    ws_result = {"connected": False, "message_received": False}

    def on_message(ws, message):
        print(f"   Received WS Message: {message[:100]}...")
        ws_result["message_received"] = True
        ws.close()

    def on_error(ws, error):
        print(f"   WS Error: {error}")

    def on_close(ws, close_status_code, close_msg):
        print("   WS Closed")

    def on_open(ws):
        print("   WS Connection Opened")
        ws_result["connected"] = True
        # Send a ping or hello
        payload = {"type": "ping", "timestamp": time.time()}
        ws.send(json.dumps(payload))
        print("   Sent Ping")

    # Run WS in thread to not block
    ws = websocket.WebSocketApp(
        WS_URL + "?client_id=diagnostic_script",
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    wst = threading.Thread(target=ws.run_forever)
    wst.daemon = True
    wst.start()

    # Wait for connection
    time.sleep(3)

    print_status("WebSocket Connect", ws_result["connected"], "Connected to " + WS_URL)
    if ws_result["connected"]:
        # Wait a bit more for message
        time.sleep(2)
        print_status(
            "WebSocket Receive",
            ws_result["message_received"],
            "Received response from server",
        )

    if ws.keep_running:
        ws.close()


if __name__ == "__main__":
    print("=== Backend Diagnostic Tool ===\n")
    print("Ensuring server is running...")

    if check_http_health():
        check_websocket()
    else:
        print("\nCould not connect to HTTP server. Is the application running?")
        print("Please start XiaoyouCore.exe first, then run this script.")

    print("\n=== Diagnosis Complete ===")
