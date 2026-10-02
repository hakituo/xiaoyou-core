"""分析合并后的 Aveline short_term，统计所有可恢复的对话消息。"""

import json
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter


def main():
    short_file = Path(
        'companion_data/aveline_data/memories/short_term/'
        'private_10001__scope__aveline_short.json'
    )
    data = json.loads(short_file.read_text(encoding='utf-8'))
    print(f'总记录数: {len(data)}')
    print()

    # 按 role 统计
    role_counter = Counter()
    for m in data:
        role_counter[m.get('role', 'unknown')] += 1
    print('role 分布:')
    for k, v in role_counter.most_common():
        print(f'  {k}: {v}')
    print()

    # 按 source 统计
    source_counter = Counter()
    for m in data:
        source_counter[m.get('source', 'unknown')] += 1
    print('source 分布:')
    for k, v in source_counter.most_common():
        print(f'  {k}: {v}')
    print()

    # 按时间范围统计
    timestamps = [m.get('timestamp', 0) or 0 for m in data]
    if timestamps:
        min_ts = min(timestamps)
        max_ts = max(timestamps)
        min_dt = datetime.fromtimestamp(min_ts, tz=timezone.utc).astimezone()
        max_dt = datetime.fromtimestamp(max_ts, tz=timezone.utc).astimezone()
        print(f'时间范围: {min_dt.strftime("%Y-%m-%d %H:%M")} ~ {max_dt.strftime("%Y-%m-%d %H:%M")}')
    print()

    # 按日期统计 user/assistant 消息数（真正的对话）
    date_counter = Counter()
    cid_counter = Counter()
    dialogue_count = 0
    for m in data:
        role = m.get('role', '')
        if role not in ('user', 'assistant'):
            continue
        meta = m.get('metadata', {}) or {}
        if meta.get('hidden') is True:
            continue
        content = m.get('content', '') or ''
        if not content:
            continue
        ts = m.get('timestamp', 0) or 0
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
        date_counter[dt.strftime('%Y-%m-%d')] += 1
        dialogue_count += 1
        cid = meta.get('conversation_id', '') or ''
        cid_counter[cid] += 1

    print(f'可恢复的对话消息（user/assistant）: {dialogue_count} 条')
    print()
    print('按日期分布（对话消息）:')
    for date_str in sorted(date_counter.keys()):
        print(f'  {date_str}: {date_counter[date_str]} 条')
    print()
    print('按 conversation_id 分布（对话消息）:')
    for k, v in cid_counter.most_common():
        print(f'  {k!r}: {v} 条')


if __name__ == '__main__':
    main()
