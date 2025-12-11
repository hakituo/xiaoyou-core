import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.config_loader import ConfigLoader

def debug_config():
    loader = ConfigLoader()
    print("Config Loader Initialized.")
    
    # Check 'app' config
    app_config = loader.configs.get('app', {})
    print(f"\nApp Config keys: {list(app_config.keys())}")
    
    if 'system' in app_config:
        print(f"App System Config: {app_config['system']}")
    else:
        print("App config does not have 'system' key.")
        
    # Check 'system' config (top level from environment or other)
    system_config = loader.configs.get('system', {})
    print(f"\nSystem Config keys: {list(system_config.keys())}")
    print(f"System Config Content: {system_config}")

    # Check retrieval
    val1 = loader.get('system.dashscope_api_key')
    print(f"\nget('system.dashscope_api_key'): {val1}")
    
    val2 = loader.get('app.system.dashscope_api_key')
    print(f"get('app.system.dashscope_api_key'): {val2}")

    # Check env vars
    print(f"\nDASHSCOPE_API_KEY env var: {os.getenv('DASHSCOPE_API_KEY')}")

if __name__ == "__main__":
    debug_config()
