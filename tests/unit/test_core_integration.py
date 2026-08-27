import pytest
import os
import asyncio
from config.integrated_config import get_settings
from core.trm_adapter import TRMAdapter
from core.exceptions import XiaoyouError, ModelError

def test_configuration_auto_detection():
    # Set dummy env var to simulate auto-detection trigger if needed
    # But logic runs on import/get_settings.
    settings = get_settings()
    assert settings is not None
    # We can't guarantee models exist in CI/Test env, but we can check if attributes exist
    assert hasattr(settings.model, "text_path")
    print(f"Text Model Path: {settings.model.text_path}")

@pytest.mark.asyncio
async def test_trm_adapter_init():
    adapter = TRMAdapter()
    assert adapter is not None
    await adapter.close()

def test_exceptions():
    try:
        raise ModelError("Test error")
    except XiaoyouError as e:
        assert e.code == "MODEL_ERROR"
        assert str(e) == "Test error"

if __name__ == "__main__":
    # Manually run if pytest not available
    test_configuration_auto_detection()
    test_exceptions()
    asyncio.run(test_trm_adapter_init())
    print("All tests passed manually.")
