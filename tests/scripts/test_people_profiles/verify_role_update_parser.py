"""验证角色更新响应解析器能处理完整和末尾截断的 JSON。"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core.character.people.extractor import PeopleProfileExtractor  # noqa: E402


def main() -> None:
    extractor = PeopleProfileExtractor()

    complete = (
        '{"role_updates":[{"role":"ling","facts":[]},'
        '{"role":"aveline","facts":[{"key":"偏好","value":"完整"}]}]}'
    )
    truncated = (
        '{"role_updates":[{"role":"ling","facts":[]},'
        '{"role":"aveline","facts":[{"key":"偏好","value":"截断'
    )

    complete_updates = extractor._parse_role_update_response(complete)
    recovered_updates = extractor._parse_role_update_response(truncated)

    assert len(complete_updates) == 2
    assert len(recovered_updates) == 1
    assert recovered_updates[0]["role"] == "ling"
    print("角色更新 JSON 解析验证通过")


if __name__ == "__main__":
    main()
