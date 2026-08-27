"""查看今天 short_term 记录的完整字段，找出 conversation_id 线索。"""

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

    # 打印第一条记录的完整字段
    if today:
        print('=== 第一条记录的完整字段 ===')
        print(json.dumps(today[0], ensure_ascii=False, indent=2))
        print()
        print('=== 第二条记录的完整字段 ===')
        if len(today) > 1:
            print(json.dumps(today[1], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
