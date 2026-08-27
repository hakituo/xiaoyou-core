
import os
import sys
import time
from fastapi.testclient import TestClient

import pytest

# Add project root to path
sys.path.append(os.getcwd())

pytestmark = pytest.mark.integration

if os.getenv("XIAOYOU_RUN_INTEGRATION_TESTS") != "1":
    pytest.skip(
        "需要设置 XIAOYOU_RUN_INTEGRATION_TESTS=1 才运行集成测试",
        allow_module_level=True,
    )

def test_main_app_response():
    print("Importing main app...", flush=True)
    try:
        from main import app
    except ImportError as e:
        print(f"Failed to import main app: {e}", flush=True)
        return

    print("Creating TestClient (this triggers lifespan startup)...", flush=True)
    # Using with block to ensure lifespan events (startup/shutdown) are triggered
    try:
        with TestClient(app) as client:
            print("App startup complete. Sending request...", flush=True)
            
            payload = {
                "content": "你好，测试主程序响应",
                "conversation_id": "test_real_app_user",
                "stream": True
            }
            
            start_time = time.time()
            try:
                # Using stream=True with TestClient is tricky, but we can iterate the response
                # Note: stream=True is a request kwarg, not client.stream() for TestClient usually
                # But recent Starlette/FastAPI TestClient uses httpx.
                response = client.post("/api/v1/message", json=payload)
                
                if response.status_code != 200:
                    print(f"Request failed with status {response.status_code}: {response.text}", flush=True)
                    return

                print("Response received. Reading stream...", flush=True)
                first_chunk = True
                for line in response.iter_lines():
                    if line:
                        if first_chunk:
                            print(f"First chunk received after {time.time() - start_time:.4f}s", flush=True)
                            first_chunk = False
                        # print(f"Chunk: {line}", flush=True)
                
                print(f"Stream finished. Total time: {time.time() - start_time:.4f}s", flush=True)
                
            except Exception as e:
                print(f"Request failed: {e}", flush=True)
                import traceback
                traceback.print_exc()
    except Exception as e:
        print(f"Startup failed: {e}", flush=True)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_main_app_response()
