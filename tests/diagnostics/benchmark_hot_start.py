import asyncio
import websockets
import json
import requests
import time
import sys
import os
import subprocess
import psutil

import signal

# Configuration
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8000
BASE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"
WS_URL = f"ws://{SERVER_HOST}:{SERVER_PORT}/api/v1/ws"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def is_port_open(host, port):
    try:
        response = requests.get(f"http://{host}:{port}/health", timeout=1)
        return response.status_code == 200
    except Exception:
        return False

def start_server():
    print(f"Starting server from {PROJECT_ROOT}...")
    env = os.environ.copy()
    # Ensure we are using the venv python if possible, or sys.executable
    python_exe = sys.executable
    
    # We can set some env vars to disable heavy components if needed, 
    # but user wants to test "hot start" which might imply full system.
    # For now, let's run as is, or maybe disable Forge/TTS if they are not needed for LLM text chat.
    # But the user mentioned "5070 graphics card", so they probably have GPU enabled.
    
    cmd = [python_exe, "main.py"]
    process = subprocess.Popen(
        cmd,
        cwd=PROJECT_ROOT,
        env=env,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    )
    return process

async def measure_round(websocket, round_idx):
    print(f"\n--- Round {round_idx} ---")
    request_id = f"latency_test_{int(time.time() * 1000)}"
    msg = {
        "type": "message",
        "content": "你好，请用一句话介绍你自己。",
        "conversation_id": f"latency_test_conv_{int(time.time())}",
        "message_id": str(int(time.time())),
        "request_id": request_id
    }
    
    print(f"Sending: {msg['content']}")
    t_send = time.time()
    ack_time = None
    first_token_time = None
    first_llm_ttft = None
    response_text = ""
    
    await websocket.send(json.dumps(msg))
    
    print("Waiting for response...")
    while True:
        try:
            resp = await asyncio.wait_for(websocket.recv(), timeout=60.0)
            data = json.loads(resp)
            
            msg_type = data.get('type')
            resp_request_id = data.get("request_id")
            
            if resp_request_id and resp_request_id != request_id:
                continue
                
            if msg_type == 'message':
                subtype = data.get('subtype')
                if subtype == 'acknowledged':
                    if ack_time is None:
                        ack_time = time.time() - t_send
                        print(f"Ack received in {ack_time:.4f}s")
                elif subtype == 'response_chunk':
                    content = data.get('content', '')
                    is_backchannel = bool(data.get("backchannel"))
                    
                    if content and (not is_backchannel):
                        if first_token_time is None:
                            first_token_time = time.time() - t_send
                            print(f"First visible token (User Latency) in {first_token_time:.4f}s")
                        
                        sys.stdout.write(content)
                        sys.stdout.flush()
                        response_text += content
                elif subtype == 'response_done':
                    total_time = time.time() - t_send
                    print(f"\nResponse done. Total time: {total_time:.4f}s")
                    break
            elif msg_type == 'debug':
                if data.get("subtype") == "ttft_info" and first_llm_ttft is None:
                    first_llm_ttft = data.get("ttft")
                    print(f"\n[Server Log] LLM Internal TTFT: {float(first_llm_ttft):.4f}s")
            elif msg_type == 'error':
                print(f"\nError: {data.get('message')}")
                break
                
        except asyncio.TimeoutError:
            print("\nTimeout waiting for response")
            break
            
    return {
        "round": round_idx,
        "ack_time": ack_time,
        "first_token_time": first_token_time,
        "llm_ttft": first_llm_ttft,
        "total_time": time.time() - t_send
    }

async def run_test():
    server_process = None
    server_started_by_script = False
    
    try:
        # 1. Check/Start Server
        if not is_port_open(SERVER_HOST, SERVER_PORT):
            print("Server not running. Starting it...")
            server_process = start_server()
            server_started_by_script = True
            
            # Wait for start
            print("Waiting for server to be ready (timeout 60s)...")
            start_wait = time.time()
            ready = False
            while time.time() - start_wait < 60:
                if is_port_open(SERVER_HOST, SERVER_PORT):
                    ready = True
                    break
                time.sleep(1)
            
            if not ready:
                print("Server failed to start in time.")
                return
            print(f"Server ready in {time.time() - start_wait:.2f}s")
            # Give it a bit more time to initialize internal components
            await asyncio.sleep(5)
        else:
            print("Server already running. Connecting...")

        # 2. Run Benchmark
        print(f"Connecting to {WS_URL}...")
        async with websockets.connect(WS_URL) as websocket:
            print("Connected! Starting latency test...")
            
            results = []
            # Run 3 rounds
            for i in range(1, 4):
                res = await measure_round(websocket, i)
                results.append(res)
                print("\nWaiting 2s before next round...")
                await asyncio.sleep(2)
                
            print("\n\n=== Latency Test Results ===")
            print(f"{'Round':<10} {'Ack (s)':<15} {'User TTFT (s)':<15} {'LLM TTFT (s)':<15} {'Total (s)':<15}")
            print("-" * 70)
            for r in results:
                ack = f"{r['ack_time']:.4f}" if r['ack_time'] else "N/A"
                ft = f"{r['first_token_time']:.4f}" if r['first_token_time'] else "N/A"
                lt = f"{float(r['llm_ttft']):.4f}" if r['llm_ttft'] else "N/A"
                tot = f"{r['total_time']:.4f}"
                print(f"{r['round']:<10} {ack:<15} {ft:<15} {lt:<15} {tot:<15}")

    except Exception as e:
        print(f"Test failed: {e}")
    finally:
                if server_started_by_script and server_process:
                    print("Stopping server gracefully...")
                    try:
                        if sys.platform == "win32":
                            server_process.send_signal(signal.CTRL_C_EVENT)
                        else:
                            server_process.send_signal(signal.SIGINT)
                    except Exception as e:
                        print(f"Failed to send signal: {e}")
                        server_process.terminate()

                    try:
                        server_process.wait(timeout=15)
                        print("Server stopped gracefully.")
                    except subprocess.TimeoutExpired:
                        print("Server did not stop in time. Forcing termination...")
                        server_process.terminate()
                        try:
                            server_process.wait(timeout=5)
                        except Exception:
                            server_process.kill()
                        print("Server forced stopped.")

if __name__ == "__main__":
    asyncio.run(run_test())
