import asyncio
import logging
import websockets
import time
from typing import Optional

from core.server.connection_manager import ConnectionManager, get_connection_manager
from core.server.handler import WebSocketHandler

logger = logging.getLogger(__name__)

class XiaoyouServer:
    """
    Main WebSocket Server class for Xiaoyou Core.
    """
    def __init__(self, host: str = "0.0.0.0", port: int = 6789):
        self.host = host
        self.port = port
        self.connection_manager = get_connection_manager()
        self.handler = WebSocketHandler(self.connection_manager)
        self.running = False
        self.start_time = time.time()
        
    async def start(self):
        self.running = True
        logger.info(f"Starting Xiaoyou Server on ws://{self.host}:{self.port}")
        
        # Tasks
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        maintenance_task = asyncio.create_task(self._maintenance_loop())
        
        server_config = {
            "max_size": 5 * 1024 * 1024, # 5MB
            "ping_interval": 20,
            "ping_timeout": 20
        }
        
        try:
            async with websockets.serve(self.handler.handle, self.host, self.port, **server_config):
                logger.info("Server started successfully.")
                logger.info("Supported messages: text_input, audio_input, system_status, heartbeat")
                await asyncio.Future() # Keep running
        except asyncio.CancelledError:
            logger.info("Server stopping...")
        except Exception as e:
            logger.critical(f"Server crashed: {e}", exc_info=True)
            raise
        finally:
            heartbeat_task.cancel()
            maintenance_task.cancel()
            self.running = False
            
    async def _heartbeat_loop(self):
        """Periodically check for client heartbeats."""
        while self.running:
            try:
                await asyncio.sleep(30)
                await self.connection_manager.check_heartbeats()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat loop error: {e}")
            
    async def _maintenance_loop(self):
        """Periodically log system status."""
        while self.running:
            try:
                await asyncio.sleep(300)
                uptime = time.time() - self.start_time
                hours, remainder = divmod(int(uptime), 3600)
                minutes, seconds = divmod(remainder, 60)
                
                logger.info(f"📊 System Status - Uptime: {hours}h {minutes}m {seconds}s, "
                           f"Active Users: {self.connection_manager.get_active_count()}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Maintenance loop error: {e}")

def run_server():
    """Entry point to run the server."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    server = XiaoyouServer()
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logger.info("Server stopped by user.")
    except Exception as e:
        logger.critical(f"Failed to start server: {e}")
