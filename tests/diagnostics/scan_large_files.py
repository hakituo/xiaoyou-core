import os

base = '.'
big_files = []
# 排除所有非核心目录
skip_dirs = {
    'node_modules', '.git', '__pycache__', 'build', 'legacy', 'external',
    'venv_core', 'venv', '.pnpm',
    # 外部第三方库/模型（不维护的）
    'models', 'clients',
    # IDE/工具
    '.idea', '.vscode', '.pytest_cache', '.mypy_cache', '__pycache__',
}

for root, dirs, files in os.walk(base):
    # 修改 dirs 列表以跳过不需要的目录
    dirs[:] = [d for d in dirs if d not in skip_dirs]

    for file in files:
        if file.endswith('.py'):
            filepath = os.path.join(root, file)
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = sum(1 for _ in f)
                if lines > 500:
                    rel_path = os.path.relpath(filepath, base)
                    size_kb = os.path.getsize(filepath) / 1024
                    big_files.append((lines, rel_path, round(size_kb, 1)))
            except Exception:
                pass

big_files.sort(key=lambda x: x[0], reverse=True)

print('=' * 110)
print(f"{'排名':<4} {'行数':>7} {'大小(KB)':>9} 文件路径")
print('=' * 110)
for i, (lines, path, size) in enumerate(big_files[:35], 1):
    print(f"{i:<4} {lines:>7} {size:>9.1f} {path}")
print('=' * 110)
print(f"\n总计发现 {len(big_files)} 个大文件 (>500 行)")
