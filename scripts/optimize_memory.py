import json
import logging
import hashlib
import time
import datetime
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Constants
HISTORY_DIR = Path("d:/AI/xiaoyou-core/history")
LONG_TERM_DIR = HISTORY_DIR / "long_term"
SHORT_TERM_DIR = HISTORY_DIR / "short_term"
SENSITIVE_DIR = HISTORY_DIR / "sensitive"


def is_garbage(content: str) -> bool:
    """Check if content is a system prompt or garbage."""
    if not content:
        return True
    content_strip = content.strip()
    if not content_strip:
        return True

    # System Prompts / Injections
    if content_strip.startswith("# Role Definition"):
        return True
    if content_strip.startswith("[SYSTEM]"):
        return True
    if "You are Aveline" in content:
        return True
    if "你是 Aveline" in content:
        return True
    if "你是 **Aveline" in content:
        return True
    if "You are an AI assistant" in content:
        return True
    if "Ignore previous instructions" in content:
        return True

    # Common accidental saves
    if content_strip == "User":
        return True
    if content_strip == "Assistant":
        return True

    return False


def optimize_memory():
    logger.info("Starting memory optimization...")

    deleted_files = 0
    cleaned_entries = 0
    backfilled_timestamps = 0

    # 1. Clean up empty files and garbage entries
    for directory in [LONG_TERM_DIR, SENSITIVE_DIR, SHORT_TERM_DIR]:
        if not directory.exists():
            continue

        for file_path in directory.glob("*.json"):
            try:
                # Check for 0-byte files
                if file_path.stat().st_size == 0:
                    file_path.unlink()
                    deleted_files += 1
                    logger.info(f"Deleted 0-byte file: {file_path.name}")
                    continue

                with open(file_path, "r", encoding="utf-8") as f:
                    try:
                        data = json.load(f)
                    except json.JSONDecodeError:
                        file_path.unlink()
                        deleted_files += 1
                        logger.info(f"Deleted corrupted JSON file: {file_path.name}")
                        continue

                if not isinstance(data, list):
                    # Should be a list of memories
                    if isinstance(data, dict) and not data:  # Empty dict
                        file_path.unlink()
                        deleted_files += 1
                        continue
                    # If it's a dict, maybe wrap it in list? No, structure is list.
                    logger.warning(
                        f"Unexpected data format in {file_path.name}, skipping"
                    )
                    continue

                if not data:
                    file_path.unlink()
                    deleted_files += 1
                    logger.info(f"Deleted empty list file: {file_path.name}")
                    continue

                # Filter garbage and backfill timestamps
                new_data = []
                modified = False

                for item in data:
                    if not isinstance(item, dict):
                        modified = True
                        continue

                    content = item.get("content", "")
                    if is_garbage(content):
                        cleaned_entries += 1
                        modified = True
                        continue

                    # Backfill timestamp/created_at
                    if "created_at" not in item:
                        ts = item.get("timestamp", time.time())
                        item["created_at"] = datetime.datetime.fromtimestamp(
                            ts
                        ).strftime("%Y-%m-%d %H:%M:%S")
                        modified = True
                        backfilled_timestamps += 1

                    new_data.append(item)

                if modified:
                    if not new_data:
                        file_path.unlink()
                        deleted_files += 1
                        logger.info(
                            f"Deleted file after cleaning all entries: {file_path.name}"
                        )
                    else:
                        with open(file_path, "w", encoding="utf-8") as f:
                            json.dump(new_data, f, ensure_ascii=False, indent=2)
                        logger.info(
                            f"Optimized {file_path.name} (Cleaned: {len(data) - len(new_data)})"
                        )

            except Exception as e:
                logger.error(f"Error processing {file_path.name}: {e}")

    # 2. Deduplicate Long Term vs Sensitive
    # Sensitive takes precedence. If content is in Sensitive, remove from Long Term.

    sensitive_hashes = set()
    sensitive_map = {}  # hash -> content (for debugging)

    # Collect all sensitive hashes
    for file_path in SENSITIVE_DIR.glob("*.json"):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    content = item.get("content", "")
                    if content:
                        h = hashlib.md5(content.encode()).hexdigest()
                        sensitive_hashes.add(h)
                        sensitive_map[h] = content
        except Exception:
            pass

    # Remove from Long Term
    long_term_duplicates = 0
    for file_path in LONG_TERM_DIR.glob("*.json"):
        try:
            modified = False
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            new_data = []
            for item in data:
                content = item.get("content", "")
                h = hashlib.md5(content.encode()).hexdigest()

                if h in sensitive_hashes:
                    long_term_duplicates += 1
                    modified = True
                    # logger.info(f"Removed duplicate from long_term: {content[:30]}...")
                else:
                    new_data.append(item)

            if modified:
                if not new_data:
                    file_path.unlink()
                    deleted_files += 1
                else:
                    with open(file_path, "w", encoding="utf-8") as f:
                        json.dump(new_data, f, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"Error deduplicating {file_path.name}: {e}")

    logger.info("Optimization Complete.")
    logger.info(f"Deleted Empty/Garbage Files: {deleted_files}")
    logger.info(f"Cleaned Garbage Entries: {cleaned_entries}")
    logger.info(f"Backfilled Timestamps: {backfilled_timestamps}")
    logger.info(f"Removed Long-Term Duplicates: {long_term_duplicates}")


if __name__ == "__main__":
    optimize_memory()
