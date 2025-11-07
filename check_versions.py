import sys
import asyncio
import psutil

print(f"Python version: {sys.version}")
print(f"asyncio version: {asyncio.__version__ if hasattr(asyncio, '__version__') else 'built-in module'}")
print(f"psutil version: {psutil.__version__}")