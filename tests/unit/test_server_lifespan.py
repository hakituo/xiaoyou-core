import sys
import os
import logging
from fastapi.testclient import TestClient
import pytest


pytestmark = pytest.mark.integration


if os.getenv("XIAOYOU_RUN_INTEGRATION_TESTS") != "1":
    pytest.skip(
        "需要设置 XIAOYOU_RUN_INTEGRATION_TESTS=1 才运行集成测试",
        allow_module_level=True,
    )


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TEST_SERVER_LIFESPAN")

def test_server():
    sys.path.append(os.getcwd())
    from main import app
    print("Starting TestClient with lifespan...")
    
    # TestClient context manager triggers lifespan
    with TestClient(app) as client:
        print("Lifespan started. Sending request...")
        
        payload = {
            "content": "Hello, this is a test from lifespan server.",
            "conversation_id": "test_lifespan_user"
        }
        
        print(f"Sending request: {payload}")
        try:
            response = client.post("/api/v1/message", json=payload)
            print(f"Response Status: {response.status_code}")
            print(f"Response JSON: {response.json()}")
        except Exception as e:
            print(f"Request failed: {e}")
            import traceback
            traceback.print_exc()
            
    print("Lifespan finished.")

if __name__ == "__main__":
    test_server()
