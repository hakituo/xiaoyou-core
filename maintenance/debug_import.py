import sys
import os
import traceback

print(f"Python Executable: {sys.executable}")
print(f"CWD: {os.getcwd()}")
print(f"Sys Path: {sys.path}")

try:
    import llama_cpp

    print(f"llama_cpp imported successfully: {llama_cpp.__file__}")
    from llama_cpp import Llama

    print(f"Llama class imported successfully: {Llama}")
except ImportError as e:
    print(f"ImportError caught: {e}")
    traceback.print_exc()
except Exception as e:
    print(f"Other Exception caught: {e}")
    traceback.print_exc()
