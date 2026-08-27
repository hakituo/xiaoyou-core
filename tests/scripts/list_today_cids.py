"""列出所有今天记录的 conversation_id，决定写到哪个 JSONL 文件。"""

import json
from pathlib import Path
from datetime import datetime, timezone


def main():
    short_file = Path(
        'companion_data/aveline_data/memories/short_term/'
        'private_10001__scope__aveline_short.json'
    )
    data = json.loads(short_file.read_text(encoding='utf-8'))

    START_TS = datetime(2026, 7, 20, 0, 0, 0, tzinfo=timezone.utc).timestamp()
    END_TS = datetime(2026, 7, 20, 23, 59, 59, tzinfo=timezone.utc).timestamp()

    today = [m for m in data if START_TS <= (m.get('timestamp', 0) or 0) <= END_TS]
    today.sort(key=lambda x: x.get('timestamp', 0) or 0)

    # 看看历史记录（前 7 天）的 conversation_id 分布
    SEVEN_DAYS_AGO = datetime(2026, 7, 13, 0, 0, 0, tzinfo=timezone.utc).timestamp()
    recent = [
        m for m in data
        if SEVEN_DAYS_AGO <= (m.get('timestamp', 0) or 0) <= END_TS
    ]
    recent.sort(key=lambda x: x.get('timestamp', 0) or 0)

    print(f'近 7 天记录数: {len(recent)}')
    conv_set = set()
    for m in recent:
        meta = m.get('metadata', {}) or {}
        cid = meta.get('conversation_id', '')
        event_ref = meta.get('event_ref', {}) or {}
        rel_path = event_ref.get('relative_path', '')
        if cid or rel_path:
            conv_set.add((cid, rel_path))
    print('近 7 天的 (conversation_id, relative_path) 组合:')
    for cid, rel in sorted(conv_set):
        print(f'  cid={cid!r}, rel={rel!r}')

    print()
    print(f'今天的记录数: {len(today)}')
    print('每条记录的关键字段:')
    for i, m in enumerate(today):
        meta = m.get('metadata', {}) or {}
        cid = meta.get('conversation_id', '')
        msg_id = meta.get('message_id', '')
        print(f'[{i+1}] ts={m.get("timestamp"):.0f} role={m.get("role"):10} '
              f'cid={cid!r:50} msg_id={msg_id!r}')
        print(f'    content: {m.get("content", "")[:80]}')


if __name__ == '__main__':
    main()
