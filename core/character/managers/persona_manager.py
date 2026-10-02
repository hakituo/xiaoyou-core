from core.utils.logger import get_logger
import os
import json

import re
from pathlib import Path
from typing import List, Dict, Optional, Any, Iterator

logger = get_logger("PersonaManager")

class PersonaManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PersonaManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        self.configs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'configs')
        
        # Check for SFW only mode
        sfw_only = str(os.getenv("XIAOYOU_SFW_ONLY", "")).lower() in ("true", "1", "yes", "on")
        
        # 启动默认人设的唯一来源是 app.yaml 的 persona.default_map（见 config/persona_config.py）；
        # 这里只负责在配置缺失或文件不存在时回退到既有兜底人设。
        self.current_persona_file = self._resolve_startup_persona_file()

        if not self._persona_file_exists(self.current_persona_file):
            # SFW Mode: 默认核心人设，缺失时再回退 Cloud SFW
            self.current_persona_file = "sfw/Aveline_DeepSeek_SFW.json"
        if not self._persona_file_exists(self.current_persona_file):
            self.current_persona_file = "sfw/Aveline_Cloud_SFW.json"
        if not sfw_only and not self._persona_file_exists(self.current_persona_file):
            # Default Mode 再回退学习人设
            self.current_persona_file = "study/Aveline_Study.json"

        self.current_persona_data = {}
        self.model_persona_map = {} # model_name -> persona_file
        self._revision = 0
        
        self._load_current_persona()
        self._initialized = True

    def _inject_extras(self):
        """Inject distilled memories and extra profiles into the persona"""
        enabled = str(os.getenv("XIAOYOU_PERSONA_INJECT_EXTRAS", "")).lower() in (
            "true",
            "1",
            "yes",
            "on",
        )
        if not enabled:
            return

        try:
            max_chars = int(os.getenv("XIAOYOU_PERSONA_EXTRAS_MAX_CHARS", "0") or "0")
        except Exception:
            max_chars = 0

        extra_dir = os.path.join(self.configs_dir, "extra")
        if not os.path.exists(extra_dir):
            return

        # Find all distilled_profile.md files
        profiles = []
        # Walk and collect all distilled profiles
        for root, _, files in os.walk(extra_dir):
            for f in files:
                if f == "distilled_profile.md":
                    path = os.path.join(root, f)
                    try:
                        with open(path, "r", encoding="utf-8") as file:
                            content = str(file.read() or "").strip()
                            if max_chars > 0 and len(content) > max_chars:
                                content = content[:max_chars].rstrip()
                            profiles.append(content)
                    except Exception as e:
                        logger.error(f"Failed to read extra profile {path}: {e}")
        
        if profiles:
            combined_extras = "\n\n".join(profiles)
            # Inject into system_prompt_template
            if "system_prompt_template" in self.current_persona_data:
                # Avoid duplication if re-injected (simple check)
                tmpl = str(self.current_persona_data.get("system_prompt_template") or "")
                if "### Additional Memory Context" not in tmpl and "【额外画像】" not in tmpl:
                    self.current_persona_data["system_prompt_template"] = (
                        tmpl.rstrip() + f"\n\n【额外画像】\n{combined_extras}"
                    )
                    logger.info(f"Injected {len(profiles)} extra profile(s) into system prompt.")

    def _iter_layered_personas(self) -> Iterator[tuple[Path, Dict[str, Any]]]:
        """发现分层人设入口，保留旧 filename 作为客户端稳定标识。"""
        for path in sorted(Path(self.configs_dir).glob("*/core_*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    continue
                meta = data.get("meta")
                identity = data.get("identity")
                if not isinstance(meta, dict) or not isinstance(identity, dict):
                    continue
                scope = str(meta.get("scope") or "").strip()
                if path.parent.name != scope or path.name != f"core_{scope}.json":
                    continue
                if not re.fullmatch(r"[a-z][a-z0-9_]*", scope) or meta.get("deprecated"):
                    continue
                # v2 用 nickname/real_name 描述身份；兼容列表与旧调用方的 name 字段。
                identity["name"] = (
                    identity.get("name") or identity.get("nickname")
                    or identity.get("real_name") or scope
                )
                yield path, data
            except (OSError, ValueError) as exc:
                logger.warning("读取分层人设入口失败 %s: %s", path, exc)

    def _find_layered_persona(self, filename: str) -> Dict[str, Any]:
        """旧文件已移除时，按入口文件名或声明的文件别名加载 v2。"""
        token = str(filename or "").strip().replace("\\", "/").lower()
        for path, data in self._iter_layered_personas():
            aliases = data["meta"].get("aliases") or []
            if not isinstance(aliases, list):
                aliases = []
            filenames = [path.name] + [
                alias for alias in aliases
                if isinstance(alias, str) and alias.lower().endswith(".json")
            ]
            if token in {name.replace("\\", "/").lower() for name in filenames}:
                return data
        return {}

    def list_personas(self) -> List[Dict[str, Any]]:
        """列出旧版配置与 Persona 2.0 分层入口。"""
        personas = []
        layered_personas = list(self._iter_layered_personas())
        layered_dirs = {path.parent for path, _ in layered_personas}
            
        # Check for SFW only mode
        sfw_only = str(os.getenv("XIAOYOU_SFW_ONLY", "")).lower() in ("true", "1", "yes", "on")
        
        for root, dirs, files in os.walk(self.configs_dir):
            # 分层目录只暴露核心入口，知识、语气与覆盖层不能被当成独立人设。
            if Path(root) in layered_dirs:
                dirs[:] = []
                continue
            # Ignore legacy folder
            if "legacy" in os.path.relpath(root, self.configs_dir).lower().split(os.sep):
                continue
                
            for f in files:
                # Explicitly skip reference dialogue files and other non-persona JSONs
                if f.endswith(".json") and not f.startswith("special_") and "reference_dialogue" not in f:
                    path = os.path.join(root, f)
                    
                    # Determine category based on folder name
                    rel_dir = os.path.relpath(root, self.configs_dir)
                    category = "general"
                    dir_parts = rel_dir.lower().split(os.sep)
                    if "sensitive" in dir_parts:
                        category = "sensitive"
                    elif "sfw" in dir_parts:
                        category = "sfw"
                    
                    # SFW Only Filtering
                    if sfw_only and category != "sfw":
                        continue
                        
                    try:
                        # 读取失败时最多重试一次，规避文件处于"保存中途"导致的
                        # 偶发 JSON 截断（Unterminated string）问题
                        data = None
                        for attempt in range(2):
                            try:
                                with open(path, 'r', encoding='utf-8') as file:
                                    data = json.load(file)
                                break
                            except Exception:
                                if attempt == 0:
                                    import time
                                    time.sleep(0.1)
                                else:
                                    raise

                        # Validation: Must be a dict (not list like reference_dialogue)
                        if not isinstance(data, dict):
                            continue

                        # Validation: Must have identity or extends (valid persona markers)
                        if "identity" not in data and "extends" not in data:
                            continue

                        # 跳过已废弃的人设
                        meta = data.get("meta", {})
                        if isinstance(meta, dict) and meta.get("deprecated"):
                            continue

                        name = data.get("identity", {}).get("name", "Unknown")
                        version = data.get("meta", {}).get("version") or data.get("identity", {}).get("version", "1.0.0")

                        # 提取角色标识（role）：以 identity.name 去掉括号后缀作为角色名
                        # 例如 "Aveline (QQ)" -> "Aveline"；"Ling" -> "Ling"
                        # 用于 Android 端按角色分组展示 persona 列表
                        role_name = str(name).split("(")[0].split("（")[0].strip()
                        if not role_name:
                            role_name = str(name)

                        # Determine category based on folder name (Recalculate or reuse)
                        rel_dir = os.path.relpath(root, self.configs_dir)
                        category = "general"
                        dir_parts = rel_dir.lower().split(os.sep)
                        if "daily" in dir_parts:
                            category = "daily"
                        elif "study" in dir_parts:
                            category = "study"
                        elif "sensitive" in dir_parts:
                            category = "sensitive"
                        elif "sfw" in dir_parts:
                            category = "sfw"

                        # 可访问角色列表（显式声明，用于双QQ模式过滤）
                        # 例如敏感人设 Frost.json 声明 ["ling"]，则Ling账号可见
                        meta_dict = data.get("meta", {}) if isinstance(data.get("meta"), dict) else {}
                        accessible_roles = meta_dict.get("accessible_roles") or []

                        # Get relative path for switching
                        rel_path = os.path.relpath(path, self.configs_dir).replace("\\", "/")

                        personas.append({
                            "filename": rel_path,
                            "name": name,
                            "version": version,
                            "path": path,
                            "category": category,
                            "accessible_roles": accessible_roles,
                            "role": role_name,
                        })
                    except Exception as e:
                        logger.error(f"Failed to read persona {f}: {e}")
        # 同目录发现的 v2 核心入口沿用原 filename，避免改变客户端偏好与历史标识。
        known_filenames = {p["filename"].lower() for p in personas}
        for path, data in layered_personas:
            meta = data["meta"]
            category = str(meta.get("category") or "general")
            if sfw_only and category != "sfw":
                continue
            if path.name.lower() in known_filenames:
                continue
            name = data["identity"]["name"]
            personas.append({
                "filename": path.name,
                "name": name,
                "version": meta.get("version") or data.get("version") or "2.0.0",
                "path": str(path),
                "category": category,
                "accessible_roles": meta.get("accessible_roles") or [],
                "role": str(name).split("(")[0].split("（")[0].strip(),
            })
            known_filenames.add(path.name.lower())
        return self._mark_and_order_defaults(personas)

    def _resolve_startup_persona_file(self) -> str:
        """启动默认人设：persona.default_map 里 aveline 那一项，读不到才回退内置值。"""
        try:
            from config.persona_config import get_default_persona_filename

            return get_default_persona_filename("aveline", "core_aveline.json") or "core_aveline.json"
        except Exception as exc:
            logger.debug(f"读取 persona.default_map 失败，回退 core_aveline.json: {exc}")
            return "core_aveline.json"

    def _persona_file_exists(self, filename: str) -> bool:
        """人设文件是否存在；只以入口名声明的分层人设（如 aveline/core_aveline.json）也算存在。"""
        name = str(filename or "").strip()
        if not name:
            return False
        if os.path.exists(os.path.join(self.configs_dir, name)):
            return True
        try:
            return bool(self._find_layered_persona(name))
        except Exception:
            return False

    def _mark_and_order_defaults(self, personas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """按 persona.default_map 标注默认人设，并把默认人设排到该角色第一位。

        客户端按角色分组后取“该角色第一个 persona”作为默认选中项，因此默认人设必须
        排在最前；未被配置覆盖到的角色保持原发现顺序，不做猜测。
        """
        try:
            from config.persona_config import get_default_persona_filename
        except Exception:
            return personas

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        role_order: List[str] = []
        for item in personas:
            role = str(item.get("role") or "")
            if role not in grouped:
                grouped[role] = []
                role_order.append(role)
            filename = str(item.get("filename") or "").replace("\\", "/")
            default_name = get_default_persona_filename(filename, "").replace("\\", "/")
            item["is_default"] = bool(default_name) and filename.lower() == default_name.lower()
            grouped[role].append(item)

        ordered: List[Dict[str, Any]] = []
        for role in role_order:
            group = grouped[role]
            ordered.extend([item for item in group if item.get("is_default")])
            ordered.extend([item for item in group if not item.get("is_default")])
        return ordered

    def set_persona(self, filename: str) -> bool:
        """Set the current persona by filename"""
        path = os.path.join(self.configs_dir, filename)
        if not os.path.exists(path) and not self._find_layered_persona(filename):
            logger.error(f"Persona file not found: {filename}")
            return False

        prev_file = self.current_persona_file
        self.current_persona_file = filename
        ok = self._load_current_persona()
        if not ok:
            self.current_persona_file = prev_file
            self._load_current_persona()
            return False

        self._revision += 1

        try:
            from core.agents.chat_agent_components.persona_system.prompt.data import clear_persona_cache
            clear_persona_cache()
        except Exception:
            pass

        # 清除 OOC Emoji 过滤缓存
        try:
            from clients.bots.qq.utils import clear_allowed_emoji_cache
            clear_allowed_emoji_cache()
        except Exception:
            pass

        return True

    def get_revision(self) -> int:
        try:
            return int(self._revision)
        except Exception:
            return 0

    def get_persona_by_filename(self, filename: str) -> Dict[str, Any]:
        try:
            rel = str(filename or "").strip().replace("\\", "/")
            if not rel:
                return {}
            target = os.path.join(self.configs_dir, rel)
            data = self._load_persona_recursive(target)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.error(f"Failed to load persona by filename {filename}: {e}")
            return {}

    def _load_current_persona(self) -> bool:
        path = os.path.join(self.configs_dir, self.current_persona_file)
        try:
            self.current_persona_data = self._load_persona_recursive(path)

            if isinstance(self.current_persona_data, dict):
                # 1. Expand {base_system_prompt} if it exists
                system_prompt_base = str(self.current_persona_data.get("system_prompt_base") or "")
                system_prompt_template = str(self.current_persona_data.get("system_prompt_template") or "")
                if not system_prompt_template:
                    interaction = self.current_persona_data.get("interaction_logic")
                    if isinstance(interaction, dict):
                        system_prompt_template = str(interaction.get("system_prompt_template") or "")
                
                if "{base_system_prompt}" in system_prompt_template:
                    if system_prompt_base:
                        try:
                            system_prompt_template = system_prompt_template.replace("{base_system_prompt}", system_prompt_base)
                            self.current_persona_data["system_prompt_template"] = system_prompt_template
                            logger.info("Injected base_system_prompt into system_prompt_template")
                        except Exception as e:
                            logger.error(f"Failed to inject base_system_prompt: {e}")
                    else:
                        logger.warning("{base_system_prompt} placeholder found but system_prompt_base is empty")
                elif system_prompt_template and not self.current_persona_data.get("system_prompt_template"):
                    self.current_persona_data["system_prompt_template"] = system_prompt_template
                
                # 2. Infer user name if missing
                user_profile = self.current_persona_data.get("user_profile")
                has_name = False
                if isinstance(user_profile, dict):
                    has_name = bool(str(user_profile.get("name") or "").strip())
                if not has_name:
                    inferred_name = self._infer_user_name_from_persona(self.current_persona_data)
                    if inferred_name:
                        self.current_persona_data["user_profile"] = {"name": inferred_name}
            
            # Inject extra memories
            self._inject_extras()
            
            logger.info(f"Loaded persona: {self.current_persona_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to load persona {self.current_persona_file}: {e}")
            return False

    def _load_persona_recursive(self, path: str, visited=None) -> Dict:
        """递归加载人设配置，支持 extends 继承"""
        if visited is None:
            visited = set()
            
        if path in visited:
            logger.error(f"Circular inheritance detected: {path}")
            return {}
            
        visited.add(path)
        
        if not os.path.exists(path):
            rel = os.path.relpath(path, self.configs_dir).replace("\\", "/")
            layered = self._find_layered_persona(rel)
            if layered:
                return layered
            logger.error(f"Persona file not found: {path}")
            return {}
            
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        parent_file = data.get("extends")
        if parent_file:
            # 寻找父配置文件，支持相对路径和相对于 configs_dir 的路径
            parent_path = os.path.join(os.path.dirname(path), parent_file)
            if not os.path.exists(parent_path):
                parent_path = os.path.join(self.configs_dir, parent_file)
                
            if os.path.exists(parent_path):
                parent_data = self._load_persona_recursive(parent_path, visited)
                # 合并数据：子配置覆盖父配置
                merged = self._deep_merge(parent_data, data)
                
                # 特殊处理：system_prompt_base 需要追加而不是覆盖 (或者根据需求决定)
                # 目前逻辑：子配置如果定义了 system_prompt_base，通常是替换。
                # 但如果是 Template 继承，我们需要确保子 template 能访问到父的 base
                
                # 修复：确保 system_prompt_base 从父级继承（如果子级没写）
                # _deep_merge 已经处理了 key 覆盖。如果子级没有 system_prompt_base，会自动用父级的。
                # 如果子级有，就用子级的。
                
                return merged
            else:
                logger.warning(f"Parent persona file not found: {parent_file}")
                
        return data

    def _deep_merge(self, base: Dict, override: Dict) -> Dict:
        """深度合并两个字典"""
        result = base.copy()
        for key, value in override.items():
            if key == "extends":
                continue
            if isinstance(value, dict) and key in result and isinstance(result[key], dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def _infer_user_name_from_persona(self, persona: Dict) -> str:
        if not isinstance(persona, dict):
            return ""

        def _iter_strings(obj: Any):
            if isinstance(obj, str):
                yield obj
                return
            if isinstance(obj, dict):
                for v in obj.values():
                    yield from _iter_strings(v)
                return
            if isinstance(obj, list):
                for v in obj:
                    yield from _iter_strings(v)
                return

        # for s in _iter_strings(persona):
        #     if "Master" in s:
        #         return "Master"

        candidates: List[str] = []
        identity = persona.get("identity")
        if isinstance(identity, dict):
            core_identity = identity.get("core_identity")
            if isinstance(core_identity, dict):
                candidates.append(str(core_identity.get("primary_objective") or ""))
            candidates.append(str(identity.get("context") or ""))
            candidates.append(str(identity.get("greeting") or ""))

        tmpl = persona.get("system_prompt_template")
        if isinstance(tmpl, str):
            candidates.append(tmpl)
        meta = persona.get("meta")
        if isinstance(meta, dict):
            field_desc = meta.get("field_descriptions")
            if isinstance(field_desc, dict):
                nested_tmpl = field_desc.get("system_prompt_template")
                if isinstance(nested_tmpl, str):
                    candidates.append(nested_tmpl)

        patterns = [
            r"陪伴我的\s*([A-Za-z0-9_\u4e00-\u9fff]{1,12})",
            r"created by\s*([A-Za-z0-9_\u4e00-\u9fff]{1,12})",
            r"深深爱着\s*([A-Za-z0-9_\u4e00-\u9fff]{1,12})",
            r"爱着\s*([A-Za-z0-9_\u4e00-\u9fff]{1,12})",
            r"分析\s*([A-Za-z0-9_\u4e00-\u9fff]{1,12})\s*话语",
            r"对\s*([A-Za-z0-9_\u4e00-\u9fff]{1,12})\s*的事情",
        ]

        for text in candidates:
            s = str(text or "")
            if not s.strip():
                continue
            for pat in patterns:
                m = re.search(pat, s, flags=re.IGNORECASE)
                if m:
                    name = (m.group(1) or "").strip()
                    if name and name != "用户":
                        return name
        return ""

    def get_current_persona(self) -> Dict:
        return self.current_persona_data
    
    def get_current_filename(self) -> str:
        return self.current_persona_file

    def set_persona_for_model(self, model_name: str, persona_filename: str):
        self.model_persona_map[model_name] = persona_filename
        
    def get_persona_for_model(self, model_name: str) -> Optional[str]:
        return self.model_persona_map.get(model_name)

_persona_manager = PersonaManager()

def get_persona_manager():
    return _persona_manager
