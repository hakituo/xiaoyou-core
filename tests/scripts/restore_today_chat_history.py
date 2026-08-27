"""从 short_term 恢复今天（2026-07-20）的 Aveline chat_history JSONL。

策略：
1. 从合并后的 short_term 文件读取今天的记录
2. 对每条记录，从 metadata.conversation_id 或 message_id 解析 conversation_id
3. 通过 ChatHistoryStore.append_event 接口写回 JSONL，保留原始 timestamp
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from datetime import datetime, timezone


def parse_cid_from_msg_id(msg_id: str) -> str:
    """从 message_id 反解 conversation_id

    message_id 格式：msg_{conversation_id}_{timestamp}
    例如：msg_private_10001__persona__aveline_qq_master_1784537626.268988
    """
    if not msg_id or not msg_id.startswith('msg_'):
        return ''
    body = msg_id[4:]  # 去掉 'msg_' 前缀
    # 从右往左找最后一个 '_' 后跟数字（含小数点）的部分
    match = re.match(r'^(.*)_(\d+\.\d+)$', body)
    if match:
        return match.group(1)
    return body


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
    print(f'今天的记录数: {len(today)}')

    # 添加项目根目录到 path
    sys.path.insert(0, str(Path.cwd()))

    from core.services.chat_history_store import get_chat_history_store
    from core.utils.time_utils import get_current_time

    store = get_chat_history_store()

    # 今天的对话按 conversation_id 分组
    grouped: dict[str, list[dict]] = {}
    skipped = []
    for m in today:
        meta = m.get('metadata', {}) or {}
        cid = meta.get('conversation_id', '') or ''
        msg_id = meta.get('message_id', '') or ''
        if not cid and msg_id:
            cid = parse_cid_from_msg_id(msg_id)
        if not cid:
            # 跳过无法识别 cid 的记录（如纯 thinking 记录）
            skipped.append(m)
            continue
        # 排除 hidden 的 system thinking 记录
        if meta.get('hidden') is True:
            skipped.append(m)
            continue
        grouped.setdefault(cid, []).append(m)

    print(f'跳过 {len(skipped)} 条（无 cid 或 hidden）')
    print(f'按 cid 分组:')
    for cid, items in grouped.items():
        print(f'  {cid}: {len(items)} 条')

    # 写回 JSONL
    print()
    print('=== 写入 chat_history ===')
    total_written = 0
    for cid, items in grouped.items():
        print(f'\n[{cid}] {len(items)} 条')
        for m in items:
            ts = m.get('timestamp', 0) or 0
            try:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
            except (OSError, ValueError):
                dt = get_current_time()

            content = m.get('content', '') or ''
            role = m.get('role', 'system') or 'system'
            # 短期记忆里 system 角色一般是 thinking，不是真正的对话消息
            # 如果是 active_care 的 thinking 记录，跳过
            meta = m.get('metadata', {}) or {}
            if role == 'system' and meta.get('hidden') is True:
                continue
            if not content:
                continue

            # event_type: active_care 是主动消息
            event_type = 'message'
            if meta.get('is_proactive') is True or meta.get('type') == 'proactive':
                event_type = 'proactive'

            # 用 store.append_event 写入
            try:
                store.append_event(
                    conversation_id=cid,
                    role=role,
                    content=content,
                    message_id=meta.get('message_id', '') or f'restored_{m.get("id", "")}',
                    event_type=event_type,
                    metadata={
                        'restored_from': 'short_term',
                        'memory_id': m.get('id', ''),
                        'source': m.get('source', ''),
                        **{k: v for k, v in meta.items() if k not in ('message_id',)},
                    },
                    now_dt=dt,
                )
                total_written += 1
                print(f'  [OK] ts={ts:.0f} role={role} '
                      f'content={content[:50]!r}')
            except Exception as e:
                print(f'  [ERR] ts={ts:.0f} role={role}: {e}')

    print(f'\n=== 恢复完成: 共写入 {total_written} 条消息 ===')

    # 列出恢复后的 chat_history 目录
    print()
    print('=== chat_history/2026/07/20 目录结构 ===')
    for scope_data in ('aveline_data', 'ling_data'):
        base = Path(f'companion_data/{scope_data}/chat_history/2026/07/20')
        if not base.exists():
            continue
        print(f'\n{scope_data}/chat_history/2026/07/20/')
        for f in sorted(base.rglob('*')):
            if f.is_file():
                size = f.stat().st_size
                # 统计行数
                try:
                    lines = sum(1 for _ in open(f, encoding='utf-8'))
                except Exception:
                    lines = '-'
                rel = f.relative_to(base)
                print(f'  {rel}  ({size} bytes, {lines} 行)')


if __name__ == '__main__':
    main()
