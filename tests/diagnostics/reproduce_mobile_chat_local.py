import asyncio
import websockets
import json
import time
import sys

# Color codes for output
GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"

async def receive_response(websocket, timeout=60.0):
    full_response = ""
    start_time = time.time()
    
    while True:
        try:
            remaining = timeout - (time.time() - start_time)
            if remaining <= 0:
                print("\nTimeout waiting for response.")
                break
                
            response = await asyncio.wait_for(websocket.recv(), timeout=remaining)
            data = json.loads(response)
            msg_type = data.get("type")
            
            if msg_type == "token":
                content = data.get("content", "")
                full_response += content
                print(content, end="", flush=True)
                
            elif msg_type == "chat_stream_end":
                print("\n[Stream Ended]")
                break
                
            elif msg_type == "error":
                print(f"\n{RED}❌ Received Error: {data.get('message')}{RESET}")
                return None
                
        except asyncio.TimeoutError:
            print("\nTimeout waiting for response.")
            break
        except websockets.exceptions.ConnectionClosed:
            print("\nConnection closed.")
            break
        except Exception as e:
            print(f"\nError receiving: {e}")
            break
            
    return full_response

async def reproduce_chat_local_param():
    uri = "ws://localhost:8000/api/v1/ws?client_id=mobile_chat_tester"
    
    print(f"Connecting to {uri}...")
    try:
        async with websockets.connect(uri) as websocket:
            print(f"{GREEN}Connected.{RESET}")
            
            # --- TEST 1: Cloud Mode ---
            print("\n" + "="*50)
            print("TEST 1: Global Cloud Mode")
            print("="*50)
            
            print("1. Setting global config to CLOUD (DeepSeek)...")
            setup_msg = {
                "type": "update_settings",
                "settings": {"llm": {"provider": "deepseek", "model": "deepseek-chat"}},
                "request_id": "setup_cloud_001",
                "_send_ts": time.time() * 1000
            }
            await websocket.send(json.dumps(setup_msg))
            await asyncio.sleep(1) # Wait for settings to propagate
            
            print("2. Sending Chat Request (Implicit Cloud)...")
            chat_msg_cloud = {
                "type": "chat",
                "content": "Who are you? (Cloud Test)",
                "model": "cloud:deepseek", # Explicitly request cloud
                "request_id": "test_chat_cloud_001",
                "conversation_id": "test_conv_cloud",
                "_send_ts": time.time() * 1000
            }
            await websocket.send(json.dumps(chat_msg_cloud))
            
            print("Listening for Cloud response...")
            resp_cloud = await receive_response(websocket)
            if resp_cloud:
                print(f"\n{GREEN}✅ Cloud Response Received{RESET}")
            else:
                print(f"\n{RED}❌ Cloud Response Failed{RESET}")


            # --- TEST 2: Local Mode (Override) ---
            print("\n" + "="*50)
            print("TEST 2: Local Mode Override")
            print("="*50)
            print("Global config is still Cloud. Now sending chat request with model='local'...")
            
            chat_msg_local = {
                "type": "chat",
                "content": "Who are you? (Local Test)",
                "model": "local",  # <--- CRITICAL PARAMETER
                "request_id": "test_chat_local_001",
                "conversation_id": "test_conv_local",
                "_send_ts": time.time() * 1000
            }
            await websocket.send(json.dumps(chat_msg_local))
            
            print("Listening for Local response...")
            resp_local = await receive_response(websocket)
            
            if resp_local:
                print(f"\n{GREEN}✅ Local Response Received{RESET}")
                # We can't easily verify WHICH model generated it without parsing content or logs,
                # but getting a response is the first step.
            else:
                print(f"\n{RED}❌ Local Response Failed{RESET}")

            print("\n\n--- Test Finished ---")
            print("Please check server logs to confirm:")
            print("1. Test 1 used Cloud provider")
            print("2. Test 2 used Local provider (and was NOT overridden)")

    except Exception as e:
        print(f"{RED}❌ Connection/Runtime Error: {e}{RESET}")

if __name__ == "__main__":
    asyncio.run(reproduce_chat_local_param())
