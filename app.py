from flask import Flask, render_template, send_from_directory, request, jsonify
import os
import sys
import gc
import logging
import time
from datetime import timedelta
from functools import wraps
from collections import deque
from threading import Lock

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("flask_app.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Ensure Flask knows your templates folder is nearby
app = Flask(__name__, static_folder='static') 

# Configure static file cache time
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = timedelta(days=1)

# Performance optimization configuration
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Limit request body size to 16MB
app.config['TEMPLATES_AUTO_RELOAD'] = False  # Disable template auto-reloading

# Global variables for rate limiting
rate_limit_data = deque(maxlen=100)  # Store recent request times
rate_limit_lock = Lock()
RATE_LIMIT_WINDOW = 60  # 60 seconds
RATE_LIMIT_MAX_REQUESTS = 60  # Maximum 60 requests per minute

# Memory monitoring
last_gc_time = time.time()
GC_INTERVAL = 300  # Garbage collection every 5 minutes

# Cache decorator (commented out unused code)
# class SimpleCache:
#     def __init__(self, timeout=3600):
#         self.cache = {}
#         self.timeout = timeout
#         self.lock = Lock()
#     
#     def __call__(self, f):
#         @wraps(f)
#         def decorated_function(*args, **kwargs):
#             key = f.__name__ + str(args[:2]) + str(tuple(sorted(kwargs.items())[:2]))
#             
#             with self.lock:
#                 current_time = time.time()
#                 if key in self.cache:
#                     value, timestamp = self.cache[key]
#                     if current_time - timestamp < self.timeout:
#                         return value
#             
#             result = f(*args, **kwargs)
#             
#             if result and sys.getsizeof(result) < 1024 * 1024:
#                 with self.lock:
#                     self.cache[key] = (result, time.time())
#                     if len(self.cache) > 100:
#                         self._cleanup()
#             
#             return result
#         
#         def _cleanup(self):
#             current_time = time.time()
#             self.cache = {k: v for k, v in self.cache.items() if current_time - v[1] < self.timeout}
#         
#         decorated_function._cleanup = lambda: _cleanup(self)
#         return decorated_function

# Cache instance (not currently used)

# Memory optimization middleware - simplified version
@app.before_request
def before_request():
    global last_gc_time
    current_time = time.time()
    
    # Regularly trigger garbage collection
    if current_time - last_gc_time > GC_INTERVAL:
        try:
            gc.collect()
            last_gc_time = current_time
            logger.info("Garbage collection completed")
        except Exception as e:
            logger.error(f"Failed to perform garbage collection: {e}")

# Rate limiting decorator
def rate_limit():
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            current_time = time.time()
            
            with rate_limit_lock:
                # Remove expired request records
                while rate_limit_data and current_time - rate_limit_data[0] > RATE_LIMIT_WINDOW:
                    rate_limit_data.popleft()
                
                # Check if rate limit is exceeded
                if len(rate_limit_data) >= RATE_LIMIT_MAX_REQUESTS:
                    logger.warning(f"Rate limit triggered: {request.remote_addr}")
                    return jsonify({"error": "Too many requests, please try again later"}), 429
                
                # Record new request
                rate_limit_data.append(current_time)
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Error handling
@app.errorhandler(404)
def page_not_found(e):
    logger.warning(f"404 error: {request.path} - {request.remote_addr}")
    return render_template("error.html", error="Page not found"), 404

@app.errorhandler(413)
def request_entity_too_large(e):
    logger.warning(f"Request body too large: {request.path} - {request.remote_addr}")
    return jsonify({"error": "Request body too large"}), 413

@app.errorhandler(Exception)
def internal_server_error(e):
    logger.error(f"Internal server error: {str(e)}", exc_info=True)
    return render_template("error.html", error="Internal server error"), 500

@app.route("/")
@rate_limit()
def index():
    # Render the new ultimate sci-fi interface
    logger.info("Using template: ultimate_xiaoyou_optimized.html")
    return render_template('ultimate_xiaoyou_optimized.html')

# Add a route to serve static audio files from the voice directory
@app.route('/voice/<path:filename>')
@rate_limit()
def serve_voice(filename):
    voice_dir = os.path.join(app.root_path, 'voice')
    
    # Security check: prevent directory traversal attacks
    if '..' in filename or '\\' in filename:
        logger.warning(f"Security warning: attempt to access illegal path: {filename} - {request.remote_addr}")
        return jsonify({"error": "Access denied"}), 403
    
    try:
        response = send_from_directory(voice_dir, filename)
        # Additional cache control
        response.headers['Cache-Control'] = 'public, max-age=86400'
        return response
    except Exception as e:
        logger.error(f"Failed to serve audio file: {filename} - {str(e)}")
        return jsonify({"error": "File not found"}), 404

# Health check endpoint
@app.route('/health')
def health_check():
    return jsonify({
        "status": "healthy",
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.0.0"
    })

# Resource cleanup function
def cleanup_resources():
    # Force garbage collection
    try:
        gc.collect()
    except Exception as e:
        logger.error(f"Failed to perform garbage collection during resource cleanup: {e}")

if __name__ == "__main__":
    try:
        # Final optimization configuration for low-spec computers
        app.run(
            host="0.0.0.0", 
            port=5000, 
            debug=False, 
            threaded=True,
            processes=1,  # Single process mode to reduce memory usage
            use_reloader=False,  # Disable reloader to reduce resource usage
            load_dotenv=False,  # Disable dotenv loading to improve startup speed
            passthrough_errors=False  # Capture all errors
        )
    except KeyboardInterrupt:
        logger.info("Flask application interrupted by user")
        cleanup_resources()
    except Exception as e:
        logger.critical(f"Failed to start Flask application: {e}", exc_info=True)
        cleanup_resources()
        sys.exit(1)