from core.utils.logger import get_logger
import json

import time
import uuid
import asyncio
import aiohttp
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional, List
try:
    import websocket
except Exception:
    websocket = None

logger = get_logger("ComfyClient")


class ComfyClient:
    """
    Client for interacting with ComfyUI API
    """

    def __init__(self, host="127.0.0.1", port=8188):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.ws_url = f"ws://{host}:{port}/ws"
        self.client_id = str(uuid.uuid4())
        self._nunchaku_available = None  # Cache for Nunchaku node availability

    async def ping(self) -> bool:
        """Check if ComfyUI is reachable"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/system_stats", timeout=2.0
                ) as resp:
                    return resp.status == 200
        except Exception:
            return False

    async def get_system_stats(self) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.base_url}/system_stats") as resp:
                return await resp.json()

    async def check_nunchaku_availability(self) -> bool:
        """Check if Nunchaku nodes are installed in ComfyUI"""
        if self._nunchaku_available is not None:
            return self._nunchaku_available

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/object_info/NunchakuFluxLoader"
                ) as resp:
                    if resp.status == 200:
                        self._nunchaku_available = True
                        logger.info("ComfyUI: NunchakuFluxLoader detected.")
                        return True
                    else:
                        # Try alternative name just in case
                        async with session.get(
                            f"{self.base_url}/object_info/FluxNunchakuLoader"
                        ) as resp2:
                            if resp2.status == 200:
                                self._nunchaku_available = True
                                logger.info("ComfyUI: FluxNunchakuLoader detected.")
                                return True
        except Exception as e:
            logger.warning(f"Failed to check Nunchaku availability: {e}")

        self._nunchaku_available = False
        return False

    async def get_available_loras(self) -> List[str]:
        """Get list of available LoRA models from ComfyUI"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/object_info/LoraLoader"
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        # Extract list from ["LoraLoader"]["input"]["required"]["lora_name"][0]
                        # The structure is usually [ ["lora1", "lora2"], {default:..} ]
                        names = (
                            data.get("LoraLoader", {})
                            .get("input", {})
                            .get("required", {})
                            .get("lora_name", [])
                        )
                        if names and isinstance(names, list) and len(names) > 0:
                            return names[0]
        except Exception as e:
            logger.warning(f"Failed to get LoRA list: {e}")
        return []

    async def queue_prompt(self, prompt_workflow: Dict[str, Any]) -> Dict[str, Any]:
        """Submit a workflow to the queue"""
        payload = {"prompt": prompt_workflow, "client_id": self.client_id}

        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.base_url}/prompt", json=payload) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"ComfyUI Error {resp.status}: {text}")
                return await resp.json()

    async def get_history(self, prompt_id: str) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.base_url}/history/{prompt_id}") as resp:
                return await resp.json()

    async def get_image(self, filename: str, subfolder: str, folder_type: str) -> bytes:
        params = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        query = urllib.parse.urlencode(params)
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.base_url}/view?{query}") as resp:
                if resp.status == 200:
                    return await resp.read()
                raise RuntimeError(f"Failed to get image: {resp.status}")

    async def wait_for_execution(
        self, prompt_id: str, timeout: float = 300.0
    ) -> Dict[str, Any]:
        """
        Wait for a prompt to finish execution using WebSocket.
        Returns the output data (images, etc).
        """
        start_time = time.time()

        if websocket is None:
            raise RuntimeError(
                "缺少 websocket-client 依赖，无法等待 ComfyUI 执行结果，请安装 websocket-client"
            )

        # We need to connect to WS to receive events
        ws = websocket.WebSocket()
        try:
            ws.connect(f"{self.ws_url}?clientId={self.client_id}")

            while time.time() - start_time < timeout:
                try:
                    out = ws.recv()
                    if isinstance(out, str):
                        msg = json.loads(out)
                        msg_type = msg.get("type")
                        data = msg.get("data", {})

                        if msg_type == "execution_success":
                            if data.get("prompt_id") == prompt_id:
                                return await self.get_history(prompt_id)

                        elif msg_type == "execution_error":
                            if data.get("prompt_id") == prompt_id:
                                raise RuntimeError(
                                    f"ComfyUI Execution Error: {data.get('exception_message')}"
                                )

                except Exception as e:
                    if "timed out" not in str(e):
                        logger.warning(f"WS Error: {e}")
                    # Brief sleep to avoid busy loop if WS is behaving oddly
                    await asyncio.sleep(0.1)

            raise TimeoutError("ComfyUI execution timed out")

        finally:
            ws.close()

    def build_flux_workflow(
        self,
        prompt: str,
        width: int,
        height: int,
        steps: int,
        seed: int,
        use_nunchaku: bool = False,
    ) -> Dict[str, Any]:
        """
        Construct a workflow JSON for Flux generation.
        Supports standard Flux and Nunchaku FP4.
        """
        # This is a simplified programmatic construction of a ComfyUI workflow.
        # Node IDs are arbitrary but must be unique within the workflow.

        nodes = {}

        # 1. Model Loader
        if use_nunchaku:
            # Nunchaku Loader
            nodes["1"] = {
                "inputs": {
                    "ckpt_name": "flux1-dev-fp4.safetensors"  # Default assumption, user might need to config
                },
                "class_type": "NunchakuFluxLoader",
                "_meta": {"title": "Nunchaku Flux Loader"},
            }
            # Nunchaku usually returns (MODEL, CLIP, VAE) or just MODEL depending on node version
            # Assuming standard behavior where it might need separate CLIP/VAE or returns all
            # Let's assume the common "NunchakuFluxLoader" behaves like a CheckpointLoader
            model_out = ["1", 0]
            clip_out = ["1", 1]  # Assuming it outputs CLIP
            vae_out = ["1", 2]  # Assuming it outputs VAE

            # Note: If Nunchaku node only outputs MODEL, we need LoadCLIP and LoadVAE separately.
            # But based on standard usage, it often replaces the CheckpointLoader.
            # If it's just model, we'd need more nodes. Assuming integrated loader for now.
            # If standard loader is used:
            pass
        else:
            # Standard Checkpoint Loader
            nodes["1"] = {
                "inputs": {"ckpt_name": "flux1-dev-fp8.safetensors"},
                "class_type": "CheckpointLoaderSimple",
                "_meta": {"title": "Load Checkpoint"},
            }
            model_out = ["1", 0]
            clip_out = ["1", 1]
            vae_out = ["1", 2]

        # 2. CLIP Text Encode (Positive)
        nodes["6"] = {
            "inputs": {"text": prompt, "clip": clip_out},
            "class_type": "CLIPTextEncode",
            "_meta": {"title": "CLIP Text Encode (Positive)"},
        }

        # 3. CLIP Text Encode (Negative) - Flux often doesn't need negative, but we keep empty
        nodes["7"] = {
            "inputs": {"text": "", "clip": clip_out},
            "class_type": "CLIPTextEncode",
            "_meta": {"title": "CLIP Text Encode (Negative)"},
        }

        # 4. Empty Latent
        nodes["5"] = {
            "inputs": {"width": width, "height": height, "batch_size": 1},
            "class_type": "EmptyLatentImage",
            "_meta": {"title": "Empty Latent Image"},
        }

        # 5. KSampler (Flux specific settings often needed, but basic KSampler works)
        # Flux often uses "euler" / "simple" or "beta"
        nodes["3"] = {
            "inputs": {
                "seed": seed if seed != -1 else int(time.time()),
                "steps": steps,
                "cfg": 1.0,  # Flux guidance is often 1.0 or handled differently
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
                "model": model_out,
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
            "class_type": "KSampler",
            "_meta": {"title": "KSampler"},
        }

        # 6. VAE Decode
        nodes["8"] = {
            "inputs": {"samples": ["3", 0], "vae": vae_out},
            "class_type": "VAEDecode",
            "_meta": {"title": "VAE Decode"},
        }

        # 7. Save Image
        nodes["9"] = {
            "inputs": {"filename_prefix": "ComfyUI_Flux"},
            "class_type": "SaveImage",
            "_meta": {"title": "Save Image"},
        }

        return nodes

    def build_sdxl_workflow(
        self,
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        steps: int,
        seed: int,
        model_name: str = "sd_xl_base_1.0.safetensors",
        lora_names: Optional[List[str]] = None,
        cfg: float = 7.0,
        sampler_name: str = "euler_ancestral",
        scheduler: str = "normal",
    ) -> Dict[str, Any]:
        """
        Construct a standard workflow JSON for SDXL generation.
        Supports multiple LoRAs.
        """
        nodes = {}

        # 1. Checkpoint Loader
        nodes["4"] = {
            "inputs": {"ckpt_name": model_name},
            "class_type": "CheckpointLoaderSimple",
            "_meta": {"title": "Load Checkpoint"},
        }

        last_model = ["4", 0]
        last_clip = ["4", 1]

        # 1.5 Optional LoRA Loaders
        if lora_names:
            for idx, lora_name in enumerate(lora_names):
                node_id = str(10 + idx)
                nodes[node_id] = {
                    "inputs": {
                        "model": last_model,
                        "clip": last_clip,
                        "lora_name": lora_name,
                        "strength_model": 1.0,
                        "strength_clip": 1.0,
                    },
                    "class_type": "LoraLoader",
                    "_meta": {"title": f"Load LoRA {idx + 1}"},
                }
                last_model = [node_id, 0]
                last_clip = [node_id, 1]

        # 2. CLIP Text Encode (Positive)
        nodes["6"] = {
            "inputs": {"text": prompt, "clip": last_clip},
            "class_type": "CLIPTextEncode",
            "_meta": {"title": "CLIP Text Encode (Positive)"},
        }

        # 3. CLIP Text Encode (Negative)
        nodes["7"] = {
            "inputs": {
                "text": negative_prompt
                if negative_prompt
                else "text, watermark, low quality",
                "clip": last_clip,
            },
            "class_type": "CLIPTextEncode",
            "_meta": {"title": "CLIP Text Encode (Negative)"},
        }

        # 4. Empty Latent Image
        nodes["5"] = {
            "inputs": {"width": width, "height": height, "batch_size": 1},
            "class_type": "EmptyLatentImage",
            "_meta": {"title": "Empty Latent Image"},
        }

        # 5. KSampler
        nodes["3"] = {
            "inputs": {
                "seed": seed if seed != -1 else int(time.time()),
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler_name,
                "scheduler": scheduler,
                "denoise": 1.0,
                "model": last_model,
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
            "class_type": "KSampler",
            "_meta": {"title": "KSampler"},
        }

        # 6. VAE Decode
        nodes["8"] = {
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
            "class_type": "VAEDecode",
            "_meta": {"title": "VAE Decode"},
        }

        # 7. Save Image
        nodes["9"] = {
            "inputs": {"filename_prefix": "ComfyUI_SDXL"},
            "class_type": "SaveImage",
            "_meta": {"title": "Save Image"},
        }

        return nodes
