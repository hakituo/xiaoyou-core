import sys
import traceback

print(f"Python version: {sys.version}")

try:
    import chromadb
    print(f"chromadb version: {chromadb.__version__}")
    from chromadb import Client
    from chromadb.config import Settings
    print("chromadb.Client imported successfully")
except Exception:
    traceback.print_exc()

import sqlite3
print(f"sqlite3 version: {sqlite3.version}")
print(f"sqlite3.sqlite_version: {sqlite3.sqlite_version}")
