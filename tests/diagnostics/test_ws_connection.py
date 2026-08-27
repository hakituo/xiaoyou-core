import asyncio
import websockets
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

async def test_connection():
    # Get server configuration
    host = os.getenv("XIAOYOU_SERVER_HOST", "127.0.0.1")
    if host == "0.0.0.0":
        host = "127.0.0.1"
    port = os.getenv("XIAOYOU_SERVER_PORT", "8000")
    
    # Construct WebSocket URL
    uri = f"ws://{host}:{port}/api/v1/ws"
    print(f"Attempting to connect to {uri}...")
    
    # Get token if configured
    token = os.getenv("XIAOYOU_SECURITY_WEB_ACCESS_TOKEN")
    headers = {}
    if token:
        print(f"Using access token: {token[:3]}***")
        headers["Authorization"] = f"Bearer {token}"
    
    try:
        async with websockets.connect(uri, extra_headers=headers) as websocket:
            print("Successfully connected to WebSocket server!")
            
            # Send a test message
            await websocket.send('{"type": "ping", "request_id": "test_ping"}')
            print("Sent ping message")
            
            # Wait for response
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                print(f"Received response: {response}")
            except asyncio.TimeoutError:
                print("Timeout waiting for response")
                
            # Keep connection open for a bit to allow server to see it
            print("Holding connection for 5 seconds...")
            await asyncio.sleep(5)
            
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    # Check if websockets is installed
    try:
        import websockets
        asyncio.run(test_connection())
    except ImportError:
        print("Error: 'websockets' package is not installed. Please install it using 'pip install websockets'")
