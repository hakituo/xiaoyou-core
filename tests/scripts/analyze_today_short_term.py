"""分析今天的 short_term 记录，准备恢复 chat_history。"""

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

    START_TS = datetime(2026, 7, 20, 0, 0, 0, tzinfo=timezone.utc).timestamp()
    END_TS = datetime(2026, 7, 20, 23, 59, 59, tzinfo=timezone.utc).timestamp()

    today = [m for m in data if START_TS <= (m.get('timestamp', 0) or 0) <= END_TS]
    print(f'总记录: {len(data)}, 今天: {len(today)}')
    print()

    sources = Counter()
    roles = Counter()
    conv_ids = Counter()
    rel_paths = Counter()
    for m in today:
        sources[m.get('source', 'unknown')] += 1
        roles[m.get('role', 'unknown')] += 1
        meta = m.get('metadata', {}) or {}
        event_ref = meta.get('event_ref', {}) or {}
        conv_ids[event_ref.get('conversation_id', 'unknown')] += 1
        rel_paths[event_ref.get('relative_path', 'unknown')] += 1

    print('source 分布:')
    for k, v in sources.most_common():
        print(f'  {k}: {v}')
    print()
    print('role 分布:')
    for k, v in roles.most_common():
        print(f'  {k}: {v}')
    print()
    print('conversation_id 分布:')
    for k, v in conv_ids.most_common():
        print(f'  {k}: {v}')
    print()
    print('relative_path 分布:')
    for k, v in rel_paths.most_common():
        print(f'  {k}: {v}')
    print()

    original_dialogue = [m for m in today if m.get('role') in ('user', 'assistant')]
    print(f'原始对话消息（user/assistant）: {len(original_dialogue)}')

    # 看看 user 消息的样子
    print()
    print('=== user 消息示例（前 2 条）===')
    count = 0
    for m in today:
        if m.get('role') == 'user':
            print(f'  id: {m.get("id")}')
            content = m.get('content', '')
            print(f'  content: {content[:200]}')
            print(f'  timestamp: {m.get("timestamp")}')
            meta = m.get('metadata', {}) or {}
            event_ref = meta.get('event_ref', {}) or {}
            print(f'  event_ref: {event_ref}')
            print('---')
            count += 1
            if count >= 2:
                break

    print()
    print('=== assistant 消息示例（前 2 条）===')
    count = 0
    for m in today:
        if m.get('role') == 'assistant':
            print(f'  id: {m.get("id")}')
            content = m.get('content', '')
            print(f'  content: {content[:200]}')
            print(f'  timestamp: {m.get("timestamp")}')
            meta = m.get('metadata', {}) or {}
            event_ref = meta.get('event_ref', {}) or {}
            print(f'  event_ref: {event_ref}')
            print('---')
            count += 1
            if count >= 2:
                break


if __name__ == '__main__':
    main()
