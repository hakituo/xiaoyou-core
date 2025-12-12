import requests
import json
import base64
import time
import logging

logger = logging.getLogger("ForgeClient")

class ForgeClient:
    def __init__(self, base_url="http://127.0.0.1:7860"):
        self.base_url = base_url
        # 1. Define model mapping (Filenames must match Forge exactly)
        self.model_map = {
            "sd1.5": "nsfw_v10.safetensors",
            "sdxl": "sd_xl_base_1.0.safetensors",
            "pony": "ponyDiffusionV6XL_v6StartWithThisOne.safetensors" # Added for anime support
        }
        self.lora_map = {
            # Add LoRA mappings here if needed, or rely on dynamic names
            # "blindbox": {"filename": "blindbox_v1", "base": "sd1.5"},
        }
        self.current_model = None

    def _get_current_model_filename(self):
        """Get currently loaded model filename in Forge"""
        try:
            resp = requests.get(f"{self.base_url}/sdapi/v1/options", timeout=5)
            if resp.status_code == 200:
                return resp.json().get('sd_model_checkpoint')
        except Exception as e:
            logger.error(f"Failed to get current model: {e}")
            return None
        return None

    def switch_model(self, model_type):
        """Switch model (SD1.5 <-> SDXL)"""
        # Resolve model alias to filename, or use as is if not found
        target_filename = self.model_map.get(model_type, model_type)
        
        # Check if it's already a known filename value (reverse lookup not needed if we just use target_filename)
        # But if user passed "sd1.5", we got "nsfw_v10...". If user passed "nsfw_v10...", we use it directly.
        
        current = self._get_current_model_filename()
        if current and target_filename in current:
            logger.info(f"Model already loaded: {current}")
            self.current_model = model_type
            return True

        logger.info(f"Switching model to: {target_filename} ...")
        
        payload = {
            "sd_model_checkpoint": target_filename
        }
        
        try:
            resp = requests.post(f"{self.base_url}/sdapi/v1/options", json=payload, timeout=30)
            
            if resp.status_code == 200:
                time.sleep(2) # Buffer time for model loading
                logger.info("Model switch command sent successfully.")
                self.current_model = model_type
                return True
            else:
                logger.error(f"Model switch failed: {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Model switch exception: {e}")
            return False

    def generate(self, prompt, model_type="sd1.5", lora_name=None, lora_weight=0.8, **kwargs):
        """Generate image"""
        # 1. Ensure correct model
        self.switch_model(model_type)

        # 2. Dynamic parameters based on model type
        # Default settings
        width = kwargs.get("width", 512)
        height = kwargs.get("height", 512)
        steps = kwargs.get("steps", 20)
        cfg_scale = kwargs.get("cfg_scale", 7)
        restore_faces = False

        if model_type == "sdxl" or model_type == "pony":
            # SDXL defaults
            if "width" not in kwargs: width = 1024
            if "height" not in kwargs: height = 1024
            restore_faces = False # SDXL usually doesn't need it
        else:
            # SD1.5 defaults
            if "width" not in kwargs: width = 512
            if "height" not in kwargs: height = 512
            restore_faces = True # SD1.5 benefits from face restoration
        
        # Override restore_faces if explicitly provided
        if "restore_faces" in kwargs:
            restore_faces = kwargs["restore_faces"]

        # 3. LoRA Handling
        final_prompt = prompt
        if lora_name:
            # Basic compatibility check
            if (model_type == "sdxl" or model_type == "pony") and "sd1.5" in lora_name.lower():
                logger.warning(f"Warning: Using SD1.5 LoRA ({lora_name}) with SDXL model. This might fail.")
            
            final_prompt = f"{prompt}, <lora:{lora_name}:{lora_weight}>"

        logger.info(f"Forge Request - Model: {model_type}, Prompt: {final_prompt}")

        payload = {
            "prompt": final_prompt,
            "negative_prompt": kwargs.get("negative_prompt", ""),
            "steps": steps,
            "width": width,
            "height": height,
            "cfg_scale": cfg_scale,
            "sampler_name": kwargs.get("sampler_name", "Euler a"),
            "restore_faces": restore_faces,
            "seed": kwargs.get("seed", -1)
        }

        try:
            resp = requests.post(f"{self.base_url}/sdapi/v1/txt2img", json=payload, timeout=120)
            
            if resp.status_code == 200:
                r = resp.json()
                if 'images' in r and len(r['images']) > 0:
                    return base64.b64decode(r['images'][0])
            
            logger.error(f"Generation failed: {resp.status_code} - {resp.text}")
            return None
        except Exception as e:
            logger.error(f"Generation exception: {e}")
            return None
