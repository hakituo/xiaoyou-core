import sys
import asyncio
import logging
import signal
import gc
import os
import subprocess
import time
import multiprocessing

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("startup.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Add project path to system path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Low-spec computer optimization: reduce memory usage
gc.set_threshold(5000, 10, 10)  # Adjust garbage collection thresholds

# Try to set process priority (Windows system)
try:
    if sys.platform == 'win32':
        import win32api
        import win32process
        import win32con
        # Set to below normal priority but not the lowest to maintain responsiveness
        win32process.SetPriorityClass(
            win32api.GetCurrentProcess(), 
            win32process.BELOW_NORMAL_PRIORITY_CLASS
        )
        logger.info("Process priority has been set to below normal")
except Exception as e:
    logger.warning(f"Failed to set process priority: {e}")

# Process management
global_processes = []



# Graceful shutdown handling
def signal_handler(sig, frame):
    logger.info(f"Received signal {sig}, preparing to exit...")
    
    # Stop all child processes
    for proc in global_processes:
        try:
            if proc.is_alive():
                logger.info(f"Terminating process: {proc.name}")
                proc.terminate()
                proc.join(timeout=3)  # Wait for process to end, maximum 3 seconds
        except Exception as e:
            logger.error(f"Failed to terminate process: {e}")
    
    # Trigger garbage collection
    gc.collect()
    logger.info("Resources cleaned up, exiting program")
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Function to start Flask application
def start_flask_app():
    try:
        logger.info("Starting Flask application...")
        # Directly import app.py module
        from app import app
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Failed to start Flask application: {e}", exc_info=True)
        sys.exit(1)

async def main_with_error_handling():
    try:
        # Theme selection no longer needed, start services directly
        logger.info("Preparing to start services...")
        
        # Start Flask application process
        flask_process = multiprocessing.Process(target=start_flask_app, name='FlaskApp')
        flask_process.daemon = True  # Set as daemon process, will automatically terminate when main process ends
        flask_process.start()
        global_processes.append(flask_process)
        logger.info("Flask application process has started")
        
        # Wait for Flask application initialization
        time.sleep(2)
        
        # Lazy import to reduce memory usage during startup
        from ws_server import main
        
        logger.info("Starting WebSocket service...")
        # Start WebSocket server
        await main()
    except ImportError as e:
        logger.error(f"Failed to start service: {e}")
    except asyncio.CancelledError:
        logger.info("Task cancelled")
    except Exception as e:
        logger.error(f"Failed to start service: {e}", exc_info=True)
    finally:
        # Clean up resources
        for proc in global_processes:
            try:
                if proc.is_alive():
                    proc.terminate()
            except:
                pass
        gc.collect()
        logger.info("Program exited normally")

if __name__ == "__main__":
    logger.info("Xiaoyou AI system one-click startup in progress...")
    logger.info("Preparing to start Flask application and WebSocket service...")
    
    try:
        # Disable multiprocessing fork mode, use spawn mode which is safer
        multiprocessing.set_start_method('spawn', force=True)
    except RuntimeError:
        # Ignore if already set
        pass
    
    try:
        # Use more efficient event loop
        if sys.version_info >= (3, 7):
            asyncio.run(main_with_error_handling())
        else:
            # Compatible with older Python versions
            loop = asyncio.get_event_loop()
            try:
                loop.run_until_complete(main_with_error_handling())
            finally:
                try:
                    loop.shutdown_asyncgens()
                    loop.close()
                except:
                    pass
    except KeyboardInterrupt:
        logger.info("User interrupted program")
        # Clean up all processes
        for proc in global_processes:
            try:
                if proc.is_alive():
                    proc.terminate()
            except:
                pass
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        # Clean up all processes
        for proc in global_processes:
            try:
                if proc.is_alive():
                    proc.terminate()
            except:
                pass
        sys.exit(1)
