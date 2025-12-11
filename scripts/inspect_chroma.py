import chromadb
import inspect

print(f"chromadb version: {chromadb.__version__}")
print(f"chromadb.Client: {chromadb.Client}")
try:
    print(f"chromadb.PersistentClient: {chromadb.PersistentClient}")
except AttributeError:
    print("chromadb.PersistentClient not found")

print(f"inspect.signature(chromadb.Client): {inspect.signature(chromadb.Client)}")
