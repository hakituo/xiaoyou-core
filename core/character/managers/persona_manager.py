from core.utils.logger import get_logger
import os
import json

import re
from typing import List, Dict, Optional, Any
from core.utils.time_utils import get_current_time

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
        
        if sfw_only:
             # SFW Mode: Try QQ Master first, then Cloud SFW
             self.current_persona_file = "qq/Aveline_QQ_Master.json"
             if not os.path.exists(os.path.join(self.configs_dir, self.current_persona_file)):
                 self.current_persona_file = "sfw/Aveline_DeepSeek_SFW.json"
             if not os.path.exists(os.path.join(self.configs_dir, self.current_persona_file)):
                 self.current_persona_file = "sfw/Aveline_Cloud_SFW.json"
        else:
            # Default Mode: Try QQ Master first, then NSFW/SFW fallbacks
            self.current_persona_file = "qq/Aveline_QQ_Master.json"
            if not os.path.exists(os.path.join(self.configs_dir, self.current_persona_file)):
                self.current_persona_file = "sfw/Aveline_DeepSeek_SFW.json"
            if not os.path.exists(os.path.join(self.configs_dir, self.current_persona_file)):
                self.current_persona_file = "nsfw/Aveline_L3_NSFW.json"
            if not os.path.exists(os.path.join(self.configs_dir, self.current_persona_file)):
                self.current_persona_file = "sfw/Aveline_Cloud_SFW.json"
            if not os.path.exists(os.path.join(self.configs_dir, self.current_persona_file)):
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

    def list_personas(self) -> List[Dict[str, str]]:
        """List all available persona JSON files recursively"""
        personas = []
        if not os.path.exists(self.configs_dir):
            return []
            
        # Check for SFW only mode
        sfw_only = str(os.getenv("XIAOYOU_SFW_ONLY", "")).lower() in ("true", "1", "yes", "on")
        
        for root, dirs, files in os.walk(self.configs_dir):
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
                    if "nsfw" in dir_parts or "sensitive" in dir_parts:
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
                        elif "nsfw" in dir_parts or "sensitive" in dir_parts:
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
        return personas

    def set_persona(self, filename: str) -> bool:
        """Set the current persona by filename"""
        path = os.path.join(self.configs_dir, filename)
        if not os.path.exists(path):
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
            if not os.path.exists(target):
                logger.warning(f"Persona file not found when loading by filename: {rel}")
                return {}
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

    def update_dynamic_traits(self, evolution_data: Dict) -> bool:
        """
        Update persona evolution history in separated storage.
        path: core/character/configs/evolution/{YYYY}/{MM}.json
        """
        try:
            now = get_current_time()
            year = now.strftime("%Y")
            month = now.strftime("%m")
            
            evo_dir = os.path.join(self.configs_dir, "evolution", year)
            if not os.path.exists(evo_dir):
                os.makedirs(evo_dir)
                
            filename = f"{month}.json"
            filepath = os.path.join(evo_dir, filename)
            
            record = {
                "date": now.strftime("%Y-%m-%d %H:%M:%S"),
                "source": "monthly_summary",
                "content": evolution_data
            }
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(record, f, indent=2, ensure_ascii=False)
                
            logger.info(f"Updated persona evolution at {filepath}")
            return True
        except Exception as e:
            logger.error(f"Failed to update dynamic traits: {e}")
            return False

    def get_recent_evolution(self, limit: int = 3) -> List[Dict]:
        """
        Retrieve recent persona evolution records from storage.
        """
        records = []
        evo_root = os.path.join(self.configs_dir, "evolution")
        if not os.path.exists(evo_root):
            return []
            
        try:
            # Walk through years and months
            # We want reverse chronological order
            years = sorted([d for d in os.listdir(evo_root) if d.isdigit()], reverse=True)
            
            for year in years:
                year_dir = os.path.join(evo_root, year)
                if not os.path.isdir(year_dir):
                    continue
                months = sorted([f for f in os.listdir(year_dir) if f.endswith(".json")], reverse=True)
                
                for month_file in months:
                    path = os.path.join(year_dir, month_file)
                    try:
                        with open(path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            records.append(data)
                            if len(records) >= limit:
                                return records
                    except Exception as e:
                        logger.error(f"Error reading evolution file {path}: {e}")
        except Exception as e:
            logger.error(f"Error listing evolution directories: {e}")
            
        return records

_persona_manager = PersonaManager()

def get_persona_manager():
    return _persona_manager
