import asyncio
import websockets
import json
import requests
import time
import sys

def _pick_base_url() -> str:
    candidates = [f"http://localhost:{p}" for p in range(8000, 8051)]
    for base in candidates:
        try:
            r = requests.get(f"{base}/health", timeout=1.0)
            if r.status_code == 200:
                return base
        except Exception:
            pass
    return candidates[0]

BASE_URL = _pick_base_url()
WS_URL = BASE_URL.replace("http://", "ws://") + "/api/v1/ws"

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

async def main():
    print(f"Connecting to {WS_URL}...")
    try:
        async with websockets.connect(WS_URL) as websocket:
            print("Connected! Starting latency test...")
            
            results = []
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
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
