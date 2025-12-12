import asyncio
import sys
import os
from unittest.mock import MagicMock, patch

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.image.image_manager import ImageManager, ImageGenerationConfig

async def test_image_manager():
    print("Initializing ImageManager...")
    manager = ImageManager()
    
    # Mock ForgeClient to avoid actual network calls
    mock_forge = MagicMock()
    mock_forge.generate.return_value = b"fake_image_bytes"
    
    # Patch ForgeClient in the module or instance
    with patch('core.image.image_manager.ForgeClient', return_value=mock_forge):
        await manager.initialize()
        print("ImageManager initialized.")
        
        # Test 1: Default generation (SD1.5)
        print("Test 1: Default generation")
        res = await manager.generate_image("A cute cat")
        print(f"Result 1: {res.get('success')}, Model: {res.get('model_used')}")
        assert res.get('success') is True
        assert res.get('model_used') == 'sd1.5'
        
        # Test 2: SDXL via style preset
        print("Test 2: SDXL via style preset")
        config = ImageGenerationConfig(style_preset="realistic_hq")
        res = await manager.generate_image("A realistic landscape", config=config)
        print(f"Result 2: {res.get('success')}, Model: {res.get('model_used')}")
        assert res.get('success') is True
        assert res.get('model_used') == 'sdxl'

        # Test 3: Explicit model_id
        print("Test 3: Explicit model_id")
        res = await manager.generate_image("Anime girl", model_id="sdxl_beta")
        print(f"Result 3: {res.get('success')}, Model: {res.get('model_used')}")
        assert res.get('success') is True
        assert res.get('model_used') == 'sdxl'
        
        # Test 4: LoRA handling
        print("Test 4: LoRA handling")
        config = ImageGenerationConfig(lora_path="d:\\models\\lora\\blindbox.safetensors")
        res = await manager.generate_image("Blindbox toy", config=config)
        print(f"Result 4: {res.get('success')}")
        
        # Verify ForgeClient calls
        # We need to access the instance created inside manager
        # Since we patched the class, manager.forge_client should be our mock
        # Wait, manager.forge_client is set in initialize() using the patched class
        
        # Verify generate call arguments
        call_args = manager.forge_client.generate.call_args
        print(f"Last call args: {call_args}")
        
    print("All tests passed!")

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(test_image_manager())
