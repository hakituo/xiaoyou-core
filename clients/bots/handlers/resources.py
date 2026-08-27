import json
import os

from clients.bots.handlers.base import BaseHandler
from clients.bots.qq.settings import (
    _HAS_STATUS_RENDERER,
    generate_model_list_image,
    generate_persona_list_image,
    generate_voice_list_image,
)
from clients.bots.qq.utils import _build_cq_image, _truncate_text, build_persona_conversation_id, parse_session_user_id

class ResourceHandler(BaseHandler):
    def _active_tokens(self, current_value) -> set[str]:
        tokens = set()

        def _add(value):
            s = str(value or "").strip()
            if s:
                tokens.add(s)

        if isinstance(current_value, dict):
            provider = str(current_value.get("provider") or "").strip()
            model = str(current_value.get("model") or "").strip()
            path = str(current_value.get("path") or "").strip()
            _add(provider)
            _add(model)
            _add(path)
            if provider and model:
                _add(f"{provider}:{model}")
                _add(f"cloud:{provider}:{model}")
            # 支持新的模型路径格式 cloud:provider:key_alias:model
            if path and path.startswith("cloud:"):
                parts = path.split(":")
                if len(parts) >= 4:
                    key_alias = parts[2]
                    _add(f"cloud:{provider}:{key_alias}:{model}")
        elif isinstance(current_value, (list, tuple, set)):
            for item in current_value:
                _add(item)
        else:
            _add(current_value)

        return tokens

    def _is_active_model_entry(self, entry: dict, active_tokens: set[str]) -> bool:
        if not isinstance(entry, dict) or not active_tokens:
            return False
        candidates = {
            str(entry.get("id") or "").strip(),
            str(entry.get("name") or "").strip(),
            str(entry.get("path") or "").strip(),
            str(entry.get("model") or "").strip(),
        }
        provider = str(entry.get("provider") or "").strip()
        model_id = str(entry.get("id") or entry.get("model") or entry.get("name") or "").strip()
        if provider and model_id:
            candidates.add(f"{provider}:{model_id}")
            candidates.add(f"cloud:{provider}:{model_id}")
        # 支持新的模型路径格式 cloud:provider:key_alias:model
        path = str(entry.get("path") or "").strip()
        if path and path.startswith("cloud:"):
            parts = path.split(":")
            if len(parts) >= 4:
                key_alias = parts[2]
                candidates.add(f"cloud:{provider}:{key_alias}:{model_id}")
        candidates.discard("")
        return bool(candidates & active_tokens)

    async def _get_current_model_state(self) -> dict:
        try:
            status, data = await self.api_request("GET", "/api/v1/models")
            if status == 200 and isinstance(data, dict) and isinstance(data.get("current"), dict):
                return data.get("current") or {}
        except Exception as e:
            self.logger.warning(f"Failed to query current model state: {e}")
        return {}

    def _sync_prefs_from_model_state(self, prefs: dict, current_model: dict):
        if not isinstance(prefs, dict) or not isinstance(current_model, dict):
            return
        provider = str(current_model.get("provider") or "").strip()
        model = str(current_model.get("model") or "").strip()
        path = str(current_model.get("path") or "").strip()
        if provider:
            prefs["model_provider"] = provider
        if provider == "local":
            prefs["model_name"] = path or model or prefs.get("model_name") or ""
            prefs["chat_model"] = ""
        else:
            prefs["model_name"] = model or prefs.get("model_name") or ""
            # 支持新的模型路径格式 cloud:provider:key_alias:model
            # 从path中提取key_alias
            key_alias = None
            if path and path.startswith("cloud:"):
                parts = path.split(":")
                if len(parts) >= 4:
                    key_alias = parts[2]  # cloud:provider:key_alias:model
            prefs["chat_model"] = self.adapter.config_handler.make_cloud_model_hint(provider, model, key_alias)

    def _get_persona_audio(self, persona_filename: str) -> str | None:
        """根据人设文件名查找对应的参考音频路径"""
        try:
            import importlib
            config_mod = importlib.import_module("config.integrated_config")
            get_settings_fn = getattr(config_mod, "get_settings", None)
            if not get_settings_fn:
                return None
            settings = get_settings_fn()
            persona_audio_map = getattr(settings.model, "persona_audio_map", None)
            if not persona_audio_map:
                return None
            fn_lower = str(persona_filename or "").strip().lower()
            for persona_key, audio_path in persona_audio_map.items():
                key_lower = str(persona_key).strip().lower()
                if key_lower in fn_lower:
                    return audio_path
        except Exception:
            pass
        return None

    async def _clear_persona_short_memory(self, conversation_id: str):
        try:
            await self.api_request(
                "POST",
                "/api/v1/memories/clear",
                json_body={"user_id": str(conversation_id or "").strip(), "mode": "short"},
            )
        except Exception as e:
            self.logger.warning(f"clear persona short memory failed: {e}")

    async def show_models(self, session_id, prefs, filter_arg: str = "", silent: bool = False):
        filter_type = "all"
        arg_lower = filter_arg.lower().strip()
        if arg_lower in {"llm", "语言", "语言模型", "文字"}:
            filter_type = "llm"
        elif arg_lower in {"image", "图像", "图片", "画图", "img", "绘画"}:
            filter_type = "image"

        # 1. Get LLM Models
        s1, d1 = await self.api_request("GET", "/api/v1/models", params={"type": "llm"})
        llm_list = []
        if isinstance(d1, dict):
             # 支持两种字段名：available（旧格式）和 data（新格式）
             llm_list.extend(d1.get("available", []) or d1.get("data", []))
             llm_list.extend(d1.get("options", []))

        # 调试日志
        self.logger.info(f"[DEBUG] show_models: s1={s1}, d1 type={type(d1)}")
        if isinstance(d1, dict):
            self.logger.info(f"[DEBUG] show_models: available={d1.get('available', [])}")
            self.logger.info(f"[DEBUG] show_models: data={d1.get('data', [])}")
            self.logger.info(f"[DEBUG] show_models: options={d1.get('options', [])}")
        self.logger.info(f"[DEBUG] show_models: llm_list length={len(llm_list)}")

        # 2. Get Image Models
        s2, d2 = await self.api_request("GET", "/api/v1/vision/image/models")
        img_list = []

        def _normalize_image_models(raw):
            if isinstance(raw, list):
                return [m for m in raw if isinstance(m, dict)]
            if not isinstance(raw, dict):
                return []

            out = []
            for group, group_data in raw.items():
                if isinstance(group_data, list):
                    for v in group_data:
                        s = str(v or "").strip()
                        if s:
                            out.append({"id": s, "name": s, "path": s, "group": str(group)})
                    continue
                if not isinstance(group_data, dict):
                    continue

                for key in ("checkpoints", "models", "loras"):
                    items = group_data.get(key)
                    if not isinstance(items, list):
                        continue
                    for v in items:
                        s = str(v or "").strip()
                        if s:
                            out.append({"id": s, "name": s, "path": s, "group": f"{group}:{key}"})
            return out

        if isinstance(d2, dict):
            raw = d2.get("data")
            img_list = _normalize_image_models(raw)

        # Cache for index selection
        self.adapter._list_cache[session_id] = {
            "type": "model",
            "llm": llm_list,
            "image": img_list
        }

        if silent:
            return

        current_model = await self._get_current_model_state()
        self._sync_prefs_from_model_state(prefs, current_model)
        current_llm = current_model or (prefs.get("model_name") or "Unknown")
        current_img = prefs.get("image_model") or "Unknown"
        current_llm_tokens = self._active_tokens(current_llm)

        if _HAS_STATUS_RENDERER and callable(generate_model_list_image) and (llm_list or img_list):
            # 调试日志
            self.logger.info(f"[DEBUG] generate_model_list_image: llm_list length={len(llm_list)}, img_list length={len(img_list)}, filter_type={filter_type}")
            img_path = generate_model_list_image(llm_list, img_list, current_llm, current_img, filter_type=filter_type)
            if img_path and os.path.exists(img_path):
                await self.send_text(session_id, _build_cq_image(img_path))
                return

        lines = []
        # Fallback text mode should also respect filter_type
        if filter_type in ("all", "llm") and llm_list:
            lines.append("【语言模型 (LLM)】")
            for i, m in enumerate(llm_list, start=1):
                name = m.get("name") or m.get("id")
                provider = m.get("provider") or "local"
                mark = "*" if self._is_active_model_entry(m, current_llm_tokens) else ""
                lines.append(f"{i}. {mark}{name} ({provider})")
            lines.append("")
        
        if filter_type in ("all", "image") and img_list:
            lines.append("【图像模型 (Image)】")
            base = len(llm_list) if filter_type == "all" else 0
            for j, m in enumerate(img_list, start=1):
                name = m.get("name") or m.get("id") or m.get("path")
                display_name = os.path.basename(name)
                mark = "*" if name == current_img else ""
                lines.append(f"{base + j}. {mark}{display_name}")
        
        if not lines:
            await self.send_text(session_id, "没有找到可用模型")
            return
            
        await self.send_text(session_id, _truncate_text("\n".join(lines), 1800))

    async def show_personas(self, session_id, prefs=None):
        status, data = await self.api_request("GET", "/api/v1/personas")
        if status != 200 or not isinstance(data, list):
            await self.send_text(session_id, f"获取人设列表失败: {json.dumps(data, ensure_ascii=False)}")
            return

        # 双QQ模式：优先使用 adapter 自身配置的 persona_filename 作为当前人设
        own_persona = str(getattr(self.adapter.cfg, "persona_filename", "") or "").strip()
        if own_persona:
            current_filename = own_persona
        else:
            cur_status, cur_data = await self.api_request("GET", "/api/v1/personas/current")
            current_filename = ""
            if cur_status == 200 and isinstance(cur_data, dict):
                current_filename = str(cur_data.get("filename") or "").strip()

        # 双QQ模式：只显示与当前角色相关的人设
        # 优先依据 accessible_roles 显式声明（如 Frost.json 声明 ["ling"] 则Ling账号可见），
        # 未声明的人设回退到旧启发式（文件名/类别/名称包含角色标识，或通用类别）
        if own_persona:
            # 从 own_persona 推断角色标识（如 "aveline" 或 "ling"）
            own_lower = own_persona.lower()
            if "aveline" in own_lower:
                role_key = "aveline"
            elif "ling" in own_lower:
                role_key = "ling"
            else:
                role_key = ""

            if role_key:
                filtered = []
                for p in data:
                    if not isinstance(p, dict):
                        continue
                    accessible = p.get("accessible_roles") or []
                    if isinstance(accessible, list) and accessible:
                        # 显式声明了可访问角色：仅当包含当前角色时可见
                        if role_key in accessible:
                            filtered.append(p)
                        continue
                    fn = str(p.get("filename") or "").lower()
                    cat = str(p.get("category") or "").lower()
                    name = str(p.get("name") or "").lower()
                    # 未声明 accessible_roles：保留启发式（包含角色标识或通用类别）
                    if role_key in fn or role_key in cat or role_key in name or cat in ("general", "qq", ""):
                        filtered.append(p)
                if filtered:
                    data = filtered

        self.adapter._list_cache[session_id] = {
            "type": "persona",
            "data": data,
            "current": current_filename,
        }

        if _HAS_STATUS_RENDERER and callable(generate_persona_list_image):
            img_path = generate_persona_list_image(data, current_filename)
            if img_path and os.path.exists(img_path):
                await self.send_text(session_id, _build_cq_image(img_path))
                return

        lines = []
        for i, p in enumerate(data, start=1):
            if not isinstance(p, dict):
                continue
            filename = str(p.get("filename") or "").strip()
            name = str(p.get("name") or "").strip() or os.path.basename(filename)
            category = str(p.get("category") or "").strip() or "general"
            flag = "*" if filename and current_filename and filename == current_filename else ""
            lines.append(f"{i}. {flag}{name} [{category}] {filename}")

        if not lines:
            await self.send_text(session_id, "没有找到可用人设")
            return
        await self.send_text(session_id, _truncate_text("\n".join(lines), 1800))

    async def show_voices(self, session_id, prefs):
        status, data = await self.api_request("GET", "/api/v1/voice/reference-audio")
        voices = []
        if status == 200 and isinstance(data, dict):
            if isinstance(data.get("data"), list):
                voices = data.get("data")
            elif isinstance(data.get("files"), list):
                voices = data.get("files")
            elif isinstance(data.get("data"), dict) and isinstance(data.get("data", {}).get("voices"), list):
                voices = data.get("data", {}).get("voices")
            
        self.adapter._list_cache[session_id] = {
            "type": "voice",
            "data": voices
        }
        
        current = prefs.get("reference_audio")
        if _HAS_STATUS_RENDERER and callable(generate_voice_list_image):
            img_path = generate_voice_list_image(voices, current)
            if img_path and os.path.exists(img_path):
                await self.send_text(session_id, _build_cq_image(img_path))
                return

        lines = []
        for i, v in enumerate(voices, start=1):
            name = v.get("name") or os.path.basename(v.get("path") or "") or f"voice_{i}"
            p = v.get("path") or ""
            lines.append(f"{i}. {name} {p}")
        await self.send_text(session_id, _truncate_text("\n".join(lines), 1800))

    async def handle_switch_model(self, session_id, arg, prefs, user_id):
        if not arg:
            await self.send_text(session_id, "用法: /切模型 <名称或序号> 或 /切模型 [llm|img] <序号>")
            return

        parts = str(arg).strip().split()
        force_type = None
        target_arg = arg
        
        if len(parts) >= 2:
            t = parts[0].lower()
            if t in {"llm", "llms", "语言", "语言模型"}:
                force_type = "llm"
                target_arg = " ".join(parts[1:])
            elif t in {"img", "image", "sd", "flux", "图像", "画图", "生图"}:
                force_type = "image"
                target_arg = " ".join(parts[1:])

        # Get or fetch model list
        cache = self.adapter._list_cache.get(session_id)
        if not cache or cache.get("type") != "model":
            # Auto-fetch if no cache, but silent
            await self.show_models(session_id, prefs, silent=True)
            cache = self.adapter._list_cache.get(session_id)

        llms = cache.get("llm", []) if cache else []
        imgs = cache.get("image", []) if cache else []

        target_model = target_arg
        target_type = force_type or "llm"
        provider = "local"

        # Try numeric index first
        try:
            idx = int(target_arg) - 1
            if force_type == "llm":
                if 0 <= idx < len(llms):
                    m = llms[idx]
                    target_model = m.get("id") or m.get("name")
                    provider = m.get("provider", "local")
                    target_type = "llm"
                else:
                    await self.send_text(session_id, f"LLM 序号 {idx+1} 无效，可用范围: 1-{len(llms)}")
                    return
            elif force_type == "image":
                if 0 <= idx < len(imgs):
                    m = imgs[idx]
                    target_model = m.get("path") or m.get("name")
                    target_type = "image"
                else:
                    await self.send_text(session_id, f"图像模型序号 {idx+1} 无效，可用范围: 1-{len(imgs)}")
                    return
            else:
                # No force type, use global index
                if 0 <= idx < len(llms):
                    m = llms[idx]
                    target_model = m.get("id") or m.get("name")
                    provider = m.get("provider", "local")
                    target_type = "llm"
                elif 0 <= (idx - len(llms)) < len(imgs):
                    m = imgs[idx - len(llms)]
                    target_model = m.get("path") or m.get("name")
                    target_type = "image"
                else:
                    await self.send_text(session_id, f"序号 {idx+1} 无效 (LLM: 1-{len(llms)}, IMG: {len(llms)+1}-{len(llms)+len(imgs)})")
                    return
        except ValueError:
            # Not a number, fuzzy match
            q = str(target_arg).strip().lower()
            best = None
            best_type = "llm"
            best_score = -1

            def _score(hay: str) -> int:
                h = str(hay or "").lower()
                if h == q:
                    return 100
                if h.startswith(q):
                    return 50
                if q in h:
                    return 10
                return 0

            # Filter search by force_type if present
            search_llms = llms if (not force_type or force_type == "llm") else []
            search_imgs = imgs if (not force_type or force_type == "image") else []

            for m in search_llms:
                if not isinstance(m, dict):
                    continue
                mid = str(m.get("id") or "").strip()
                name = str(m.get("name") or "").strip()
                model = str(m.get("model") or "").strip()
                hay = f"{mid} {name} {model}".strip()
                s = _score(hay)
                if s > best_score:
                    best_score, best, best_type = s, m, "llm"

            for m in search_imgs:
                if not isinstance(m, dict):
                    continue
                pid = str(m.get("path") or "").strip()
                name = str(m.get("name") or "").strip()
                hay = f"{pid} {name}".strip()
                s = _score(hay)
                if s > best_score:
                    best_score, best, best_type = s, m, "image"

            if best and best_score > 0:
                if best_type == "image":
                    target_model = str(best.get("path") or best.get("name")).strip()
                    target_type = "image"
                else:
                    target_model = str(best.get("id") or best.get("model") or best.get("name")).strip()
                    provider = str(best.get("provider") or provider).strip()
                    target_type = "llm"
            else:
                if force_type:
                    await self.send_text(session_id, f"未找到匹配的 {force_type.upper()} 模型: {target_arg}")
                    return
                target_type = "llm"

        # Logic for Image Model
        # Smart detection: check if model name looks like an image model (safetensors, ckpt, or matched in image list)
        is_image_model = target_type == "image"
        
        # If not explicitly "image", check if it matches any known image model
        if not is_image_model and target_type != "llm":
             # Check if target_model is in img_list names/paths
             for m in imgs:
                 m_path = str(m.get("path") or "").lower()
                 m_name = str(m.get("name") or "").lower()
                 t_low = str(target_model).lower()
                 if t_low in m_path or t_low in m_name:
                     is_image_model = True
                     break
        
        # Also check common extensions
        if not is_image_model:
            t_low = str(target_model).lower()
            if any(ext in t_low for ext in [".safetensors", ".ckpt", ".pt", "sd", "flux", "pony", "illustrious", "animagine"]):
                is_image_model = True

        if is_image_model:
            prefs["image_model"] = target_model
            display_name = os.path.basename(target_model.replace("\\", "/")) if ("/" in target_model or "\\" in target_model) else target_model
            await self.send_text(session_id, f"生图模型已切换为: {display_name}")
            return True

        # Logic for LLM
        # Default fallback is LLM switch
        body = {"model_name": target_model, "provider": provider}
        
        # 如果target_model包含完整的cloud:格式，直接使用
        if target_model and str(target_model).startswith("cloud:"):
            # 解析cloud:格式，支持两种格式：
            # 1. cloud:provider:model（传统格式）
            # 2. cloud:provider:key_alias:model（多API key格式）
            parts = str(target_model).split(":")
            if len(parts) >= 3:
                provider = parts[1]
                # 模型名可能是第3段或第4段（取决于格式）
                if len(parts) >= 4:
                    model_name = parts[3]  # cloud:provider:key_alias:model
                else:
                    model_name = parts[2]  # cloud:provider:model
                body = {"model_name": model_name, "provider": provider}
        
        status, data = await self.api_request("POST", "/api/v1/models/switch", json_body=body)
        
        if status == 200:
            if isinstance(data, dict) and isinstance(data.get("current"), dict):
                self._sync_prefs_from_model_state(prefs, data.get("current") or {})
            else:
                prefs["model_provider"] = provider
                prefs["model_name"] = target_model
                prefs["chat_model"] = self.adapter.config_handler.make_cloud_model_hint(provider, target_model)
            display_name = os.path.basename(target_model.replace("\\", "/")) if ("/" in target_model or "\\" in target_model) else target_model
            await self.send_text(session_id, f"LLM 模型已切换: {display_name}")
            return True
        else:
            self.logger.warning(f"Failed to switch model to {target_model}: {data}")
            err = data.get("message") or data.get("detail") or "API Error"
            await self.send_friendly_error(session_id, "切换模型", err)
            return True

    async def handle_switch_persona(self, session_id, arg, prefs, user_id):
        if not arg:
            await self.send_text(session_id, "用法: /切人设 <名称/序号/filename>")
            return

        personas = None
        current_filename = ""
        cache = self.adapter._list_cache.get(session_id)
        if cache and cache.get("type") == "persona":
            personas = cache.get("data")
            current_filename = str(cache.get("current") or "").strip()

        if not isinstance(personas, list):
            status, data = await self.api_request("GET", "/api/v1/personas")
            if status != 200 or not isinstance(data, list):
                await self.send_text(session_id, f"获取人设列表失败: {json.dumps(data, ensure_ascii=False)}")
                return
            personas = data

        s = str(arg).strip()
        target = None
        try:
            idx = int(s) - 1
            if 0 <= idx < len(personas):
                p = personas[idx]
                if isinstance(p, dict):
                    target = p
        except Exception:
            target = None

        if target is None:
            s_low = s.lower()
            exact = []
            partial = []
            for p in personas:
                if not isinstance(p, dict):
                    continue
                filename = str(p.get("filename") or "").strip()
                name = str(p.get("name") or "").strip()
                if filename.lower() == s_low or name.lower() == s_low:
                    exact.append(p)
                    continue
                if s_low and (s_low in filename.lower() or s_low in name.lower()):
                    partial.append(p)
            if exact:
                target = exact[0]
            elif partial:
                target = partial[0]

        if not isinstance(target, dict):
            self.logger.warning(f"Persona not found: {s}. Falling back to chat.")
            return False

        filename = str(target.get("filename") or "").strip()
        if not filename:
            await self.send_text(session_id, "人设条目缺少 filename，无法切换")
            return

        # 双QQ模式：禁止跨角色切换人设
        own_persona = str(getattr(self.adapter.cfg, "persona_filename", "") or "").strip()
        if own_persona:
            own_lower = own_persona.lower()
            target_lower = filename.lower()
            # 推断角色标识
            if "aveline" in own_lower:
                own_role, cross_role = "aveline", "ling"
            elif "ling" in own_lower:
                own_role, cross_role = "ling", "aveline"
            else:
                own_role, cross_role = "", ""

            if own_role and cross_role in target_lower and own_role not in target_lower:
                await self.send_text(session_id, "当前账号不允许切换到其他角色的人设")
                return True

            # 显式声明了 accessible_roles 的人设：仅允许声明中的角色切换
            accessible = target.get("accessible_roles") or []
            if isinstance(accessible, list) and accessible and own_role and own_role not in accessible:
                await self.send_text(session_id, "当前账号不允许切换到该人设")
                return True

        if current_filename and filename == current_filename:
            await self.send_text(session_id, f"当前已经是该人设: {filename}")
            return True

        # 双QQ模式下，adapter 自身已配置 persona_filename，不调后端全局 API 切换人设
        # 只更新本地 session prefs 即可
        own_persona = str(getattr(self.adapter.cfg, "persona_filename", "") or "").strip()
        if own_persona:
            prefs["persona_filename"] = filename
            if cache and cache.get("type") == "persona":
                cache["current"] = filename
            self.logger.info(f"[Persona Switch] Multi-QQ mode: updated session prefs to {filename}, skipping global API")

            current_model = await self._get_current_model_state()
            self._sync_prefs_from_model_state(prefs, current_model)

            _auto_ref_audio = self._get_persona_audio(filename)
            if _auto_ref_audio:
                prefs["reference_audio"] = _auto_ref_audio

            try:
                await self.adapter.config_handler.persist_user_override(user_id, prefs)
            except Exception as e:
                self.logger.warning(f"persist_user_override failed after persona switch: {e}")
            try:
                target_cid = build_persona_conversation_id(session_id, filename)
                await self._clear_persona_short_memory(target_cid)
            except Exception as e:
                self.logger.warning(f"persona switch memory isolation cleanup failed: {e}")
            await self.send_text(session_id, f"人设已切换: {filename}")
            return True

        status, data = await self.api_request("POST", "/api/v1/personas/switch", json_body={"filename": filename})
        if status == 200 and isinstance(data, dict) and str(data.get("status") or "").lower() == "success":
            prefs["persona_filename"] = filename
            if cache and cache.get("type") == "persona":
                cache["current"] = filename

            # 如果 adapter 自身已配置 persona_filename（双QQ模式），只更新 session prefs，
            # 不改变全局 PersonaManager，避免影响其他 adapter 实例
            own_persona = str(getattr(self.adapter.cfg, "persona_filename", "") or "").strip()
            if not own_persona:
                try:
                    from core.character.managers.persona_manager import get_persona_manager
                    pm = get_persona_manager()
                    pm.set_persona(filename)
                    self.logger.info(f"[Persona Switch] Updated local persona_manager to: {filename}")
                except Exception as e:
                    self.logger.warning(f"[Persona Switch] Failed to update local persona_manager: {e}")
            else:
                self.logger.info(f"[Persona Switch] Adapter has own persona_filename={own_persona}, skipping global PersonaManager update")

            current_model = await self._get_current_model_state()
            self._sync_prefs_from_model_state(prefs, current_model)

            # 根据人设自动联动参考音频
            _auto_ref_audio = self._get_persona_audio(filename)
            if _auto_ref_audio:
                prefs["reference_audio"] = _auto_ref_audio

            try:
                await self.adapter.config_handler.persist_user_override(user_id, prefs)
            except Exception as e:
                self.logger.warning(f"persist_user_override failed after persona switch: {e}")
            try:
                target_cid = build_persona_conversation_id(session_id, filename)
                await self._clear_persona_short_memory(target_cid)
            except Exception as e:
                self.logger.warning(f"persona switch memory isolation cleanup failed: {e}")
            await self.send_text(session_id, f"人设已切换: {filename}")
            return True

        self.logger.warning(f"Failed to switch persona to {filename}: {data}")
        err = data.get("message") or data.get("detail") or "API Error"
        await self.send_friendly_error(session_id, "切换人设", err)
        return True

    async def handle_set_voice(self, session_id, arg, prefs):
        if not arg:
            await self.send_text(session_id, "用法: /设置参考音频 <路径或序号>")
            return

        raw = str(arg).strip()
        if raw.lower() in {"default", "clear", "reset", "none", "空", "清除", "重置"}:
            prefs["reference_audio"] = None
            try:
                user_id = parse_session_user_id(session_id)
                await self.adapter.config_handler.persist_user_override(user_id, prefs)
            except Exception as e:
                self.logger.warning(f"persist_user_override failed after clear reference audio: {e}")
            await self.send_text(session_id, "参考音频已清除，将使用默认音色")
            return

        cache = self.adapter._list_cache.get(session_id)
        if raw.isdigit() and (not cache or cache.get("type") != "voice"):
            await self.show_voices(session_id, prefs)
            cache = self.adapter._list_cache.get(session_id)

        target_path = raw
        if raw.isdigit() and cache and cache.get("type") == "voice":
            idx = int(raw) - 1
            voices = cache.get("data", [])
            if 0 <= idx < len(voices):
                target_path = str((voices[idx] or {}).get("path") or "").strip()
            else:
                await self.send_text(session_id, f"参考音频序号 {idx+1} 无效，可用范围: 1-{len(voices)}")
                return

        if raw.isdigit() and (not target_path or target_path == raw):
            await self.send_text(session_id, "未找到对应序号的参考音频，请先发送 /参考音频 获取列表")
            return

        if not raw.isdigit() and "/" not in raw and "\\" not in raw:
            status, data = await self.api_request("GET", "/api/v1/voice/reference-audio")
            if status == 200 and isinstance(data, dict):
                files = data.get("files", [])
                if isinstance(files, list):
                    for item in files:
                        name = str((item or {}).get("name") or "").strip()
                        path = str((item or {}).get("path") or "").strip()
                        if name and raw.lower() == name.lower() and path:
                            target_path = path
                            break

        prefs["reference_audio"] = target_path
        try:
            user_id = parse_session_user_id(session_id)
            await self.adapter.config_handler.persist_user_override(user_id, prefs)
        except Exception as e:
            self.logger.warning(f"persist_user_override failed after set reference audio: {e}")
        await self.send_text(session_id, f"参考音频已设置: {os.path.basename(target_path)}")

    async def handle_image_gen(self, session_id, prompt, prefs):
        if not prompt:
            await self.send_text(session_id, "请输入提示词")
            return
            
        model_path = prefs.get("image_model")
        await self.send_text(session_id, "正在生成图片，请稍候...")
        
        body = {"prompt": prompt}
        if model_path:
            body["model_path"] = model_path
            
        status, data = await self.api_request("POST", "/api/v1/image/generate", json_body=body)
        
        if status == 200 and data.get("success"):
            image_path = data.get("image_path")
            if image_path and os.path.exists(image_path):
                await self.send_text(session_id, _build_cq_image(image_path))
            else:
                 await self.send_friendly_error(session_id, "生成图片", "文件路径无效")
        else:
             err = data.get("message") or "未知错误"
             await self.send_friendly_error(session_id, "生成图片", err)
