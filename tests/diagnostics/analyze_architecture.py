"""分析项目代码架构"""
import os
from pathlib import Path
from collections import defaultdict
import ast

project_root = Path(r"d:\AI\xiaoyou-core")
core_dir = project_root / "core"

def count_lines(file_path):
    """统计文件行数"""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return len(f.readlines())
    except Exception:
        return 0

def count_methods(file_path):
    """统计类中的方法数量"""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        tree = ast.parse(content)
        classes = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                methods = [item for item in node.body if isinstance(item, ast.FunctionDef)]
                classes.append({
                    'name': node.name,
                    'methods': len(methods),
                    'lines': node.end_lineno - node.lineno if hasattr(node, 'end_lineno') else 0
                })
        
        return classes
    except Exception:
        return []

def analyze_imports(file_path):
    """分析文件的导入依赖"""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        tree = ast.parse(content)
        imports = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                for alias in node.names:
                    imports.append(f"{module}.{alias.name}")
        
        return imports
    except Exception:
        return []

# 统计所有 Python 文件
py_files = list(core_dir.rglob("*.py"))
file_stats = []

for py_file in py_files:
    lines = count_lines(py_file)
    rel_path = py_file.relative_to(project_root)
    file_stats.append({
        'path': str(rel_path),
        'lines': lines,
        'classes': count_methods(py_file)
    })

# 按行数排序
file_stats.sort(key=lambda x: x['lines'], reverse=True)

print("=" * 80)
print("最大的 30 个 Python 文件（按行数排序）")
print("=" * 80)
print(f"{'行数':>8}  {'文件路径'}")
print("-" * 80)

total_lines = 0
for stat in file_stats[:30]:
    print(f"{stat['lines']:>8}  {stat['path']}")
    total_lines += stat['lines']

print("-" * 80)
print(f"{'总计':>8}  {total_lines} 行 (前30个文件)")

# 统计各目录的代码量
print("\n" + "=" * 80)
print("各目录代码量统计")
print("=" * 80)

dir_stats = defaultdict(lambda: {'files': 0, 'lines': 0})
for stat in file_stats:
    parts = Path(stat['path']).parts
    if len(parts) >= 3:  # core/xxx/...
        dir_name = "/".join(parts[:3])
    else:
        dir_name = str(Path(stat['path']).parent)
    
    dir_stats[dir_name]['files'] += 1
    dir_stats[dir_name]['lines'] += stat['lines']

dir_list = sorted(dir_stats.items(), key=lambda x: x[1]['lines'], reverse=True)
print(f"{'目录':<50} {'文件数':>8} {'行数':>8}")
print("-" * 80)
for dir_name, stats in dir_list[:20]:
    print(f"{dir_name:<50} {stats['files']:>8} {stats['lines']:>8}")

# 找出超大类（方法数超过15个的类）
print("\n" + "=" * 80)
print("超大类（方法数 > 15）")
print("=" * 80)

big_classes = []
for stat in file_stats:
    for cls in stat['classes']:
        if cls['methods'] > 15:
            big_classes.append({
                'file': stat['path'],
                'class': cls['name'],
                'methods': cls['methods'],
                'lines': cls['lines']
            })

big_classes.sort(key=lambda x: x['methods'], reverse=True)
print(f"{'类名':<30} {'方法数':>8} {'行数':>8}  {'文件'}")
print("-" * 80)
for cls in big_classes[:20]:
    print(f"{cls['class']:<30} {cls['methods']:>8} {cls['lines']:>8}  {cls['file']}")

# 分析超大文件的问题
print("\n" + "=" * 80)
print("架构问题分析")
print("=" * 80)

issues = []

# 检查超大文件
for stat in file_stats[:30]:
    if stat['lines'] > 1000:
        issues.append({
            'type': '超大文件',
            'severity': 'HIGH' if stat['lines'] > 2000 else 'MEDIUM',
            'file': stat['path'],
            'detail': f"{stat['lines']} 行，建议拆分"
        })

# 检查超大类
for cls in big_classes[:10]:
    issues.append({
        'type': '超大类',
        'severity': 'HIGH' if cls['methods'] > 30 else 'MEDIUM',
        'file': cls['file'],
        'detail': f"类 {cls['class']} 有 {cls['methods']} 个方法，违反单一职责"
    })

# 按严重程度排序
issues.sort(key=lambda x: x['severity'], reverse=True)

for issue in issues[:20]:
    print(f"[{issue['severity']}] {issue['type']}: {issue['file']}")
    print(f"         {issue['detail']}")
    print()

# 总结
print("\n" + "=" * 80)
print("总结")
print("=" * 80)
print(f"总文件数: {len(file_stats)}")
print(f"总行数: {sum(s['lines'] for s in file_stats)}")
print(f"超大文件(>1000行): {len([s for s in file_stats if s['lines'] > 1000])}")
print(f"超大类(>15方法): {len(big_classes)}")
