"""检查 short_term 目录的混乱情况。"""

import json
from pathlib import Path
from datetime import datetime


def main():
    short_dir = Path('companion_data/aveline_data/memories/short_term')
    files = sorted(short_dir.glob('*'), key=lambda p: p.name)

    print(f"{'文件名':<90} {'大小':>10} {'修改时间':<20} {'记录数':>8}")
    print('-' * 130)
    for f in files:
        stat = f.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
        size = stat.st_size
        count = '-'
        try:
            if f.suffix == '.json':
                data = json.loads(f.read_text(encoding='utf-8'))
                if isinstance(data, list):
                    count = len(data)
                elif isinstance(data, dict):
                    for key in ('messages', 'short_term_messages', 'weighted_memories'):
                        if key in data:
                            count = len(data[key])
                            break
                    else:
                        count = f'dict:{len(data)}keys'
            else:
                count = f'suffix:{f.suffix}'
        except Exception as e:
            count = f'ERR:{type(e).__name__}'
        print(f"{f.name:<90} {size:>10} {mtime:<20} {str(count):>8}")

    # 检查 ling_data 是否也有同样的混乱
    print()
    print("=== ling_data 的 short_term ===")
    ling_dir = Path('companion_data/ling_data/memories/short_term')
    if ling_dir.exists():
        for f in sorted(ling_dir.glob('*'), key=lambda p: p.name):
            stat = f.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            size = stat.st_size
            print(f"{f.name:<90} {size:>10} {mtime:<20}")

    print()
    print("=== user_data 的 short_term ===")
    user_dir = Path('companion_data/user_data/memories/short_term')
    if user_dir.exists():
        for f in sorted(user_dir.glob('*'), key=lambda p: p.name):
            stat = f.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            size = stat.st_size
            print(f"{f.name:<90} {size:>10} {mtime:<20}")


if __name__ == '__main__':
    main()
