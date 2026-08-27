import PyInstaller.__main__
import os
import site

# Ensure frontend is built
frontend_dist = os.path.join("clients", "frontend", "Aveline_UI", "dist")
if not os.path.exists(frontend_dist):
    print("Error: Frontend dist folder not found. Please build frontend first.")
    exit(1)

# Find llama_cpp lib directory
site_packages = site.getsitepackages()[0]  # Usually the first one in venv
if os.path.basename(site_packages) != "site-packages":
    # Fallback for some venv structures
    for p in site.getsitepackages():
        if os.path.basename(p) == "site-packages":
            site_packages = p
            break

llama_cpp_lib = os.path.join(site_packages, "llama_cpp", "lib")
if not os.path.exists(llama_cpp_lib):
    # Try hardcoded path if standard discovery fails
    llama_cpp_lib = os.path.join(
        os.getcwd(), "venv_core", "Lib", "site-packages", "llama_cpp", "lib"
    )

if not os.path.exists(llama_cpp_lib):
    print(
        f"Warning: llama_cpp lib folder not found at {llama_cpp_lib}. Llama models might fail."
    )

# Define resources to include
datas = [
    (frontend_dist, "static"),  # Source, Dest (relative to _MEIPASS)
    ("architecture.svg", "assets"),  # Include assets if needed
    (".env.example", "."),  # Include env example
    ("ref_audio", "ref_audio"),  # Include TTS reference audio
    ("config/yaml", "config/yaml"),  # Include YAML configs
]

if os.path.exists(llama_cpp_lib):
    datas.append((llama_cpp_lib, "llama_cpp/lib"))

# Construct --add-data arguments
add_data_args = []
separator = ";" if os.name == "nt" else ":"
for src, dst in datas:
    add_data_args.append(f"--add-data={src}{separator}{dst}")

# Hidden imports
hidden_imports = [
    "main",
    "uvicorn",
    "fastapi",
    "core",
    "routers",
    "pystray",
    "PIL",
    "tkinter",
    "webview",  # Added pywebview
    "clr_loader",  # pythonnet dependency
    "pythonnet",
]
hidden_import_args = []
for mod in hidden_imports:
    hidden_import_args.append(f"--hidden-import={mod}")

# Build command
args = (
    [
        "main.py",
        "--name=XiaoyouCore",
        "--onedir",
        "--windowed",
        "--clean",
        "--noconfirm",
        "--noupx",
        # "--debug=all",
    ]
    + add_data_args
    + hidden_import_args
)

print("Running PyInstaller with args:", args)

PyInstaller.__main__.run(args)
