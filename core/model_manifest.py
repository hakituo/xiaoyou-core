import os
import json
import hashlib
from typing import Dict, Any, Optional

MANIFEST_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", "manifest.json")

def calc_dir_hash(directory: str) -> str:
    if not os.path.exists(directory):
        return ""
    hasher = hashlib.md5()
    for root, _, files in os.walk(directory):
        for f in sorted(files):
            p = os.path.join(root, f)
            try:
                with open(p, "rb") as fh:
                    buf = fh.read(65536)
                    while buf:
                        hasher.update(buf)
                        buf = fh.read(65536)
            except Exception:
                continue
    return hasher.hexdigest()

def load_manifest(path: Optional[str] = None) -> Dict[str, Any]:
    p = path or MANIFEST_PATH
    if not os.path.exists(p):
        return {"models": []}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"models": []}

def update_model_hashes(manifest: Dict[str, Any]) -> Dict[str, Any]:
    models = manifest.get("models") or []
    for m in models:
        model_path = m.get("path") or ""
        m["hash"] = calc_dir_hash(model_path)
    return {"models": models}

def save_manifest(manifest: Dict[str, Any], path: Optional[str] = None) -> None:
    p = path or MANIFEST_PATH
    with open(p, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

