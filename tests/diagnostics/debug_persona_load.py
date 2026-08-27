
import os
import sys
import json
import traceback

# Add project root to path
sys.path.append(r"d:\AI\xiaoyou-core")

from core.character.managers.persona_manager import PersonaManager

def debug_load():
    pm = PersonaManager()
    
    # Test loading core_aveline.json directly
    print("--- Testing core_aveline.json ---")
    core_path = os.path.join(pm.configs_dir, "core_aveline.json")
    if os.path.exists(core_path):
        try:
            with open(core_path, 'r', encoding='utf-8') as f:
                json.load(f)
            print("PASS: core_aveline.json is valid JSON.")
        except Exception as e:
            print(f"FAIL: core_aveline.json is INVALID JSON: {e}")
    else:
        print(f"FAIL: core_aveline.json not found at {core_path}")

    # Test loading study/Aveline_Study.json
    print("\n--- Testing study/Aveline_Study.json ---")
    study_file = "study/Aveline_Study.json"
    pm.current_persona_file = study_file
    
    # Manually trigger recursive load to see traceback
    study_path = os.path.join(pm.configs_dir, study_file)
    if os.path.exists(study_path):
        try:
            with open(study_path, 'r', encoding='utf-8') as f:
                json.load(f)
            print("PASS: study/Aveline_Study.json is valid JSON.")
        except Exception as e:
            print(f"FAIL: study/Aveline_Study.json is INVALID JSON: {e}")
            
        try:
            print("Attempting _load_persona_recursive...")
            data = pm._load_persona_recursive(study_path)
            print("PASS: _load_persona_recursive succeeded.")
            print(f"Keys: {list(data.keys())}")
        except Exception as e:
            print(f"FAIL: _load_persona_recursive failed: {e}")
            traceback.print_exc()
    else:
        print(f"FAIL: study/Aveline_Study.json not found at {study_path}")

if __name__ == "__main__":
    debug_load()
