import os
import sys

# Add the build directory to the Python path so it can find the .pyd file
build_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build", "Release")
sys.path.append(build_dir)

try:
    import bert_engine_py
    print("[SUCCESS] Successfully imported bert_engine_py!")
    print(f"Module docstring: {bert_engine_py.__doc__}")
    print("The C++ BERT engine is ready to be integrated.")
except ImportError as e:
    print(f"[ERROR] Failed to import bert_engine_py: {e}")
    print("Make sure the project compiled successfully and the .pyd file is in the build/Release directory.")
