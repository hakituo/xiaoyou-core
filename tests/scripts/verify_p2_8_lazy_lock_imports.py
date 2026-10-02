"""临时脚本：检查 core/ 和 clients/ 中所有使用 LazyAsyncLock 但未导入的文件"""
import ast
import os
import sys


def check_lazy_lock_imports(directory: str):
    """查找使用 LazyAsyncLock 但未正确导入的文件"""
    issues = []
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

            # 检查是否使用了 LazyAsyncLock
            uses_lazy_lock = False
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id == 'LazyAsyncLock':
                    uses_lazy_lock = True
                    break
                if isinstance(node, ast.Attribute) and node.attr == 'LazyAsyncLock':
                    uses_lazy_lock = True
                    break
            if not uses_lazy_lock:
                continue

            # 检查是否导入了 LazyAsyncLock
            has_import = False
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if alias.name == 'LazyAsyncLock' or alias.asname == 'LazyAsyncLock':
                            has_import = True
                            break
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == 'LazyAsyncLock' or alias.asname == 'LazyAsyncLock':
                            has_import = True
                            break
            if not has_import:
                issues.append(fpath)

    return issues


if __name__ == '__main__':
    all_issues = []
    for d in ['core', 'clients']:
        all_issues.extend(check_lazy_lock_imports(d))

    if all_issues:
        print(f"发现 {len(all_issues)} 个文件使用 LazyAsyncLock 但未导入：")
        for fp in all_issues:
            print(f"  {fp}")
        sys.exit(1)
    else:
        print("✓ 所有使用 LazyAsyncLock 的文件都已正确导入")
        sys.exit(0)
