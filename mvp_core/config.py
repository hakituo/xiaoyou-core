import os
import json
from typing import Optional
from pydantic import BaseModel, Field

class ModelSettings(BaseModel):
    text_path: str = Field(default="models/llm/Qwen2.5-7B-Instruct-Q4_K_M.gguf")
    sd_path: str = Field(default="models/img/check_point/nsfw_v10.safetensors")
    vl_path: str = Field(default="models/llm/Qwen2-VL-2B-Instruct.gguf")
    tts_api: str = Field(default="http://127.0.0.1:9880")
    device: str = Field(default="cuda")

class AppSettings(BaseModel):
    model: ModelSettings = ModelSettings()

_settings = None

def get_settings() -> AppSettings:
    global _settings
    if _settings is None:
        # Load from config.json if exists
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    _settings = AppSettings(**data)
            except Exception as e:
                print(f"Warning: Failed to load config.json: {e}")
                _settings = AppSettings()
        else:
            _settings = AppSettings()
    return _settings
