"""查看 cid 为空的记录的其他字段，找出反解 cid 的线索。"""

import json
import re
from pathlib import Path
from collections import Counter


def parse_cid_from_msg_id(msg_id: str) -> str:
    """从 message_id 反解 conversation_id

    message_id 格式：msg_{conversation_id}_{timestamp}
    例如：msg_private_10001__persona__aveline_qq_master_1784537626.268988
    """
    if not msg_id or not msg_id.startswith('msg_'):
        return ''
    body = msg_id[4:]
    match = re.match(r'^(.*)_(\d+(?:\.\d+)?)$', body)
    if match:
        return match.group(1)
    return body


def main():
    short_file = Path(
        'companion_data/aveline_data/memories/short_term/'
        'private_10001__scope__aveline_short.json'
    )
    data = json.loads(short_file.read_text(encoding='utf-8'))

    # 统计 cid 为空的记录的来源
    empty_cid_counter = Counter()
    cid_from_msg_id_counter = Counter()
    no_cid_no_msgid_count = 0
    sample_no_cid = []
    sample_no_msgid = []

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

        cid = meta.get('conversation_id', '') or ''
        msg_id = meta.get('message_id', '') or ''
        source = m.get('source', '') or ''

        if not cid:
            empty_cid_counter[source] += 1
            if msg_id:
                parsed_cid = parse_cid_from_msg_id(msg_id)
                cid_from_msg_id_counter[parsed_cid] += 1
                if len(sample_no_cid) < 3:
                    sample_no_cid.append({
                        'msg_id': msg_id,
                        'parsed_cid': parsed_cid,
                        'source': source,
                        'role': role,
                        'content': content[:80],
                    })
            else:
                no_cid_no_msgid_count += 1
                if len(sample_no_msgid) < 5:
                    sample_no_msgid.append({
                        'source': source,
                        'role': role,
                        'content': content[:80],
                        'metadata': meta,
                    })

    print('=== cid 为空的记录按 source 分布 ===')
    for k, v in empty_cid_counter.most_common():
        print(f'  {k}: {v}')
    print()
    print('=== 从 message_id 反解的 cid 分布 ===')
    for k, v in cid_from_msg_id_counter.most_common():
        print(f'  {k!r}: {v}')
    print()
    print(f'=== 既无 cid 又无 message_id 的记录: {no_cid_no_msgid_count} 条 ===')
    print()
    print('=== 样本（有 msg_id 无 cid）===')
    for s in sample_no_cid:
        print(json.dumps(s, ensure_ascii=False, indent=2))
        print('---')
    print()
    print('=== 样本（既无 cid 又无 msg_id）===')
    for s in sample_no_msgid:
        print(json.dumps(s, ensure_ascii=False, indent=2))
        print('---')


if __name__ == '__main__':
    main()
