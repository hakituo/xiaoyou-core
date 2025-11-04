#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (c) 2025 Leslie Qi

import asyncio
import websockets
import json
import time
import logging
from collections import defaultdict

from core.llm_connector import query_model, task_manager
from memory.memory_manager import MemoryManager
from core.utils import tts_generate

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Connection management
global_clients = set()
# Use dictionary to store MemoryManager instances for each user
user_memory_map = defaultdict(lambda: MemoryManager(user_id="default", max_length=10, auto_save_interval=300))
# Heartbeat time records
socket_heartbeats = {}
# Maximum connections
MAX_CONNECTIONS = 10
# Heartbeat interval (seconds)
HEARTBEAT_INTERVAL = 30
# Heartbeat timeout (seconds)
HEARTBEAT_TIMEOUT = 60

async def broadcast(msg, exclude_client=None):
    """Optimized broadcast function that supports excluding specific clients and error handling"""
    if not global_clients:
        return
    
    # Filter out possibly closed connections
    # Use getattr for safe checking, compatible with different WebSocket implementations
    active_clients = []
    for c in global_clients:
        try:
            # Try to check if connection is still open
            # For websockets library, use socket property or other methods to determine
            if hasattr(c, 'closed'):
                if not c.closed:
                    active_clients.append(c)
            elif hasattr(c, 'socket') and c.socket:
                active_clients.append(c)
            elif hasattr(c, 'connection') and c.connection:
                active_clients.append(c)
            else:
                # If unable to determine, try sending a ping or simple message
                # But for safety, keep the connection by default
                active_clients.append(c)
        except:
            # If check fails, exclude this connection
            pass
    
    # Update global client set
    global_clients.clear()
    global_clients.update(active_clients)
    
    if not active_clients:
        return
    
    # Create list of send tasks
    send_tasks = []
    for client in active_clients:
        if client != exclude_client:
            send_tasks.append(send_with_retry(client, json.dumps(msg)))
    
    if send_tasks:
        # Execute all send tasks asynchronously
        results = await asyncio.gather(*send_tasks, return_exceptions=True)
        # Handle failed sending cases
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Failed to broadcast message to client: {result}")

async def send_with_retry(websocket, message, max_retries=2):
    """Message sending function with retry mechanism and connection status pre-check"""
    # Validate inputs
    if not websocket or not message:
        logger.error("Invalid websocket or message parameter")
        return False
    
    # Check connection status first
    if hasattr(websocket, 'closed') and websocket.closed:
        logger.warning("Connection closed, skipping sending")
        return False
    
    retries = 0
    while retries <= max_retries:
        try:
            # Use shield to prevent cancellation from affecting sending
            await asyncio.shield(websocket.send(message))
            return True
        except (websockets.exceptions.ConnectionClosedError, websockets.exceptions.ConnectionClosedOK) as conn_err:
            # Connection closed, stop retrying
            logger.warning(f"Connection closed, stopping retry: {conn_err}")
            return False
        except asyncio.TimeoutError:
            # Handle timeout specifically
            logger.warning(f"Message send timeout, retrying ({retries}/{max_retries})")
        except Exception as e:
            logger.error(f"Failed to send message: {e}")

        retries += 1
        if retries > max_retries:
            logger.error(f"Failed to send message, reached maximum retry attempts: {e}")
            # No longer throw exceptions to avoid task failure
            return False
        logger.warning(f"Failed to send message, retrying ({retries}/{max_retries}): {e}")
        # Exponential backoff with jitter
        await asyncio.sleep(0.5 * (1.5 ** (retries - 1)))
    
    return False

async def handle_message(websocket, data):
    """Process received messages using task manager to limit concurrency"""
    platform = data.get("platform", "unknown")
    user_id = data.get("user_id", "web")
    text = data.get("message", "").strip()
    
    # Skip empty messages
    if not text:
        return
    
    try:
        # Check if it's a file upload message
        if data.get("file_info"):
            file_info = data["file_info"]
            file_name = file_info.get("name", "Unknown file")
            file_size = file_info.get("size", 0)
            
            logger.info(f"Received file upload request - User: {user_id}, File name: {file_name}, Size: {file_size} bytes")
            
            # Since Qianwen 3max model may not directly support file processing, we provide a friendly response
            file_response = f"I have received your uploaded file '{file_name}'. Currently, the Qianwen 3max model supports processing text content. If you would like me to analyze the file content, please describe the key information in the file, and I will do my best to help you."
            
            # Get or create memory manager for the user
            user_memory = user_memory_map[user_id]
            
            # Add messages to history
            user_memory.add_message("user", text)
            user_memory.add_message("assistant", file_response)
            
            # Prepare response data
            msg_data = {
                "type": "message",
                "platform": platform,
                "user_id": user_id,
                "text": text,
                "response": file_response,
                "timestamp": time.time()
            }
            
            # Send response to client
            await send_with_retry(websocket, json.dumps(msg_data))
            return
        
        # Check if it's a heartbeat message
        if text == "__heartbeat__":
            socket_heartbeats[websocket] = time.time()
            await websocket.send(json.dumps({"type": "heartbeat"}))
            return
        
        # Get or create memory manager for the user
        user_memory = user_memory_map[user_id]
        
        # Use task manager to limit concurrent requests
        response = await task_manager.run_task(query_model(text, user_memory))
        
        # Asynchronously generate TTS without blocking the response
        tts_path = ""
        try:
            tts_path = await tts_generate(response)
        except Exception as e:
            logger.error(f"Failed to generate TTS: {e}")
            # Continue processing response even if TTS fails
        
        # Add message to history
        user_memory.add_message("user", text)
        user_memory.add_message("assistant", response)
        
        # Prepare response data
        msg_data = {
            "type": "message",
            "platform": platform,
            "user_id": user_id,
            "text": text,
            "response": response,
            "tts": tts_path,
            "audio_file": tts_path.split('/')[-1] if tts_path else None,  # Add audio_file field containing only the file name
            "timestamp": time.time()
        }
        
        # Send response to current client
        await send_with_retry(websocket, json.dumps(msg_data))
        
        # Broadcast message to other clients
        await broadcast(msg_data, exclude_client=websocket)
        
        logger.info(f"Message processing completed - User: {user_id}, Platform: {platform}, Message length: {len(text)}")
    
    except json.JSONDecodeError:
        error_msg = "Invalid JSON format"
        await websocket.send(json.dumps({"type": "error", "message": error_msg}))
        logger.error(f"JSON parsing error: {data}")
    except Exception as e:
        error_msg = f"Error processing message: {str(e)}"
        await websocket.send(json.dumps({"type": "error", "message": error_msg}))
        logger.error(f"Error processing message: {e}", exc_info=True)

async def handler(websocket):
    """Optimized WebSocket connection handling function"""
    # Check connection limit
    if len(global_clients) >= MAX_CONNECTIONS:
        await websocket.send(json.dumps({"type": "error", "message": "Connection limit reached, please try again later"}))
        await websocket.close()
        logger.warning("Rejected new connection, maximum connection limit reached")
        return
    
    # Add to client set
    global_clients.add(websocket)
    socket_heartbeats[websocket] = time.time()
    client_ip = websocket.remote_address[0] if websocket.remote_address else "unknown"
    logger.info(f"New client connected: {client_ip}, Current connections: {len(global_clients)}")
    
    try:
        # Send welcome message
        await websocket.send(json.dumps({
            "type": "welcome", 
            "message": "Connection successful, welcome to Xiaoyou AI!",
            "version": "1.0.0"
        }))
        
        # Message handling loop
        async for message in websocket:
            try:
                data = json.loads(message)
                # Process messages asynchronously to avoid blocking, use task for better tracking
                task = asyncio.create_task(handle_message(websocket, data))
                # Add exception handling to avoid uncaught task exceptions
                task.add_done_callback(lambda t: logger.error(f"Message processing task exception: {t.exception()}") if t.exception() else None)
            except json.JSONDecodeError:
                await websocket.send(json.dumps({"type": "error", "message": "Invalid JSON format"}))
    except websockets.exceptions.ConnectionClosedError as e:
        logger.info(f"Client connection closed abnormally: {client_ip}, Error code: {e.code}, Reason: {e.reason}")
    except websockets.exceptions.ConnectionClosedOK:
        logger.info(f"Client connection closed normally: {client_ip}")
    except Exception as e:
        logger.error(f"Error occurred while handling client: {e}", exc_info=True)
    finally:
        # Clean up resources
        global_clients.discard(websocket)
        socket_heartbeats.pop(websocket, None)
        logger.info(f"Client disconnected: {client_ip}, Current connections: {len(global_clients)}")

async def heartbeat_checker():
    """Periodically check connection heartbeats and clean up timed-out connections"""
    while True:
        try:
            current_time = time.time()
            to_close = []
            
            # Find timed-out connections
            for websocket, last_heartbeat in socket_heartbeats.items():
                if current_time - last_heartbeat > HEARTBEAT_TIMEOUT:
                    to_close.append(websocket)
                    logger.info(f"Detected timed-out connection, preparing to close")
            
            # Close timed-out connections, using more appropriate error code 1001(going away) instead of 1008(policy violation)
            for websocket in to_close:
                try:
                    await websocket.close(code=1001, reason="Connection timed out")
                    socket_heartbeats.pop(websocket, None)
                    global_clients.discard(websocket)
                except Exception as e:
                    # Connection might already be closed, silently handle error
                    socket_heartbeats.pop(websocket, None)
                    global_clients.discard(websocket)
                    logger.debug(f"Failed to close timed-out connection (might already be closed): {e}")
            
            # Send heartbeat checks
            for websocket in list(global_clients):
                try:
                    # Safely check connection status
                    if hasattr(websocket, 'closed') and websocket.closed:
                        # Connection closed, clean up resources
                        socket_heartbeats.pop(websocket, None)
                        global_clients.discard(websocket)
                        continue
                    
                    # Use safer way to send heartbeat to avoid errors during transmission
                    await asyncio.shield(websocket.send(json.dumps({"type": "ping"})))
                except Exception as e:
                    # Connection might be closed, clean up resources
                    socket_heartbeats.pop(websocket, None)
                    global_clients.discard(websocket)
                    logger.debug(f"Failed to send heartbeat (connection might be closed): {e}")
            
            # Check at regular intervals
            await asyncio.sleep(HEARTBEAT_INTERVAL)
        except Exception as e:
            logger.error(f"Error in heartbeat check: {e}", exc_info=True)
            await asyncio.sleep(HEARTBEAT_INTERVAL)

async def main():
    """WebSocket server main function"""
    # Start heartbeat checker task
    asyncio.create_task(heartbeat_checker())
    
    # Configure WebSocket server
    server_config = {
        "host": "0.0.0.0",
        "port": 6789,
        "max_size": 1 * 1024 * 1024,  # Limit maximum message size to 1MB
        "ping_interval": None,  # Disable built-in ping, use custom heartbeat
        "ping_timeout": None,
    }
    
    try:
        async with websockets.serve(handler, **server_config):
            logger.info(f"WebSocket service started successfully: ws://{server_config['host']}:{server_config['port']}")
            logger.info(f"Maximum connection limit: {MAX_CONNECTIONS}")
            logger.info(f"Heartbeat interval: {HEARTBEAT_INTERVAL}s, Timeout: {HEARTBEAT_TIMEOUT}s")
            # Keep server running
            await asyncio.Future()
    except KeyboardInterrupt:
        logger.info("⚠️ WebSocket service stopping...")
    except Exception as e:
        logger.error(f"❌ WebSocket server error: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⚠️ WebSocket service stopped (user interruption)")
    except Exception as e:
        logger.critical(f"❌ WebSocket service failed to start: {e}", exc_info=True)