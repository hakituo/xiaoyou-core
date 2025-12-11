import os
import logging
import ssl
import certifi

# CRITICAL: Set this BEFORE importing huggingface_hub
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

# Patch SSL to disable verification
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

from huggingface_hub import snapshot_download

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def download_model():
    model_name = "sentence-transformers/all-MiniLM-L6-v2"
    local_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "embedding", "all-MiniLM-L6-v2")
    
    print(f"Downloading {model_name} from hf-mirror.com...")
    print(f"Target directory: {local_dir}")
    print("SSL verification disabled.")
    
    try:
        snapshot_download(
            repo_id=model_name,
            local_dir=local_dir,
            local_dir_use_symlinks=False,
            resume_download=True
        )
        print("Download completed successfully!")
        return True
    except Exception as e:
        print(f"Download failed: {e}")
        return False

if __name__ == "__main__":
    download_model()
