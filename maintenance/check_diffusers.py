import sys
try:
    import transformers
    print(f"transformers version: {transformers.__version__}")
    import diffusers
    print(f"diffusers version: {diffusers.__version__}")
    from diffusers import StableDiffusionPipeline
    print("StableDiffusionPipeline imported successfully")
except ImportError as e:
    print(f"ImportError: {e}")
except Exception as e:
    print(f"Error: {e}")
