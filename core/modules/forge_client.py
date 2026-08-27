from core.utils.logger import get_logger
import requests
import base64
import time

logger = get_logger("ForgeClient")


class ForgeClient:
    def __init__(self, base_url="http://127.0.0.1:7860"):
        self.base_url = base_url
        # 1. Define model mapping (Filenames must match Forge exactly)
        self.model_map = {
            "sd1.5": "SD1.5\\chilloutmix_NiPrunedFp32Fix.safetensors",
            "sd1.5_realistic": "SD1.5\\chilloutmix_NiPrunedFp32Fix.safetensors",
            "sdxl": "SDXL\\juggernautXL_ragnarokBy.safetensors",
            "juggernaut": "SDXL\\juggernautXL_ragnarokBy.safetensors",
            "pony": "SDXL\\ponyDiffusionV6XL_v6StartWithThisOne.safetensors",
            "illustrious": "SDXL\\Illustrious-XL-v2.0.safetensors",
            "noobai": "SDXL\\NoobAI-XL-Vpred-v1.0.safetensors",
        }
        self.vae_map = {
            "anime": "vaeKlF8Anime2_klF8Anime2VAE.safetensors",
            "default": "Automatic",
        }
        self.lora_map = {
            # Add LoRA mappings here if needed, or rely on dynamic names
            # "blindbox": {"filename": "blindbox_v1", "base": "sd1.5"},
        }
        self.current_model = None
        self._models_cache = None
        self._models_cache_ts = 0.0
        self._last_loaded_checkpoint = None
        self._last_unavailable_log_ts = 0.0
        self._unavailable_log_interval = 15.0

    def _is_connection_error(self, err: Exception) -> bool:
        try:
            text = str(err).lower()
        except Exception:
            return False
        return (
            "cannot connect" in text
            or "connection refused" in text
            or "failed to establish a new connection" in text
            or "max retries exceeded" in text
            or "connection error" in text
            or "timed out" in text
            or "timeout" in text
            or "actively refused" in text
        )

    def _log_unavailable(self, action: str, err: Exception) -> None:
        now = time.monotonic()
        if (
            now - float(self._last_unavailable_log_ts or 0.0)
        ) >= self._unavailable_log_interval:
            self._last_unavailable_log_ts = now
            logger.warning("Forge 后端不可用，%s: %s", action, err)
        else:
            logger.debug("Forge 后端不可用，%s: %s", action, err)

    def _get_current_model_filename(self):
        """Get currently loaded model filename in Forge"""
        try:
            resp = requests.get(f"{self.base_url}/sdapi/v1/options", timeout=5)
            if resp.status_code == 200:
                return resp.json().get("sd_model_checkpoint")
        except Exception as e:
            if self._is_connection_error(e):
                self._log_unavailable("查询当前模型", e)
            else:
                logger.error(f"Failed to get current model: {e}")
            return None
        return None

    def get_options(self, timeout: float = 5.0):
        try:
            resp = requests.get(
                f"{self.base_url}/sdapi/v1/options", timeout=max(0.1, float(timeout))
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            if self._is_connection_error(e):
                self._log_unavailable("获取配置", e)
            else:
                logger.error(f"Failed to get options: {e}")
        return None

    def ping(self, timeout: float = 2.0) -> bool:
        try:
            resp = requests.get(
                f"{self.base_url}/sdapi/v1/options", timeout=max(0.1, float(timeout))
            )
            return resp.status_code == 200
        except Exception:
            return False

    def unload_model(self):
        """请求 Forge 卸载当前模型以释放显存"""
        try:
            resp = requests.post(
                f"{self.base_url}/sdapi/v1/unload-checkpoint", timeout=10
            )
            if resp.status_code in (200, 204):
                logger.info("Forge unload-checkpoint request sent successfully")
                self._last_loaded_checkpoint = None
                return True

            logger.warning(
                f"Forge unload-checkpoint failed: {resp.status_code} - {resp.text}"
            )
            return False
        except Exception as e:
            logger.error(f"Forge checkpoint unload exception: {e}")
            return False

    def _looks_like_win_pipe_broken(self, body: str) -> bool:
        try:
            s = str(body or "")
        except Exception:
            return False
        return "[winerror 233]" in s.lower() or "管道的另一端上无任何进程" in s

    def wait_for_model_loaded(
        self, target_checkpoint: str, timeout: float = 120.0, poll_interval: float = 1.0
    ):
        deadline = time.time() + float(timeout)
        target = str(target_checkpoint or "").strip().lower()
        if not target:
            return False

        while time.time() < deadline:
            current = self._get_current_model_filename() or ""
            if target in str(current).lower():
                return True
            time.sleep(float(poll_interval))
        return False

    def get_models(self):
        """Get list of available models from Forge"""
        try:
            resp = requests.get(f"{self.base_url}/sdapi/v1/sd-models", timeout=5)
            if resp.status_code == 200:
                models = resp.json()
                self._models_cache = models
                self._models_cache_ts = time.time()
                return models
        except Exception as e:
            if self._is_connection_error(e):
                self._log_unavailable("获取模型列表", e)
            else:
                logger.error(f"Failed to get models from Forge: {e}")
        return []

    def _get_models_cached(self, max_age_seconds: float = 60.0):
        now = time.time()
        if self._models_cache and (now - self._models_cache_ts) <= max_age_seconds:
            return self._models_cache
        return self.get_models()

    def resolve_model_checkpoint(self, model_id: str):
        if not model_id:
            return None

        resolved = self.model_map.get(model_id, model_id)
        if ".safetensors" in resolved.lower():
            return resolved

        models = self._get_models_cached()
        if not models:
            return resolved

        needle = str(resolved).strip().lower()
        for m in models:
            title = str(m.get("title") or "")
            model_name = str(m.get("model_name") or "")
            filename = str(m.get("filename") or "")
            if (
                needle == model_name.lower()
                or needle in title.lower()
                or needle in filename.lower()
            ):
                return title or resolved

        return resolved

    def get_loras(self):
        """Get list of available LoRAs from Forge"""
        try:
            resp = requests.get(f"{self.base_url}/sdapi/v1/loras", timeout=5)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            if self._is_connection_error(e):
                self._log_unavailable("获取 LoRA 列表", e)
            else:
                logger.error(f"Failed to get LoRAs from Forge: {e}")
        return []

    def switch_model(self, model_type):
        """Switch model (SD1.5 <-> SDXL)"""
        target_filename = self.resolve_model_checkpoint(model_type)

        # Check if it's already a known filename value (reverse lookup not needed if we just use target_filename)
        # But if user passed "sd1.5", we got "sensitive_v10...". If user passed the filename, we use it directly.

        current = self._get_current_model_filename()
        if current and target_filename and target_filename in current:
            logger.info(f"Model already loaded: {current}")
            self.current_model = model_type
            self._last_loaded_checkpoint = current
            return True

        logger.info(f"Switching model to: {target_filename} ...")

        payload = {"sd_model_checkpoint": target_filename}

        try:
            resp = requests.post(
                f"{self.base_url}/sdapi/v1/options", json=payload, timeout=30
            )

            if resp.status_code == 200:
                time.sleep(1)
                logger.info("Model switch command sent successfully.")
                self.current_model = model_type
                self._last_loaded_checkpoint = target_filename
                return True
            else:
                logger.error(f"Model switch failed: {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Model switch exception: {e}")
            return False

    def generate_images(
        self,
        prompt,
        model_type="sd1.5",
        lora_name=None,
        lora_weight=0.8,
        sd_vae=None,
        num_images=1,
        **kwargs,
    ):
        num_images = kwargs.pop("num_images", None)
        batch_size = kwargs.pop("batch_size", None)
        if num_images is None:
            num_images = 1
        try:
            num_images = int(num_images)
        except Exception:
            num_images = 1
        if num_images < 1:
            num_images = 1

        if batch_size is None:
            batch_size = min(4, num_images)
        try:
            batch_size = int(batch_size)
        except Exception:
            batch_size = min(4, num_images)
        if batch_size < 1:
            batch_size = 1
        if batch_size > num_images:
            batch_size = num_images

        self.switch_model(model_type)

        # 2. Dynamic parameters based on model type
        # Get params from kwargs, treat None as "not provided"
        width = kwargs.get("width")
        height = kwargs.get("height")
        steps = kwargs.get("steps")
        cfg_scale = kwargs.get("cfg_scale")
        restore_faces = kwargs.get("restore_faces")

        # Set defaults based on model type
        if model_type == "sdxl" or model_type == "pony":
            # SDXL defaults (1024x1024)
            if width is None:
                width = 1024
            if height is None:
                height = 1024
            if steps is None:
                steps = 25
            if cfg_scale is None:
                cfg_scale = 7
            if restore_faces is None:
                restore_faces = False
        else:
            # Default to 1024x1024 as per architecture standard
            if width is None:
                width = 1024
            if height is None:
                height = 1024
            if steps is None:
                steps = 20
            if cfg_scale is None:
                cfg_scale = 7
            if restore_faces is None:
                restore_faces = False

            # Use Anime VAE for SD1.5 if not specified
            override_settings = kwargs.get("override_settings") or {}
            if "sd_vae" not in override_settings:
                override_settings["sd_vae"] = sd_vae or self.vae_map.get("anime")
                kwargs["override_settings"] = override_settings

        loras = kwargs.get("loras")
        if loras is None:
            loras = []
        if isinstance(loras, dict):
            loras = [loras]
        if not isinstance(loras, list):
            loras = []

        if lora_name:
            # 统一使用反斜杠，这是 Forge API 识别子目录 LORA 的关键
            safe_lora_name = lora_name.replace("/", "\\")
            loras.append({"name": safe_lora_name, "weight": lora_weight})

        final_prompt = prompt
        for lora in loras:
            if not isinstance(lora, dict):
                continue
            lname = lora.get("name")
            if not lname:
                continue
            lw = lora.get("weight", lora_weight)
            try:
                lw = float(lw)
            except Exception:
                lw = lora_weight

            if (model_type == "sdxl" or model_type == "pony") and "sd1.5" in str(
                lname
            ).lower():
                logger.warning(
                    f"Warning: Using SD1.5 LoRA ({lname}) with SDXL model. This might fail."
                )

            final_prompt = f"{final_prompt}, <lora:{lname}:{lw}>"

        logger.info(f"Forge Request - Model: {model_type}, Prompt: {final_prompt}")

        payload = {
            "prompt": final_prompt,
            "negative_prompt": kwargs.get("negative_prompt", ""),
            "steps": steps,
            "width": width,
            "height": height,
            "cfg_scale": cfg_scale,
            "sampler_name": kwargs.get(
                "sampler_name", "DPM++ 2M Karras"
            ),  # 默认用更好的采样器
            "restore_faces": False,  # 绝对强制关闭
            "seed": kwargs.get("seed", -1),
            "batch_size": batch_size,
            "n_iter": int((num_images + batch_size - 1) // batch_size),
        }

        optional_keys = [
            "scheduler",
            "enable_hr",
            "hr_scale",
            "hr_upscaler",
            "hr_second_pass_steps",
            "denoising_strength",
            "hr_additional_modules",  # 加入这个以规避部分 Forge 版本的 NoneType 错误
            "override_settings",
            "override_settings_restore_afterwards",
            "script_name",
            "script_args",
            "alwayson_scripts",
        ]
        for k in optional_keys:
            if k == "restore_faces":
                continue
            if k in kwargs and kwargs.get(k) is not None:
                payload[k] = kwargs.get(k)

        try:
            request_timeout = kwargs.get("request_timeout")
            try:
                request_timeout = (
                    float(request_timeout) if request_timeout is not None else 120.0
                )
            except Exception:
                request_timeout = 120.0

            def _do_request():
                return requests.post(
                    f"{self.base_url}/sdapi/v1/txt2img",
                    json=payload,
                    timeout=(10, max(1.0, float(request_timeout))),
                )

            resp = _do_request()

            if resp.status_code == 200:
                r = resp.json()
                images = r.get("images")
                if isinstance(images, list) and len(images) > 0:
                    out = []
                    for raw in images:
                        if isinstance(raw, dict):
                            raw = (
                                raw.get("data") or raw.get("image") or raw.get("base64")
                            )

                        if isinstance(raw, str) and raw:
                            s = raw.strip()
                            if s.startswith("data:") and "base64," in s:
                                s = s.split("base64,", 1)[1].strip()
                            out.append(base64.b64decode(s))

                    if out:
                        return out[:num_images]

            error_msg = f"Forge generation failed: {resp.status_code} - {resp.text}"
            logger.error(error_msg)

            if resp.status_code >= 500 and self._looks_like_win_pipe_broken(resp.text):
                logger.warning("Forge 返回 WinError233，尝试执行一次卸载/重试以自恢复")
                try:
                    self.unload_model()
                except Exception:
                    pass
                try:
                    time.sleep(1.0)
                except Exception:
                    pass
                try:
                    self.switch_model(model_type)
                except Exception:
                    pass
                try:
                    resp2 = _do_request()
                    if resp2.status_code == 200:
                        r2 = resp2.json()
                        images2 = r2.get("images")
                        if isinstance(images2, list) and len(images2) > 0:
                            out2 = []
                            for raw in images2:
                                if isinstance(raw, dict):
                                    raw = (
                                        raw.get("data")
                                        or raw.get("image")
                                        or raw.get("base64")
                                    )

                                if isinstance(raw, str) and raw:
                                    s = raw.strip()
                                    if s.startswith("data:") and "base64," in s:
                                        s = s.split("base64,", 1)[1].strip()
                                    out2.append(base64.b64decode(s))

                            if out2:
                                return out2[:num_images]
                except Exception:
                    pass

                raise RuntimeError(
                    "Forge 后端内部进程异常（WinError 233：管道另一端无进程）。"
                    "请重启 Forge 后端，或降低分辨率/步数后重试。"
                )

            raise RuntimeError(error_msg)
        except Exception as e:
            if isinstance(e, RuntimeError):
                raise e
            if self._is_connection_error(e):
                self._log_unavailable("生成请求", e)
            else:
                logger.error(f"Generation exception: {e}")
            raise RuntimeError(f"Forge connection error: {str(e)}")

    def generate(
        self,
        prompt,
        model_type="sd1.5",
        lora_name=None,
        lora_weight=0.8,
        sd_vae=None,
        **kwargs,
    ):
        images = self.generate_images(
            prompt,
            model_type=model_type,
            lora_name=lora_name,
            lora_weight=lora_weight,
            num_images=1,
            sd_vae=sd_vae,
            **kwargs,
        )
        if isinstance(images, list) and images:
            return images[0]
        return None
