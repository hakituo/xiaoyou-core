# Virtual environment setup script
python -m venv venv

.\venv\Scripts\activate.ps1

python -m pip install --upgrade pip

python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

python -m pip install transformers accelerate diffusers pillow flask huggingface_hub einops

echo "Environment setup completed!"