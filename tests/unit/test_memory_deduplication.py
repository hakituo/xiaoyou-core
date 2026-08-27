
import unittest
import os
import json
import time
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from memory.weighted_memory_manager import WeightedMemoryManager

# Configuration for test environment
TEST_USER_ID = "test_user_dedup"
HISTORY_DIR = Path("d:/AI/xiaoyou-core/history")
LONG_TERM_DIR = HISTORY_DIR / "long_term"
WEIGHTED_DIR = HISTORY_DIR / "weighted"
SHORT_TERM_DIR = HISTORY_DIR / "short_term"

class TestMemoryDeduplication(unittest.TestCase):
    def setUp(self):
        # Clean up previous test data
        self._clean_dirs()
        self.manager = WeightedMemoryManager(user_id=TEST_USER_ID)

    def tearDown(self):
        # self._clean_dirs()
        pass

    def _clean_dirs(self):
        for d in [LONG_TERM_DIR, WEIGHTED_DIR, SHORT_TERM_DIR]:
            if d.exists():
                # Remove test user files
                for f in d.glob(f"{TEST_USER_ID}*"):
                    try:
                        f.unlink()
                    except Exception:
                        pass
                # Also remove category folders in weighted
                if d == WEIGHTED_DIR:
                    for item in d.iterdir():
                        if item.is_dir():
                            for f in item.glob(f"{TEST_USER_ID}*"):
                                try:
                                    f.unlink()
                                except Exception:
                                    pass

    def test_no_long_term_file_creation(self):
        """Test that new memories do NOT create long_term files"""
        print("\nTesting long_term file suppression...")
        
        # Add a memory that would normally go to long term (high importance)
        self.manager.add_memory(
            content="This is a very important memory that should be weighted.",
            role="user",
            is_important=True,
            topics=["test"],
            category="test"  # Explicitly set category to force folder creation
        )
        
        # Force save
        self.manager.save_memory()
        
        # Wait a bit for file system
        time.sleep(2)
        
        # Check files
        long_file = LONG_TERM_DIR / f"{TEST_USER_ID}_long.json"
        weighted_file = WEIGHTED_DIR / "test" / f"{TEST_USER_ID}_weighted.json"
        
        print(f"DEBUG: Checking weighted file at {weighted_file}")
        if not weighted_file.exists():
            print(f"DEBUG: Content of {WEIGHTED_DIR}:")
            for root, dirs, files in os.walk(WEIGHTED_DIR):
                print(f"  {root}")
                for f in files:
                    print(f"    {f}")

        self.assertFalse(long_file.exists(), "Long term file should NOT exist")
        self.assertTrue(weighted_file.exists(), "Weighted file should exist in category folder")
        
        print("PASS: Long term file was not created.")

    def test_get_recent_history_deduplication(self):
        """Test that get_recent_history does not return duplicates"""
        print("\nTesting history deduplication...")
        
        # Add memory
        self.manager.add_memory(
            content="Duplication test message",
            role="user",
            is_important=True,
            topics=["test"]
        )
        
        # Get history
        import asyncio
        history = asyncio.run(self.manager.get_recent_history(limit=10))
        
        # Count occurrences
        count = sum(1 for m in history if m["content"] == "Duplication test message")
        self.assertEqual(count, 1, f"Message should appear exactly once, found {count}")
        
        print("PASS: History returned unique items.")

    def test_migration_legacy_data(self):
        """Test migration of legacy long_term data"""
        print("\nTesting legacy data migration...")
        
        # Create a fake legacy long_term file
        legacy_data = [
            {
                "id": "legacy_1",
                "content": "Legacy memory 1",
                "role": "user",
                "timestamp": time.time(),
                "topics": ["legacy"]
            }
        ]
        
        if not LONG_TERM_DIR.exists():
            LONG_TERM_DIR.mkdir(parents=True)
            
        long_file = LONG_TERM_DIR / f"{TEST_USER_ID}_long.json"
        with open(long_file, 'w', encoding='utf-8') as f:
            json.dump(legacy_data, f)
            
        # Re-initialize manager to trigger migration
        new_manager = WeightedMemoryManager(user_id=TEST_USER_ID)
        
        # Check if migrated
        self.assertIn("legacy_1", new_manager.weighted_memories)
        
        # Check if file renamed
        backup_file = LONG_TERM_DIR / f"{TEST_USER_ID}_long.json.bak"
        self.assertTrue(backup_file.exists(), "Backup file should exist")
        self.assertFalse(long_file.exists(), "Original long_term file should be gone")
        
        print("PASS: Legacy data migrated and file renamed.")

if __name__ == "__main__":
    unittest.main()
