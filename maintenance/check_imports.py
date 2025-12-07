import os
import ast
import sys

def check_imports(directory):
    """
    Walks through a directory, parses Python files, and checks imports.
    """
    print(f"Scanning directory: {directory}")
    
    # Mappings of known moved modules
    moved_modules = {
        'core.life_simulation': 'core.services.life_simulation.service',
        'core.websocket_manager': 'core.interfaces.websocket.websocket_manager',
        'core.lifecycle_manager': 'core.core_engine.lifecycle_manager',
        'core.event_bus': 'core.core_engine.event_bus',
        'core.model_manager': 'core.core_engine.model_manager',
        # Add other known moves here if needed
    }

    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith(".py"):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        tree = ast.parse(f.read(), filename=file_path)
                    
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                if alias.name in moved_modules:
                                    print(f"[WARN] {file_path}:{node.lineno} - Import '{alias.name}' might be deprecated. Consider using '{moved_modules[alias.name]}'.")
                        elif isinstance(node, ast.ImportFrom):
                            if node.module and node.module in moved_modules:
                                print(f"[WARN] {file_path}:{node.lineno} - From import '{node.module}' might be deprecated. Consider using '{moved_modules[node.module]}'.")
                                
                except Exception as e:
                    print(f"[ERROR] Failed to parse {file_path}: {e}")

if __name__ == "__main__":
    target_dir = "D:\\AI\\xiaoyou-core"
    check_imports(target_dir)
