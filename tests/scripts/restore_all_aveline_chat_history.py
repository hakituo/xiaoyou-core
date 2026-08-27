"""从 Aveline short_term 全量恢复历史聊天记录到 chat_history。

策略：
1. 从合并后的 short_term 文件读取所有记录
2. 过滤掉Ling的对话（cid 包含 ling 的）
3. 过滤掉非对话消息（journal/system_summary/workspace/system_profile 等）
4. 过滤掉 hidden 的 thinking 记录
5. 对话消息按 timestamp 排序
6. 解析 cid：
   - 优先使用 metadata.conversation_id
   - 如果为空，从 metadata.message_id 反解
   - 如果仍为空，根据 source 推断（aveline scope 的 assistant 消息默认归到 aveline_qq_master）
7. 通过 ChatHistoryStore.append_event 写入对应日期目录
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter


def parse_cid_from_msg_id(msg_id: str) -> str:
    """从 message_id 反解 conversation_id

    message_id 格式：msg_{conversation_id}_{timestamp}
    例如：msg_private_10001__persona__aveline_qq_master_1784537626.268988
    """
    if not msg_id or not msg_id.startswith('msg_'):
        return ''
    body = msg_id[4:]
    # 从右往左匹配最后一个 _<数字>.<数字> 作为 timestamp
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
    print(f'总记录数: {len(data)}')

    # 步骤1：筛选要恢复的记录
    to_restore = []
    skip_reasons = Counter()
    for m in data:
        role = m.get('role', '')
        meta = m.get('metadata', {}) or {}
        content = m.get('content', '') or ''

        # 跳过非对话角色
        if role not in ('user', 'assistant'):
            skip_reasons[f'role={role}'] += 1
            continue
        # 跳过 hidden 的 thinking 记录
        if meta.get('hidden') is True:
            skip_reasons['hidden_thinking'] += 1
            continue
        # 跳过空内容
        if not content.strip():
            skip_reasons['empty_content'] += 1
            continue

        # 解析 cid
        cid = meta.get('conversation_id', '') or ''
        msg_id = meta.get('message_id', '') or ''
        if not cid and msg_id:
            cid = parse_cid_from_msg_id(msg_id)

        # 如果 cid 仍然为空（976 条 assistant 消息），根据 source 推断
        if not cid:
            source = m.get('source', '')
            # aveline scope 文件里的 assistant 消息，默认归到 aveline_qq_master
            if role == 'assistant':
                cid = 'private_10001__persona__aveline_qq_master'
            else:
                # user 消息但没 cid，从其他线索推断
                skip_reasons['no_cid_user'] += 1
                continue

        # 过滤掉Ling的对话（cid 包含 ling）
        if 'ling' in cid.lower() and 'aveline' not in cid.lower():
            skip_reasons['ling_persona'] += 1
            continue

        to_restore.append({
            'cid': cid,
            'role': role,
            'content': content,
            'timestamp': m.get('timestamp', 0) or 0,
            'message_id': msg_id,
            'memory_id': m.get('id', ''),
            'source': m.get('source', ''),
            'metadata': meta,
        })

    print(f'要恢复的对话消息: {len(to_restore)} 条')
    print(f'跳过原因统计:')
    for k, v in skip_reasons.most_common():
        print(f'  {k}: {v}')
    print()

    # 按 cid 分布
    cid_counter = Counter(r['cid'] for r in to_restore)
    print('按 conversation_id 分布:')
    for k, v in cid_counter.most_common():
        print(f'  {k!r}: {v}')
    print()

    # 步骤2：按时间排序
    to_restore.sort(key=lambda r: r['timestamp'])

    # 步骤3：写入 chat_history
    sys.path.insert(0, str(Path.cwd()))
    from core.services.chat_history_store import get_chat_history_store
    from core.utils.time_utils import get_current_time

    store = get_chat_history_store()

    print('=== 开始写入 chat_history ===')
    total_written = 0
    errors = 0
    for i, r in enumerate(to_restore):
        ts = r['timestamp']
        try:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
        except (OSError, ValueError):
            dt = get_current_time()

        content = r['content']
        role = r['role']
        msg_id = r['message_id'] or f'restored_{r["memory_id"]}'

        # event_type: active_care 主动消息
        event_type = 'message'
        meta = r['metadata']
        if meta.get('is_proactive') is True or meta.get('type') == 'proactive':
            event_type = 'proactive'

        try:
            store.append_event(
                conversation_id=r['cid'],
                role=role,
                content=content,
                message_id=msg_id,
                event_type=event_type,
                metadata={
                    'restored_from': 'short_term',
                    'memory_id': r['memory_id'],
                    'source': r['source'],
                    **{k: v for k, v in meta.items() if k != 'message_id'},
                },
                now_dt=dt,
            )
            total_written += 1
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f'  [ERR] ts={ts:.0f} role={role} cid={r["cid"]!r}: {e}')

        # 每 500 条打印进度
        if (i + 1) % 500 == 0:
            print(f'  进度: {i+1}/{len(to_restore)}')

    print(f'=== 恢复完成: 共写入 {total_written} 条, 失败 {errors} 条 ===')


if __name__ == '__main__':
    main()
