"""用隔离的本地归档复现跨会话漏召回；不读取或修改用户真实对话。"""

from pathlib import Path
from datetime import datetime, timezone
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.services import chat_history_store
from core.tools.search_chat_history_tool import SearchChatHistoryTool
from core.utils import data_paths


def main() -> None:
    with TemporaryDirectory(prefix="verify-history-archive-") as temp:
        root = Path(temp)
        store = chat_history_store.ChatHistoryStore(root)
        for cid, ts in (("web_old", 100), ("web_role_aveline", 200)):
            store.append_event(
                conversation_id=cid, role="user", content="归档线索",
                message_id=cid, now_dt=datetime.fromtimestamp(ts, tz=timezone.utc),
                event_type="chat_message",
            )
        with patch.object(chat_history_store, "get_chat_history_store", return_value=store), patch.object(
            data_paths, "get_chat_history_dir_for_conversation", return_value=root,
        ):
            events = SearchChatHistoryTool()._search_in_store(
                conversation_id="web_role_aveline", query="归档线索", limit=20,
                roles=None, before_ts=None, after_ts=None, scope="local",
            )
        assert len(events) == 2
        assert {e["conversation_id"] for e in events} == {"web_old", "web_role_aveline"}
        print("PASS: 当前提问命中时仍可查到旧会话，且不会重复返回当前记录")


if __name__ == "__main__":
    main()
