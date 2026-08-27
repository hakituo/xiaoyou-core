"""验证 persona 别名目录迁移不会覆盖冲突文件。"""

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.migrate.merge_persona_scope_dirs import (  # noqa: E402
    merge_registered_scope_dirs,
)


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        source = base / "Mian_data"
        weighted = source / "memories" / "weighted" / "shared__scope__Mian_weighted.json"
        weighted.parent.mkdir(parents=True)
        weighted.write_text('{"weighted_memories": []}\n', encoding="utf-8")
        sessions = source / "memories" / "sessions.json"
        sessions.write_text(
            json.dumps([{"id": "shared__persona__Mian", "updated_at": 2}]),
            encoding="utf-8",
        )

        target_sessions = base / "mianmian_data" / "memories" / "sessions.json"
        target_sessions.parent.mkdir(parents=True)
        target_sessions.write_text(
            json.dumps([{"id": "shared__persona__mianmian", "updated_at": 1}]),
            encoding="utf-8",
        )

        conflict_source = base / "Kafka_data" / "notes.json"
        conflict_target = base / "kafka_data" / "notes.json"
        conflict_source.parent.mkdir(parents=True)
        conflict_target.parent.mkdir(parents=True)
        conflict_source.write_text('{"source": true}', encoding="utf-8")
        conflict_target.write_text('{"target": true}', encoding="utf-8")

        registry = {
            "mianmian": {"slugs": ["Mian"]},
            "kafka": {"slugs": ["Kafka"]},
        }
        preview = merge_registered_scope_dirs(base, registry=registry)
        assert weighted.exists(), "预览模式不应修改文件"
        assert len(preview.merged_sessions) == 1
        assert len(preview.conflicts) == 1

        report = merge_registered_scope_dirs(base, write=True, registry=registry)
        canonical_weighted = (
            base
            / "mianmian_data"
            / "memories"
            / "weighted"
            / "shared__scope__mianmian_weighted.json"
        )
        assert canonical_weighted.exists(), "weighted 文件应改为标准 scope 名"
        assert not source.exists(), "无冲突的中文别名目录应被清理"
        merged_sessions = json.loads(target_sessions.read_text(encoding="utf-8"))
        assert {row["id"] for row in merged_sessions} == {
            "shared__persona__Mian",
            "shared__persona__mianmian",
        }
        assert conflict_source.exists(), "冲突源文件必须保留"
        assert conflict_target.read_text(encoding="utf-8") == '{"target": true}'
        assert len(report.conflicts) == 1

    print("PASS: persona scope 目录安全合并、索引合并与冲突保留均符合预期")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
