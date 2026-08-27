"""验证 Aveline chat_history 全量恢复结果。"""

import json
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter


def main():
    chat_dir = Path('companion_data/aveline_data/chat_history')

    # 统计每个 jsonl 文件的行数
    print('=== 恢复后的 chat_history 文件清单 ===')
    files = sorted(chat_dir.rglob('*.jsonl'))
    total_lines = 0
    by_month = Counter()
    by_cid = Counter()
    by_role = Counter()
    date_range = []

    for f in files:
        lines = [l for l in f.read_text(encoding='utf-8').split('\n') if l.strip()]
        line_count = len(lines)
        total_lines += line_count
        rel = f.relative_to(chat_dir)

        # 解析每个事件
        for line in lines:
            try:
                data = json.loads(line)
                by_cid[data.get('conversation_id', '')] += 1
                by_role[data.get('role', '')] += 1
                ts = data.get('timestamp', 0) or 0
                dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
                by_month[dt.strftime('%Y-%m')] += 1
                date_range.append((dt, f))
            except Exception:
                pass

    print(f'文件总数: {len(files)}')
    print(f'消息总数: {total_lines}')
    print()

    # 按月份统计
    print('=== 按月份统计 ===')
    for k in sorted(by_month.keys()):
        print(f'  {k}: {by_month[k]} 条')
    print()

    # 按 conversation_id 统计
    print('=== 按 conversation_id 统计 ===')
    for k, v in by_cid.most_common():
        print(f'  {k!r}: {v}')
    print()

    # 按 role 统计
    print('=== 按 role 统计 ===')
    for k, v in by_role.most_common():
        print(f'  {k}: {v}')
    print()

    # 时间范围
    if date_range:
        min_dt = min(d for d, _ in date_range)
        max_dt = max(d for d, _ in date_range)
        print(f'时间范围: {min_dt.strftime("%Y-%m-%d %H:%M:%S")} ~ '
              f'{max_dt.strftime("%Y-%m-%d %H:%M:%S")}')
    print()

    # 文件清单（按日期分组）
    print('=== 文件清单（按日期分组）===')
    by_date = {}
    for f in files:
        rel = f.relative_to(chat_dir)
        parts = rel.parts
        if len(parts) >= 4:
            date_key = f'{parts[0]}/{parts[1]}/{parts[2]}'
            by_date.setdefault(date_key, []).append(rel)
    for date_key in sorted(by_date.keys()):
        print(f'  {date_key}:')
        for rel in by_date[date_key]:
            print(f'    {rel}')


if __name__ == '__main__':
    main()
