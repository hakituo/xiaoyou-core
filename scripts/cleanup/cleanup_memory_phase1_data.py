import argparse
import json
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def main() -> int:
    from memory.weighted_memory_manager import get_weighted_memory_manager

    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", default="default")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    manager = get_weighted_memory_manager(args.user_id)
    result = manager.clean_memory_records(
        sync_save=not args.dry_run,
        dry_run=bool(args.dry_run),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
