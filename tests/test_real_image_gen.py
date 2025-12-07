import asyncio
import os
import sys
import logging
from pathlib import Path

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Setup logging
logging.basicConfig(level=logging.INFO, format='[%(asctime)s][%(levelname)s][%(name)s] %(message)s')
logger = logging.getLogger("TEST_REAL_GEN")

from core.image.image_manager import ImageManager, ImageGenerationConfig
from core.image.model_loader import ModelDiscovery

async def test_real_generation():
    manager = ImageManager()
    
    # Initialize
    logger.info("Initializing ImageManager...")
    await manager.initialize()
    
    # Models to test
    models_to_test = [
        "chilloutmix_NiPrunedFp32Fix.safetensors",
        "nsfw_v10.safetensors"
    ]
    
    for model_id in models_to_test:
        logger.info(f"==================================================")
        logger.info(f"Testing Model: {model_id}")
        logger.info(f"==================================================")
        
        # 1. Resolve Path
        resolved_path = ModelDiscovery.resolve_model_path(model_id)
        if resolved_path:
            logger.info(f"Model resolved to: {resolved_path}")
        else:
            logger.error(f"Could not resolve path for {model_id}")
            continue
            
        # 2. Load Model
        logger.info(f"Loading model {model_id}...")
        load_success = await manager.load_model(model_id)
        
        if not load_success:
            logger.error(f"Failed to load model {model_id}")
            continue
            
        logger.info(f"Model {model_id} loaded successfully.")
        
        # 3. Generate Image
        logger.info(f"Generating image with {model_id}...")
        prompt = "1girl, solo, smile, simple background, white background"
        result = await manager.generate_image(
            prompt=prompt,
            model_id=model_id,
            config=ImageGenerationConfig(
                width=512,
                height=512,
                num_inference_steps=20 # Low steps for speed
            )
        )
        
        if result['success']:
            image_path = result['image_path']
            logger.info(f"Generation successful: {image_path}")
            
            # 4. Verify File Size
            if image_path and os.path.exists(image_path):
                file_size = os.path.getsize(image_path)
                logger.info(f"File size: {file_size} bytes ({file_size/1024:.2f} KB)")
                
                if file_size > 1024 * 10: # Expect > 10KB
                    logger.info("File size check passed (Real image generated).")
                else:
                    logger.warning("File size too small! (Possibly blank or mock image)")
            else:
                logger.error("Image file not found!")
        else:
            logger.error(f"Generation failed: {result.get('error')}")
            
        # Unload to save memory for next test
        await manager.unload_model(model_id)

if __name__ == "__main__":
    # Use WindowsProactorEventLoopPolicy if needed on Windows, but default should work for simple script
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    asyncio.run(test_real_generation())
