import os
import shutil
import subprocess
from pathlib import Path

lib_path = ""
try:
    import llama_cpp

    base_dir = Path(llama_cpp.__file__).resolve().parent
    if os.name == "nt":
        candidates = [
            base_dir / "lib" / "llama.dll",
            *list(base_dir.glob("**/*.dll")),
        ]
        lib_path = next(
            (
                str(p)
                for p in candidates
                if p.name.lower() == "llama.dll" and p.exists()
            ),
            "",
        )
    elif os.name == "posix":
        candidates = [
            *list(base_dir.glob("**/libllama.so")),
            *list(base_dir.glob("**/llama.so")),
            *list(base_dir.glob("**/*.so")),
            *list(base_dir.glob("**/*.dylib")),
        ]
        lib_path = next(
            (str(p) for p in candidates if "llama" in p.name.lower() and p.exists()), ""
        )
except Exception:
    lib_path = ""

if not lib_path or not os.path.exists(lib_path):
    print(f"未找到 llama 相关动态库: {lib_path}")
    raise SystemExit(1)

try:
    if os.name == "nt":
        import pefile

        pe = pefile.PE(lib_path)
        print(f"Exports for {lib_path}:")
        for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
            if not exp.name:
                continue
            name = exp.name.decode("utf-8", errors="ignore")
            if "sample" in name or "token" in name:
                print(name)
    else:
        nm = shutil.which("nm")
        if not nm:
            print(f"已找到动态库: {lib_path}")
            print("未找到 nm，无法列出导出符号")
            raise SystemExit(0)

        result = subprocess.run(
            [nm, "-D", "--defined-only", lib_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "nm 执行失败")

        print(f"Exports for {lib_path}:")
        for line in result.stdout.splitlines():
            name = (line.split() or [""])[-1]
            if "sample" in name or "token" in name:
                print(name)
except Exception as e:
    print(f"Error: {e}")
