"""临时脚本：查找 core/ 和 clients/ 中 __init__/__new__ 方法内的 asyncio.Lock() 调用"""
import ast
import os
import sys


def find_asyncio_locks_in_init(directory: str):
    """查找指定目录中所有 __init__/__new__ 方法内的 asyncio.Lock() 调用"""
    found = []
    for root, _, files in os.walk(directory):
        for fname in files:
            if not fname.endswith('.py'):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, encoding='utf-8') as f:
                    source = f.read()
                tree = ast.parse(source, filename=fpath)
            except (SyntaxError, UnicodeDecodeError):
                continue

            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.name not in ('__init__', '__new__'):
                    continue
                # 检查方法体内是否有 asyncio.Lock() 调用
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        func = child.func
                        # 匹配 asyncio.Lock()
                        if (isinstance(func, ast.Attribute)
                                and func.attr == 'Lock'
                                and isinstance(func.value, ast.Name)
                                and func.value.id == 'asyncio'):
                            found.append((fpath, child.lineno, node.name))
    return found


if __name__ == '__main__':
    all_found = []
    for d in ['core', 'clients']:
        all_found.extend(find_asyncio_locks_in_init(d))

    if all_found:
        print(f"发现 {len(all_found)} 处 asyncio.Lock() 在 __init__/__new__ 中：")
        for fpath, lineno, method in all_found:
            print(f"  {fpath}:{lineno} in {method}()")
        sys.exit(1)
    else:
        print("✓ 未发现任何 asyncio.Lock() 在 __init__/__new__ 方法中（全部已修复）")
        sys.exit(0)
