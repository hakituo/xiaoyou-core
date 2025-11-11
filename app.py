from flask import Flask, render_template, send_from_directory, request, jsonify
import os
import sys
import gc
import logging
import time
import uuid
from datetime import timedelta
from functools import wraps
from collections import deque
from threading import Lock
from werkzeug.utils import secure_filename

# 导入配置
from config.config import Config
config = Config()

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(config.LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Ensure Flask knows your templates folder is nearby
app = Flask(__name__, static_folder='static') 

# Configure static file cache time
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = timedelta(days=1)

# Performance optimization configuration
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
app.config['TEMPLATES_AUTO_RELOAD'] = False

# Global variables for rate limiting
rate_limit_data = deque(maxlen=100)  # Store recent request times
rate_limit_lock = Lock()
RATE_LIMIT_WINDOW = 60  # 60 seconds
RATE_LIMIT_MAX_REQUESTS = config.MAX_REQUESTS_PER_MINUTE

# Memory monitoring
last_gc_time = time.time()
GC_INTERVAL = 300  # Garbage collection every 5 minutes

# Upload configuration
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
ALLOWED_AUDIO_EXTENSIONS = {'wav', 'mp3', 'm4a', 'ogg'}
MAX_CONTENT_LENGTH = config.MAX_CONTENT_LENGTH

# Create upload folder if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)



# Memory optimization middleware
@app.before_request
def before_request():
    global last_gc_time
    current_time = time.time()
    
    # Regularly trigger garbage collection
    if current_time - last_gc_time > GC_INTERVAL:
        try:
            gc.collect()
            last_gc_time = current_time
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
    return jsonify({"error": "Internal server error occurred"}), 500

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
    # Voice files moved to multimodal/voice directory
    voice_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'multimodal', 'voice')
    
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
        "service": "xiaoyou-core"
    }), 200

# Helper functions
def allowed_file(filename, allowed_extensions):
    """Check if the file has an allowed extension"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

# API endpoints for file upload and STT
@app.route('/api/upload', methods=['POST'])
@rate_limit()
def upload_file():
    """Handle file uploads (images/audio)"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file part'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400
        
        # Generate unique filename to avoid conflicts
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4()}_{filename}"
        file_path = os.path.join(UPLOAD_FOLDER, unique_filename)
        
        # Save the file
        file.save(file_path)
        
        # Determine file type and return appropriate data
        file_ext = filename.rsplit('.', 1)[1].lower()
        file_type = 'image' if file_ext in ALLOWED_IMAGE_EXTENSIONS else 'audio'
        
        return jsonify({
            'success': True,
            'filename': unique_filename,
            'original_filename': filename,
            'file_path': file_path,
            'file_type': file_type
        })
        
    except Exception as e:
        logger.error(f"File upload error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/stt', methods=['POST'])
@rate_limit()
def speech_to_text():
    """Convert speech to text using STT functionality"""
    try:
        if 'audio' not in request.files:
            return jsonify({'error': 'No audio file provided'}), 400
        
        audio_file = request.files['audio']
        if audio_file.filename == '':
            return jsonify({'error': 'No selected audio file'}), 400
        
        # Check if the file extension is allowed
        if not allowed_file(audio_file.filename, ALLOWED_AUDIO_EXTENSIONS):
            return jsonify({'error': 'File type not allowed'}), 400
        
        # Save the audio file temporarily
        filename = f"{uuid.uuid4()}_{secure_filename(audio_file.filename)}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        audio_file.save(filepath)
        
        # Import STT connector and process the audio
        from multimodal.stt_connector import STTConnector
        stt_connector = STTConnector()
        text = stt_connector.transcribe(filepath)
        
        # Clean up the temporary file
        try:
            os.remove(filepath)
        except:
            pass
        
        return jsonify({'text': text})
        
    except Exception as e:
        logger.error(f"STT conversion error: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Resource cleanup function
def cleanup_resources():
    """Clean up resources before shutdown"""
    # Add any cleanup logic here
    pass

if __name__ == "__main__":
    try:
        app.run(
            host="0.0.0.0", 
            port=5000, 
            debug=False, 
            threaded=True,
            processes=1,
            use_reloader=False,
            load_dotenv=False
        )
    except KeyboardInterrupt:
        cleanup_resources()
        sys.exit(0)
    except Exception:
        cleanup_resources()
        sys.exit(1)